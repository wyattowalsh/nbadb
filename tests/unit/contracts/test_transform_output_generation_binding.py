from __future__ import annotations

import hashlib
import json
from dataclasses import fields, replace
from typing import TYPE_CHECKING

import pytest

from nbadb.contracts import transform_output_disposition_authority as authority_module
from nbadb.contracts import transform_output_generation_binding as binding_module
from nbadb.contracts import transform_output_materialization_receipt as receipt_module
from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
    TransformOutputEvidenceReferenceV1,
    TransformOutputSemanticClaimV1,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
)
from nbadb.contracts.transform_output_generation_binding import (
    TransformOutputGenerationBindingError,
    TransformOutputGenerationBindingV1,
    compile_transform_output_generation_binding,
)
from nbadb.orchestrate.successor_transform_authority import TransformOutputAttestation
from tests.unit.contracts.test_transform_output_disposition_authority import _authority_packet

if TYPE_CHECKING:
    from collections.abc import Callable

    from nbadb.contracts.transform_output_materialization_receipt import (
        TransformOutputMaterializationReceiptV1,
    )


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _entry() -> CurrentTransformOutputDispositionV1:
    evidence = _digest("evidence")
    return CurrentTransformOutputDispositionV1(
        output_name="dim_sample",
        family="dim",
        table_contract_sha256=_digest("contract"),
        schema_identity_sha256=_digest("schema"),
        transform_identity_sha256=_digest("transform"),
        ordered_columns_sha256=_digest("columns"),
        dependency_identity_sha256=_digest("dependencies"),
        state="active",
        capability_policy=TransformOutputCapabilityPolicyV1(True, True, True, True, True),
        semantic_claims=(
            TransformOutputSemanticClaimV1("grain", "grain", _digest("claim"), (evidence,)),
        ),
        reason_code="reviewed_active",
        evidence_references=(
            TransformOutputEvidenceReferenceV1("executable_test", "test.sample", evidence),
        ),
        revalidation_triggers=("contract_change",),
    )


def _attestation(
    *,
    table_name: str = "dim_sample",
    row_count: int = 2,
    schema: str = "physical-schema",
    content: str = "content",
) -> TransformOutputAttestation:
    return TransformOutputAttestation(
        table_name,
        row_count,
        _digest(schema),
        _digest(content),
    )


def _receipt(
    *,
    generation: str = "original-generation",
    materialization_id: str = "run:1:dim_sample",
    entry: CurrentTransformOutputDispositionV1 | None = None,
    attestation: TransformOutputAttestation | None = None,
) -> TransformOutputMaterializationReceiptV1:
    resolved_entry = entry or _entry()
    return receipt_module._construct_receipt(
        token=receipt_module._CONSTRUCTION_TOKEN,
        original_materialization_id=materialization_id,
        transaction_generation_identity_sha256=_digest(generation),
        disposition_entry=resolved_entry,
        materialization_scope="primary_working_duckdb",
        attestation=attestation or _attestation(table_name=resolved_entry.output_name),
    )


def _binding(
    *,
    current_generation: str = "later-generation",
    operation: str = "operation",
    envelope: str = "envelope",
    authored_authority: str = "authored-decision-authority",
    **changes: object,
) -> TransformOutputGenerationBindingV1:
    receipt = changes.pop("receipt", None)
    if receipt is None:
        receipt = _receipt()
    entry = changes.pop("current_entry", receipt.disposition_entry)
    fresh = changes.pop("fresh_attestation", receipt.attestation)
    return binding_module._construct_binding(
        token=binding_module._TOKEN,
        operation_identity_sha256=_digest(operation),
        transaction_generation_identity_sha256=_digest(current_generation),
        current_envelope_sha256=_digest(envelope),
        authored_decision_authority_sha256=_digest(authored_authority),
        current_entry=entry,
        receipt=receipt,
        fresh_attestation=fresh,
        canonical_relation_name=changes.pop("canonical_relation_name", entry.output_name),
        **changes,
    )


def _binding_for_entry(
    entry: CurrentTransformOutputDispositionV1,
) -> TransformOutputGenerationBindingV1:
    attestation = _attestation(table_name=entry.output_name)
    receipt = _receipt(
        materialization_id=f"run:1:{entry.output_name}",
        entry=entry,
        attestation=attestation,
    )
    return _binding(receipt=receipt, current_entry=entry, fresh_attestation=attestation)


def _binding_for_attestation(
    attestation: TransformOutputAttestation,
) -> TransformOutputGenerationBindingV1:
    receipt = _receipt(attestation=attestation)
    return _binding(receipt=receipt, fresh_attestation=attestation)


def _admit_fictional_envelope_replay(
    monkeypatch: pytest.MonkeyPatch,
    envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
) -> None:
    expected = envelope.canonical_bytes()

    def replay(
        cls: type[VerifiedTransformOutputDispositionAuthorityEnvelopeV1],
        raw: bytes,
    ) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
        assert cls is VerifiedTransformOutputDispositionAuthorityEnvelopeV1
        if raw != expected:
            raise ValueError("fictional envelope bytes changed")
        return envelope

    monkeypatch.setattr(
        VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
        "from_canonical_bytes",
        classmethod(replay),
    )


def test_parser_only_surface_and_canonical_round_trip() -> None:
    with pytest.raises(TypeError, match="from_canonical_bytes"):
        TransformOutputGenerationBindingV1()
    with pytest.raises(TransformOutputGenerationBindingError, match="token"):
        binding_module._construct_binding(
            token=object(),
            operation_identity_sha256=_digest("operation"),
            transaction_generation_identity_sha256=_digest("generation"),
            current_envelope_sha256=_digest("envelope"),
            authored_decision_authority_sha256=_digest("authored-decision-authority"),
            current_entry=_entry(),
            receipt=_receipt(),
            fresh_attestation=_attestation(),
            canonical_relation_name="dim_sample",
        )
    binding = _binding()
    assert (
        TransformOutputGenerationBindingV1.from_canonical_bytes(binding.canonical_bytes()).to_dict()
        == binding.to_dict()
    )


def test_public_compiler_derives_every_envelope_and_relation_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = authority_module._construct_verified_envelope(**_authority_packet())
    _admit_fictional_envelope_replay(monkeypatch, envelope)
    entry = envelope.entries[0]
    attestation = _attestation(table_name=entry.output_name)
    receipt = _receipt(entry=entry, attestation=attestation)

    binding = compile_transform_output_generation_binding(
        operation_identity_sha256=_digest("operation"),
        transaction_generation_identity_sha256=_digest("current-generation"),
        authority_envelope=envelope,
        receipt=receipt,
        fresh_attestation=attestation,
    )

    assert binding.current_envelope_sha256 == envelope.envelope_sha256
    assert binding.authored_decision_authority_sha256 == envelope.authored_decision_authority_sha256
    assert binding.current_entry == entry
    assert binding.canonical_relation_name == entry.output_name
    assert (
        TransformOutputGenerationBindingV1.from_canonical_bytes(binding.canonical_bytes())
        == binding
    )

    with pytest.raises(TransformOutputGenerationBindingError, match="exact executable"):
        compile_transform_output_generation_binding(
            operation_identity_sha256=_digest("operation"),
            transaction_generation_identity_sha256=_digest("current-generation"),
            authority_envelope=envelope,
            receipt=_receipt(),
            fresh_attestation=_attestation(),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "envelope_root",
        "authored_root",
        "executable_membership",
        "entry_omission",
        "entry_substitution",
    ),
)
def test_public_compiler_rejects_mutated_exact_typed_envelope(
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = authority_module._construct_verified_envelope(**_authority_packet())
    _admit_fictional_envelope_replay(monkeypatch, envelope)
    original_entry = envelope.entries[0]
    attestation = _attestation(table_name=original_entry.output_name)
    receipt = _receipt(entry=original_entry, attestation=attestation)
    if mutation == "envelope_root":
        object.__setattr__(envelope, "envelope_sha256", _digest("forged-envelope"))
    elif mutation == "authored_root":
        object.__setattr__(
            envelope,
            "authored_decision_authority_sha256",
            _digest("forged-authored-authority"),
        )
    elif mutation == "executable_membership":
        object.__setattr__(envelope, "executable_output_names", ())
    elif mutation == "entry_omission":
        object.__setattr__(envelope, "entries", ())
    else:
        object.__setattr__(
            envelope,
            "entries",
            (replace(original_entry, output_name="dim_substituted"),),
        )

    with pytest.raises(
        TransformOutputGenerationBindingError,
        match="strict replayable authority",
    ):
        compile_transform_output_generation_binding(
            operation_identity_sha256=_digest("operation"),
            transaction_generation_identity_sha256=_digest("current-generation"),
            authority_envelope=envelope,
            receipt=receipt,
            fresh_attestation=attestation,
        )


def test_classification_is_derived_for_reuse_and_rebuild() -> None:
    reuse = _binding(current_generation="later-generation")
    rebuild = _binding(current_generation="original-generation")
    assert reuse.classification == "reuse"
    assert rebuild.classification == "rebuild"
    assert reuse.binding_sha256 != rebuild.binding_sha256
    with pytest.raises(TransformOutputGenerationBindingError, match="verifier-derived"):
        _binding(expected_classification="rebuild")


def test_local_physical_and_relation_mismatch_fail_closed() -> None:
    changed_entry = _entry()
    object.__setattr__(changed_entry, "entry_sha256", _digest("foreign-entry"))
    with pytest.raises(TransformOutputGenerationBindingError, match="local authority"):
        _binding(current_entry=changed_entry)
    with pytest.raises(TransformOutputGenerationBindingError, match="fresh attestation"):
        _binding(fresh_attestation=_attestation(content="drift"))
    with pytest.raises(TransformOutputGenerationBindingError, match="canonical relation"):
        binding_module._construct_binding(
            token=binding_module._TOKEN,
            operation_identity_sha256=_digest("operation"),
            transaction_generation_identity_sha256=_digest("later"),
            current_envelope_sha256=_digest("envelope"),
            authored_decision_authority_sha256=_digest("authored-decision-authority"),
            current_entry=_entry(),
            receipt=_receipt(),
            fresh_attestation=_attestation(),
            canonical_relation_name="dim_other",
        )


def test_every_operation_and_authority_identity_changes_binding() -> None:
    baseline = _binding()
    variants = (
        binding_module._construct_binding(
            token=binding_module._TOKEN,
            operation_identity_sha256=_digest("other-operation"),
            transaction_generation_identity_sha256=baseline.transaction_generation_identity_sha256,
            current_envelope_sha256=baseline.current_envelope_sha256,
            authored_decision_authority_sha256=baseline.authored_decision_authority_sha256,
            current_entry=baseline.current_entry,
            receipt=baseline.receipt,
            fresh_attestation=baseline.fresh_attestation,
            canonical_relation_name=baseline.canonical_relation_name,
        ),
        binding_module._construct_binding(
            token=binding_module._TOKEN,
            operation_identity_sha256=baseline.operation_identity_sha256,
            transaction_generation_identity_sha256=baseline.transaction_generation_identity_sha256,
            current_envelope_sha256=_digest("other-envelope"),
            authored_decision_authority_sha256=baseline.authored_decision_authority_sha256,
            current_entry=baseline.current_entry,
            receipt=baseline.receipt,
            fresh_attestation=baseline.fresh_attestation,
            canonical_relation_name=baseline.canonical_relation_name,
        ),
    )
    assert all(item.binding_sha256 != baseline.binding_sha256 for item in variants)


_AUTHORITATIVE_BINDING_FIELDS = frozenset(
    {
        "operation_identity_sha256",
        "transaction_generation_identity_sha256",
        "current_envelope_sha256",
        "authored_decision_authority_sha256",
        "current_entry",
        "receipt",
        "fresh_attestation",
        "canonical_relation_name",
    }
)
_DERIVED_BINDING_FIELDS = frozenset(
    {
        "canonical_relation_identity_sha256",
        "classification",
        "binding_sha256",
    }
)
_EXERCISED_AUTHORITATIVE_INPUTS = frozenset(
    {
        "operation_identity_sha256",
        "transaction_generation_identity_sha256:reuse",
        "transaction_generation_identity_sha256:rebuild",
        "current_envelope_sha256",
        "authored_decision_authority_sha256",
        "receipt.original_materialization_id",
        "receipt.transaction_generation_identity_sha256",
        "current_entry.output_name+canonical_relation_name+fresh_attestation.table_name",
        "current_entry.family",
        "current_entry.table_contract_sha256",
        "current_entry.schema_identity_sha256",
        "current_entry.transform_identity_sha256",
        "current_entry.ordered_columns_sha256",
        "current_entry.dependency_identity_sha256",
        "current_entry.state+capability_policy",
        "current_entry.semantic_claims",
        "current_entry.reason_code",
        "current_entry.evidence_references",
        "current_entry.revalidation_triggers",
        "fresh_attestation.row_count",
        "fresh_attestation.schema_sha256",
        "fresh_attestation.content_sha256",
    }
)


def _valid_authoritative_input_variants() -> dict[
    str,
    Callable[[], TransformOutputGenerationBindingV1],
]:
    entry = _entry()
    evidence = entry.evidence_references[0]
    variants: dict[str, Callable[[], TransformOutputGenerationBindingV1]] = {
        "operation_identity_sha256": lambda: _binding(operation="other-operation"),
        "transaction_generation_identity_sha256:reuse": lambda: _binding(
            current_generation="another-later-generation"
        ),
        "transaction_generation_identity_sha256:rebuild": lambda: _binding(
            current_generation="original-generation"
        ),
        "current_envelope_sha256": lambda: _binding(envelope="other-envelope"),
        "authored_decision_authority_sha256": lambda: _binding(
            authored_authority="other-authored-decision-authority"
        ),
        "receipt.original_materialization_id": lambda: _binding(
            receipt=_receipt(materialization_id="run:2:dim_sample")
        ),
        "receipt.transaction_generation_identity_sha256": lambda: _binding(
            receipt=_receipt(generation="another-original-generation")
        ),
        "current_entry.output_name+canonical_relation_name+fresh_attestation.table_name": (
            lambda: _binding_for_entry(replace(_entry(), output_name="dim_relabelled"))
        ),
        "current_entry.family": lambda: _binding_for_entry(
            replace(_entry(), output_name="fact_relabelled", family="fact")
        ),
        "current_entry.state+capability_policy": lambda: _binding_for_entry(
            replace(
                _entry(),
                state="observed_only_experimental",
                capability_policy=TransformOutputCapabilityPolicyV1(
                    True,
                    True,
                    False,
                    False,
                    False,
                ),
            )
        ),
        "current_entry.semantic_claims": lambda: _binding_for_entry(
            replace(
                _entry(),
                semantic_claims=(
                    replace(_entry().semantic_claims[0], claim_sha256=_digest("other-claim")),
                ),
            )
        ),
        "current_entry.reason_code": lambda: _binding_for_entry(
            replace(_entry(), reason_code="reviewed_active_again")
        ),
        "current_entry.evidence_references": lambda: _binding_for_entry(
            replace(
                _entry(),
                evidence_references=(replace(evidence, reference_id="test.other-sample"),),
            )
        ),
        "current_entry.revalidation_triggers": lambda: _binding_for_entry(
            replace(_entry(), revalidation_triggers=("dependency_change",))
        ),
        "fresh_attestation.row_count": lambda: _binding_for_attestation(_attestation(row_count=3)),
        "fresh_attestation.schema_sha256": lambda: _binding_for_attestation(
            _attestation(schema="other-physical-schema")
        ),
        "fresh_attestation.content_sha256": lambda: _binding_for_attestation(
            _attestation(content="other-content")
        ),
    }
    for field_name in (
        "table_contract_sha256",
        "schema_identity_sha256",
        "transform_identity_sha256",
        "ordered_columns_sha256",
        "dependency_identity_sha256",
    ):
        variants[f"current_entry.{field_name}"] = lambda field_name=field_name: _binding_for_entry(
            replace(_entry(), **{field_name: _digest(f"other:{field_name}")})
        )
    return variants


def test_authoritative_and_derived_binding_field_inventory_is_exact() -> None:
    assert {field.name for field in fields(TransformOutputGenerationBindingV1)} == (
        _AUTHORITATIVE_BINDING_FIELDS | _DERIVED_BINDING_FIELDS
    )


def test_every_authoritative_input_is_exercised_and_changes_fully_resealed_binding() -> None:
    baseline = _binding()
    variants = _valid_authoritative_input_variants()

    assert frozenset(variants) == _EXERCISED_AUTHORITATIVE_INPUTS
    for variant_factory in variants.values():
        variant = variant_factory()
        assert variant.binding_sha256 != baseline.binding_sha256
        assert (
            TransformOutputGenerationBindingV1.from_canonical_bytes(variant.canonical_bytes())
            == variant
        )


@pytest.mark.parametrize(
    "entry",
    [
        replace(_entry(), output_name="dim_other"),
        replace(_entry(), output_name="fact_other", family="fact"),
        *[
            replace(_entry(), **{field_name: _digest(f"mismatch:{field_name}")})
            for field_name in (
                "table_contract_sha256",
                "schema_identity_sha256",
                "transform_identity_sha256",
                "ordered_columns_sha256",
                "dependency_identity_sha256",
            )
        ],
        replace(
            _entry(),
            state="observed_only_experimental",
            capability_policy=TransformOutputCapabilityPolicyV1(True, True, False, False, False),
        ),
    ],
)
def test_each_current_entry_identity_mismatch_is_rejected(
    entry: CurrentTransformOutputDispositionV1,
) -> None:
    with pytest.raises(TransformOutputGenerationBindingError, match="local authority"):
        _binding(current_entry=entry)


@pytest.mark.parametrize(
    "attestation",
    [
        _attestation(table_name="dim_other"),
        _attestation(row_count=3),
        _attestation(schema="mismatched-schema"),
        _attestation(content="mismatched-content"),
    ],
)
def test_each_fresh_attestation_identity_mismatch_is_rejected(
    attestation: TransformOutputAttestation,
) -> None:
    with pytest.raises(TransformOutputGenerationBindingError, match="fresh attestation"):
        _binding(fresh_attestation=attestation)


@pytest.mark.parametrize(
    "field,value",
    [
        ("classification", "rebuild"),
        ("canonical_relation_identity_sha256", "0" * 64),
        ("binding_sha256", "0" * 64),
        ("kind", "foreign_kind"),
        ("schema_version", 2),
    ],
)
def test_canonical_mutations_fail(field: str, value: object) -> None:
    payload = json.loads(_binding().canonical_bytes())
    payload[field] = value
    with pytest.raises(TransformOutputGenerationBindingError):
        TransformOutputGenerationBindingV1.from_canonical_bytes(
            binding_module._canonical(payload) + b"\n"
        )


def test_authored_authority_is_mandatory_and_strictly_sha_typed() -> None:
    missing = json.loads(_binding().canonical_bytes())
    missing.pop("authored_decision_authority_sha256")
    with pytest.raises(TransformOutputGenerationBindingError, match="fields differ"):
        TransformOutputGenerationBindingV1.from_canonical_bytes(
            binding_module._canonical(missing) + b"\n"
        )

    malformed = json.loads(_binding().canonical_bytes())
    malformed["authored_decision_authority_sha256"] = "not-a-sha"
    malformed["binding_sha256"] = binding_module._digest(
        {key: value for key, value in malformed.items() if key != "binding_sha256"}
    )
    with pytest.raises(
        TransformOutputGenerationBindingError,
        match="authored_decision_authority_sha256",
    ):
        TransformOutputGenerationBindingV1.from_canonical_bytes(
            binding_module._canonical(malformed) + b"\n"
        )


@pytest.mark.parametrize(
    "raw",
    [b'{"value":NaN}\n', b'{"x":1,"x":1}\n', b" {}\n", b"{}\n\n"],
)
def test_nonfinite_duplicate_and_noncanonical_bytes_fail(raw: bytes) -> None:
    with pytest.raises(TransformOutputGenerationBindingError):
        TransformOutputGenerationBindingV1.from_canonical_bytes(raw)


def test_direct_receipt_that_cannot_replay_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _receipt()
    monkeypatch.setattr(receipt_module, "_MAX_CANONICAL_BYTES", 1)
    with pytest.raises(TransformOutputGenerationBindingError, match="persistable"):
        _binding(receipt=receipt)


@pytest.mark.parametrize(
    ("bound_name", "bound_value", "message"),
    [
        ("_MAX_BYTES", 32, "canonical byte bound"),
        ("_MAX_DEPTH", 1, "depth bound"),
        ("_MAX_NODES", 2, "aggregate bound"),
        ("_MAX_STRING_BYTES", 2, "aggregate bound"),
    ],
)
def test_private_construction_eagerly_proves_complete_binding_is_persistable(
    monkeypatch: pytest.MonkeyPatch,
    bound_name: str,
    bound_value: int,
    message: str,
) -> None:
    monkeypatch.setattr(binding_module, bound_name, bound_value)
    with pytest.raises(TransformOutputGenerationBindingError, match=message):
        _binding()


def test_parser_rejects_over_bound_integer_tokens_before_typed_construction() -> None:
    raw = b'{"row_count":' + (b"1" * (binding_module._MAX_NUMBER_CHARS + 1)) + b"}\n"
    with pytest.raises(TransformOutputGenerationBindingError, match="number token"):
        TransformOutputGenerationBindingV1.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (
            b"[" * (binding_module._MAX_DEPTH + 1)
            + b"0"
            + b"]" * (binding_module._MAX_DEPTH + 1)
            + b"\n",
            "lexical depth",
        ),
        (
            b"[" + b",".join([b"0"] * (binding_module._MAX_NODES + 1)) + b"]\n",
            "lexical structure",
        ),
        (
            b'["' + b"\\u0061" * (binding_module._MAX_STRING_BYTES // 6 + 1) + b'"]\n',
            "string token",
        ),
        (
            b'["'
            + b"a" * (binding_module._MAX_STRING_BYTES // 2 + 1)
            + b'","'
            + b"b" * (binding_module._MAX_STRING_BYTES // 2 + 1)
            + b'"]\n',
            "aggregate string",
        ),
    ],
)
def test_hostile_under_byte_cap_shape_is_rejected_before_json_materialization(
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes,
    message: str,
) -> None:
    assert len(raw) < binding_module._MAX_BYTES

    def _must_not_materialize(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("json.loads must not run before lexical rejection")

    monkeypatch.setattr(binding_module.json, "loads", _must_not_materialize)
    with pytest.raises(TransformOutputGenerationBindingError, match=message):
        TransformOutputGenerationBindingV1.from_canonical_bytes(raw)


def test_decoder_memory_failure_is_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _binding().canonical_bytes()

    def _memory_error(*_args: object, **_kwargs: object) -> object:
        raise MemoryError

    monkeypatch.setattr(binding_module.json, "loads", _memory_error)
    with pytest.raises(TransformOutputGenerationBindingError, match="JSON is invalid"):
        TransformOutputGenerationBindingV1.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    ("path", "field", "value"),
    [
        ((), "schema_version", True),
        ((), "kind", 1),
        (("current_entry",), "schema_version", True),
        (("current_entry",), "kind", 1),
    ],
)
def test_schema_and_kind_literals_reject_bool_integer_type_confusion(
    path: tuple[str, ...],
    field: str,
    value: object,
) -> None:
    payload: object = json.loads(_binding().canonical_bytes())
    target = payload
    for segment in path:
        target = target[segment]  # type: ignore[index]
    target[field] = value  # type: ignore[index]
    with pytest.raises(TransformOutputGenerationBindingError, match="schema|current entry"):
        TransformOutputGenerationBindingV1.from_canonical_bytes(
            binding_module._canonical(payload) + b"\n"
        )
