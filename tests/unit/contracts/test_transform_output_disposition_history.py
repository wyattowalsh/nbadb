from __future__ import annotations

import base64
import hashlib
import inspect
from dataclasses import replace
from typing import Any, cast

import pytest

from nbadb.contracts import transform_output_disposition_authored as authored_module
from nbadb.contracts import transform_output_disposition_authority as authority_module
from nbadb.contracts import transform_output_disposition_history as history_module
from nbadb.contracts import transform_output_staging_input_authority as staging_authority_module
from nbadb.contracts.transform_output_disposition_authority import (
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
    TransformOutputChangeV1,
    TransformOutputDependencyV1,
    TransformOutputDispositionAuditMetadataV1,
    TransformOutputEvidenceReferenceV1,
    TransformOutputRemovedTombstoneV1,
    TransformOutputSemanticClaimV1,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    TransformOutputDispositionProofPackV1,
    TransformOutputDispositionSourceBundleV1,
    TransformOutputDispositionSourceMemberV1,
    TransformOutputDispositionValidationEvidenceV1,
    canonical_json_bytes_v1,
    decode_canonical_json_bytes_v1,
    persisted_canonical_json_bytes_v1,
)
from nbadb.contracts.transform_output_disposition_history import (
    MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1,
    TransformOutputDispositionHistoryChainV1,
    TransformOutputDispositionHistoryError,
    TransformOutputDispositionHistoryGenerationV1,
    TransformOutputDispositionHistoryStagingSnapshotV1,
)
from nbadb.contracts.transform_output_disposition_structural import (
    TransformOutputStructuralAuthorityV1,
    TransformOutputStructuralTableAuthorityV1,
)
from nbadb.contracts.transform_output_staging_input_authority import (
    RegisteredStagingInputContractInventoryV1,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _authored_root(generation_sequence: int) -> str:
    return _sha(f"fictional-authored-decision-authority:{generation_sequence}")


def _structural() -> TransformOutputStructuralAuthorityV1:
    table = TransformOutputStructuralTableAuthorityV1(
        output_name="dim_fictional_history",
        table_family="dim",
        table_contract_sha256=_sha("fictional-table-contract"),
        schema_sha256=_sha("fictional-schema"),
        transform_sha256=_sha("fictional-transform"),
        ordered_columns=("fictional_id",),
        dependencies=("stg_fictional_history",),
    )
    return TransformOutputStructuralAuthorityV1(
        output_names=(table.output_name,),
        star_model_contract_sha256=_sha("fictional-star-contract"),
        tables=(table,),
    )


def _member(
    *,
    path: str,
    role: str,
    generation_sequence: int,
) -> TransformOutputDispositionSourceMemberV1:
    if role == "verifier_source":
        return TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path=path,
            role=cast("Any", role),
            media_type="text/x-python",
            content=b"# fictional history verifier\n",
        )
    return TransformOutputDispositionSourceMemberV1.from_typed_projection(
        normalized_path=path,
        role=cast("Any", role),
        media_type="application/json",
        projection={
            "generation_sequence": generation_sequence,
            "kind": f"fictional_{role}_projection",
            "schema_version": 1,
        },
    )


def _proof_pack(generation_sequence: int) -> TransformOutputDispositionProofPackV1:
    paths_by_role = {
        "authored_entries": "fictional/authored-entries.json",
        "dependencies": "fictional/dependencies.json",
        "prior_or_initial_history": "fictional/local-prior-reference.json",
        "proof_inputs": "fictional/proof-inputs.json",
        "star_projection": "fictional/star-projection.json",
        "structural_discovery": "fictional/structural-discovery.json",
        "validation_evidence": "fictional/validation-evidence.json",
        "verifier_source": "fictional/verifier.py",
    }
    members = tuple(
        sorted(
            (
                _member(
                    path=path,
                    role=role,
                    generation_sequence=generation_sequence,
                )
                for role, path in paths_by_role.items()
            ),
            key=lambda item: item.normalized_path,
        )
    )
    bundle = TransformOutputDispositionSourceBundleV1(members=members)
    proof_input = bundle.members_for_role("proof_inputs")[0]
    validation_member = bundle.members_for_role("validation_evidence")[0]
    validation_rows = tuple(
        TransformOutputDispositionValidationEvidenceV1(
            case_id=case_id,
            validation_class=cast("Any", validation_class),
            proof_input_member_sha256=proof_input.member_sha256,
            evidence_member_sha256s=(validation_member.member_sha256,),
            expected_outcome=cast("Any", outcome),
            observed_outcome=cast("Any", outcome),
        )
        for case_id, validation_class, outcome in (
            ("fictional-mutation", "mutation", "rejected"),
            ("fictional-negative", "negative", "rejected"),
            ("fictional-positive", "positive", "accepted"),
        )
    )
    return TransformOutputDispositionProofPackV1(
        source_bundle=bundle,
        claimed_reconstructed_result_sha256=_sha(
            f"fictional-reconstructed-result:{generation_sequence}"
        ),
        validation_evidence=validation_rows,
    )


def _staging_inventory(
    *,
    structural_output_names: tuple[str, ...] = ("dim_fictional_history",),
    star_model_contract_sha256: str | None = None,
    route_contract_sha256: str | None = None,
    include_extra_entry: bool = False,
) -> RegisteredStagingInputContractInventoryV1:
    entry = staging_authority_module._build_entry(
        dependency_id="stg_fictional_history",
        route_ids=("fictional_history.primary",),
        route_contract_sha256s=(route_contract_sha256 or _sha("fictional-staging-route-contract"),),
        schema_module="fictional.history.staging",
        schema_class="FictionalHistoryStagingSchema",
        staging_schema_sha256=_sha("fictional-staging-schema"),
    )
    entries = [entry]
    if include_extra_entry:
        entries.append(
            staging_authority_module._build_entry(
                dependency_id="stg_fictional_unused",
                route_ids=("fictional_unused.primary",),
                route_contract_sha256s=(_sha("fictional-unused-route-contract"),),
                schema_module="fictional.history.staging",
                schema_class="FictionalUnusedStagingSchema",
                staging_schema_sha256=_sha("fictional-unused-staging-schema"),
            )
        )
    return staging_authority_module._build_inventory(
        tuple(entries),
        structural_output_names=structural_output_names,
        star_model_contract_sha256=(star_model_contract_sha256 or _sha("fictional-star-contract")),
    )


def _envelope(
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    *,
    staging_inventory: RegisteredStagingInputContractInventoryV1 | None = None,
    authored_decision_authority_sha256: str | None = None,
) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    staging_inventory = staging_inventory or _staging_inventory()
    structural = _structural()
    proof_pack = _proof_pack(generation_sequence)
    verifier_member = proof_pack.source_bundle.members_for_role("verifier_source")[0]
    evidence_sha256 = verifier_member.content_sha256
    table = structural.tables[0]
    entry = CurrentTransformOutputDispositionV1(
        output_name=table.output_name,
        family=table.table_family,
        table_contract_sha256=table.table_contract_sha256,
        schema_identity_sha256=table.schema_sha256,
        transform_identity_sha256=table.transform_sha256,
        ordered_columns_sha256=table.ordered_column_inventory_sha256,
        dependency_identity_sha256=table.dependency_inventory_sha256,
        state="active",
        capability_policy=TransformOutputCapabilityPolicyV1(True, True, True, True, True),
        semantic_claims=(
            TransformOutputSemanticClaimV1(
                claim_id="fictional-grain",
                claim_kind="grain",
                claim_sha256=_sha("fictional-grain-claim"),
                evidence_sha256s=(evidence_sha256,),
            ),
        ),
        reason_code="fictional_reviewed_active",
        evidence_references=(
            TransformOutputEvidenceReferenceV1(
                evidence_class="executable_test",
                reference_id="fictional.history.test",
                evidence_sha256=evidence_sha256,
            ),
        ),
        revalidation_triggers=("contract_change",),
    )
    dependency = TransformOutputDependencyV1(
        output_name=entry.output_name,
        ordinal=0,
        dependency_id="stg_fictional_history",
        dependency_kind="staging_input",
        dependency_contract_sha256=staging_inventory.entries[0].contract_sha256,
    )
    audit = TransformOutputDispositionAuditMetadataV1(
        proof_pack_root_sha256=proof_pack.proof_pack_root_sha256,
        author_task_id="fictional-history-author",
        author_role="fictional-author",
        reviewer_task_id="fictional-history-reviewer",
        reviewer_role="fictional-reviewer",
    )
    return authority_module._construct_verified_envelope(
        token=authority_module._VERIFIED_ENVELOPE_CONSTRUCTION_TOKEN,
        structural_authority=structural,
        proof_pack=proof_pack,
        audit_metadata=audit,
        entries=(entry,),
        tombstones=(),
        changes=(),
        dependencies=(dependency,),
        authored_decision_authority_sha256=(
            authored_decision_authority_sha256 or _authored_root(generation_sequence)
        ),
        generation_sequence=generation_sequence,
        prior_envelope_sha256=prior_envelope_sha256,
    )


def _generation(
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    *,
    staging_inventory: RegisteredStagingInputContractInventoryV1 | None = None,
    authored_decision_authority_sha256: str | None = None,
) -> TransformOutputDispositionHistoryGenerationV1:
    staging_inventory = staging_inventory or _staging_inventory()
    envelope = _envelope(
        generation_sequence,
        prior_envelope_sha256,
        staging_inventory=staging_inventory,
        authored_decision_authority_sha256=authored_decision_authority_sha256,
    )
    return _generation_from_envelope(envelope, staging_inventory=staging_inventory)


def _generation_from_envelope(
    envelope: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    *,
    staging_inventory: RegisteredStagingInputContractInventoryV1 | None = None,
) -> TransformOutputDispositionHistoryGenerationV1:
    staging_inventory = staging_inventory or _staging_inventory()
    envelope_member = TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
        normalized_path=history_module._envelope_member_path(envelope.generation_sequence),
        role="prior_or_initial_history",
        media_type="application/json",
        content=envelope.canonical_bytes(),
    )
    staging_snapshot = history_module._construct_staging_snapshot(
        token=history_module._STAGING_TOKEN,
        inventory=staging_inventory,
    )
    return history_module._construct_generation(
        token=history_module._GENERATION_TOKEN,
        generation_sequence=envelope.generation_sequence,
        envelope_member=envelope_member,
        staging_snapshot=staging_snapshot,
    )


def _rebuild_envelope(
    template: VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    *,
    entries: tuple[CurrentTransformOutputDispositionV1, ...] | None = None,
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...] | None = None,
    changes: tuple[TransformOutputChangeV1, ...] | None = None,
) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    return authority_module._construct_verified_envelope(
        token=authority_module._VERIFIED_ENVELOPE_CONSTRUCTION_TOKEN,
        structural_authority=template.structural_authority,
        proof_pack=template.proof_pack,
        audit_metadata=template.audit_metadata,
        entries=template.entries if entries is None else entries,
        tombstones=template.tombstones if tombstones is None else tombstones,
        changes=template.changes if changes is None else changes,
        dependencies=template.dependencies,
        authored_decision_authority_sha256=(template.authored_decision_authority_sha256),
        generation_sequence=template.generation_sequence,
        prior_envelope_sha256=template.prior_envelope_sha256,
    )


def _state_transition_envelopes() -> tuple[
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
]:
    prior = _envelope(1, None)
    template = _envelope(2, prior.envelope_sha256)
    current_entry = replace(
        template.entries[0],
        state="observed_only_experimental",
        capability_policy=TransformOutputCapabilityPolicyV1(True, True, False, False, False),
    )
    transition = TransformOutputChangeV1(
        change_kind="state_transition",
        output_name=current_entry.output_name,
        prior_entry_sha256=prior.entries[0].entry_sha256,
        current_entry_sha256=current_entry.entry_sha256,
        prior_state=prior.entries[0].state,
        current_state=current_entry.state,
        prior_table_contract_sha256=prior.entries[0].table_contract_sha256,
        current_table_contract_sha256=current_entry.table_contract_sha256,
        evidence_sha256s=tuple(item.evidence_sha256 for item in current_entry.evidence_references),
    )
    return prior, _rebuild_envelope(
        template,
        entries=(current_entry,),
        changes=(transition,),
    )


def _persistent_tombstone_envelopes() -> tuple[
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
    TransformOutputRemovedTombstoneV1,
]:
    prior_template = _envelope(2, _sha("fictional-generation-one-envelope"))
    evidence_sha256 = prior_template.proof_pack.source_bundle.members_for_role("verifier_source")[
        0
    ].content_sha256
    removal = TransformOutputChangeV1(
        change_kind="removal",
        output_name="fact_retired_history",
        prior_entry_sha256=_sha("retired-history-entry"),
        current_entry_sha256=None,
        prior_state="active",
        current_state=None,
        prior_table_contract_sha256=_sha("retired-history-contract"),
        current_table_contract_sha256=None,
        evidence_sha256s=(evidence_sha256,),
    )
    tombstone = TransformOutputRemovedTombstoneV1(
        output_name=removal.output_name,
        family="fact",
        last_entry_sha256=cast("str", removal.prior_entry_sha256),
        removal_change_sha256=removal.change_sha256,
        first_tombstone_generation_sequence=2,
        prior_envelope_sha256=cast("str", prior_template.prior_envelope_sha256),
        removal_reason_code="fictional_history_removal",
        removal_evidence_sha256s=removal.evidence_sha256s,
    )
    prior = _rebuild_envelope(
        prior_template,
        tombstones=(tombstone,),
        changes=(removal,),
    )
    current_template = _envelope(3, prior.envelope_sha256)
    current = _rebuild_envelope(current_template, tombstones=(tombstone,))
    return prior, current, tombstone


def _chain(count: int) -> TransformOutputDispositionHistoryChainV1:
    generations: list[TransformOutputDispositionHistoryGenerationV1] = []
    prior: str | None = None
    for generation_sequence in range(1, count + 1):
        generation = _generation(generation_sequence, prior)
        generations.append(generation)
        prior = generation.envelope_sha256
    return history_module._construct_chain(
        token=history_module._CHAIN_TOKEN,
        generations=tuple(generations),
    )


def _payload(raw: bytes) -> dict[str, object]:
    return cast("dict[str, object]", decode_canonical_json_bytes_v1(raw, persisted=True))


def _raw(payload: dict[str, object]) -> bytes:
    return persisted_canonical_json_bytes_v1(payload)


def _replace_staging_bytes(snapshot: dict[str, object], raw: bytes) -> None:
    snapshot["canonical_bytes_base64"] = base64.b64encode(raw).decode("ascii")
    snapshot["byte_length"] = len(raw)
    snapshot["content_sha256"] = hashlib.sha256(raw).hexdigest()
    preimage = {
        key: value
        for key, value in snapshot.items()
        if key not in {"canonical_bytes_base64", "snapshot_identity_sha256"}
    }
    snapshot["snapshot_identity_sha256"] = history_module._domain_sha256(
        history_module._STAGING_SNAPSHOT_DOMAIN,
        preimage,
    )


def _reseal_generation(row: dict[str, object]) -> None:
    preimage = {key: value for key, value in row.items() if key != "generation_record_sha256"}
    row["generation_record_sha256"] = history_module._domain_sha256(
        history_module._GENERATION_RECORD_DOMAIN,
        preimage,
    )


def _reseal_chain(payload: dict[str, object]) -> None:
    rows = cast("list[dict[str, object]]", payload["generations"])
    payload["generation_record_inventory_root_sha256"] = history_module._domain_sha256(
        history_module._GENERATION_INVENTORY_DOMAIN,
        [row["generation_record_sha256"] for row in rows],
    )
    preimage = {key: value for key, value in payload.items() if key != "chain_root_sha256"}
    payload["chain_root_sha256"] = history_module._domain_sha256(
        history_module._CHAIN_DOMAIN,
        preimage,
    )


def test_public_surface_is_parser_only_and_multi_generation_chain_round_trips() -> None:
    for constructor in (
        TransformOutputDispositionHistoryChainV1,
        TransformOutputDispositionHistoryGenerationV1,
        TransformOutputDispositionHistoryStagingSnapshotV1,
    ):
        with pytest.raises(TypeError, match="requires"):
            constructor()

    expected = _chain(3)
    raw = expected.canonical_bytes()
    observed = TransformOutputDispositionHistoryChainV1.from_canonical_bytes(raw)

    assert observed.canonical_bytes() == raw
    assert observed.generation_count == 3
    assert tuple(item.generation_sequence for item in observed.generations) == (1, 2, 3)
    assert observed.generations[0].prior_envelope_sha256 is None
    assert observed.generations[1].prior_envelope_sha256 == observed.generations[0].envelope_sha256
    assert observed.initial_generation_sequence == 1
    assert observed.terminal_generation_sequence == 3
    assert observed.initial_envelope_sha256 == observed.generations[0].envelope_sha256
    assert observed.terminal_envelope_sha256 == observed.generations[-1].envelope_sha256
    assert tuple(item.authored_decision_authority_sha256 for item in observed.generations) == tuple(
        _authored_root(sequence) for sequence in range(1, 4)
    )
    assert all(item.staging_snapshot.content_bytes for item in observed.generations)
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert all(
        not item.staging_snapshot.content_bytes.endswith(b"\n") for item in observed.generations
    )


def test_history_binds_true_source_roles_and_separate_staging_snapshot() -> None:
    generation = _chain(1).generations[0]
    roles = {role for _path, role, _sha256 in generation.source_member_inventory}

    assert roles == {
        "authored_entries",
        "dependencies",
        "prior_or_initial_history",
        "proof_inputs",
        "star_projection",
        "structural_discovery",
        "validation_evidence",
        "verifier_source",
    }
    assert generation.staging_snapshot.snapshot_identity_sha256 not in {
        member_sha256 for _path, _role, member_sha256 in generation.source_member_inventory
    }
    inventory = generation.staging_snapshot.inventory
    assert generation.staging_snapshot.semantic_schema_version == inventory.schema_version
    assert generation.staging_snapshot.semantic_kind == inventory.kind
    assert generation.staging_snapshot.semantic_contract_sha256 == inventory.contract_sha256
    assert (
        generation.staging_snapshot.structural_output_inventory_sha256
        == inventory.structural_output_inventory_sha256
    )
    assert (
        generation.staging_snapshot.star_model_contract_sha256
        == inventory.star_model_contract_sha256
    )
    assert generation.staging_snapshot.entry_inventory_sha256 == inventory.entry_inventory_sha256
    assert "staging_authority" not in roles


def test_staging_snapshot_constructor_accepts_only_typed_inventory() -> None:
    assert tuple(inspect.signature(history_module._construct_staging_snapshot).parameters) == (
        "token",
        "inventory",
    )
    assert all(
        name not in inspect.signature(history_module._construct_staging_snapshot).parameters
        for name in ("raw", "root", "mode", "current", "historical")
    )


def test_historical_staging_replay_never_calls_current_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _chain(2).canonical_bytes()

    def _forbidden_current(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("historical history replay must not consult current registries")

    monkeypatch.setattr(
        staging_authority_module,
        "compile_registered_staging_input_contract_inventory",
        _forbidden_current,
    )
    monkeypatch.setattr(
        RegisteredStagingInputContractInventoryV1,
        "from_canonical_bytes",
        classmethod(_forbidden_current),
    )

    observed = TransformOutputDispositionHistoryChainV1.from_canonical_bytes(raw)
    assert observed.canonical_bytes() == raw


def test_historical_replay_never_calls_current_authored_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _chain(2).canonical_bytes()

    def _forbidden_current(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("historical replay must not consult today's authored corpus")

    monkeypatch.setattr(
        authored_module,
        "load_current_transform_output_disposition_authored_authority",
        _forbidden_current,
    )

    observed = TransformOutputDispositionHistoryChainV1.from_canonical_bytes(raw)
    assert tuple(item.authored_decision_authority_sha256 for item in observed.generations) == (
        _authored_root(1),
        _authored_root(2),
    )


@pytest.mark.parametrize("mutation", ["missing", "malformed", "unknown"])
def test_historical_envelope_requires_exact_authored_root_field(mutation: str) -> None:
    payload = _payload(_envelope(1, None).canonical_bytes())
    if mutation == "missing":
        del payload["authored_decision_authority_sha256"]
    elif mutation == "malformed":
        payload["authored_decision_authority_sha256"] = True
    else:
        payload["unknown_authored_decision_authority_sha256"] = _sha("unknown")

    with pytest.raises(TransformOutputDispositionHistoryError):
        history_module._reconstruct_historical_envelope(_raw(payload))


def test_embedded_authored_root_mutation_fails_exact_envelope_reconstruction() -> None:
    payload = _payload(_envelope(1, None).canonical_bytes())
    payload["authored_decision_authority_sha256"] = _sha("foreign-authored-root")

    with pytest.raises(TransformOutputDispositionHistoryError, match="exact sealed reconstruction"):
        history_module._reconstruct_historical_envelope(_raw(payload))


@pytest.mark.parametrize("add_trailing_lf", [False, True])
def test_foreign_or_persisted_inner_staging_bytes_fail_typed_replay(
    add_trailing_lf: bool,
) -> None:
    payload = _payload(_chain(1).canonical_bytes())
    row = cast("list[dict[str, object]]", payload["generations"])[0]
    snapshot = cast("dict[str, object]", row["staging_snapshot"])
    if add_trailing_lf:
        foreign_raw = base64.b64decode(cast("str", snapshot["canonical_bytes_base64"])) + b"\n"
    else:
        foreign_raw = canonical_json_bytes_v1(
            {
                "kind": "fictional_foreign_canonical_json",
                "schema_version": 1,
            }
        )
    _replace_staging_bytes(snapshot, foreign_raw)
    _reseal_generation(row)
    _reseal_chain(payload)

    with pytest.raises(
        TransformOutputDispositionHistoryError,
        match="typed historical staging authority",
    ):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("semantic_schema_version", 2),
        ("semantic_kind", "foreign_registered_staging_inventory"),
        ("semantic_contract_sha256", _sha("foreign-staging-semantic-contract")),
        ("structural_output_count", 2),
        ("structural_output_inventory_sha256", _sha("foreign-structural-output-root")),
        ("star_model_contract_sha256", _sha("foreign-snapshot-star-root")),
        ("entry_count", 2),
        ("entry_inventory_sha256", _sha("foreign-entry-inventory-root")),
    ],
)
def test_every_resealed_staging_semantic_identity_substitution_fails(
    field: str,
    replacement: object,
) -> None:
    payload = _payload(_chain(1).canonical_bytes())
    row = cast("list[dict[str, object]]", payload["generations"])[0]
    snapshot = cast("dict[str, object]", row["staging_snapshot"])
    snapshot[field] = replacement
    _replace_staging_bytes(
        snapshot,
        base64.b64decode(cast("str", snapshot["canonical_bytes_base64"])),
    )
    _reseal_generation(row)
    _reseal_chain(payload)

    with pytest.raises(TransformOutputDispositionHistoryError, match="staging snapshot differs"):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


@pytest.mark.parametrize(
    "field",
    ["byte_length", "semantic_schema_version", "structural_output_count", "entry_count"],
)
def test_staging_snapshot_rejects_bool_as_integer(field: str) -> None:
    payload = _payload(_chain(1).canonical_bytes())
    row = cast("list[dict[str, object]]", payload["generations"])[0]
    snapshot = cast("dict[str, object]", row["staging_snapshot"])
    snapshot[field] = True

    with pytest.raises(TransformOutputDispositionHistoryError, match="byte length|foreign types"):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


def _construct_generation_with_foreign_staging_snapshot(
    inventory: RegisteredStagingInputContractInventoryV1,
) -> TransformOutputDispositionHistoryGenerationV1:
    envelope = _envelope(1, None)
    envelope_member = TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
        normalized_path=history_module._envelope_member_path(1),
        role="prior_or_initial_history",
        media_type="application/json",
        content=envelope.canonical_bytes(),
    )
    snapshot = history_module._construct_staging_snapshot(
        token=history_module._STAGING_TOKEN,
        inventory=inventory,
    )
    return history_module._construct_generation(
        token=history_module._GENERATION_TOKEN,
        generation_sequence=1,
        envelope_member=envelope_member,
        staging_snapshot=snapshot,
    )


def test_typed_staging_structural_output_denominator_must_join_envelope() -> None:
    inventory = _staging_inventory(structural_output_names=("agg_fictional_foreign",))
    with pytest.raises(TransformOutputDispositionHistoryError, match="structural output"):
        _construct_generation_with_foreign_staging_snapshot(inventory)


def test_typed_staging_star_contract_must_join_envelope() -> None:
    inventory = _staging_inventory(star_model_contract_sha256=_sha("foreign-star-contract"))
    with pytest.raises(TransformOutputDispositionHistoryError, match="star-model contract"):
        _construct_generation_with_foreign_staging_snapshot(inventory)


def test_typed_staging_dependency_contract_must_join_envelope() -> None:
    inventory = _staging_inventory(route_contract_sha256=_sha("foreign-staging-route-contract"))
    with pytest.raises(TransformOutputDispositionHistoryError, match="staging dependency differs"):
        _construct_generation_with_foreign_staging_snapshot(inventory)


def test_typed_staging_dependency_denominator_must_join_envelope() -> None:
    inventory = _staging_inventory(include_extra_entry=True)
    with pytest.raises(TransformOutputDispositionHistoryError, match="dependency denominator"):
        _construct_generation_with_foreign_staging_snapshot(inventory)


def test_exact_maximum_is_iterative_and_max_plus_one_fails_before_member_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maximum = MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1
    raw = _chain(maximum).canonical_bytes()
    assert (
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(raw).generation_count
        == maximum
    )

    payload = _payload(raw)
    rows = cast("list[object]", payload["generations"])
    rows.append(rows[-1])
    payload["generation_count"] = maximum + 1

    def _must_not_replay(_cls: object, _value: object) -> object:
        raise AssertionError("generation member replay must not begin")

    monkeypatch.setattr(
        TransformOutputDispositionHistoryGenerationV1,
        "from_dict",
        classmethod(_must_not_replay),
    )
    with pytest.raises(TransformOutputDispositionHistoryError, match="count"):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


def test_generation_replay_call_depth_is_constant(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _chain(MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1).canonical_bytes()
    original = history_module._reconstruct_historical_envelope
    depths: list[int] = []

    def _record_depth(member_bytes: bytes) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
        depths.append(len(inspect.stack(0)))
        return original(member_bytes)

    monkeypatch.setattr(history_module, "_reconstruct_historical_envelope", _record_depth)
    TransformOutputDispositionHistoryChainV1.from_canonical_bytes(raw)

    assert len(depths) == 2 * MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1
    first_pass = depths[:MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1]
    adjacency_pass = depths[MAX_TRANSFORM_OUTPUT_DISPOSITION_HISTORY_GENERATIONS_V1:]
    assert max(first_pass) == min(first_pass)
    assert max(adjacency_pass) == min(adjacency_pass)


def test_adjacent_history_accepts_one_exact_state_transition() -> None:
    prior, current = _state_transition_envelopes()
    chain = history_module._construct_chain(
        token=history_module._CHAIN_TOKEN,
        generations=(
            _generation_from_envelope(prior),
            _generation_from_envelope(current),
        ),
    )

    observed = TransformOutputDispositionHistoryChainV1.from_canonical_bytes(
        chain.canonical_bytes()
    )
    assert observed.terminal_envelope_sha256 == current.envelope_sha256


def test_coherently_resealed_state_change_without_change_row_fails_history() -> None:
    prior, current = _state_transition_envelopes()
    resealed_without_change = _rebuild_envelope(current, changes=())

    with pytest.raises(TransformOutputDispositionHistoryError, match="missing one exact change"):
        history_module._construct_chain(
            token=history_module._CHAIN_TOKEN,
            generations=(
                _generation_from_envelope(prior),
                _generation_from_envelope(resealed_without_change),
            ),
        )


def test_unchanged_adjacent_history_rejects_extra_change() -> None:
    prior = _envelope(1, None)
    template = _envelope(2, prior.envelope_sha256)
    current_entry = template.entries[0]
    extra = TransformOutputChangeV1(
        change_kind="structural_addition",
        output_name=current_entry.output_name,
        prior_entry_sha256=None,
        current_entry_sha256=current_entry.entry_sha256,
        prior_state=None,
        current_state=current_entry.state,
        prior_table_contract_sha256=None,
        current_table_contract_sha256=current_entry.table_contract_sha256,
        evidence_sha256s=tuple(item.evidence_sha256 for item in current_entry.evidence_references),
    )
    current = _rebuild_envelope(template, changes=(extra,))

    with pytest.raises(TransformOutputDispositionHistoryError, match="extra or missing"):
        history_module._construct_chain(
            token=history_module._CHAIN_TOKEN,
            generations=(
                _generation_from_envelope(prior),
                _generation_from_envelope(current),
            ),
        )


def test_adjacent_history_rejects_wrong_change_kind_for_contract_rebind() -> None:
    prior = _envelope(1, None)
    template = _envelope(2, prior.envelope_sha256)
    current_entry = replace(template.entries[0], reason_code="fictional_semantic_rebind")
    relabeled = TransformOutputChangeV1(
        change_kind="structural_addition",
        output_name=current_entry.output_name,
        prior_entry_sha256=None,
        current_entry_sha256=current_entry.entry_sha256,
        prior_state=None,
        current_state=current_entry.state,
        prior_table_contract_sha256=None,
        current_table_contract_sha256=current_entry.table_contract_sha256,
        evidence_sha256s=tuple(item.evidence_sha256 for item in current_entry.evidence_references),
    )
    current = _rebuild_envelope(
        template,
        entries=(current_entry,),
        changes=(relabeled,),
    )

    with pytest.raises(TransformOutputDispositionHistoryError, match="misclassifies"):
        history_module._construct_chain(
            token=history_module._CHAIN_TOKEN,
            generations=(
                _generation_from_envelope(prior),
                _generation_from_envelope(current),
            ),
        )


def test_adjacent_history_rejects_tombstone_delete_mutation_and_name_reuse() -> None:
    prior, current, tombstone = _persistent_tombstone_envelopes()
    history_module._validate_adjacent_evolution(prior=prior, current=current)

    deleted = _rebuild_envelope(current, tombstones=())
    with pytest.raises(TransformOutputDispositionHistoryError, match="deleted or mutated"):
        history_module._validate_adjacent_evolution(prior=prior, current=deleted)

    mutated = _rebuild_envelope(
        current,
        tombstones=(replace(tombstone, removal_reason_code="rewritten_history_removal"),),
    )
    with pytest.raises(TransformOutputDispositionHistoryError, match="deleted or mutated"):
        history_module._validate_adjacent_evolution(prior=prior, current=mutated)

    reappeared = _rebuild_envelope(current)
    reserved_entry = replace(
        reappeared.entries[0],
        output_name=tombstone.output_name,
        family="fact",
    )
    object.__setattr__(reappeared, "entries", (reserved_entry,))
    with pytest.raises(TransformOutputDispositionHistoryError, match="reappears"):
        history_module._validate_adjacent_evolution(prior=prior, current=reappeared)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"schema_version": True}),
        lambda payload: payload.update({"kind": 1}),
        lambda payload: payload.update({"generation_count": True}),
        lambda payload: payload.update({"unexpected": "field"}),
        lambda payload: cast("list[dict[str, object]]", payload["generations"])[0].update(
            {"generation_sequence": True}
        ),
        lambda payload: cast("list[dict[str, object]]", payload["generations"])[0][
            "staging_snapshot"
        ].update({"schema_version": True}),
    ],
)
def test_exact_types_and_unknown_fields_fail(mutation: Any) -> None:
    payload = _payload(_chain(1).canonical_bytes())
    mutation(payload)
    with pytest.raises(TransformOutputDispositionHistoryError):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: b" " + raw,
        lambda raw: raw + b"\n",
        lambda raw: raw.replace(b'"kind":', b'"kind":"duplicate","kind":', 1),
        lambda _raw_value: b'{"value":NaN}\n',
    ],
)
def test_noncanonical_duplicate_and_nonfinite_bytes_fail(mutation: Any) -> None:
    with pytest.raises((TransformOutputDispositionHistoryError, ValueError)):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(
            mutation(_chain(1).canonical_bytes())
        )


@pytest.mark.parametrize(
    "rows",
    [
        lambda values: [values[1], values[0]],
        lambda values: [values[0], values[0]],
        lambda values: [values[0], values[2]],
    ],
)
def test_reorder_duplicate_and_generation_gap_fail(rows: Any) -> None:
    payload = _payload(_chain(3).canonical_bytes())
    original = cast("list[dict[str, object]]", payload["generations"])
    payload["generations"] = rows(original)
    payload["generation_count"] = 2
    _reseal_chain(payload)
    with pytest.raises(
        TransformOutputDispositionHistoryError,
        match="contiguous|duplicate|predecessor",
    ):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


def test_broken_predecessor_and_cycle_fail() -> None:
    first = _generation(1, None)
    wrong_second = _generation(2, _sha("foreign-predecessor"))
    payload = _payload(_chain(2).canonical_bytes())
    payload["generations"] = [first.to_dict(), wrong_second.to_dict()]
    _reseal_chain(payload)
    with pytest.raises(TransformOutputDispositionHistoryError, match="predecessor"):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))

    valid_second = _generation(2, first.envelope_sha256)
    object.__setattr__(valid_second, "envelope_sha256", first.envelope_sha256)
    with pytest.raises(TransformOutputDispositionHistoryError, match="duplicate or cycle"):
        history_module._construct_chain(
            token=history_module._CHAIN_TOKEN,
            generations=(first, valid_second),
        )


def test_resealed_source_inventory_substitution_fails_exact_reconstruction() -> None:
    payload = _payload(_chain(1).canonical_bytes())
    row = cast("list[dict[str, object]]", payload["generations"])[0]
    inventory = cast("list[dict[str, object]]", row["source_member_inventory"])
    inventory[0]["member_sha256"] = _sha("foreign-source-member")
    _reseal_generation(row)
    _reseal_chain(payload)

    with pytest.raises(TransformOutputDispositionHistoryError, match="generation differs"):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


@pytest.mark.parametrize(
    ("mutation", "replacement"),
    [("missing", None), ("malformed", True), ("malformed", "A" * 64)],
)
def test_generation_codec_requires_exact_authored_root_field(
    mutation: str,
    replacement: object,
) -> None:
    payload = _payload(_chain(1).canonical_bytes())
    row = cast("list[dict[str, object]]", payload["generations"])[0]
    if mutation == "missing":
        del row["authored_decision_authority_sha256"]
    else:
        row["authored_decision_authority_sha256"] = replacement

    with pytest.raises(TransformOutputDispositionHistoryError):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


def test_authored_root_projection_and_generation_digests_are_sensitive() -> None:
    baseline = _generation(1, None)
    replacement_root = _sha("replacement-authored-decision-authority")
    changed = _generation(
        1,
        None,
        authored_decision_authority_sha256=replacement_root,
    )

    assert baseline.authored_decision_authority_sha256 == _authored_root(1)
    assert changed.authored_decision_authority_sha256 == replacement_root
    assert changed.envelope_sha256 != baseline.envelope_sha256
    assert changed.generation_identity_sha256 != baseline.generation_identity_sha256
    assert changed.generation_record_sha256 != baseline.generation_record_sha256

    baseline_chain = history_module._construct_chain(
        token=history_module._CHAIN_TOKEN,
        generations=(baseline,),
    )
    changed_chain = history_module._construct_chain(
        token=history_module._CHAIN_TOKEN,
        generations=(changed,),
    )
    assert changed_chain.generation_record_inventory_root_sha256 != (
        baseline_chain.generation_record_inventory_root_sha256
    )
    assert changed_chain.chain_root_sha256 != baseline_chain.chain_root_sha256


@pytest.mark.parametrize(
    "field",
    [
        "prior_envelope_sha256",
        "envelope_sha256",
        "generation_identity_sha256",
        "structural_authority_sha256",
        "authored_decision_authority_sha256",
        "source_bundle_root_sha256",
        "proof_pack_root_sha256",
        "source_member_inventory_root_sha256",
    ],
)
def test_resealed_generation_authority_root_substitution_fails(field: str) -> None:
    payload = _payload(_chain(1).canonical_bytes())
    row = cast("list[dict[str, object]]", payload["generations"])[0]
    row[field] = _sha(f"foreign:{field}")
    _reseal_generation(row)
    _reseal_chain(payload)

    with pytest.raises(TransformOutputDispositionHistoryError):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


def test_resealed_envelope_member_root_substitution_fails_inner_replay() -> None:
    payload = _payload(_chain(1).canonical_bytes())
    row = cast("list[dict[str, object]]", payload["generations"])[0]
    envelope_member = cast("dict[str, object]", row["envelope_member"])
    envelope_member["member_sha256"] = _sha("foreign-envelope-member")
    _reseal_generation(row)
    _reseal_chain(payload)

    with pytest.raises(TransformOutputDispositionHistoryError, match="source member digest"):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


def test_resealed_staging_snapshot_content_claim_fails_inner_replay() -> None:
    payload = _payload(_chain(1).canonical_bytes())
    row = cast("list[dict[str, object]]", payload["generations"])[0]
    snapshot = cast("dict[str, object]", row["staging_snapshot"])
    snapshot["content_sha256"] = _sha("foreign-staging-content")
    snapshot_preimage = {
        key: value
        for key, value in snapshot.items()
        if key not in {"canonical_bytes_base64", "snapshot_identity_sha256"}
    }
    snapshot["snapshot_identity_sha256"] = history_module._domain_sha256(
        history_module._STAGING_SNAPSHOT_DOMAIN,
        snapshot_preimage,
    )
    _reseal_generation(row)
    _reseal_chain(payload)

    with pytest.raises(TransformOutputDispositionHistoryError, match="staging snapshot differs"):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


@pytest.mark.parametrize(
    "field",
    [
        "generation_count",
        "initial_generation_sequence",
        "initial_envelope_sha256",
        "terminal_generation_sequence",
        "terminal_envelope_sha256",
        "generation_record_inventory_root_sha256",
        "chain_root_sha256",
    ],
)
def test_every_declared_chain_summary_and_root_is_exact(field: str) -> None:
    payload = _payload(_chain(2).canonical_bytes())
    payload[field] = (
        99
        if field.endswith("sequence") or field == "generation_count"
        else _sha(f"foreign:{field}")
    )
    with pytest.raises(TransformOutputDispositionHistoryError):
        TransformOutputDispositionHistoryChainV1.from_canonical_bytes(_raw(payload))


def test_history_never_calls_public_envelope_verifier_or_exposes_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden_public_replay(_cls: object, _raw_value: bytes) -> object:
        raise AssertionError("history structural replay must not call the public verifier")

    monkeypatch.setattr(
        VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
        "from_canonical_bytes",
        classmethod(_forbidden_public_replay),
    )
    raw = _chain(2).canonical_bytes()
    assert TransformOutputDispositionHistoryChainV1.from_canonical_bytes(raw).generation_count == 2
    assert tuple(
        inspect.signature(TransformOutputDispositionHistoryChainV1.from_canonical_bytes).parameters
    ) == ("raw",)
    assert all(
        forbidden not in history_module.__all__
        for forbidden in ("admit", "materialize", "publish", "verification_mode")
    )
