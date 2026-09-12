from __future__ import annotations

from typing import TYPE_CHECKING

from nbadb.contracts import transform_output_disposition_verifier as verifier_module
from nbadb.contracts import transform_output_operation_commitment as commitment_module
from nbadb.contracts.transform_output_operation_commitment import (
    TransformOutputOperationCommitmentV1,
    compile_transform_output_operation_commitment,
)
from tests.unit.contracts.test_transform_output_disposition_verifier import (
    _fixture,
    _patch_current_authorities,
)
from tests.unit.contracts.test_transform_output_operation_commitment import (
    _bindings,
)
from tests.unit.contracts.test_transform_output_operation_data_authority import (
    _evidence,
)

if TYPE_CHECKING:
    import pytest


def test_independently_compiled_authored_root_propagates_without_source_bundle_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    _patch_current_authorities(monkeypatch, fixture)

    envelope = verifier_module.verify_transform_output_disposition_envelope(fixture.raw)
    evidence = _evidence("full_extraction")
    bindings = _bindings(
        envelope,
        operation_identity_sha256=evidence.operation_context.operation_sha256,
        transaction_generation_identity_sha256=(
            evidence.operation_context.transaction_generation_identity_sha256
        ),
    )
    commitment = compile_transform_output_operation_commitment(
        authority_envelope=envelope,
        bindings=bindings,
        operation_data_evidence=evidence,
    )

    assert envelope.authored_decision_authority_sha256 == fixture.authored.authority_sha256
    assert envelope.authored_decision_authority_sha256 != envelope.source_bundle_sha256
    assert {binding.authored_decision_authority_sha256 for binding in commitment.bindings} == {
        fixture.authored.authority_sha256
    }
    assert commitment.authored_decision_authority_sha256 == fixture.authored.authority_sha256
    assert commitment.operation_data_evidence_sha256 == (evidence.operation_data_evidence_sha256)
    assert commitment.commitment_sha256 == commitment_module._digest(commitment._preimage())

    replayed = TransformOutputOperationCommitmentV1.from_canonical_bytes(
        commitment.canonical_bytes()
    )
    assert replayed == commitment
