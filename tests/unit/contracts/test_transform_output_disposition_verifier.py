from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from nbadb.contracts import transform_output_disposition_authored as authored_module
from nbadb.contracts import transform_output_disposition_authority as authority_module
from nbadb.contracts import transform_output_disposition_history as history_module
from nbadb.contracts import transform_output_disposition_verifier as verifier_module
from nbadb.contracts import transform_output_staging_input_authority as staging_module
from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
    TransformOutputDependencyV1,
    TransformOutputDispositionAuthorityError,
    TransformOutputEvidenceReferenceV1,
    TransformOutputRemovedTombstoneV1,
    TransformOutputSemanticClaimV1,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    TransformOutputDispositionAuditMetadataV1,
    TransformOutputDispositionProofPackV1,
    TransformOutputDispositionSourceBundleV1,
    TransformOutputDispositionSourceMemberV1,
    TransformOutputDispositionValidationEvidenceV1,
    decode_canonical_json_bytes_v1,
    persisted_canonical_json_bytes_v1,
)
from nbadb.contracts.transform_output_disposition_structural import (
    TransformOutputStructuralAuthorityV1,
    TransformOutputStructuralTableAuthorityV1,
)
from nbadb.contracts.transform_output_disposition_verifier import (
    TransformOutputDispositionVerificationError,
    verify_transform_output_disposition_envelope,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nbadb.contracts.transform_output_staging_input_authority import (
        RegisteredStagingInputContractInventoryV1,
    )


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _structural_authority(
    *,
    cycle: bool = False,
) -> TransformOutputStructuralAuthorityV1:
    dim_dependencies = ("fact_fictional_beta",) if cycle else ("stg_fictional_alpha",)
    fact_dependencies = ("dim_fictional_alpha", "stg_fictional_beta")
    tables = (
        TransformOutputStructuralTableAuthorityV1(
            output_name="dim_fictional_alpha",
            table_family="dim",
            table_contract_sha256=_sha("dim-table-contract"),
            schema_sha256=_sha("dim-schema"),
            transform_sha256=_sha("dim-transform"),
            ordered_columns=("alpha_id", "alpha_label"),
            dependencies=dim_dependencies,
        ),
        TransformOutputStructuralTableAuthorityV1(
            output_name="fact_fictional_beta",
            table_family="fact",
            table_contract_sha256=_sha("fact-table-contract"),
            schema_sha256=_sha("fact-schema"),
            transform_sha256=_sha("fact-transform"),
            ordered_columns=("beta_id", "alpha_id"),
            dependencies=fact_dependencies,
        ),
    )
    return TransformOutputStructuralAuthorityV1(
        output_names=tuple(table.output_name for table in tables),
        star_model_contract_sha256=_sha("fictional-star-contract"),
        tables=tables,
    )


def _entry(
    table: TransformOutputStructuralTableAuthorityV1,
    *,
    state: str,
    evidence_projection: authored_module.AuthoredTransformOutputEvidenceProjectionV1,
) -> CurrentTransformOutputDispositionV1:
    policy_values = {
        "active": (True, True, True, True, True),
        "observed_only_experimental": (True, True, False, False, False),
        "contract_not_modeled": (False, False, False, False, False),
    }[state]
    policy = TransformOutputCapabilityPolicyV1(*policy_values)
    claim = TransformOutputSemanticClaimV1(
        claim_id=f"claim:{table.output_name}",
        claim_kind="fictional_test_claim",
        claim_sha256=_sha(f"claim:{table.output_name}"),
        evidence_sha256s=(evidence_projection.evidence_sha256,),
    )
    evidence = TransformOutputEvidenceReferenceV1(
        evidence_class="fictional_test_evidence",
        reference_id=evidence_projection.reference_id,
        evidence_sha256=evidence_projection.evidence_sha256,
    )
    return CurrentTransformOutputDispositionV1(
        output_name=table.output_name,
        family=table.table_family,
        table_contract_sha256=table.table_contract_sha256,
        schema_identity_sha256=table.schema_sha256,
        transform_identity_sha256=table.transform_sha256,
        ordered_columns_sha256=table.ordered_column_inventory_sha256,
        dependency_identity_sha256=table.dependency_inventory_sha256,
        state=cast(
            "authority_module.TransformOutputDispositionState",
            state,
        ),
        capability_policy=policy,
        semantic_claims=(claim,),
        reason_code="fictional_test_reason",
        evidence_references=(evidence,),
        revalidation_triggers=("contract_change",),
    )


def _entries(
    structural: TransformOutputStructuralAuthorityV1,
    *,
    fact_state: str = "observed_only_experimental",
) -> tuple[CurrentTransformOutputDispositionV1, ...]:
    projections = _evidence_projections(structural)
    return (
        _entry(
            structural.tables[0],
            state="active",
            evidence_projection=projections[0],
        ),
        _entry(
            structural.tables[1],
            state=fact_state,
            evidence_projection=projections[1],
        ),
    )


def _evidence_projections(
    structural: TransformOutputStructuralAuthorityV1,
) -> tuple[authored_module.AuthoredTransformOutputEvidenceProjectionV1, ...]:
    return tuple(
        authored_module.AuthoredTransformOutputEvidenceProjectionV1(
            output_name=table.output_name,
            evidence_class="fictional_test_evidence",
            reference_id=f"reference-{table.output_name.replace('_', '-')}",
            evidence_payload={
                "schema_version": 1,
                "kind": "fictional_table_local_evidence",
                "output_name": table.output_name,
                "table_authority_sha256": table.table_authority_sha256,
            },
        )
        for table in structural.tables
    )


def _authored_decision(
    entry: CurrentTransformOutputDispositionV1,
    table: TransformOutputStructuralTableAuthorityV1,
    *,
    revision: int,
) -> authored_module.AuthoredCurrentTransformOutputDecisionV1:
    return authored_module.AuthoredCurrentTransformOutputDecisionV1(
        output_name=entry.output_name,
        authored_decision_revision=revision,
        structural_table_authority_sha256=table.table_authority_sha256,
        state=entry.state,
        capability_policy=entry.capability_policy,
        semantic_claims=entry.semantic_claims,
        reason_code=entry.reason_code,
        evidence_references=entry.evidence_references,
        revalidation_triggers=entry.revalidation_triggers,
    )


def _initial_authored_authority(
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
) -> authored_module.CompiledAuthoredTransformOutputDispositionAuthorityV1:
    corpus = authored_module.AuthoredTransformOutputDispositionCorpusV1(
        generation_sequence=1,
        prior_authored_authority_sha256=None,
        structural_authority_sha256=structural.authority_sha256,
        star_model_contract_sha256=structural.star_model_contract_sha256,
        current_decisions=tuple(
            _authored_decision(entry, table, revision=1)
            for entry, table in zip(entries, structural.tables, strict=True)
        ),
        removal_decisions=(),
        evidence_projections=_evidence_projections(structural),
    )
    return authored_module._compile_authored_transform_output_disposition_authority(
        corpus.canonical_bytes(),
        structural,
    )


def _successor_authored_authority(
    prior: authored_module.CompiledAuthoredTransformOutputDispositionAuthorityV1,
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
) -> authored_module.CompiledAuthoredTransformOutputDispositionAuthorityV1:
    prior_by_name = {decision.output_name: decision for decision in prior.corpus.current_decisions}
    decisions = []
    for entry, table in zip(entries, structural.tables, strict=True):
        candidate = _authored_decision(entry, table, revision=2)
        previous = prior_by_name[entry.output_name]
        decisions.append(
            previous
            if candidate._decision_body_dict() == previous._decision_body_dict()
            else candidate
        )
    corpus = authored_module.AuthoredTransformOutputDispositionCorpusV1(
        generation_sequence=2,
        prior_authored_authority_sha256=prior.corpus.authored_authority_sha256,
        structural_authority_sha256=structural.authority_sha256,
        star_model_contract_sha256=structural.star_model_contract_sha256,
        current_decisions=tuple(decisions),
        removal_decisions=prior.corpus.removal_decisions,
        evidence_projections=prior.corpus.evidence_projections,
    )
    corpus.validate_successor_of(prior.corpus)
    return authored_module._compile_authored_transform_output_disposition_authority(
        corpus.canonical_bytes(),
        structural,
    )


def _staging_inventory(
    structural: TransformOutputStructuralAuthorityV1,
) -> RegisteredStagingInputContractInventoryV1:
    dependency_ids = sorted(
        {
            dependency
            for table in structural.tables
            for dependency in table.dependencies
            if dependency.startswith("stg_")
        }
    )
    entries = tuple(
        staging_module._build_entry(
            dependency_id=dependency_id,
            route_ids=(f"route:{dependency_id}",),
            route_contract_sha256s=(_sha(f"route:{dependency_id}"),),
            schema_module="tests.fictional_staging",
            schema_class=f"{dependency_id.title()}Schema",
            staging_schema_sha256=_sha(f"schema:{dependency_id}"),
        )
        for dependency_id in dependency_ids
    )
    return staging_module._build_inventory(
        entries,
        structural_output_names=structural.output_names,
        star_model_contract_sha256=structural.star_model_contract_sha256,
    )


def _dependencies(
    structural: TransformOutputStructuralAuthorityV1,
    staging_inventory: RegisteredStagingInputContractInventoryV1,
) -> tuple[TransformOutputDependencyV1, ...]:
    rows: list[TransformOutputDependencyV1] = []
    table_by_name = {table.output_name: table for table in structural.tables}
    staging_by_name = {entry.dependency_id: entry for entry in staging_inventory.entries}
    for table in structural.tables:
        for ordinal, dependency_id in enumerate(table.dependencies):
            target = table_by_name.get(dependency_id)
            rows.append(
                TransformOutputDependencyV1(
                    output_name=table.output_name,
                    ordinal=ordinal,
                    dependency_id=dependency_id,
                    dependency_kind=("transform_output" if target is not None else "staging_input"),
                    dependency_contract_sha256=(
                        target.table_contract_sha256
                        if target is not None
                        else staging_by_name[dependency_id].contract_sha256
                    ),
                )
            )
    return tuple(sorted(rows, key=lambda item: (item.output_name, item.ordinal)))


def _history_projection() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": verifier_module._HISTORY_KIND,
        "prior_generation_sequence": 0,
        "prior_envelope_sha256": None,
        "prior_entries": [],
        "prior_tombstones": [],
    }


def _member(
    *,
    path: str,
    role: str,
    projection: object,
) -> TransformOutputDispositionSourceMemberV1:
    return TransformOutputDispositionSourceMemberV1.from_typed_projection(
        normalized_path=path,
        role=cast("verifier_module.SourceMemberRole", role),
        media_type="application/json",
        projection=projection,
    )


@dataclass(frozen=True, slots=True)
class _Fixture:
    structural: TransformOutputStructuralAuthorityV1
    authored: authored_module.CompiledAuthoredTransformOutputDispositionAuthorityV1
    entries: tuple[CurrentTransformOutputDispositionV1, ...]
    dependencies: tuple[TransformOutputDependencyV1, ...]
    staging_inventory: RegisteredStagingInputContractInventoryV1
    proof_pack: TransformOutputDispositionProofPackV1
    audit_metadata: TransformOutputDispositionAuditMetadataV1
    raw: bytes


def _fixture(
    *,
    verifier_source_bytes: bytes | None = None,
    claimed_result_sha256: str | None = None,
    validation_projection: object | None = None,
    fact_state: str = "observed_only_experimental",
) -> _Fixture:
    structural = _structural_authority()
    staging_inventory = _staging_inventory(structural)
    actual_verifier_bytes = Path(verifier_module.__file__).read_bytes()
    source_bytes = actual_verifier_bytes if verifier_source_bytes is None else verifier_source_bytes
    entries = _entries(structural, fact_state=fact_state)
    authored = _initial_authored_authority(structural, entries)
    dependencies = _dependencies(structural, staging_inventory)
    history = verifier_module._PriorHistory(0, None, (), ())
    derived = verifier_module._derive_authority(
        structural=structural,
        entries=entries,
        tombstones=(),
        changes=(),
        dependencies=dependencies,
        staging_inventory=staging_inventory,
        generation_sequence=1,
        prior_envelope_sha256=None,
        history=history,
    )
    result_sha256 = verifier_module._result_sha256(
        structural=structural,
        entries=entries,
        tombstones=(),
        changes=(),
        dependencies=dependencies,
        generation_sequence=1,
        prior_envelope_sha256=None,
        authored_decision_authority_sha256=authored.authority_sha256,
        derived=derived,
    )
    members = [
        *verifier_module._expected_authored_source_members(authored),
        TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path=verifier_module._DEPENDENCIES_PATH,
            role="dependencies",
            media_type="application/json",
            content=staging_inventory.canonical_bytes(),
        ),
        _member(
            path=verifier_module._HISTORY_PATH,
            role="prior_or_initial_history",
            projection=_history_projection(),
        ),
        _member(
            path=verifier_module._PROOF_INPUTS_PATH,
            role="proof_inputs",
            projection=verifier_module._proof_inputs_projection(
                structural=structural,
                entries=entries,
                tombstones=(),
                changes=(),
                dependencies=dependencies,
                generation_sequence=1,
                prior_envelope_sha256=None,
                authored_decision_authority_sha256=(authored.authority_sha256),
            ),
        ),
        _member(
            path=verifier_module._STAR_PROJECTION_PATH,
            role="star_projection",
            projection=verifier_module._star_projection(structural),
        ),
        _member(
            path=verifier_module._STRUCTURAL_DISCOVERY_PATH,
            role="structural_discovery",
            projection=structural.to_dict(),
        ),
        _member(
            path=verifier_module._VALIDATION_EVIDENCE_PATH,
            role="validation_evidence",
            projection=(
                verifier_module._validation_cases_projection()
                if validation_projection is None
                else validation_projection
            ),
        ),
        TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path=verifier_module._VERIFIER_SOURCE_PATH,
            role="verifier_source",
            media_type="text/x-python",
            content=source_bytes,
        ),
    ]
    bundle = TransformOutputDispositionSourceBundleV1(
        members=tuple(sorted(members, key=lambda item: item.normalized_path))
    )
    proof_input = bundle.members_for_role("proof_inputs")[0]
    validation_member = bundle.members_for_role("validation_evidence")[0]
    validation_rows = tuple(
        TransformOutputDispositionValidationEvidenceV1(
            case_id=case_id,
            validation_class=cast("verifier_module.ValidationClass", validation_class),
            proof_input_member_sha256=proof_input.member_sha256,
            evidence_member_sha256s=(validation_member.member_sha256,),
            expected_outcome=("accepted" if validation_class == "positive" else "rejected"),
            observed_outcome=("accepted" if validation_class == "positive" else "rejected"),
        )
        for case_id, validation_class, _operation in verifier_module._VALIDATION_CASES
    )
    proof_pack = TransformOutputDispositionProofPackV1(
        source_bundle=bundle,
        claimed_reconstructed_result_sha256=(
            result_sha256 if claimed_result_sha256 is None else claimed_result_sha256
        ),
        validation_evidence=validation_rows,
    )
    audit_metadata = TransformOutputDispositionAuditMetadataV1(
        proof_pack_root_sha256=proof_pack.proof_pack_root_sha256,
        author_task_id="fictional-same-task",
        author_role="fictional-same-role",
        reviewer_task_id="fictional-same-task",
        reviewer_role="fictional-same-role",
    )
    envelope = authority_module._construct_verified_envelope(
        token=authority_module._VERIFIED_ENVELOPE_CONSTRUCTION_TOKEN,
        structural_authority=structural,
        proof_pack=proof_pack,
        audit_metadata=audit_metadata,
        entries=entries,
        tombstones=(),
        changes=(),
        dependencies=dependencies,
        authored_decision_authority_sha256=authored.authority_sha256,
        generation_sequence=1,
        prior_envelope_sha256=None,
    )
    return _Fixture(
        structural=structural,
        authored=authored,
        entries=entries,
        dependencies=dependencies,
        staging_inventory=staging_inventory,
        proof_pack=proof_pack,
        audit_metadata=audit_metadata,
        raw=envelope.canonical_bytes(),
    )


def _successor_fixture(
    prior: _Fixture,
    *,
    embedded_prior_bytes: bytes | None = None,
) -> _Fixture:
    structural = prior.structural
    staging_inventory = prior.staging_inventory
    verifier_bytes = Path(verifier_module.__file__).read_bytes()
    verifier_sha256 = hashlib.sha256(verifier_bytes).hexdigest()
    current_fact = replace(
        prior.entries[1],
        state="active",
        capability_policy=TransformOutputCapabilityPolicyV1(True, True, True, True, True),
    )
    entries = (prior.entries[0], current_fact)
    authored = _successor_authored_authority(prior.authored, structural, entries)
    evidence_sha256s = tuple(item.evidence_sha256 for item in current_fact.evidence_references)
    change = authority_module.TransformOutputChangeV1(
        change_kind="state_transition",
        output_name=current_fact.output_name,
        prior_entry_sha256=prior.entries[1].entry_sha256,
        current_entry_sha256=current_fact.entry_sha256,
        prior_state=prior.entries[1].state,
        current_state=current_fact.state,
        prior_table_contract_sha256=prior.entries[1].table_contract_sha256,
        current_table_contract_sha256=current_fact.table_contract_sha256,
        evidence_sha256s=evidence_sha256s,
    )
    changes = (change,)
    dependencies = prior.dependencies
    prior_payload = _payload(prior.raw)
    prior_envelope_sha256 = cast("str", prior_payload["envelope_sha256"])
    history = verifier_module._PriorHistory(
        prior_generation_sequence=1,
        prior_envelope_sha256=prior_envelope_sha256,
        entries=prior.entries,
        tombstones=(),
    )
    prior_member = TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
        normalized_path=history_module._envelope_member_path(1),
        role="prior_or_initial_history",
        media_type="application/json",
        content=prior.raw,
    )
    prior_generation = history_module._construct_generation(
        token=history_module._GENERATION_TOKEN,
        generation_sequence=1,
        envelope_member=prior_member,
        staging_snapshot=history_module._construct_staging_snapshot(
            token=history_module._STAGING_TOKEN,
            inventory=prior.staging_inventory,
        ),
    )
    history_chain = history_module._construct_chain(
        token=history_module._CHAIN_TOKEN,
        generations=(prior_generation,),
    )
    derived = verifier_module._derive_authority(
        structural=structural,
        entries=entries,
        tombstones=(),
        changes=changes,
        dependencies=dependencies,
        staging_inventory=staging_inventory,
        generation_sequence=2,
        prior_envelope_sha256=prior_envelope_sha256,
        history=history,
    )
    result_sha256 = verifier_module._result_sha256(
        structural=structural,
        entries=entries,
        tombstones=(),
        changes=changes,
        dependencies=dependencies,
        generation_sequence=2,
        prior_envelope_sha256=prior_envelope_sha256,
        authored_decision_authority_sha256=authored.authority_sha256,
        derived=derived,
    )
    members = [
        *verifier_module._expected_authored_source_members(authored),
        TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path=verifier_module._DEPENDENCIES_PATH,
            role="dependencies",
            media_type="application/json",
            content=staging_inventory.canonical_bytes(),
        ),
        TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path=verifier_module._HISTORY_PATH,
            role="prior_or_initial_history",
            media_type="application/json",
            content=(
                history_chain.canonical_bytes()
                if embedded_prior_bytes is None
                else embedded_prior_bytes
            ),
        ),
        _member(
            path=verifier_module._PROOF_INPUTS_PATH,
            role="proof_inputs",
            projection=verifier_module._proof_inputs_projection(
                structural=structural,
                entries=entries,
                tombstones=(),
                changes=changes,
                dependencies=dependencies,
                generation_sequence=2,
                prior_envelope_sha256=prior_envelope_sha256,
                authored_decision_authority_sha256=(authored.authority_sha256),
            ),
        ),
        _member(
            path=verifier_module._STAR_PROJECTION_PATH,
            role="star_projection",
            projection=verifier_module._star_projection(structural),
        ),
        _member(
            path=verifier_module._STRUCTURAL_DISCOVERY_PATH,
            role="structural_discovery",
            projection=structural.to_dict(),
        ),
        _member(
            path=verifier_module._VALIDATION_EVIDENCE_PATH,
            role="validation_evidence",
            projection=verifier_module._validation_cases_projection(),
        ),
        TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path=verifier_module._VERIFIER_SOURCE_PATH,
            role="verifier_source",
            media_type="text/x-python",
            content=verifier_bytes,
        ),
    ]
    assert verifier_sha256 == members[-1].content_sha256
    bundle = TransformOutputDispositionSourceBundleV1(
        members=tuple(sorted(members, key=lambda item: item.normalized_path))
    )
    proof_input = bundle.members_for_role("proof_inputs")[0]
    validation_member = bundle.members_for_role("validation_evidence")[0]
    proof_pack = TransformOutputDispositionProofPackV1(
        source_bundle=bundle,
        claimed_reconstructed_result_sha256=result_sha256,
        validation_evidence=tuple(
            TransformOutputDispositionValidationEvidenceV1(
                case_id=case_id,
                validation_class=cast(
                    "verifier_module.ValidationClass",
                    validation_class,
                ),
                proof_input_member_sha256=proof_input.member_sha256,
                evidence_member_sha256s=(validation_member.member_sha256,),
                expected_outcome=("accepted" if validation_class == "positive" else "rejected"),
                observed_outcome=("accepted" if validation_class == "positive" else "rejected"),
            )
            for case_id, validation_class, _operation in verifier_module._VALIDATION_CASES
        ),
    )
    audit_metadata = TransformOutputDispositionAuditMetadataV1(
        proof_pack_root_sha256=proof_pack.proof_pack_root_sha256,
        author_task_id="fictional-successor-author",
        author_role="fictional-author-role",
        reviewer_task_id="fictional-successor-reviewer",
        reviewer_role="fictional-reviewer-role",
    )
    envelope = authority_module._construct_verified_envelope(
        token=authority_module._VERIFIED_ENVELOPE_CONSTRUCTION_TOKEN,
        structural_authority=structural,
        proof_pack=proof_pack,
        audit_metadata=audit_metadata,
        entries=entries,
        tombstones=(),
        changes=changes,
        dependencies=dependencies,
        authored_decision_authority_sha256=authored.authority_sha256,
        generation_sequence=2,
        prior_envelope_sha256=prior_envelope_sha256,
    )
    return _Fixture(
        structural=structural,
        authored=authored,
        entries=entries,
        dependencies=dependencies,
        staging_inventory=staging_inventory,
        proof_pack=proof_pack,
        audit_metadata=audit_metadata,
        raw=envelope.canonical_bytes(),
    )


def _payload(raw: bytes) -> dict[str, object]:
    return cast("dict[str, object]", decode_canonical_json_bytes_v1(raw, persisted=True))


def _raw(payload: Mapping[str, object]) -> bytes:
    return persisted_canonical_json_bytes_v1(dict(payload))


def _admit(
    monkeypatch: pytest.MonkeyPatch,
    fixture: _Fixture,
) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    _patch_current_authorities(monkeypatch, fixture)
    return verify_transform_output_disposition_envelope(fixture.raw)


def _patch_current_authorities(
    monkeypatch: pytest.MonkeyPatch,
    fixture: _Fixture,
) -> None:
    monkeypatch.setattr(
        verifier_module,
        "compile_current_transform_output_structural_authority",
        lambda: fixture.structural,
    )
    monkeypatch.setattr(
        verifier_module,
        "compile_registered_staging_input_contract_inventory",
        lambda: fixture.staging_inventory,
    )
    monkeypatch.setattr(
        verifier_module,
        "load_current_transform_output_disposition_authored_authority",
        lambda: fixture.authored,
    )
    monkeypatch.setattr(
        staging_module,
        "compile_registered_staging_input_contract_inventory",
        lambda: fixture.staging_inventory,
    )


def test_fictional_initial_envelope_fresh_replays_and_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    observed = _admit(monkeypatch, fixture)

    assert observed.canonical_bytes() == fixture.raw
    assert observed.structural_output_names == (
        "dim_fictional_alpha",
        "fact_fictional_beta",
    )
    assert observed.active_output_names == ("dim_fictional_alpha",)
    assert observed.experimental_output_names == ("fact_fictional_beta",)
    assert observed.topological_order == (
        "dim_fictional_alpha",
        "fact_fictional_beta",
    )
    assert observed.audit_metadata.establishes_independence is False
    assert observed.authored_decision_authority_sha256 == fixture.authored.authority_sha256
    assert observed.authored_decision_authority_sha256 != (
        fixture.authored.corpus.authored_authority_sha256
    )
    assert (
        VerifiedTransformOutputDispositionAuthorityEnvelopeV1.from_canonical_bytes(fixture.raw)
        == observed
    )


def test_fictional_successor_replays_exact_prior_envelope_and_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    successor = _successor_fixture(_fixture())
    observed = _admit(monkeypatch, successor)

    assert observed.generation_sequence == 2
    assert observed.changes[0].change_kind == "state_transition"
    assert observed.active_output_names == (
        "dim_fictional_alpha",
        "fact_fictional_beta",
    )


def test_successor_rejects_resealed_but_mutated_prior_envelope_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior = _fixture()
    mutated_prior = _payload(prior.raw)
    mutated_prior["envelope_sha256"] = _sha("mutated-prior-envelope")
    successor = _successor_fixture(
        prior,
        embedded_prior_bytes=_raw(mutated_prior),
    )
    _patch_current_authorities(monkeypatch, successor)

    with pytest.raises(TransformOutputDispositionVerificationError, match="history|envelope"):
        verify_transform_output_disposition_envelope(successor.raw)


def test_public_verifier_accepts_raw_bytes_only_and_sealed_dto_has_no_public_constructor() -> None:
    signature = inspect.signature(verify_transform_output_disposition_envelope)
    assert tuple(signature.parameters) == ("raw",)
    assert signature.parameters["raw"].default is inspect.Parameter.empty
    assert not {
        "authority",
        "proof",
        "result",
        "root",
        "count",
        "verified",
        "resolver",
    } & set(signature.parameters)

    with pytest.raises(TypeError, match="from_canonical_bytes"):
        VerifiedTransformOutputDispositionAuthorityEnvelopeV1()
    with pytest.raises(TransformOutputDispositionVerificationError, match="exact bytes"):
        verify_transform_output_disposition_envelope(bytearray(b"{}"))  # type: ignore[arg-type]


@pytest.mark.parametrize("field_name", ["structural_authority", "proof_pack", "entries"])
def test_envelope_rejects_missing_top_level_fields(
    field_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    payload = _payload(fixture.raw)
    del payload[field_name]
    monkeypatch.setattr(
        verifier_module,
        "compile_current_transform_output_structural_authority",
        lambda: fixture.structural,
    )

    with pytest.raises(TransformOutputDispositionVerificationError, match="missing="):
        verify_transform_output_disposition_envelope(_raw(payload))


def test_envelope_rejects_extra_duplicate_noncanonical_and_bool_integer_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    monkeypatch.setattr(
        verifier_module,
        "compile_current_transform_output_structural_authority",
        lambda: fixture.structural,
    )
    payload = _payload(fixture.raw)
    payload["foreign"] = True
    with pytest.raises(TransformOutputDispositionVerificationError, match="unexpected=foreign"):
        verify_transform_output_disposition_envelope(_raw(payload))

    payload = _payload(fixture.raw)
    payload["generation_sequence"] = True
    with pytest.raises(TransformOutputDispositionVerificationError, match="exact integer"):
        verify_transform_output_disposition_envelope(_raw(payload))

    noncanonical = fixture.raw.replace(b'"active_output_names":', b'"active_output_names" :', 1)
    with pytest.raises(TransformOutputDispositionVerificationError, match="canonical byte form"):
        verify_transform_output_disposition_envelope(noncanonical)

    duplicate = fixture.raw.replace(
        b"{",
        b'{"kind":"nbadb_verified_transform_output_disposition_authority_envelope",',
        1,
    )
    with pytest.raises(TransformOutputDispositionVerificationError, match="duplicate"):
        verify_transform_output_disposition_envelope(duplicate)

    with pytest.raises(
        TransformOutputDispositionVerificationError,
        match="canonical byte form",
    ):
        verify_transform_output_disposition_envelope(fixture.raw + b"\n")


def test_fresh_structural_recompile_rejects_stale_or_foreign_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    foreign = replace(
        fixture.structural,
        star_model_contract_sha256=_sha("foreign-star-contract"),
    )
    _patch_current_authorities(monkeypatch, fixture)
    monkeypatch.setattr(
        verifier_module,
        "compile_current_transform_output_structural_authority",
        lambda: foreign,
    )

    with pytest.raises(TransformOutputDispositionVerificationError, match="fresh two-source"):
        verify_transform_output_disposition_envelope(fixture.raw)


def test_self_resealed_claimed_result_is_rejected_by_independent_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(claimed_result_sha256=_sha("self-certified-result"))
    _patch_current_authorities(monkeypatch, fixture)

    with pytest.raises(TransformOutputDispositionVerificationError, match="claimed result"):
        verify_transform_output_disposition_envelope(fixture.raw)


def test_coherently_resealed_candidate_cannot_replace_fixed_authored_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trusted = _fixture()
    resealed = _fixture(fact_state="active")
    assert resealed.entries != trusted.entries
    assert resealed.authored.authority_sha256 != trusted.authored.authority_sha256
    _patch_current_authorities(monkeypatch, resealed)
    monkeypatch.setattr(
        verifier_module,
        "load_current_transform_output_disposition_authored_authority",
        lambda: trusted.authored,
    )

    with pytest.raises(
        TransformOutputDispositionVerificationError,
        match="fresh fixed repository authority",
    ):
        verify_transform_output_disposition_envelope(resealed.raw)


def test_embedded_verifier_source_must_equal_current_implementation_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = Path(verifier_module.__file__).read_bytes()
    fixture = _fixture(verifier_source_bytes=current + b"# fictional foreign verifier\n")
    _patch_current_authorities(monkeypatch, fixture)

    with pytest.raises(TransformOutputDispositionVerificationError, match="current implementation"):
        verify_transform_output_disposition_envelope(fixture.raw)


def test_validation_case_inventory_is_fixed_and_cannot_be_blanket_substituted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(
        validation_projection={
            "schema_version": 1,
            "kind": verifier_module._VALIDATION_CASES_KIND,
            "cases": [
                {
                    "case_id": "01-positive-exact-reconstruction",
                    "validation_class": "positive",
                    "operation": "exact_reconstruction",
                }
            ],
        }
    )
    _patch_current_authorities(monkeypatch, fixture)

    with pytest.raises(TransformOutputDispositionVerificationError, match="validation_evidence"):
        verify_transform_output_disposition_envelope(fixture.raw)


@pytest.mark.parametrize(
    ("collection", "expected"),
    [
        ("entries", "authored"),
        ("dependencies", "proof_inputs"),
    ],
)
def test_missing_current_rows_fail_before_sealed_construction(
    collection: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    payload = _payload(fixture.raw)
    rows = cast("list[object]", payload[collection])
    payload[collection] = rows[1:]
    _patch_current_authorities(monkeypatch, fixture)

    with pytest.raises(TransformOutputDispositionVerificationError, match=expected):
        verify_transform_output_disposition_envelope(_raw(payload))


def test_capability_mutation_is_rejected_even_when_nested_entry_is_resealed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    payload = _payload(fixture.raw)
    entries = cast("list[dict[str, object]]", payload["entries"])
    policy = cast("dict[str, object]", entries[0]["capability_policy"])
    policy["stable_load"] = False
    policy["policy_sha256"] = _sha("resealed-policy")
    entries[0]["entry_sha256"] = _sha("resealed-entry")
    _patch_current_authorities(monkeypatch, fixture)

    with pytest.raises(TransformOutputDispositionVerificationError, match="policy|capability"):
        verify_transform_output_disposition_envelope(_raw(payload))


def test_initial_generation_rejects_foreign_change_and_prior_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    payload = _payload(fixture.raw)
    payload["prior_envelope_sha256"] = _sha("foreign-prior")
    _patch_current_authorities(monkeypatch, fixture)

    with pytest.raises(TransformOutputDispositionVerificationError, match="proof_inputs"):
        verify_transform_output_disposition_envelope(_raw(payload))


def test_audit_labels_never_substitute_for_exact_proof_pack_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    payload = _payload(fixture.raw)
    audit = cast("dict[str, object]", payload["audit_metadata"])
    audit["proof_pack_root_sha256"] = _sha("foreign-proof-pack")
    audit["audit_metadata_sha256"] = _sha("resealed-audit")
    monkeypatch.setattr(
        verifier_module,
        "compile_current_transform_output_structural_authority",
        lambda: fixture.structural,
    )

    with pytest.raises(TransformOutputDispositionVerificationError, match="audit|proof"):
        verify_transform_output_disposition_envelope(_raw(payload))


def test_proof_or_envelope_derived_root_substitution_is_rejected_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    _patch_current_authorities(monkeypatch, fixture)
    for field_name in (
        "authored_decision_authority_sha256",
        "entries_sha256",
        "dependency_graph_sha256",
        "topological_order_sha256",
        "generation_identity_sha256",
        "envelope_sha256",
    ):
        payload = _payload(fixture.raw)
        payload[field_name] = _sha(f"foreign:{field_name}")
        with pytest.raises(
            TransformOutputDispositionVerificationError,
            match="sealed envelope|authored decision authority",
        ):
            verify_transform_output_disposition_envelope(_raw(payload))


def test_direct_private_seal_requires_unforgeable_module_token() -> None:
    fixture = _fixture()
    with pytest.raises(TransformOutputDispositionAuthorityError, match="token"):
        authority_module._construct_verified_envelope(
            token=object(),
            structural_authority=fixture.structural,
            proof_pack=fixture.proof_pack,
            audit_metadata=fixture.audit_metadata,
            entries=fixture.entries,
            tombstones=(),
            changes=(),
            dependencies=fixture.dependencies,
            authored_decision_authority_sha256=fixture.authored.authority_sha256,
            generation_sequence=1,
            prior_envelope_sha256=None,
        )


def test_initial_evolution_validator_rejects_any_prior_or_change_state() -> None:
    fixture = _fixture()
    with pytest.raises(TransformOutputDispositionVerificationError, match="initial generation"):
        verifier_module._validate_evolution(
            entries=fixture.entries,
            tombstones=(),
            changes=(),
            generation_sequence=1,
            prior_envelope_sha256=_sha("foreign-prior"),
            history=verifier_module._PriorHistory(0, None, (), ()),
        )


def test_noninitial_state_transition_requires_one_exact_change() -> None:
    fixture = _fixture()
    prior_sha256 = _sha("fictional-prior-envelope")
    prior_entries = fixture.entries
    current_fact = replace(
        prior_entries[1],
        state="active",
        capability_policy=TransformOutputCapabilityPolicyV1(True, True, True, True, True),
    )
    current_entries = (prior_entries[0], current_fact)
    evidence_sha256s = tuple(item.evidence_sha256 for item in current_fact.evidence_references)
    transition = authority_module.TransformOutputChangeV1(
        change_kind="state_transition",
        output_name=current_fact.output_name,
        prior_entry_sha256=prior_entries[1].entry_sha256,
        current_entry_sha256=current_fact.entry_sha256,
        prior_state=prior_entries[1].state,
        current_state=current_fact.state,
        prior_table_contract_sha256=prior_entries[1].table_contract_sha256,
        current_table_contract_sha256=current_fact.table_contract_sha256,
        evidence_sha256s=evidence_sha256s,
    )
    history = verifier_module._PriorHistory(1, prior_sha256, prior_entries, ())

    verifier_module._validate_evolution(
        entries=current_entries,
        tombstones=(),
        changes=(transition,),
        generation_sequence=2,
        prior_envelope_sha256=prior_sha256,
        history=history,
    )
    with pytest.raises(TransformOutputDispositionVerificationError, match="missing"):
        verifier_module._validate_evolution(
            entries=current_entries,
            tombstones=(),
            changes=(),
            generation_sequence=2,
            prior_envelope_sha256=prior_sha256,
            history=history,
        )


def test_evolution_machine_derives_structural_addition_and_rejects_relabel() -> None:
    fixture = _fixture()
    prior_entries = (fixture.entries[0],)
    added = fixture.entries[1]
    prior_sha = _sha("prior-addition-envelope")
    change = authority_module.TransformOutputChangeV1(
        change_kind="structural_addition",
        output_name=added.output_name,
        prior_entry_sha256=None,
        current_entry_sha256=added.entry_sha256,
        prior_state=None,
        current_state=added.state,
        prior_table_contract_sha256=None,
        current_table_contract_sha256=added.table_contract_sha256,
        evidence_sha256s=tuple(ref.evidence_sha256 for ref in added.evidence_references),
    )
    verifier_module._validate_evolution(
        entries=fixture.entries,
        tombstones=(),
        changes=(change,),
        generation_sequence=2,
        prior_envelope_sha256=prior_sha,
        history=verifier_module._PriorHistory(1, prior_sha, prior_entries, ()),
    )
    relabeled = authority_module.TransformOutputChangeV1(
        change_kind="contract_rebind",
        output_name=added.output_name,
        prior_entry_sha256=_sha("fabricated-prior-entry"),
        current_entry_sha256=added.entry_sha256,
        prior_state=added.state,
        current_state=added.state,
        prior_table_contract_sha256=_sha("fabricated-prior-contract"),
        current_table_contract_sha256=added.table_contract_sha256,
        evidence_sha256s=tuple(ref.evidence_sha256 for ref in added.evidence_references),
    )
    with pytest.raises(TransformOutputDispositionVerificationError, match="misclassifies"):
        verifier_module._validate_evolution(
            entries=fixture.entries,
            tombstones=(),
            changes=(relabeled,),
            generation_sequence=2,
            prior_envelope_sha256=prior_sha,
            history=verifier_module._PriorHistory(1, prior_sha, prior_entries, ()),
        )


def test_evolution_machine_derives_contract_rebind_for_structural_and_semantic_drift() -> None:
    fixture = _fixture()
    prior = fixture.entries[0]
    current = replace(
        prior,
        table_contract_sha256=_sha("rebound-table"),
        schema_identity_sha256=_sha("rebound-schema"),
        transform_identity_sha256=_sha("rebound-transform"),
        ordered_columns_sha256=_sha("rebound-columns"),
        dependency_identity_sha256=_sha("rebound-dependencies"),
    )
    prior_sha = _sha("prior-rebind-envelope")
    change = authority_module.TransformOutputChangeV1(
        change_kind="contract_rebind",
        output_name=current.output_name,
        prior_entry_sha256=prior.entry_sha256,
        current_entry_sha256=current.entry_sha256,
        prior_state=prior.state,
        current_state=current.state,
        prior_table_contract_sha256=prior.table_contract_sha256,
        current_table_contract_sha256=current.table_contract_sha256,
        evidence_sha256s=tuple(ref.evidence_sha256 for ref in current.evidence_references),
    )
    history = verifier_module._PriorHistory(1, prior_sha, (prior,), ())
    verifier_module._validate_evolution(
        entries=(current,),
        tombstones=(),
        changes=(change,),
        generation_sequence=2,
        prior_envelope_sha256=prior_sha,
        history=history,
    )

    semantic_drift = replace(prior, reason_code="authored_semantic_rebind")
    semantic_change = authority_module.TransformOutputChangeV1(
        change_kind="contract_rebind",
        output_name=semantic_drift.output_name,
        prior_entry_sha256=prior.entry_sha256,
        current_entry_sha256=semantic_drift.entry_sha256,
        prior_state=prior.state,
        current_state=semantic_drift.state,
        prior_table_contract_sha256=prior.table_contract_sha256,
        current_table_contract_sha256=semantic_drift.table_contract_sha256,
        evidence_sha256s=tuple(ref.evidence_sha256 for ref in semantic_drift.evidence_references),
    )
    verifier_module._validate_evolution(
        entries=(semantic_drift,),
        tombstones=(),
        changes=(semantic_change,),
        generation_sequence=2,
        prior_envelope_sha256=prior_sha,
        history=history,
    )


@pytest.mark.parametrize(
    ("field_name", "new_value"),
    [
        ("schema_identity_sha256", _sha("rebound-schema-only")),
        ("transform_identity_sha256", _sha("rebound-transform-only")),
        ("ordered_columns_sha256", _sha("rebound-columns-only")),
        ("dependency_identity_sha256", _sha("rebound-dependencies-only")),
        (
            "semantic_claims",
            (
                TransformOutputSemanticClaimV1(
                    claim_id="claim:dim_fictional_alpha_rebound",
                    claim_kind="fictional_test_claim",
                    claim_sha256=_sha("rebound-semantic-claim"),
                    evidence_sha256s=(_sha("rebound-semantic-evidence"),),
                ),
            ),
        ),
        ("reason_code", "authored_reason_rebind"),
        (
            "evidence_references",
            (
                TransformOutputEvidenceReferenceV1(
                    evidence_class="fictional_test_evidence",
                    reference_id="reference:dim_fictional_alpha_rebound",
                    evidence_sha256=_sha("rebound-reference-evidence"),
                ),
            ),
        ),
        ("revalidation_triggers", ("contract_change", "semantic_review")),
    ],
)
def test_same_state_table_local_drift_is_exactly_contract_rebind(
    field_name: str,
    new_value: object,
) -> None:
    fixture = _fixture()
    prior = fixture.entries[0]
    current = replace(prior, **{field_name: new_value})
    prior_sha = _sha(f"prior-{field_name}-envelope")
    change = authority_module.TransformOutputChangeV1(
        change_kind="contract_rebind",
        output_name=current.output_name,
        prior_entry_sha256=prior.entry_sha256,
        current_entry_sha256=current.entry_sha256,
        prior_state=prior.state,
        current_state=current.state,
        prior_table_contract_sha256=prior.table_contract_sha256,
        current_table_contract_sha256=current.table_contract_sha256,
        evidence_sha256s=tuple(ref.evidence_sha256 for ref in current.evidence_references),
    )

    verifier_module._validate_evolution(
        entries=(current,),
        tombstones=(),
        changes=(change,),
        generation_sequence=2,
        prior_envelope_sha256=prior_sha,
        history=verifier_module._PriorHistory(1, prior_sha, (prior,), ()),
    )


def test_state_transition_rejects_simultaneous_semantic_or_structural_drift() -> None:
    fixture = _fixture()
    prior = fixture.entries[1]
    prior_sha = _sha("prior-combined-drift-envelope")
    current = replace(
        prior,
        state="active",
        capability_policy=TransformOutputCapabilityPolicyV1(True, True, True, True, True),
        reason_code="simultaneous_semantic_drift",
    )
    transition = authority_module.TransformOutputChangeV1(
        change_kind="state_transition",
        output_name=current.output_name,
        prior_entry_sha256=prior.entry_sha256,
        current_entry_sha256=current.entry_sha256,
        prior_state=prior.state,
        current_state=current.state,
        prior_table_contract_sha256=prior.table_contract_sha256,
        current_table_contract_sha256=current.table_contract_sha256,
        evidence_sha256s=tuple(ref.evidence_sha256 for ref in current.evidence_references),
    )

    with pytest.raises(TransformOutputDispositionVerificationError, match="incompatible"):
        verifier_module._validate_evolution(
            entries=(current,),
            tombstones=(),
            changes=(transition,),
            generation_sequence=2,
            prior_envelope_sha256=prior_sha,
            history=verifier_module._PriorHistory(1, prior_sha, (prior,), ()),
        )


def test_unchanged_entry_has_no_change_row_and_rejects_extra_change() -> None:
    fixture = _fixture()
    prior = fixture.entries[0]
    prior_sha = _sha("prior-unchanged-envelope")
    history = verifier_module._PriorHistory(1, prior_sha, (prior,), ())

    verifier_module._validate_evolution(
        entries=(prior,),
        tombstones=(),
        changes=(),
        generation_sequence=2,
        prior_envelope_sha256=prior_sha,
        history=history,
    )
    extra = authority_module.TransformOutputChangeV1(
        change_kind="structural_addition",
        output_name="fact_fictional_extra",
        prior_entry_sha256=None,
        current_entry_sha256=_sha("foreign-current-entry"),
        prior_state=None,
        current_state="active",
        prior_table_contract_sha256=None,
        current_table_contract_sha256=_sha("foreign-current-contract"),
        evidence_sha256s=(_sha("foreign-change-evidence"),),
    )
    with pytest.raises(TransformOutputDispositionVerificationError, match="extra or missing"):
        verifier_module._validate_evolution(
            entries=(prior,),
            tombstones=(),
            changes=(extra,),
            generation_sequence=2,
            prior_envelope_sha256=prior_sha,
            history=history,
        )


def test_structural_addition_requires_exact_authored_decision_change() -> None:
    fixture = _fixture()
    prior = fixture.entries[0]
    added = fixture.entries[1]
    prior_sha = _sha("prior-decision-envelope")
    history = verifier_module._PriorHistory(1, prior_sha, (prior,), ())

    with pytest.raises(TransformOutputDispositionVerificationError, match="missing"):
        verifier_module._validate_evolution(
            entries=(prior, added),
            tombstones=(),
            changes=(),
            generation_sequence=2,
            prior_envelope_sha256=prior_sha,
            history=history,
        )
    wrong_evidence = authority_module.TransformOutputChangeV1(
        change_kind="structural_addition",
        output_name=added.output_name,
        prior_entry_sha256=None,
        current_entry_sha256=added.entry_sha256,
        prior_state=None,
        current_state=added.state,
        prior_table_contract_sha256=None,
        current_table_contract_sha256=added.table_contract_sha256,
        evidence_sha256s=(_sha("unrelated-decision-evidence"),),
    )
    with pytest.raises(TransformOutputDispositionVerificationError, match="evidence"):
        verifier_module._validate_evolution(
            entries=(prior, added),
            tombstones=(),
            changes=(wrong_evidence,),
            generation_sequence=2,
            prior_envelope_sha256=prior_sha,
            history=history,
        )


def test_noninitial_removal_requires_exact_new_immutable_tombstone() -> None:
    fixture = _fixture()
    prior_sha256 = _sha("fictional-prior-envelope")
    removed = fixture.entries[1]
    evidence_sha256s = tuple(item.evidence_sha256 for item in removed.evidence_references)
    removal = authority_module.TransformOutputChangeV1(
        change_kind="removal",
        output_name=removed.output_name,
        prior_entry_sha256=removed.entry_sha256,
        current_entry_sha256=None,
        prior_state=removed.state,
        current_state=None,
        prior_table_contract_sha256=removed.table_contract_sha256,
        current_table_contract_sha256=None,
        evidence_sha256s=evidence_sha256s,
    )
    tombstone = TransformOutputRemovedTombstoneV1(
        output_name=removed.output_name,
        family=removed.family,
        last_entry_sha256=removed.entry_sha256,
        removal_change_sha256=removal.change_sha256,
        first_tombstone_generation_sequence=2,
        prior_envelope_sha256=prior_sha256,
        removal_reason_code="fictional_removal",
        removal_evidence_sha256s=evidence_sha256s,
    )
    history = verifier_module._PriorHistory(1, prior_sha256, fixture.entries, ())

    verifier_module._validate_evolution(
        entries=(fixture.entries[0],),
        tombstones=(tombstone,),
        changes=(removal,),
        generation_sequence=2,
        prior_envelope_sha256=prior_sha256,
        history=history,
    )
    with pytest.raises(TransformOutputDispositionVerificationError, match="tombstone"):
        verifier_module._validate_evolution(
            entries=(fixture.entries[0],),
            tombstones=(),
            changes=(removal,),
            generation_sequence=2,
            prior_envelope_sha256=prior_sha256,
            history=history,
        )

    mutated_tombstone = replace(
        tombstone,
        removal_evidence_sha256s=(_sha("foreign-removal-evidence"),),
    )
    with pytest.raises(TransformOutputDispositionVerificationError, match="tombstone"):
        verifier_module._validate_evolution(
            entries=(fixture.entries[0],),
            tombstones=(mutated_tombstone,),
            changes=(removal,),
            generation_sequence=2,
            prior_envelope_sha256=prior_sha256,
            history=history,
        )


def test_prior_tombstones_persist_unchanged_and_permanently_reserve_names() -> None:
    fixture = _fixture()
    prior_sha = _sha("prior-persistent-tombstone-envelope")
    removal = authority_module.TransformOutputChangeV1(
        change_kind="removal",
        output_name="fact_retired_fictional",
        prior_entry_sha256=_sha("retired-entry"),
        current_entry_sha256=None,
        prior_state="active",
        current_state=None,
        prior_table_contract_sha256=_sha("retired-contract"),
        current_table_contract_sha256=None,
        evidence_sha256s=(_sha("retired-removal-evidence"),),
    )
    tombstone = TransformOutputRemovedTombstoneV1(
        output_name="fact_retired_fictional",
        family="fact",
        last_entry_sha256=cast("str", removal.prior_entry_sha256),
        removal_change_sha256=removal.change_sha256,
        first_tombstone_generation_sequence=2,
        prior_envelope_sha256=_sha("generation-one-envelope"),
        removal_reason_code="authored_retirement",
        removal_evidence_sha256s=removal.evidence_sha256s,
    )
    history = verifier_module._PriorHistory(2, prior_sha, fixture.entries, (tombstone,))

    verifier_module._validate_evolution(
        entries=fixture.entries,
        tombstones=(tombstone,),
        changes=(),
        generation_sequence=3,
        prior_envelope_sha256=prior_sha,
        history=history,
    )
    with pytest.raises(TransformOutputDispositionVerificationError, match="deleted or mutated"):
        verifier_module._validate_evolution(
            entries=fixture.entries,
            tombstones=(),
            changes=(),
            generation_sequence=3,
            prior_envelope_sha256=prior_sha,
            history=history,
        )
    with pytest.raises(TransformOutputDispositionVerificationError, match="deleted or mutated"):
        verifier_module._validate_evolution(
            entries=fixture.entries,
            tombstones=(replace(tombstone, removal_reason_code="rewritten_retirement"),),
            changes=(),
            generation_sequence=3,
            prior_envelope_sha256=prior_sha,
            history=history,
        )

    reserved_entry = fixture.entries[1]
    reserved_removal = replace(
        tombstone,
        output_name=reserved_entry.output_name,
        last_entry_sha256=_sha("reserved-prior-entry"),
    )
    reuse_history = verifier_module._PriorHistory(
        2,
        prior_sha,
        (fixture.entries[0],),
        (reserved_removal,),
    )
    with pytest.raises(TransformOutputDispositionVerificationError, match="reappears"):
        verifier_module._validate_evolution(
            entries=fixture.entries,
            tombstones=(reserved_removal,),
            changes=(),
            generation_sequence=3,
            prior_envelope_sha256=prior_sha,
            history=reuse_history,
        )


def test_dependency_graph_rejects_cycle_and_non_executable_edges() -> None:
    structural = _structural_authority(cycle=True)
    entries = _entries(structural)
    entries = (
        entries[0],
        replace(
            entries[1],
            state="active",
            capability_policy=TransformOutputCapabilityPolicyV1(
                True,
                True,
                True,
                True,
                True,
            ),
        ),
    )
    staging_inventory = _staging_inventory(structural)
    with pytest.raises(TransformOutputDispositionVerificationError, match="cycle"):
        verifier_module._derive_authority(
            structural=structural,
            entries=entries,
            tombstones=(),
            changes=(),
            dependencies=_dependencies(structural, staging_inventory),
            staging_inventory=staging_inventory,
            generation_sequence=1,
            prior_envelope_sha256=None,
            history=verifier_module._PriorHistory(0, None, (), ()),
        )


@pytest.mark.parametrize("mutation", ["duplicate", "foreign"])
def test_entry_identity_mutations_are_rejected_before_source_admission(
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture()
    payload = _payload(fixture.raw)
    entries = cast("list[dict[str, object]]", payload["entries"])
    if mutation == "duplicate":
        payload["entries"] = [entries[0], entries[0]]
    else:
        entries[0]["output_name"] = "dim_fictional_foreign"
        entries[0]["entry_sha256"] = _sha("resealed-foreign-entry")
    monkeypatch.setattr(
        verifier_module,
        "compile_current_transform_output_structural_authority",
        lambda: fixture.structural,
    )

    with pytest.raises(
        TransformOutputDispositionVerificationError,
        match="unique|typed reconstruction|structural",
    ):
        verify_transform_output_disposition_envelope(_raw(payload))
