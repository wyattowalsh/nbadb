from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import fields, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from nbadb.contracts import transform_output_disposition_authority as authority_module
from nbadb.contracts import transform_output_disposition_evidence as evidence_module
from nbadb.contracts import transform_output_generation_binding as binding_module
from nbadb.contracts import transform_output_materialization_receipt as receipt_module
from nbadb.contracts import transform_output_operation_commitment as commitment_module
from nbadb.contracts.transform_output_disposition_authority import (
    TransformOutputCapabilityPolicyV1,
    TransformOutputChangeV1,
    TransformOutputRemovedTombstoneV1,
)
from nbadb.contracts.transform_output_generation_binding import (
    TransformOutputGenerationBindingV1,
)
from nbadb.contracts.transform_output_operation_commitment import (
    TransformOutputCurrentRootV1,
    TransformOutputOperationCommitmentError,
    TransformOutputOperationCommitmentV1,
    compile_transform_output_operation_commitment,
)
from nbadb.orchestrate.successor_transform_authority import TransformOutputAttestation
from tests.unit.contracts.test_transform_output_disposition_authority import _authority_packet
from tests.unit.contracts.test_transform_output_operation_data_authority import (
    _evidence,
)

if TYPE_CHECKING:
    from nbadb.contracts.transform_output_disposition_authority import (
        VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    )
    from nbadb.contracts.transform_output_operation_data_authority import (
        OperationDataEvidenceV1,
    )


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _envelope() -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    return authority_module._construct_verified_envelope(**_authority_packet(include_fact=True))


def _bindings(
    envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    *,
    operation_identity_sha256: str | None = None,
    transaction_generation_identity_sha256: str | None = None,
) -> tuple[TransformOutputGenerationBindingV1, ...]:
    operation_identity = operation_identity_sha256 or _digest("operation")
    transaction_generation_identity = transaction_generation_identity_sha256 or _digest(
        "current-generation"
    )
    result = []
    executable = frozenset(envelope.executable_output_names)
    for entry in envelope.entries:
        if entry.output_name not in executable:
            continue
        attestation = TransformOutputAttestation(
            entry.output_name,
            1,
            _digest(f"schema:{entry.output_name}"),
            _digest(f"content:{entry.output_name}"),
        )
        receipt = receipt_module.compile_transform_output_materialization_receipt(
            original_materialization_id=f"run:1:{entry.output_name}",
            transaction_generation_identity_sha256=_digest("original-generation"),
            disposition_entry=entry,
            attestation=attestation,
        )
        with patch.object(
            authority_module.importlib,
            "import_module",
            return_value=SimpleNamespace(
                verify_transform_output_disposition_envelope=lambda _raw: envelope
            ),
        ):
            result.append(
                binding_module.compile_transform_output_generation_binding(
                    operation_identity_sha256=operation_identity,
                    transaction_generation_identity_sha256=(transaction_generation_identity),
                    authority_envelope=envelope,
                    receipt=receipt,
                    fresh_attestation=attestation,
                )
            )
    return tuple(result)


def _install_echo_verifier(
    monkeypatch: pytest.MonkeyPatch,
    envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
) -> None:
    monkeypatch.setattr(
        authority_module.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            verify_transform_output_disposition_envelope=lambda _raw: envelope
        ),
    )


def _install_exact_verifier(
    monkeypatch: pytest.MonkeyPatch,
    envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
) -> None:
    expected = envelope.canonical_bytes()

    def verify(raw: bytes) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
        if raw != expected:
            raise ValueError("fictional envelope bytes changed")
        return envelope

    monkeypatch.setattr(
        authority_module.importlib,
        "import_module",
        lambda _name: SimpleNamespace(verify_transform_output_disposition_envelope=verify),
    )


def _matching_public_inputs() -> tuple[
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    tuple[TransformOutputGenerationBindingV1, ...],
    OperationDataEvidenceV1,
]:
    evidence = _evidence("full_extraction")
    envelope = _envelope()
    bindings = _bindings(
        envelope,
        operation_identity_sha256=evidence.operation_context.operation_sha256,
        transaction_generation_identity_sha256=(
            evidence.operation_context.transaction_generation_identity_sha256
        ),
    )
    return envelope, bindings, evidence


def _binding_with_context(
    binding: TransformOutputGenerationBindingV1,
    *,
    operation_identity_sha256: str | None = None,
    transaction_generation_identity_sha256: str | None = None,
) -> TransformOutputGenerationBindingV1:
    return binding_module._construct_binding(
        token=binding_module._TOKEN,
        operation_identity_sha256=(operation_identity_sha256 or binding.operation_identity_sha256),
        transaction_generation_identity_sha256=(
            transaction_generation_identity_sha256 or binding.transaction_generation_identity_sha256
        ),
        current_envelope_sha256=binding.current_envelope_sha256,
        authored_decision_authority_sha256=(binding.authored_decision_authority_sha256),
        current_entry=binding.current_entry,
        receipt=binding.receipt,
        fresh_attestation=binding.fresh_attestation,
        canonical_relation_name=binding.canonical_relation_name,
    )


def _foreign_subclass_instance(value: object) -> object:
    foreign_type = type(f"Foreign{type(value).__name__}", (type(value),), {})
    result = object.__new__(foreign_type)
    for item in fields(type(value)):
        object.__setattr__(result, item.name, getattr(value, item.name))
    return result


def _mixed_envelope() -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    packet = _authority_packet(include_fact=True)
    entries = list(packet["entries"])
    entries[1] = replace(
        entries[1],
        state="contract_not_modeled",
        capability_policy=TransformOutputCapabilityPolicyV1(False, False, False, False, False),
    )
    proof_pack = packet["proof_pack"]
    evidence_sha256 = proof_pack.source_bundle.members_for_role("prior_or_initial_history")[
        0
    ].member_sha256
    prior_envelope_sha256 = _digest("prior-envelope")
    removal = TransformOutputChangeV1(
        change_kind="removal",
        output_name="fact_retired",
        prior_entry_sha256=_digest("retired-entry"),
        current_entry_sha256=None,
        prior_state="active",
        current_state=None,
        prior_table_contract_sha256=_digest("retired-contract"),
        current_table_contract_sha256=None,
        evidence_sha256s=(evidence_sha256,),
    )
    tombstone = TransformOutputRemovedTombstoneV1(
        output_name="fact_retired",
        family="fact",
        last_entry_sha256=removal.prior_entry_sha256,
        removal_change_sha256=removal.change_sha256,
        first_tombstone_generation_sequence=2,
        prior_envelope_sha256=prior_envelope_sha256,
        removal_reason_code="contract_removed",
        removal_evidence_sha256s=(evidence_sha256,),
    )
    return authority_module._construct_verified_envelope(
        **{
            **packet,
            "entries": tuple(entries),
            "generation_sequence": 2,
            "prior_envelope_sha256": prior_envelope_sha256,
            "changes": (removal,),
            "tombstones": (tombstone,),
        }
    )


def _commitment() -> TransformOutputOperationCommitmentV1:
    envelope = _envelope()
    return commitment_module._construct_operation_commitment(
        token=commitment_module._TOKEN,
        authority_envelope=envelope,
        bindings=_bindings(envelope),
        operation_data_evidence_sha256=_digest("operation-data-evidence"),
    )


def test_exact_sets_graph_roots_and_binding_inventory_are_derived() -> None:
    commitment = _commitment()
    envelope = commitment.authority_envelope
    assert commitment.binding_count == 2
    assert tuple(name for name, _root in commitment.binding_inventory) == (
        "dim_alpha",
        "fact_beta",
    )
    assert commitment.structural_output_names == envelope.structural_output_names
    assert commitment.executable_output_names == envelope.executable_output_names
    assert commitment.active_output_names == envelope.active_output_names
    assert (
        commitment.authored_decision_authority_sha256 == envelope.authored_decision_authority_sha256
    )
    assert commitment.operation_data_evidence_sha256 == _digest("operation-data-evidence")
    assert commitment.non_executable_output_names == envelope.non_executable_output_names
    assert commitment.tombstone_output_names == envelope.tombstone_output_names
    assert commitment.dependency_graph == envelope.dependency_graph
    assert commitment.topological_order == ("dim_alpha", "fact_beta")
    assert (
        tuple(item.output_name for item in commitment.current_roots)
        == envelope.structural_output_names
    )
    assert commitment.commitment_sha256 == commitment_module._digest(commitment._preimage())


def test_current_root_is_exactly_derived_from_entry() -> None:
    entry = _envelope().entries[0]
    row = TransformOutputCurrentRootV1.from_entry(entry)
    assert row.entry_sha256 == entry.entry_sha256
    assert row.policy_sha256 == entry.capability_policy.policy_sha256
    assert row.dependency_identity_sha256 == entry.dependency_identity_sha256
    assert row.current_root_sha256 == commitment_module._digest(row._preimage())


def test_parser_only_round_trip_replays_embedded_authorities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commitment = _commitment()
    with pytest.raises(TypeError, match="from_canonical_bytes"):
        TransformOutputOperationCommitmentV1()
    _install_echo_verifier(monkeypatch, commitment.authority_envelope)
    replayed = TransformOutputOperationCommitmentV1.from_canonical_bytes(
        commitment.canonical_bytes()
    )
    assert replayed.to_dict() == commitment.to_dict()


def test_parser_uses_real_verified_envelope_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    from nbadb.contracts import transform_output_disposition_verifier as verifier_module
    from tests.unit.contracts.test_transform_output_disposition_verifier import (
        _fixture,
        _patch_current_authorities,
    )

    fixture = _fixture()
    _patch_current_authorities(monkeypatch, fixture)
    envelope = verifier_module.verify_transform_output_disposition_envelope(fixture.raw)
    commitment = commitment_module._construct_operation_commitment(
        token=commitment_module._TOKEN,
        authority_envelope=envelope,
        bindings=_bindings(envelope),
        operation_data_evidence_sha256=_digest("operation-data-evidence"),
    )

    replayed = TransformOutputOperationCommitmentV1.from_canonical_bytes(
        commitment.canonical_bytes()
    )
    assert replayed == commitment


def test_parser_rejects_a_sealed_envelope_without_real_verifier_admission() -> None:
    commitment = _commitment()
    with pytest.raises(TransformOutputOperationCommitmentError):
        TransformOutputOperationCommitmentV1.from_canonical_bytes(commitment.canonical_bytes())


def test_public_compiler_has_only_exact_typed_upstream_inputs_and_derives_e_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, bindings, evidence = _matching_public_inputs()
    _install_exact_verifier(monkeypatch, envelope)

    signature = inspect.signature(compile_transform_output_operation_commitment)
    assert tuple(signature.parameters) == (
        "authority_envelope",
        "bindings",
        "operation_data_evidence",
    )
    assert {
        "operation_data_evidence_sha256",
        "operation_identity_sha256",
        "transaction_generation_identity_sha256",
        "disposition_generation_identity_sha256",
        "authored_decision_authority_sha256",
        "binding_inventory_sha256",
        "current_root_inventory_sha256",
        "commitment_sha256",
    }.isdisjoint(signature.parameters)

    commitment = compile_transform_output_operation_commitment(
        authority_envelope=envelope,
        bindings=bindings,
        operation_data_evidence=evidence,
    )

    assert commitment.operation_data_evidence_sha256 == (evidence.operation_data_evidence_sha256)
    assert commitment.operation_identity_sha256 == (evidence.operation_context.operation_sha256)
    assert commitment.transaction_generation_identity_sha256 == (
        evidence.operation_context.transaction_generation_identity_sha256
    )
    assert commitment.authored_decision_authority_sha256 == (
        envelope.authored_decision_authority_sha256
    )
    assert (
        TransformOutputOperationCommitmentV1.from_canonical_bytes(commitment.canonical_bytes())
        == commitment
    )


@pytest.mark.parametrize(
    "input_name",
    (
        "envelope_root",
        "envelope_executable_membership",
        "envelope_entry_substitution",
        "binding_root",
        "receipt",
        "fresh_attestation",
        "evidence",
    ),
)
def test_public_compiler_rejects_mutated_exact_typed_inputs_before_commitment(
    monkeypatch: pytest.MonkeyPatch,
    input_name: str,
) -> None:
    envelope, bindings, evidence = _matching_public_inputs()
    _install_exact_verifier(monkeypatch, envelope)
    if input_name == "envelope_root":
        object.__setattr__(envelope, "envelope_sha256", _digest("forged-envelope"))
    elif input_name == "envelope_executable_membership":
        object.__setattr__(envelope, "executable_output_names", ())
    elif input_name == "envelope_entry_substitution":
        object.__setattr__(
            envelope,
            "entries",
            (
                replace(envelope.entries[0], reason_code="substituted-entry"),
                *envelope.entries[1:],
            ),
        )
    elif input_name == "binding_root":
        object.__setattr__(bindings[0], "binding_sha256", _digest("forged-binding"))
    elif input_name == "receipt":
        object.__setattr__(
            bindings[0].receipt,
            "receipt_sha256",
            _digest("forged-receipt"),
        )
    elif input_name == "fresh_attestation":
        object.__setattr__(
            bindings[0].fresh_attestation,
            "content_sha256",
            _digest("forged-fresh-attestation"),
        )
    else:
        object.__setattr__(
            evidence,
            "operation_data_evidence_sha256",
            _digest("forged-operation-data-evidence"),
        )

    with pytest.raises(
        TransformOutputOperationCommitmentError,
        match="strict replayable|differs after strict replay",
    ):
        compile_transform_output_operation_commitment(
            authority_envelope=envelope,
            bindings=bindings,
            operation_data_evidence=evidence,
        )


@pytest.mark.parametrize(
    "input_name",
    ("envelope", "binding", "evidence"),
)
def test_public_compiler_rejects_foreign_subclasses(
    input_name: str,
) -> None:
    envelope, bindings, evidence = _matching_public_inputs()
    if input_name == "envelope":
        envelope = _foreign_subclass_instance(envelope)  # type: ignore[assignment]
    elif input_name == "binding":
        bindings = (
            _foreign_subclass_instance(bindings[0]),  # type: ignore[arg-type]
            *bindings[1:],
        )
    else:
        evidence = _foreign_subclass_instance(evidence)  # type: ignore[assignment]

    with pytest.raises(TransformOutputOperationCommitmentError, match="foreign|exact typed"):
        compile_transform_output_operation_commitment(
            authority_envelope=envelope,
            bindings=bindings,  # type: ignore[arg-type]
            operation_data_evidence=evidence,
        )


@pytest.mark.parametrize(
    "context_field",
    ("operation", "transaction_generation"),
)
def test_operation_data_evidence_must_match_every_binding_context(
    monkeypatch: pytest.MonkeyPatch,
    context_field: str,
) -> None:
    envelope, bindings, evidence = _matching_public_inputs()
    changed = _binding_with_context(
        bindings[-1],
        operation_identity_sha256=(
            _digest("foreign-operation") if context_field == "operation" else None
        ),
        transaction_generation_identity_sha256=(
            _digest("foreign-generation") if context_field == "transaction_generation" else None
        ),
    )
    mixed = (*bindings[:-1], changed)
    _install_exact_verifier(monkeypatch, envelope)

    with pytest.raises(
        TransformOutputOperationCommitmentError,
        match="evidence differs from binding operation or generation",
    ):
        compile_transform_output_operation_commitment(
            authority_envelope=envelope,
            bindings=mixed,
            operation_data_evidence=evidence,
        )


def test_operation_data_evidence_context_must_match_the_complete_uniform_binding_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, bindings, evidence = _matching_public_inputs()
    foreign_bindings = tuple(
        _binding_with_context(
            binding,
            operation_identity_sha256=_digest("uniform-foreign-operation"),
            transaction_generation_identity_sha256=_digest("uniform-foreign-generation"),
        )
        for binding in bindings
    )
    _install_exact_verifier(monkeypatch, envelope)

    with pytest.raises(
        TransformOutputOperationCommitmentError,
        match="evidence differs from binding operation or generation",
    ):
        compile_transform_output_operation_commitment(
            authority_envelope=envelope,
            bindings=foreign_bindings,
            operation_data_evidence=evidence,
        )


def test_public_compiler_rejects_fully_resealed_binding_entry_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, bindings, evidence = _matching_public_inputs()
    original = bindings[-1]
    changed_entry = replace(
        original.current_entry,
        reason_code="fully_resealed_substituted_entry",
    )
    changed_receipt = receipt_module.compile_transform_output_materialization_receipt(
        original_materialization_id=original.receipt.original_materialization_id,
        transaction_generation_identity_sha256=(
            original.receipt.transaction_generation_identity_sha256
        ),
        disposition_entry=changed_entry,
        attestation=original.fresh_attestation,
    )
    changed_binding = binding_module._construct_binding(
        token=binding_module._TOKEN,
        operation_identity_sha256=original.operation_identity_sha256,
        transaction_generation_identity_sha256=(original.transaction_generation_identity_sha256),
        current_envelope_sha256=original.current_envelope_sha256,
        authored_decision_authority_sha256=(original.authored_decision_authority_sha256),
        current_entry=changed_entry,
        receipt=changed_receipt,
        fresh_attestation=original.fresh_attestation,
        canonical_relation_name=original.canonical_relation_name,
    )
    _install_exact_verifier(monkeypatch, envelope)

    with pytest.raises(
        TransformOutputOperationCommitmentError,
        match="binding current entry differs from envelope",
    ):
        compile_transform_output_operation_commitment(
            authority_envelope=envelope,
            bindings=(*bindings[:-1], changed_binding),
            operation_data_evidence=evidence,
        )


def test_parser_rejects_foreign_commitment_subclass_before_replay() -> None:
    foreign = type(
        "ForeignTransformOutputOperationCommitmentV1",
        (TransformOutputOperationCommitmentV1,),
        {},
    )
    with pytest.raises(TransformOutputOperationCommitmentError, match="exact DTO class"):
        foreign.from_canonical_bytes(_commitment().canonical_bytes())


def test_missing_and_stale_substituted_operation_data_evidence_root_fail_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commitment = _commitment()
    _install_echo_verifier(monkeypatch, commitment.authority_envelope)
    for mutation in ("missing", "substituted"):
        payload = json.loads(commitment.canonical_bytes())
        if mutation == "missing":
            payload.pop("operation_data_evidence_sha256")
        else:
            payload["operation_data_evidence_sha256"] = _digest(
                "substituted-operation-data-evidence"
            )
        with pytest.raises(TransformOutputOperationCommitmentError):
            TransformOutputOperationCommitmentV1.from_canonical_bytes(
                commitment_module._canonical(payload) + b"\n"
            )


def test_binding_denominator_mismatch_fails_before_binding_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope, bindings, evidence = _matching_public_inputs()
    _install_exact_verifier(monkeypatch, envelope)

    def _must_not_replay(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("binding replay must not start for a wrong denominator")

    monkeypatch.setattr(
        TransformOutputGenerationBindingV1,
        "from_canonical_bytes",
        classmethod(_must_not_replay),
    )
    with pytest.raises(TransformOutputOperationCommitmentError, match="binding count"):
        compile_transform_output_operation_commitment(
            authority_envelope=envelope,
            bindings=bindings + bindings,
            operation_data_evidence=evidence,
        )


def test_persisted_binding_denominator_mismatch_fails_before_binding_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commitment = _commitment()
    payload = json.loads(commitment.canonical_bytes())
    payload["bindings"] = []
    _install_echo_verifier(monkeypatch, commitment.authority_envelope)

    def _must_not_replay(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("persisted binding replay must wait for denominator proof")

    monkeypatch.setattr(
        TransformOutputGenerationBindingV1,
        "from_canonical_bytes",
        classmethod(_must_not_replay),
    )
    with pytest.raises(
        TransformOutputOperationCommitmentError,
        match="persisted binding count",
    ):
        TransformOutputOperationCommitmentV1.from_canonical_bytes(
            commitment_module._canonical(payload) + b"\n"
        )


def test_binding_set_must_exactly_cover_executable_outputs() -> None:
    envelope = _envelope()
    bindings = _bindings(envelope)
    for invalid in (bindings[:-1], tuple(reversed(bindings)), bindings + bindings[:1]):
        with pytest.raises(TransformOutputOperationCommitmentError, match="exactly cover"):
            commitment_module._construct_operation_commitment(
                token=commitment_module._TOKEN,
                authority_envelope=envelope,
                bindings=invalid,
                operation_data_evidence_sha256=_digest("operation-data-evidence"),
            )


def test_mixed_operation_transaction_envelope_authored_authority_and_entry_fail() -> None:
    envelope = _envelope()
    bindings = list(_bindings(envelope))
    mutations = (
        binding_module._construct_binding(
            token=binding_module._TOKEN,
            operation_identity_sha256=_digest("other-operation"),
            transaction_generation_identity_sha256=bindings[
                1
            ].transaction_generation_identity_sha256,
            current_envelope_sha256=envelope.envelope_sha256,
            authored_decision_authority_sha256=(bindings[1].authored_decision_authority_sha256),
            current_entry=bindings[1].current_entry,
            receipt=bindings[1].receipt,
            fresh_attestation=bindings[1].fresh_attestation,
            canonical_relation_name=bindings[1].canonical_relation_name,
        ),
        binding_module._construct_binding(
            token=binding_module._TOKEN,
            operation_identity_sha256=bindings[1].operation_identity_sha256,
            transaction_generation_identity_sha256=_digest("other-transaction"),
            current_envelope_sha256=envelope.envelope_sha256,
            authored_decision_authority_sha256=(bindings[1].authored_decision_authority_sha256),
            current_entry=bindings[1].current_entry,
            receipt=bindings[1].receipt,
            fresh_attestation=bindings[1].fresh_attestation,
            canonical_relation_name=bindings[1].canonical_relation_name,
        ),
        binding_module._construct_binding(
            token=binding_module._TOKEN,
            operation_identity_sha256=bindings[1].operation_identity_sha256,
            transaction_generation_identity_sha256=(
                bindings[1].transaction_generation_identity_sha256
            ),
            current_envelope_sha256=envelope.envelope_sha256,
            authored_decision_authority_sha256=_digest("foreign-authored-authority"),
            current_entry=bindings[1].current_entry,
            receipt=bindings[1].receipt,
            fresh_attestation=bindings[1].fresh_attestation,
            canonical_relation_name=bindings[1].canonical_relation_name,
        ),
    )
    for mutation in mutations:
        with pytest.raises(TransformOutputOperationCommitmentError, match="mix"):
            commitment_module._construct_operation_commitment(
                token=commitment_module._TOKEN,
                authority_envelope=envelope,
                bindings=(bindings[0], mutation),
                operation_data_evidence_sha256=_digest("operation-data-evidence"),
            )


def test_valid_foreign_envelope_and_fully_resealed_entry_substitution_fail() -> None:
    envelope = _envelope()
    bindings = list(_bindings(envelope))
    packet = _authority_packet(include_fact=True)
    foreign_envelope = authority_module._construct_verified_envelope(
        **{
            **packet,
            "audit_metadata": replace(
                packet["audit_metadata"],
                author_task_id="different-author-task",
            ),
        }
    )
    with pytest.raises(TransformOutputOperationCommitmentError, match="mix"):
        commitment_module._construct_operation_commitment(
            token=commitment_module._TOKEN,
            authority_envelope=foreign_envelope,
            bindings=tuple(bindings),
            operation_data_evidence_sha256=_digest("operation-data-evidence"),
        )

    original = bindings[1]
    changed_entry = replace(original.current_entry, reason_code="different_review_reason")
    changed_receipt = receipt_module._construct_receipt(
        token=receipt_module._CONSTRUCTION_TOKEN,
        original_materialization_id=original.receipt.original_materialization_id,
        transaction_generation_identity_sha256=(
            original.receipt.transaction_generation_identity_sha256
        ),
        disposition_entry=changed_entry,
        materialization_scope="primary_working_duckdb",
        attestation=original.fresh_attestation,
    )
    changed_binding = binding_module._construct_binding(
        token=binding_module._TOKEN,
        operation_identity_sha256=original.operation_identity_sha256,
        transaction_generation_identity_sha256=original.transaction_generation_identity_sha256,
        current_envelope_sha256=envelope.envelope_sha256,
        authored_decision_authority_sha256=original.authored_decision_authority_sha256,
        current_entry=changed_entry,
        receipt=changed_receipt,
        fresh_attestation=original.fresh_attestation,
        canonical_relation_name=changed_entry.output_name,
    )
    with pytest.raises(TransformOutputOperationCommitmentError, match="current entry"):
        commitment_module._construct_operation_commitment(
            token=commitment_module._TOKEN,
            authority_envelope=envelope,
            bindings=(bindings[0], changed_binding),
            operation_data_evidence_sha256=_digest("operation-data-evidence"),
        )


def test_mixed_executable_nonexecutable_and_tombstone_sets_are_exact() -> None:
    envelope = _mixed_envelope()
    bindings = _bindings(envelope)
    commitment = commitment_module._construct_operation_commitment(
        token=commitment_module._TOKEN,
        authority_envelope=envelope,
        bindings=bindings,
        operation_data_evidence_sha256=_digest("operation-data-evidence"),
    )

    assert tuple(item.current_entry.output_name for item in bindings) == ("dim_alpha",)
    assert commitment.executable_output_names == ("dim_alpha",)
    assert commitment.non_executable_output_names == ("fact_beta",)
    assert commitment.tombstone_output_names == ("fact_retired",)
    assert tuple(item.output_name for item in commitment.current_roots) == (
        "dim_alpha",
        "fact_beta",
    )
    assert "fact_retired" not in {item.output_name for item in commitment.current_roots}

    nonexecutable = envelope.entries[1]
    attestation = TransformOutputAttestation(
        nonexecutable.output_name,
        1,
        _digest("nonexec-schema"),
        _digest("nonexec-content"),
    )
    receipt = receipt_module._construct_receipt(
        token=receipt_module._CONSTRUCTION_TOKEN,
        original_materialization_id="run:1:fact_beta",
        transaction_generation_identity_sha256=_digest("original-generation"),
        disposition_entry=nonexecutable,
        materialization_scope="primary_working_duckdb",
        attestation=attestation,
    )
    forbidden_binding = binding_module._construct_binding(
        token=binding_module._TOKEN,
        operation_identity_sha256=bindings[0].operation_identity_sha256,
        transaction_generation_identity_sha256=bindings[0].transaction_generation_identity_sha256,
        current_envelope_sha256=envelope.envelope_sha256,
        authored_decision_authority_sha256=bindings[0].authored_decision_authority_sha256,
        current_entry=nonexecutable,
        receipt=receipt,
        fresh_attestation=attestation,
        canonical_relation_name=nonexecutable.output_name,
    )
    with pytest.raises(TransformOutputOperationCommitmentError, match="exactly cover"):
        commitment_module._construct_operation_commitment(
            token=commitment_module._TOKEN,
            authority_envelope=envelope,
            bindings=(*bindings, forbidden_binding),
            operation_data_evidence_sha256=_digest("operation-data-evidence"),
        )

    top_level_fields = {item.name for item in fields(TransformOutputOperationCommitmentV1)}
    assert all(
        forbidden not in field_name
        for field_name in top_level_fields
        for forbidden in ("persisted", "materialized", "physical_relation", "publication_admission")
    )


_PERSISTED_FIELD_MUTATIONS: tuple[tuple[str, object], ...] = (
    ("authority_envelope", {}),
    ("bindings", []),
    ("operation_identity_sha256", "0" * 64),
    ("transaction_generation_identity_sha256", "0" * 64),
    ("disposition_generation_identity_sha256", "0" * 64),
    ("authored_decision_authority_sha256", "0" * 64),
    ("operation_data_evidence_sha256", "0" * 64),
    ("binding_count", 99),
    ("binding_inventory", []),
    ("binding_inventory_sha256", "0" * 64),
    ("structural_output_names", ["dim_alpha"]),
    ("executable_output_names", ["dim_alpha"]),
    ("active_output_names", ["dim_alpha"]),
    ("non_executable_output_names", ["fact_beta"]),
    ("tombstone_output_names", ["fact_retired"]),
    ("dependency_graph", []),
    ("topological_order", ["fact_beta", "dim_alpha"]),
    ("current_roots", []),
    ("current_root_inventory_sha256", "0" * 64),
    ("commitment_sha256", "0" * 64),
    ("kind", "foreign_kind"),
    ("schema_version", 2),
)


@pytest.mark.parametrize(
    "field,value",
    _PERSISTED_FIELD_MUTATIONS,
)
def test_caller_inventory_root_order_and_schema_mutations_fail(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    commitment = _commitment()
    payload = json.loads(commitment.canonical_bytes())
    payload[field] = value
    _install_echo_verifier(monkeypatch, commitment.authority_envelope)
    with pytest.raises(TransformOutputOperationCommitmentError):
        TransformOutputOperationCommitmentV1.from_canonical_bytes(
            commitment_module._canonical(payload) + b"\n"
        )


def test_persisted_mutation_inventory_exactly_covers_the_complete_dto() -> None:
    assert {name for name, _value in _PERSISTED_FIELD_MUTATIONS} == (
        set(TransformOutputOperationCommitmentV1.__annotations__) | {"schema_version", "kind"}
    )


@pytest.mark.parametrize(
    ("bound_name", "bound_value", "raw", "message"),
    [
        ("_MAX_DEPTH", 2, b"[[[0]]]\n", "lexical depth"),
        ("_MAX_NODES", 3, b"[0,0,0]\n", "lexical structure"),
        ("_MAX_STRING_BYTES", 4, b'["aa","bbb"]\n', "aggregate string"),
        ("_MAX_NUMBER_CHARS", 2, b"[123]\n", "number token"),
    ],
)
def test_hostile_shape_is_rejected_before_shared_decoder_materialization(
    monkeypatch: pytest.MonkeyPatch,
    bound_name: str,
    bound_value: int,
    raw: bytes,
    message: str,
) -> None:
    monkeypatch.setattr(commitment_module, bound_name, bound_value)

    def _must_not_decode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("shared decoder must not run before lexical rejection")

    monkeypatch.setattr(commitment_module, "decode_canonical_json_bytes_v1", _must_not_decode)
    with pytest.raises(TransformOutputOperationCommitmentError, match=message):
        TransformOutputOperationCommitmentV1.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", True), ("schema_version", 1.0), ("kind", 1)],
)
def test_schema_identity_rejects_bool_integer_and_float_confusion(
    field: str,
    value: object,
) -> None:
    payload = json.loads(_commitment().canonical_bytes())
    payload[field] = value
    with pytest.raises(TransformOutputOperationCommitmentError, match="schema identity"):
        TransformOutputOperationCommitmentV1.from_canonical_bytes(
            evidence_module.persisted_canonical_json_bytes_v1(payload)
        )


def test_decoder_memory_failure_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _commitment().canonical_bytes()

    def _memory_error(*_args: object, **_kwargs: object) -> object:
        raise MemoryError

    monkeypatch.setattr(commitment_module, "decode_canonical_json_bytes_v1", _memory_error)
    with pytest.raises(TransformOutputOperationCommitmentError, match="resource bounds"):
        TransformOutputOperationCommitmentV1.from_canonical_bytes(raw)


def test_private_construction_eagerly_proves_complete_commitment_is_persistable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commitment = _commitment()
    monkeypatch.setattr(evidence_module, "CANONICAL_JSON_MAX_BYTES", 32)
    with pytest.raises(TransformOutputOperationCommitmentError, match="canonical JSON"):
        commitment_module._construct_operation_commitment(
            token=commitment_module._TOKEN,
            authority_envelope=commitment.authority_envelope,
            bindings=commitment.bindings,
            operation_data_evidence_sha256=commitment.operation_data_evidence_sha256,
        )


@pytest.mark.parametrize("raw", [b'{"x":NaN}\n', b'{"x":1,"x":1}\n', b" {}\n", b"{}\n\n"])
def test_nonfinite_duplicate_and_noncanonical_bytes_fail(raw: bytes) -> None:
    with pytest.raises(TransformOutputOperationCommitmentError):
        TransformOutputOperationCommitmentV1.from_canonical_bytes(raw)
