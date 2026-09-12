from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError, fields, replace
from types import SimpleNamespace
from typing import cast

import pytest

from nbadb.contracts import transform_output_disposition_authority as authority_module
from nbadb.contracts.transform_output_disposition_authority import (
    CURRENT_TRANSFORM_OUTPUT_DISPOSITION_KIND,
    TRANSFORM_OUTPUT_DISPOSITION_AUTHORITY_KIND,
    TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION,
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
    TransformOutputChangeV1,
    TransformOutputDependencyV1,
    TransformOutputDispositionAuthorityError,
    TransformOutputEvidenceReferenceV1,
    TransformOutputRemovedTombstoneV1,
    TransformOutputSemanticClaimV1,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    REQUIRED_SOURCE_MEMBER_ROLES_V1,
    TransformOutputDispositionAuditMetadataV1,
    TransformOutputDispositionProofPackV1,
    TransformOutputDispositionSourceBundleV1,
    TransformOutputDispositionSourceMemberV1,
    TransformOutputDispositionValidationEvidenceV1,
)
from nbadb.contracts.transform_output_disposition_structural import (
    TransformOutputStructuralAuthorityV1,
    TransformOutputStructuralTableAuthorityV1,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _policy(state: str = "active") -> TransformOutputCapabilityPolicyV1:
    values = {
        "active": (True, True, True, True, True),
        "observed_only_experimental": (True, True, False, False, False),
        "contract_not_modeled": (False, False, False, False, False),
    }[state]
    return TransformOutputCapabilityPolicyV1(*values)


def _claim(
    label: str = "grain",
    *,
    evidence_sha256: str | None = None,
) -> TransformOutputSemanticClaimV1:
    return TransformOutputSemanticClaimV1(
        claim_id=label,
        claim_kind="semantic_contract",
        claim_sha256=_digest(f"claim:{label}"),
        evidence_sha256s=(evidence_sha256 or _digest(f"claim-evidence:{label}"),),
    )


def _evidence(
    label: str = "schema",
    *,
    evidence_sha256: str | None = None,
) -> TransformOutputEvidenceReferenceV1:
    return TransformOutputEvidenceReferenceV1(
        evidence_class="typed_contract",
        reference_id=f"fixture/{label}",
        evidence_sha256=evidence_sha256 or _digest(f"evidence:{label}"),
    )


def _entry(
    *,
    output_name: str = "dim_alpha",
    state: str = "active",
    structural_table: TransformOutputStructuralTableAuthorityV1 | None = None,
    evidence_sha256: str | None = None,
) -> CurrentTransformOutputDispositionV1:
    family = output_name.split("_", 1)[0]
    table_contract_sha256 = (
        structural_table.table_contract_sha256
        if structural_table is not None
        else _digest(f"table:{output_name}")
    )
    schema_identity_sha256 = (
        structural_table.schema_sha256
        if structural_table is not None
        else _digest(f"schema:{output_name}")
    )
    transform_identity_sha256 = (
        structural_table.transform_sha256
        if structural_table is not None
        else _digest(f"transform:{output_name}")
    )
    ordered_columns_sha256 = (
        structural_table.ordered_column_inventory_sha256
        if structural_table is not None
        else _digest(f"columns:{output_name}")
    )
    dependency_identity_sha256 = (
        structural_table.dependency_inventory_sha256
        if structural_table is not None
        else _digest(f"dependencies:{output_name}")
    )
    return CurrentTransformOutputDispositionV1(
        output_name=output_name,
        family=cast("authority_module.TransformOutputFamily", family),
        table_contract_sha256=table_contract_sha256,
        schema_identity_sha256=schema_identity_sha256,
        transform_identity_sha256=transform_identity_sha256,
        ordered_columns_sha256=ordered_columns_sha256,
        dependency_identity_sha256=dependency_identity_sha256,
        state=cast("authority_module.TransformOutputDispositionState", state),
        capability_policy=_policy(state),
        semantic_claims=(_claim(evidence_sha256=evidence_sha256),),
        reason_code="authored_review",
        evidence_references=(_evidence(evidence_sha256=evidence_sha256),),
        revalidation_triggers=("contract_change", "upstream_change"),
    )


def _structural_authority(
    *,
    include_fact: bool = False,
) -> TransformOutputStructuralAuthorityV1:
    alpha = TransformOutputStructuralTableAuthorityV1(
        output_name="dim_alpha",
        table_family="dim",
        table_contract_sha256=_digest("table:dim_alpha"),
        schema_sha256=_digest("schema:dim_alpha"),
        transform_sha256=_digest("transform:dim_alpha"),
        ordered_columns=("alpha_id",),
        dependencies=(),
    )
    tables = [alpha]
    if include_fact:
        tables.append(
            TransformOutputStructuralTableAuthorityV1(
                output_name="fact_beta",
                table_family="fact",
                table_contract_sha256=_digest("table:fact_beta"),
                schema_sha256=_digest("schema:fact_beta"),
                transform_sha256=_digest("transform:fact_beta"),
                ordered_columns=("alpha_id", "value"),
                dependencies=("dim_alpha", "stg_beta"),
            )
        )
    ordered = tuple(sorted(tables, key=lambda item: item.output_name))
    return TransformOutputStructuralAuthorityV1(
        output_names=tuple(item.output_name for item in ordered),
        star_model_contract_sha256=_digest("fictional-star-model"),
        tables=ordered,
    )


def _proof_pack() -> TransformOutputDispositionProofPackV1:
    members: list[TransformOutputDispositionSourceMemberV1] = []
    for index, role in enumerate(sorted(REQUIRED_SOURCE_MEMBER_ROLES_V1)):
        if role == "verifier_source":
            member = TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
                normalized_path=f"authority/{index:02d}-{role}.py",
                role=role,
                media_type="text/x-python",
                content=b"def verify(value: object) -> bool:\n    return value is not None\n",
            )
        else:
            member = TransformOutputDispositionSourceMemberV1.from_typed_projection(
                normalized_path=f"authority/{index:02d}-{role}.json",
                role=role,
                media_type="application/json",
                projection={"role": role, "schema_version": 1},
            )
        members.append(member)
    bundle = TransformOutputDispositionSourceBundleV1(
        members=tuple(sorted(members, key=lambda item: item.normalized_path))
    )
    proof_input = bundle.members_for_role("proof_inputs")[0].member_sha256
    evidence = bundle.members_for_role("validation_evidence")[0].member_sha256
    rows = tuple(
        TransformOutputDispositionValidationEvidenceV1(
            case_id=case_id,
            validation_class=validation_class,
            proof_input_member_sha256=proof_input,
            evidence_member_sha256s=(evidence,),
            expected_outcome=expected,
            observed_outcome=expected,
        )
        for case_id, validation_class, expected in (
            ("01-positive", "positive", "accepted"),
            ("02-negative", "negative", "rejected"),
            ("03-mutation", "mutation", "rejected"),
        )
    )
    return TransformOutputDispositionProofPackV1(
        source_bundle=bundle,
        claimed_reconstructed_result_sha256=_digest("fictional-reconstructed-result"),
        validation_evidence=rows,
    )


def _authority_packet(
    *,
    include_fact: bool = False,
    alpha_state: str = "active",
) -> dict[str, object]:
    structural = _structural_authority(include_fact=include_fact)
    proof_pack = _proof_pack()
    evidence_sha256 = proof_pack.source_bundle.members_for_role("authored_entries")[0].member_sha256
    entries = tuple(
        _entry(
            output_name=table.output_name,
            state=alpha_state if table.output_name == "dim_alpha" else "active",
            structural_table=table,
            evidence_sha256=evidence_sha256,
        )
        for table in structural.tables
    )
    dependencies: tuple[TransformOutputDependencyV1, ...] = ()
    if include_fact:
        dependencies = (
            TransformOutputDependencyV1(
                output_name="fact_beta",
                ordinal=0,
                dependency_id="dim_alpha",
                dependency_kind="transform_output",
                dependency_contract_sha256=structural.tables[0].table_contract_sha256,
            ),
            TransformOutputDependencyV1(
                output_name="fact_beta",
                ordinal=1,
                dependency_id="stg_beta",
                dependency_kind="staging_input",
                dependency_contract_sha256=_digest("staging:stg_beta"),
            ),
        )
    return {
        "token": authority_module._VERIFIED_ENVELOPE_CONSTRUCTION_TOKEN,
        "structural_authority": structural,
        "proof_pack": proof_pack,
        "audit_metadata": TransformOutputDispositionAuditMetadataV1(
            proof_pack_root_sha256=proof_pack.proof_pack_root_sha256,
            author_task_id="fictional-author",
            author_role="author",
            reviewer_task_id="fictional-reviewer",
            reviewer_role="reviewer",
        ),
        "entries": entries,
        "tombstones": (),
        "changes": (),
        "dependencies": dependencies,
        "authored_decision_authority_sha256": _digest("authored-decision-authority"),
        "generation_sequence": 1,
        "prior_envelope_sha256": None,
    }


def test_public_surface_and_schema_identifiers_are_exact() -> None:
    assert authority_module.__all__ == [
        "CURRENT_TRANSFORM_OUTPUT_DISPOSITION_KIND",
        "TRANSFORM_OUTPUT_DISPOSITION_AUTHORITY_KIND",
        "TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION",
        "CurrentTransformOutputDispositionV1",
        "TransformOutputCapabilityPolicyV1",
        "TransformOutputChangeV1",
        "TransformOutputDependencyV1",
        "TransformOutputDispositionAuthorityError",
        "TransformOutputEvidenceReferenceV1",
        "TransformOutputRemovedTombstoneV1",
        "TransformOutputSemanticClaimV1",
        "VerifiedTransformOutputDispositionAuthorityEnvelopeV1",
    ]
    assert TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION == 1
    assert CURRENT_TRANSFORM_OUTPUT_DISPOSITION_KIND == (
        "nbadb_current_transform_output_disposition"
    )
    assert TRANSFORM_OUTPUT_DISPOSITION_AUTHORITY_KIND == (
        "nbadb_verified_transform_output_disposition_authority_envelope"
    )
    assert not hasattr(CurrentTransformOutputDispositionV1, "from_dict")
    assert not hasattr(VerifiedTransformOutputDispositionAuthorityEnvelopeV1, "from_dict")
    assert tuple(
        inspect.signature(
            VerifiedTransformOutputDispositionAuthorityEnvelopeV1.from_canonical_bytes
        ).parameters
    ) == ("raw",)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("active", (True, True, True, True, True)),
        ("observed_only_experimental", (True, True, False, False, False)),
        ("contract_not_modeled", (False, False, False, False, False)),
    ],
)
def test_exact_authored_capability_matrix_is_accepted(
    state: str,
    expected: tuple[bool, bool, bool, bool, bool],
) -> None:
    policy = _policy(state)
    assert (
        policy.execute,
        policy.primary_materialize,
        policy.stable_load,
        policy.transform_publication,
        policy.chat_ceiling,
    ) == expected
    policy.validate_for_state(cast("authority_module.TransformOutputDispositionState", state))
    assert policy.policy_sha256 == authority_module._sha256_json(policy._digest_preimage())


def test_policy_is_not_filled_and_unknown_or_removed_current_states_fail() -> None:
    policy = TransformOutputCapabilityPolicyV1(True, True, True, True, False)
    with pytest.raises(TransformOutputDispositionAuthorityError, match="differs"):
        policy.validate_for_state("active")
    with pytest.raises(TransformOutputDispositionAuthorityError, match="state is invalid"):
        policy.validate_for_state(
            cast("authority_module.TransformOutputDispositionState", "removed")
        )
    with pytest.raises(TransformOutputDispositionAuthorityError, match="current state"):
        replace(
            _entry(),
            state=cast("authority_module.TransformOutputDispositionState", "removed"),
        )
    with pytest.raises(TransformOutputDispositionAuthorityError, match="current state"):
        replace(
            _entry(),
            state=cast("authority_module.TransformOutputDispositionState", "future_state"),
        )


def test_current_entry_field_tuple_and_digest_allowlist_are_strictly_table_local() -> None:
    assert tuple(item.name for item in fields(CurrentTransformOutputDispositionV1)) == (
        "output_name",
        "family",
        "table_contract_sha256",
        "schema_identity_sha256",
        "transform_identity_sha256",
        "ordered_columns_sha256",
        "dependency_identity_sha256",
        "state",
        "capability_policy",
        "semantic_claims",
        "reason_code",
        "evidence_references",
        "revalidation_triggers",
        "entry_sha256",
    )
    assert CurrentTransformOutputDispositionV1.digest_field_names == (
        "schema_version",
        "kind",
        "output_name",
        "family",
        "table_contract_sha256",
        "schema_identity_sha256",
        "transform_identity_sha256",
        "ordered_columns_sha256",
        "dependency_identity_sha256",
        "state",
        "capability_policy",
        "semantic_claims",
        "reason_code",
        "evidence_references",
        "revalidation_triggers",
    )
    forbidden = {
        "inventory",
        "generation",
        "proof",
        "source_bundle",
        "author",
        "reviewer",
        "task",
        "role",
        "change",
        "operation",
        "transaction",
        "receipt",
        "materialization",
        "publication",
        "envelope",
    }
    assert not any(
        token in field_name
        for field_name in CurrentTransformOutputDispositionV1.digest_field_names
        for token in forbidden
    )
    entry = _entry()
    assert tuple(entry._digest_preimage()) == CurrentTransformOutputDispositionV1.digest_field_names
    assert entry.entry_sha256 == authority_module._sha256_json(entry._digest_preimage())
    assert entry.canonical_bytes() == authority_module._canonical_json_bytes(entry.to_dict())


def test_entry_is_deterministic_and_every_table_local_mutation_changes_digest() -> None:
    baseline = _entry()
    assert baseline == _entry()
    assert baseline.entry_sha256 == _entry().entry_sha256
    mutations = (
        replace(baseline, table_contract_sha256=_digest("different-table")),
        replace(baseline, schema_identity_sha256=_digest("different-schema")),
        replace(baseline, transform_identity_sha256=_digest("different-transform")),
        replace(baseline, ordered_columns_sha256=_digest("different-columns")),
        replace(baseline, dependency_identity_sha256=_digest("different-dependencies")),
        replace(
            baseline,
            state="observed_only_experimental",
            capability_policy=_policy("observed_only_experimental"),
        ),
        replace(baseline, semantic_claims=(_claim("filter"),)),
        replace(baseline, reason_code="different_reason"),
        replace(baseline, evidence_references=(_evidence("implementation"),)),
        replace(baseline, revalidation_triggers=("schema_change",)),
    )
    assert len({item.entry_sha256 for item in mutations}) == len(mutations)
    assert baseline.entry_sha256 not in {item.entry_sha256 for item in mutations}
    with pytest.raises(FrozenInstanceError):
        baseline.reason_code = "mutated"  # type: ignore[misc]


def test_entry_rejects_family_ordering_evidence_and_policy_mismatches() -> None:
    baseline = _entry()
    with pytest.raises(TransformOutputDispositionAuthorityError, match="family"):
        replace(baseline, family="fact")
    with pytest.raises(TransformOutputDispositionAuthorityError, match="semantic_claims"):
        replace(baseline, semantic_claims=())
    with pytest.raises(TransformOutputDispositionAuthorityError, match="sorted and unique"):
        replace(baseline, semantic_claims=(_claim("zeta"), _claim("alpha")))
    with pytest.raises(TransformOutputDispositionAuthorityError, match="evidence_references"):
        replace(baseline, evidence_references=())
    with pytest.raises(TransformOutputDispositionAuthorityError, match="sorted and unique"):
        replace(baseline, revalidation_triggers=("zeta", "alpha"))
    with pytest.raises(TransformOutputDispositionAuthorityError, match="differs"):
        replace(baseline, capability_policy=_policy("contract_not_modeled"))


def test_claim_and_evidence_types_reject_noncanonical_or_weak_values() -> None:
    reversed_digests = tuple(reversed(sorted((_digest("z"), _digest("a")))))
    with pytest.raises(TransformOutputDispositionAuthorityError, match="sorted and unique"):
        TransformOutputSemanticClaimV1(
            claim_id="grain",
            claim_kind="semantic_contract",
            claim_sha256=_digest("claim"),
            evidence_sha256s=reversed_digests,
        )
    with pytest.raises(TransformOutputDispositionAuthorityError, match="safe nonempty"):
        TransformOutputEvidenceReferenceV1(
            evidence_class="bad space",
            reference_id="fixture/id",
            evidence_sha256=_digest("evidence"),
        )
    with pytest.raises(TransformOutputDispositionAuthorityError, match="lowercase SHA-256"):
        replace(_evidence(), evidence_sha256="A" * 64)


def test_tombstone_change_and_dependency_dtos_are_typed_and_deterministic() -> None:
    removal_change = TransformOutputChangeV1(
        change_kind="removal",
        output_name="fact_retired",
        prior_entry_sha256=_digest("prior"),
        current_entry_sha256=None,
        prior_state="active",
        current_state=None,
        prior_table_contract_sha256=_digest("prior-contract"),
        current_table_contract_sha256=None,
        evidence_sha256s=(_digest("removal"),),
    )
    tombstone = TransformOutputRemovedTombstoneV1(
        output_name="fact_retired",
        family="fact",
        last_entry_sha256=_digest("last-entry"),
        removal_change_sha256=removal_change.change_sha256,
        first_tombstone_generation_sequence=2,
        prior_envelope_sha256=_digest("prior-envelope"),
        removal_reason_code="contract_removed",
        removal_evidence_sha256s=(_digest("removal"),),
    )
    assert tombstone == replace(tombstone)
    assert tombstone.tombstone_sha256 == authority_module._sha256_json(tombstone._digest_preimage())

    addition = TransformOutputChangeV1(
        change_kind="structural_addition",
        output_name="dim_alpha",
        prior_entry_sha256=None,
        current_entry_sha256=_digest("current"),
        prior_state=None,
        current_state="active",
        prior_table_contract_sha256=None,
        current_table_contract_sha256=_digest("current-contract"),
        evidence_sha256s=(_digest("change"),),
    )
    assert addition.change_sha256 != removal_change.change_sha256
    semantic_rebind = TransformOutputChangeV1(
        change_kind="contract_rebind",
        output_name="dim_alpha",
        prior_entry_sha256=_digest("prior-semantic-entry"),
        current_entry_sha256=_digest("current-semantic-entry"),
        prior_state="active",
        current_state="active",
        prior_table_contract_sha256=_digest("unchanged-contract"),
        current_table_contract_sha256=_digest("unchanged-contract"),
        evidence_sha256s=(_digest("semantic-rebind-evidence"),),
    )
    assert semantic_rebind.prior_table_contract_sha256 == (
        semantic_rebind.current_table_contract_sha256
    )
    with pytest.raises(TransformOutputDispositionAuthorityError, match="incompatible"):
        replace(addition, prior_entry_sha256=_digest("unexpected-prior"))
    with pytest.raises(TransformOutputDispositionAuthorityError, match="incompatible"):
        TransformOutputChangeV1(
            change_kind="state_transition",
            output_name="dim_alpha",
            prior_entry_sha256=_digest("same"),
            current_entry_sha256=_digest("same"),
            prior_state="active",
            current_state="observed_only_experimental",
            prior_table_contract_sha256=_digest("contract"),
            current_table_contract_sha256=_digest("contract"),
            evidence_sha256s=(_digest("change"),),
        )

    transform_edge = TransformOutputDependencyV1(
        output_name="fact_beta",
        ordinal=0,
        dependency_id="dim_alpha",
        dependency_kind="transform_output",
        dependency_contract_sha256=_digest("dependency-contract"),
    )
    staging_edge = TransformOutputDependencyV1(
        output_name="fact_beta",
        ordinal=1,
        dependency_id="stg_beta",
        dependency_kind="staging_input",
        dependency_contract_sha256=_digest("staging-contract"),
    )
    assert transform_edge.dependency_sha256 != staging_edge.dependency_sha256
    with pytest.raises(TransformOutputDispositionAuthorityError, match="itself"):
        replace(transform_edge, dependency_id="fact_beta")
    with pytest.raises(TransformOutputDispositionAuthorityError, match="staging"):
        replace(staging_edge, dependency_id="fact_foreign")


def test_verified_envelope_is_sealed_recomputes_roots_and_persists_one_lf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packet = _authority_packet(include_fact=True)
    with pytest.raises(TypeError, match="from_canonical_bytes"):
        VerifiedTransformOutputDispositionAuthorityEnvelopeV1()
    with pytest.raises(TransformOutputDispositionAuthorityError, match="token"):
        authority_module._construct_verified_envelope(**{**packet, "token": object()})

    envelope = authority_module._construct_verified_envelope(**packet)
    encoded = envelope.canonical_bytes()
    assert encoded.endswith(b"\n") and not encoded.endswith(b"\n\n")
    payload = json.loads(encoded)
    assert payload["envelope_sha256"] == envelope.envelope_sha256
    assert envelope.entries_sha256 == authority_module._sha256_json(
        [item.entry_sha256 for item in envelope.entries]
    )
    assert envelope.tombstones_sha256 == authority_module._sha256_json([])
    assert envelope.structural_authority is packet["structural_authority"]
    assert envelope.proof_pack is packet["proof_pack"]
    assert envelope.audit_metadata is packet["audit_metadata"]
    assert (
        envelope.authored_decision_authority_sha256 == packet["authored_decision_authority_sha256"]
    )
    assert (
        payload["authored_decision_authority_sha256"]
        == packet["authored_decision_authority_sha256"]
    )
    assert envelope.structural_output_names == ("dim_alpha", "fact_beta")
    assert envelope.active_output_names == envelope.executable_output_names
    assert envelope.non_executable_output_names == ()
    assert envelope.dependency_graph == (
        ("dim_alpha", ()),
        ("fact_beta", ("dim_alpha",)),
    )
    assert envelope.topological_order == ("dim_alpha", "fact_beta")
    assert envelope.generation_identity_sha256 == payload["generation_identity_sha256"]
    with pytest.raises(FrozenInstanceError):
        envelope.structural_count = 2  # type: ignore[misc]

    monkeypatch.setattr(
        authority_module.importlib,
        "import_module",
        lambda _name: SimpleNamespace(
            verify_transform_output_disposition_envelope=lambda raw: envelope
        ),
    )
    assert (
        VerifiedTransformOutputDispositionAuthorityEnvelopeV1.from_canonical_bytes(encoded)
        is envelope
    )
    with pytest.raises(TransformOutputDispositionAuthorityError, match="foreign"):
        VerifiedTransformOutputDispositionAuthorityEnvelopeV1.from_canonical_bytes(
            cast("bytes", bytearray(encoded))
        )
    with pytest.raises(TransformOutputDispositionAuthorityError, match="differing"):
        VerifiedTransformOutputDispositionAuthorityEnvelopeV1.from_canonical_bytes(
            encoded.replace(b'"generation_sequence":1', b'"generation_sequence":2')
        )


def test_authored_decision_authority_is_mandatory_strict_and_identity_bound() -> None:
    packet = _authority_packet()
    constructor_parameter = inspect.signature(
        authority_module._construct_verified_envelope
    ).parameters["authored_decision_authority_sha256"]
    assert constructor_parameter.default is inspect.Parameter.empty
    omitted = dict(packet)
    del omitted["authored_decision_authority_sha256"]
    with pytest.raises(TypeError, match="authored_decision_authority_sha256"):
        authority_module._construct_verified_envelope(**omitted)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="unexpected keyword"):
        authority_module._construct_verified_envelope(
            **{**packet, "unknown_authored_decision_authority_sha256": _digest("unknown")}
        )
    for malformed in (None, "", "A" * 64, "0" * 63, _digest("valid") + "0"):
        with pytest.raises(TransformOutputDispositionAuthorityError, match="lowercase SHA-256"):
            authority_module._construct_verified_envelope(
                **{**packet, "authored_decision_authority_sha256": malformed}
            )

    baseline = authority_module._construct_verified_envelope(**packet)
    mutated = authority_module._construct_verified_envelope(
        **{
            **packet,
            "authored_decision_authority_sha256": _digest("different-authored-decision-authority"),
        }
    )
    assert baseline.source_bundle_sha256 == mutated.source_bundle_sha256
    assert baseline.proof_pack_sha256 == mutated.proof_pack_sha256
    assert baseline.authored_decision_authority_sha256 != (
        mutated.authored_decision_authority_sha256
    )
    assert baseline.generation_identity_sha256 != mutated.generation_identity_sha256
    assert baseline.envelope_sha256 != mutated.envelope_sha256

    payload = baseline.to_dict()
    assert (
        payload["authored_decision_authority_sha256"]
        == packet["authored_decision_authority_sha256"]
    )
    assert payload["authored_decision_authority_sha256"] != payload["source_bundle_sha256"]


def test_envelope_rejects_incomplete_unsorted_overlapping_or_duplicate_components() -> None:
    kwargs = _authority_packet(include_fact=True)
    with pytest.raises(TransformOutputDispositionAuthorityError, match="cover"):
        authority_module._construct_verified_envelope(
            **{
                **kwargs,
                "entries": tuple(reversed(cast("tuple[object, ...]", kwargs["entries"]))),
            }
        )
    structural = cast("TransformOutputStructuralAuthorityV1", kwargs["structural_authority"])
    entries = cast("tuple[CurrentTransformOutputDispositionV1, ...]", kwargs["entries"])
    with pytest.raises(TransformOutputDispositionAuthorityError, match="structural table"):
        authority_module._construct_verified_envelope(
            **{
                **kwargs,
                "entries": (
                    replace(entries[0], schema_identity_sha256=_digest("foreign-schema")),
                    entries[1],
                ),
            }
        )
    tombstone = TransformOutputRemovedTombstoneV1(
        output_name="dim_alpha",
        family="dim",
        last_entry_sha256=_digest("last-entry"),
        removal_change_sha256=_digest("removal-change"),
        first_tombstone_generation_sequence=2,
        prior_envelope_sha256=_digest("prior-envelope"),
        removal_reason_code="removed",
        removal_evidence_sha256s=(_digest("removal"),),
    )
    with pytest.raises(TransformOutputDispositionAuthorityError, match="disjoint"):
        authority_module._construct_verified_envelope(
            **{
                **kwargs,
                "generation_sequence": 2,
                "prior_envelope_sha256": _digest("prior-envelope"),
                "tombstones": (tombstone,),
            }
        )
    edge = cast("tuple[TransformOutputDependencyV1, ...]", kwargs["dependencies"])[0]
    with pytest.raises(TransformOutputDispositionAuthorityError, match="owner ordinals"):
        authority_module._construct_verified_envelope(**{**kwargs, "dependencies": (edge, edge)})
    wrong_contract_edge = TransformOutputDependencyV1(
        output_name="fact_beta",
        ordinal=0,
        dependency_id="dim_alpha",
        dependency_kind="transform_output",
        dependency_contract_sha256=_digest("foreign-dependency"),
    )
    with pytest.raises(TransformOutputDispositionAuthorityError, match="structural contract"):
        authority_module._construct_verified_envelope(
            **{
                **kwargs,
                "dependencies": (
                    wrong_contract_edge,
                    cast("tuple[TransformOutputDependencyV1, ...]", kwargs["dependencies"])[1],
                ),
            }
        )
    assert structural.tables[1].dependencies == ("dim_alpha", "stg_beta")


def test_envelope_enforces_capability_graph_and_exact_evidence_closure() -> None:
    packet = _authority_packet(include_fact=True, alpha_state="observed_only_experimental")
    with pytest.raises(TransformOutputDispositionAuthorityError, match="not active"):
        authority_module._construct_verified_envelope(**packet)

    packet = _authority_packet()
    entries = cast("tuple[CurrentTransformOutputDispositionV1, ...]", packet["entries"])
    with pytest.raises(TransformOutputDispositionAuthorityError, match="absent"):
        authority_module._construct_verified_envelope(
            **{
                **packet,
                "entries": (replace(entries[0], evidence_references=(_evidence("foreign"),)),),
            }
        )


def test_noninitial_generation_links_additions_removals_and_tombstones_exactly() -> None:
    packet = _authority_packet()
    entry = cast("tuple[CurrentTransformOutputDispositionV1, ...]", packet["entries"])[0]
    proof_pack = cast("TransformOutputDispositionProofPackV1", packet["proof_pack"])
    evidence_sha256 = proof_pack.source_bundle.members_for_role("prior_or_initial_history")[
        0
    ].member_sha256
    addition = TransformOutputChangeV1(
        change_kind="structural_addition",
        output_name=entry.output_name,
        prior_entry_sha256=None,
        current_entry_sha256=entry.entry_sha256,
        prior_state=None,
        current_state=entry.state,
        prior_table_contract_sha256=None,
        current_table_contract_sha256=entry.table_contract_sha256,
        evidence_sha256s=(evidence_sha256,),
    )
    addition_packet = {
        **packet,
        "generation_sequence": 2,
        "prior_envelope_sha256": _digest("prior-envelope"),
        "changes": (addition,),
    }
    envelope = authority_module._construct_verified_envelope(**addition_packet)
    assert envelope.changes == (addition,)

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
        last_entry_sha256=cast("str", removal.prior_entry_sha256),
        removal_change_sha256=removal.change_sha256,
        first_tombstone_generation_sequence=2,
        prior_envelope_sha256=_digest("prior-envelope"),
        removal_reason_code="contract_removed",
        removal_evidence_sha256s=(evidence_sha256,),
    )
    removal_envelope = authority_module._construct_verified_envelope(
        **{
            **packet,
            "generation_sequence": 2,
            "prior_envelope_sha256": _digest("prior-envelope"),
            "changes": (removal,),
            "tombstones": (tombstone,),
        }
    )
    assert removal_envelope.tombstone_output_names == ("fact_retired",)
    with pytest.raises(TransformOutputDispositionAuthorityError, match="new tombstone"):
        authority_module._construct_verified_envelope(
            **{
                **packet,
                "generation_sequence": 2,
                "prior_envelope_sha256": _digest("prior-envelope"),
                "tombstones": (tombstone,),
            }
        )
