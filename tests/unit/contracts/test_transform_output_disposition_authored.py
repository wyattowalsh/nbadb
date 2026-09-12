from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

import nbadb.contracts.transform_output_disposition_authored as authored
from nbadb.contracts.transform_output_disposition_authority import (
    TransformOutputCapabilityPolicyV1,
    TransformOutputEvidenceReferenceV1,
    TransformOutputSemanticClaimV1,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1,
    AUTHORED_SOURCE_BUNDLE_RESERVED_MEMBER_COUNT_V1,
    SOURCE_BUNDLE_CANONICAL_MAX_BYTES_V1,
    SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1,
    SOURCE_BUNDLE_MAX_MEMBERS_V1,
    validate_authored_source_bundle_representability_v1,
)
from nbadb.contracts.transform_output_disposition_structural import (
    TransformOutputStructuralAuthorityV1,
    TransformOutputStructuralTableAuthorityV1,
)

if TYPE_CHECKING:
    from pathlib import Path


def _digest(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _structural() -> TransformOutputStructuralAuthorityV1:
    tables = tuple(
        TransformOutputStructuralTableAuthorityV1(
            output_name=name,
            table_family=name.split("_", 1)[0],  # type: ignore[arg-type]
            table_contract_sha256=_digest(f"contract:{name}"),
            schema_sha256=_digest(f"schema:{name}"),
            transform_sha256=_digest(f"transform:{name}"),
            ordered_columns=("id", "value"),
            dependencies=("stg_source",),
        )
        for name in ("dim_alpha", "fact_beta")
    )
    return TransformOutputStructuralAuthorityV1(
        output_names=tuple(table.output_name for table in tables),
        star_model_contract_sha256=_digest("star"),
        tables=tables,
    )


def _parts(structural: TransformOutputStructuralAuthorityV1):
    projections = tuple(
        authored.AuthoredTransformOutputEvidenceProjectionV1(
            table.output_name, "review", f"review-{table.output_name}", {"approved": True}
        )
        for table in structural.tables
    )
    policy = TransformOutputCapabilityPolicyV1(True, True, True, True, True)
    decisions = tuple(
        authored.AuthoredCurrentTransformOutputDecisionV1(
            output_name=table.output_name,
            authored_decision_revision=1,
            structural_table_authority_sha256=table.table_authority_sha256,
            state="active",
            capability_policy=policy,
            semantic_claims=(
                TransformOutputSemanticClaimV1(
                    f"claim/{table.output_name}",
                    "contract",
                    _digest(f"claim:{table.output_name}"),
                    (projection.evidence_sha256,),
                ),
            ),
            reason_code="reviewed",
            evidence_references=(
                TransformOutputEvidenceReferenceV1(
                    projection.evidence_class,
                    projection.reference_id,
                    projection.evidence_sha256,
                ),
            ),
            revalidation_triggers=("structural_change",),
        )
        for table, projection in zip(structural.tables, projections, strict=True)
    )
    return decisions, projections


def _corpus() -> tuple[
    TransformOutputStructuralAuthorityV1,
    authored.AuthoredTransformOutputDispositionCorpusV1,
]:
    structural = _structural()
    decisions, projections = _parts(structural)
    corpus = authored.AuthoredTransformOutputDispositionCorpusV1(
        generation_sequence=1,
        prior_authored_authority_sha256=None,
        structural_authority_sha256=structural.authority_sha256,
        star_model_contract_sha256=structural.star_model_contract_sha256,
        current_decisions=decisions,
        removal_decisions=(),
        evidence_projections=projections,
    )
    return structural, corpus


def _full_denominator_max_projection_corpus() -> (
    authored.AuthoredTransformOutputDispositionCorpusV1
):
    output_names = tuple(f"fact_output_{index:03d}" for index in range(261))
    quotient, remainder = divmod(
        AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1, len(output_names)
    )
    policy = TransformOutputCapabilityPolicyV1(True, True, True, True, True)
    decisions: list[authored.AuthoredCurrentTransformOutputDecisionV1] = []
    projections: list[authored.AuthoredTransformOutputEvidenceProjectionV1] = []
    for output_index, output_name in enumerate(output_names):
        table_projections = tuple(
            authored.AuthoredTransformOutputEvidenceProjectionV1(
                output_name,
                "review",
                f"r{reference_index:02d}",
                0,
            )
            for reference_index in range(quotient + (output_index < remainder))
        )
        projections.extend(table_projections)
        references = tuple(
            sorted(
                TransformOutputEvidenceReferenceV1(
                    projection.evidence_class,
                    projection.reference_id,
                    projection.evidence_sha256,
                )
                for projection in table_projections
            )
        )
        decisions.append(
            authored.AuthoredCurrentTransformOutputDecisionV1(
                output_name=output_name,
                authored_decision_revision=1,
                structural_table_authority_sha256=_digest(f"table:{output_name}"),
                state="active",
                capability_policy=policy,
                semantic_claims=(
                    TransformOutputSemanticClaimV1(
                        f"claim/{output_name}",
                        "contract",
                        _digest(f"claim:{output_name}"),
                        tuple(sorted(reference.evidence_sha256 for reference in references)),
                    ),
                ),
                reason_code="reviewed",
                evidence_references=references,
                revalidation_triggers=("structural_change",),
            )
        )
    return authored.AuthoredTransformOutputDispositionCorpusV1(
        generation_sequence=1,
        prior_authored_authority_sha256=None,
        structural_authority_sha256=_digest("wide-structural"),
        star_model_contract_sha256=_digest("wide-star"),
        current_decisions=tuple(decisions),
        removal_decisions=(),
        evidence_projections=tuple(sorted(projections)),
    )


def _successor_removing_fact_beta() -> tuple[
    authored.AuthoredTransformOutputDispositionCorpusV1,
    authored.AuthoredTransformOutputDispositionCorpusV1,
]:
    _structural_authority, prior = _corpus()
    previous = prior.current_decisions[1]
    removal_projection = authored.AuthoredTransformOutputEvidenceProjectionV1(
        previous.output_name,
        "removal_review",
        "removal-fact-beta",
        {"decision": "removed", "reviewed": True},
    )
    removal_reference = TransformOutputEvidenceReferenceV1(
        removal_projection.evidence_class,
        removal_projection.reference_id,
        removal_projection.evidence_sha256,
    )
    tombstone = authored.AuthoredTransformOutputRemovalDecisionV1(
        output_name=previous.output_name,
        prior_authored_decision_revision=previous.authored_decision_revision,
        prior_authored_decision_sha256=previous.authored_decision_sha256,
        first_tombstone_generation_sequence=2,
        removal_reason_code="removed_upstream",
        evidence_references=(removal_reference,),
        revalidation_triggers=("upstream_return",),
    )
    successor = authored.AuthoredTransformOutputDispositionCorpusV1(
        generation_sequence=2,
        prior_authored_authority_sha256=prior.authored_authority_sha256,
        structural_authority_sha256=prior.structural_authority_sha256,
        star_model_contract_sha256=prior.star_model_contract_sha256,
        current_decisions=prior.current_decisions[:1],
        removal_decisions=(tombstone,),
        evidence_projections=(prior.evidence_projections[0], removal_projection),
    )
    return prior, successor


def test_canonical_codec_is_deterministic_and_has_no_evidence_self_digest() -> None:
    _structural_authority, corpus = _corpus()
    raw = corpus.canonical_bytes()
    assert raw == corpus.canonical_bytes()
    assert authored.AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(raw) == corpus
    projection = corpus.evidence_projections[0]
    assert b"evidence_sha256" not in projection.projection_bytes
    assert projection.evidence_sha256 == hashlib.sha256(projection.projection_bytes).hexdigest()
    assert projection.source_member_path == (
        "transform-output-disposition/evidence/"
        f"{projection.output_name}/{projection.reference_id}.json"
    )


def test_evidence_projection_caches_immutable_authority_bytes() -> None:
    payload = {"nested": ["reviewed"]}
    projection = authored.AuthoredTransformOutputEvidenceProjectionV1(
        "dim_alpha", "review", "immutable", payload
    )
    original_bytes = projection.projection_bytes
    original_digest = projection.evidence_sha256
    payload["nested"].append("caller-mutation")
    cast("dict[str, object]", projection.evidence_payload)["other"] = True
    assert projection.projection_bytes == original_bytes
    assert projection.evidence_sha256 == original_digest
    assert projection.to_dict()["evidence_payload"] == {"nested": ["reviewed"]}

    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="canonical JSON"):
        authored.AuthoredTransformOutputEvidenceProjectionV1(
            "dim_alpha", "review", "foreign", object()
        )


def test_multiple_unique_evidence_references_per_table_have_exact_closure() -> None:
    _structural_authority, corpus = _corpus()
    first = corpus.current_decisions[0]
    extra_projection = authored.AuthoredTransformOutputEvidenceProjectionV1(
        first.output_name,
        "schema_review",
        "schema-dim-alpha",
        {"columns": ["id", "value"], "reviewed": True},
    )
    extra_reference = TransformOutputEvidenceReferenceV1(
        extra_projection.evidence_class,
        extra_projection.reference_id,
        extra_projection.evidence_sha256,
    )
    updated_claim = replace(
        first.semantic_claims[0],
        evidence_sha256s=tuple(
            sorted(
                (
                    first.semantic_claims[0].evidence_sha256s[0],
                    extra_projection.evidence_sha256,
                )
            )
        ),
    )
    updated_first = replace(
        first,
        semantic_claims=(updated_claim,),
        evidence_references=tuple(sorted((*first.evidence_references, extra_reference))),
    )
    candidate = replace(
        corpus,
        current_decisions=(updated_first, *corpus.current_decisions[1:]),
        evidence_projections=tuple(sorted((*corpus.evidence_projections, extra_projection))),
    )
    decoded = authored.AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(
        candidate.canonical_bytes()
    )
    assert len(decoded.current_decisions[0].evidence_references) == 2
    assert {
        item.source_member_path
        for item in decoded.evidence_projections
        if item.output_name == first.output_name
    } == {
        "transform-output-disposition/evidence/dim_alpha/review-dim_alpha.json",
        "transform-output-disposition/evidence/dim_alpha/schema-dim-alpha.json",
    }


def test_max_projection_domain_constructs_exact_minimum_mandatory_source_bundle() -> None:
    corpus = _full_denominator_max_projection_corpus()
    projection_members = tuple(
        (projection.source_member_path, projection.projection_bytes)
        for projection in corpus.evidence_projections
    )
    minimum_bundle_bytes = validate_authored_source_bundle_representability_v1(
        corpus_bytes=corpus.canonical_bytes(),
        evidence_projection_members=projection_members,
    )

    assert len(corpus.current_decisions) == 261
    assert len(corpus.evidence_projections) == (AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1)
    assert min(len(decision.evidence_references) for decision in corpus.current_decisions) >= 7
    assert len(corpus.canonical_bytes()) <= SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1
    assert minimum_bundle_bytes == corpus._minimum_source_bundle_canonical_bytes
    assert minimum_bundle_bytes <= SOURCE_BUNDLE_CANONICAL_MAX_BYTES_V1
    assert (
        len(corpus.evidence_projections) + AUTHORED_SOURCE_BUNDLE_RESERVED_MEMBER_COUNT_V1
        <= SOURCE_BUNDLE_MAX_MEMBERS_V1
    )


def test_projection_member_boundary_and_aggregate_corpus_oversize_fail_closed() -> None:
    _structural_authority, corpus = _corpus()
    original = corpus.evidence_projections[0]
    empty = replace(original, evidence_payload={"blob": ""})
    payload_bytes = SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1 - len(empty.projection_bytes)
    boundary = replace(original, evidence_payload={"blob": "x" * payload_bytes})
    assert len(boundary.projection_bytes) == SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1

    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="one source member"):
        replace(original, evidence_payload={"blob": "x" * (payload_bytes + 1)})

    boundary_reference = TransformOutputEvidenceReferenceV1(
        boundary.evidence_class,
        boundary.reference_id,
        boundary.evidence_sha256,
    )
    first = corpus.current_decisions[0]
    widened_first = replace(
        first,
        semantic_claims=(
            replace(
                first.semantic_claims[0],
                evidence_sha256s=(boundary.evidence_sha256,),
            ),
        ),
        evidence_references=(boundary_reference,),
    )
    with pytest.raises(
        authored.AuthoredTransformOutputDispositionError,
        match="corpus is not representable as one source member",
    ):
        replace(
            corpus,
            current_decisions=(widened_first, *corpus.current_decisions[1:]),
            evidence_projections=tuple(sorted((boundary, *corpus.evidence_projections[1:]))),
        )


def test_projection_count_limit_precedes_ambiguous_or_unclosed_content() -> None:
    _structural_authority, corpus = _corpus()
    with pytest.raises(
        authored.AuthoredTransformOutputDispositionError,
        match="source-bundle projection limit",
    ):
        replace(
            corpus,
            evidence_projections=(corpus.evidence_projections[0],)
            * (AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1 + 1),
        )


def test_evidence_projection_rejects_duplicate_identity_path_and_unsafe_reference() -> None:
    _structural_authority, corpus = _corpus()
    duplicate = replace(corpus.evidence_projections[0], evidence_payload={"other": True})
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="unique identities"):
        replace(
            corpus,
            evidence_projections=tuple(sorted((*corpus.evidence_projections, duplicate))),
        )

    colliding_path = replace(corpus.evidence_projections[0], evidence_class="independent_review")
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="ambiguous"):
        replace(
            corpus,
            evidence_projections=tuple(sorted((*corpus.evidence_projections, colliding_path))),
        )

    for unsafe in ("../escape", "nested/path", ".", "Uppercase"):
        with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="reference_id"):
            replace(corpus.evidence_projections[0], reference_id=unsafe)


def test_evidence_projection_exact_closure_rejects_unreferenced_and_missing_rows() -> None:
    _structural_authority, corpus = _corpus()
    extra = authored.AuthoredTransformOutputEvidenceProjectionV1(
        "dim_alpha", "review", "unreferenced", {"reviewed": False}
    )
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="exact-closure"):
        replace(
            corpus,
            evidence_projections=tuple(sorted((*corpus.evidence_projections, extra))),
        )
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="differs"):
        replace(corpus, evidence_projections=corpus.evidence_projections[1:])


def test_private_compiler_exactly_rebinds_all_structural_fields() -> None:
    structural, corpus = _corpus()
    compiled = authored._compile_authored_transform_output_disposition_authority(
        corpus.canonical_bytes(), structural
    )
    for entry, table in zip(compiled.entries, structural.tables, strict=True):
        assert entry.output_name == table.output_name
        assert entry.table_contract_sha256 == table.table_contract_sha256
        assert entry.schema_identity_sha256 == table.schema_sha256
        assert entry.transform_identity_sha256 == table.transform_sha256
        assert entry.ordered_columns_sha256 == table.ordered_column_inventory_sha256
        assert entry.dependency_identity_sha256 == table.dependency_inventory_sha256


@pytest.mark.parametrize("case", ["missing", "extra", "stale"])
def test_compiler_rejects_nonexact_join_and_stale_pins(case: str) -> None:
    structural, corpus = _corpus()
    decisions = corpus.current_decisions
    if case == "missing":
        decisions = decisions[:-1]
    elif case == "extra":
        extra = replace(decisions[-1], output_name="fact_gamma")
        decisions = (*decisions, extra)
    else:
        decisions = (
            replace(decisions[0], structural_table_authority_sha256=_digest("stale")),
            *decisions[1:],
        )
    projections = tuple(
        projection
        for projection in corpus.evidence_projections
        if projection.output_name in {decision.output_name for decision in decisions}
    )
    if case == "extra":
        projection = replace(projections[-1], output_name="fact_gamma")
        projections = (*projections, projection)
        ref = TransformOutputEvidenceReferenceV1(
            projection.evidence_class, projection.reference_id, projection.evidence_sha256
        )
        decisions = (
            *decisions[:-1],
            replace(
                decisions[-1],
                evidence_references=(ref,),
                semantic_claims=(
                    replace(
                        decisions[-1].semantic_claims[0],
                        evidence_sha256s=(projection.evidence_sha256,),
                    ),
                ),
            ),
        )
    candidate = replace(corpus, current_decisions=decisions, evidence_projections=projections)
    with pytest.raises(authored.AuthoredTransformOutputDispositionError):
        authored._compile_authored_transform_output_disposition_authority(
            candidate.canonical_bytes(), structural
        )


def test_parser_rejects_reordered_duplicate_and_protected_mutation() -> None:
    _structural_authority, corpus = _corpus()
    payload = corpus.to_dict()
    payload["current_decisions"] = list(
        reversed(cast("list[object]", payload["current_decisions"]))
    )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(authored.AuthoredTransformOutputDispositionError):
        authored.AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(raw)

    payload = corpus.to_dict()
    payload["current_decisions"] = [payload["current_decisions"][0]] * 2
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(authored.AuthoredTransformOutputDispositionError):
        authored.AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(raw)

    payload = corpus.to_dict()
    payload["current_decisions"][0]["reason_code"] = "silently_mutated"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="digest"):
        authored.AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(raw)


def test_parser_rejects_unknown_duplicate_noncanonical_and_bounded_inputs() -> None:
    _structural_authority, corpus = _corpus()

    payload = corpus.to_dict()
    payload["unexpected"] = True
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="canonical JSON"):
        authored.AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )

    duplicate_key = b'{"schema_version":1,' + corpus.canonical_bytes()[1:]
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="canonical JSON"):
        authored.AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(duplicate_key)

    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="canonical JSON"):
        authored.AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(
            corpus.canonical_bytes() + b"\n"
        )

    payload = corpus.to_dict()
    payload["evidence_projections"] = [payload["evidence_projections"][0]] * (
        authored._MAX_ROWS + 1
    )
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="bounded array"):
        authored.AuthoredTransformOutputDispositionCorpusV1.from_canonical_bytes(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )


def test_unknown_state_and_authored_decision_revision_fail_closed() -> None:
    _structural_authority, corpus = _corpus()
    decision = corpus.current_decisions[0]
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="state"):
        replace(decision, state=cast("authored.State", "removed"))
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="revision"):
        replace(decision, authored_decision_revision=0)
    changed_revision = replace(decision, authored_decision_revision=2)
    assert changed_revision.authored_decision_sha256 != decision.authored_decision_sha256
    assert "authored_decision_sha256" in decision.to_dict()
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="exceeds"):
        replace(
            corpus,
            current_decisions=(changed_revision, *corpus.current_decisions[1:]),
        )


def test_decision_requires_exact_reference_and_trigger_tuples() -> None:
    _structural_authority, corpus = _corpus()
    decision = corpus.current_decisions[0]
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="exact typed"):
        replace(decision, evidence_references=cast("object", list(decision.evidence_references)))
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="exact tuple"):
        replace(decision, revalidation_triggers=cast("object", ["structural_change"]))


def test_successor_tombstone_is_explicit_disjoint_and_bound_to_prior_decision() -> None:
    prior, successor = _successor_removing_fact_beta()
    successor.validate_successor_of(prior)
    tombstone = successor.removal_decisions[0]
    assert tombstone.prior_authored_decision_revision == 1
    assert (
        tombstone.prior_authored_decision_sha256
        == prior.current_decisions[1].authored_decision_sha256
    )
    assert tombstone.first_tombstone_generation_sequence == 2
    assert "family" not in tombstone.to_dict()
    assert "prior_structural_table_authority_sha256" not in tombstone.to_dict()
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="overlap"):
        replace(successor, current_decisions=prior.current_decisions)
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="initial"):
        replace(successor, generation_sequence=1, prior_authored_authority_sha256=None)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"prior_authored_decision_revision": 2}, "precede"),
        ({"first_tombstone_generation_sequence": 3}, "revision or tombstone"),
        ({"prior_authored_decision_sha256": "bad"}, "digest"),
    ],
)
def test_tombstone_revision_fields_fail_closed(mutation: dict[str, object], message: str) -> None:
    _prior, successor = _successor_removing_fact_beta()
    if "first_tombstone_generation_sequence" in mutation:
        changed = replace(successor.removal_decisions[0], **mutation)
        with pytest.raises(authored.AuthoredTransformOutputDispositionError, match=message):
            replace(successor, removal_decisions=(changed,))
    else:
        with pytest.raises(authored.AuthoredTransformOutputDispositionError, match=message):
            replace(successor.removal_decisions[0], **mutation)


def test_successor_rejects_mutated_retained_tombstone_and_revision_only_change() -> None:
    prior, successor = _successor_removing_fact_beta()
    retained = replace(
        successor,
        generation_sequence=3,
        prior_authored_authority_sha256=successor.authored_authority_sha256,
    )
    retained.validate_successor_of(successor)

    mutated_tombstone = replace(
        retained.removal_decisions[0], removal_reason_code="silently_changed"
    )
    mutated = replace(retained, removal_decisions=(mutated_tombstone,))
    with pytest.raises(
        authored.AuthoredTransformOutputDispositionError, match="deleted or mutated"
    ):
        mutated.validate_successor_of(successor)

    changed_decision = replace(prior.current_decisions[0], authored_decision_revision=2)
    revision_only = replace(
        prior,
        generation_sequence=2,
        prior_authored_authority_sha256=prior.authored_authority_sha256,
        current_decisions=(changed_decision, prior.current_decisions[1]),
    )
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="revision alone"):
        revision_only.validate_successor_of(prior)


def test_successor_requires_current_revision_for_semantic_change_and_exact_prior_pin() -> None:
    prior, successor = _successor_removing_fact_beta()
    changed_body = replace(prior.current_decisions[0], reason_code="new_review")
    stale_revision = replace(
        prior,
        generation_sequence=2,
        prior_authored_authority_sha256=prior.authored_authority_sha256,
        current_decisions=(changed_body, prior.current_decisions[1]),
    )
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="monotonic"):
        stale_revision.validate_successor_of(prior)

    current_revision = replace(changed_body, authored_decision_revision=2)
    valid_change = replace(
        stale_revision, current_decisions=(current_revision, prior.current_decisions[1])
    )
    valid_change.validate_successor_of(prior)

    bad_tombstone = replace(
        successor.removal_decisions[0],
        prior_authored_decision_sha256=_digest("other-prior-decision"),
    )
    wrong_prior_pin = replace(successor, removal_decisions=(bad_tombstone,))
    with pytest.raises(authored.AuthoredTransformOutputDispositionError, match="exact prior"):
        wrong_prior_pin.validate_successor_of(prior)


def test_public_loader_has_no_override_and_fails_closed_without_real_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not inspect.signature(
        authored.load_current_transform_output_disposition_authored_authority
    ).parameters
    assert [name for name in authored.__all__ if name.startswith("load_current_")] == [
        "load_current_transform_output_disposition_authored_authority"
    ]
    monkeypatch.setattr(authored, "_RESOURCE", tmp_path / "missing.json")
    with pytest.raises(
        authored.AuthoredTransformOutputDispositionError, match="resource is absent"
    ):
        authored.load_current_transform_output_disposition_authored_authority()


def test_public_loader_rejects_unsafe_fixed_resource_types(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = tmp_path / "empty.json"
    empty.touch()
    directory = tmp_path / "directory.json"
    directory.mkdir()
    target = tmp_path / "target.json"
    target.write_bytes(b"{}")
    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(target)
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.truncate(authored._MAX_BYTES + 1)

    for unsafe in (empty, directory, symlink, oversized):
        monkeypatch.setattr(authored, "_RESOURCE", unsafe)
        with pytest.raises(
            authored.AuthoredTransformOutputDispositionError, match="resource is unsafe"
        ):
            authored.load_current_transform_output_disposition_authored_authority()


def test_public_loader_rejects_under_byte_limit_unrepresentable_projection_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _structural_authority, corpus = _corpus()
    payload = corpus.to_dict()
    payload["evidence_projections"] = [payload["evidence_projections"][0]] * (
        AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1 + 1
    )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    assert len(raw) < SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1
    resource = tmp_path / "unrepresentable.json"
    resource.write_bytes(raw)
    monkeypatch.setattr(authored, "_RESOURCE", resource)

    with pytest.raises(
        authored.AuthoredTransformOutputDispositionError,
        match="source-bundle projection limit",
    ):
        authored.load_current_transform_output_disposition_authored_authority()
