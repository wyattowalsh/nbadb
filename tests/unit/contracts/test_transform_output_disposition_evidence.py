from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from nbadb.contracts import transform_output_disposition_evidence as evidence_module
from nbadb.contracts.transform_output_disposition_evidence import (
    AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1,
    AUTHORED_SOURCE_BUNDLE_RESERVED_MEMBER_COUNT_V1,
    REQUIRED_SOURCE_MEMBER_ROLES_V1,
    SOURCE_BUNDLE_CANONICAL_MAX_BYTES_V1,
    SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1,
    SOURCE_BUNDLE_MAX_MEMBERS_V1,
    DispositionEvidenceError,
    TransformOutputDispositionAuditMetadataV1,
    TransformOutputDispositionProofPackV1,
    TransformOutputDispositionSourceBundleV1,
    TransformOutputDispositionSourceMemberV1,
    TransformOutputDispositionValidationEvidenceV1,
    canonical_json_bytes_v1,
    canonical_json_sha256_v1,
    decode_canonical_json_bytes_v1,
    persisted_canonical_json_bytes_v1,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _source_members() -> tuple[TransformOutputDispositionSourceMemberV1, ...]:
    members: list[TransformOutputDispositionSourceMemberV1] = []
    for index, role in enumerate(sorted(REQUIRED_SOURCE_MEMBER_ROLES_V1)):
        if role == "verifier_source":
            member = TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
                normalized_path=f"evidence/{index:02d}-{role}.py",
                role=role,
                media_type="text/x-python",
                content=b"def verify(value: object) -> bool:\n    return value is not None\n",
            )
        else:
            member = TransformOutputDispositionSourceMemberV1.from_typed_projection(
                normalized_path=f"evidence/{index:02d}-{role}.json",
                role=role,
                media_type="application/json",
                projection={"role": role, "schema_version": 1},
            )
        members.append(member)
    return tuple(sorted(members, key=lambda item: item.normalized_path))


def _source_bundle() -> TransformOutputDispositionSourceBundleV1:
    return TransformOutputDispositionSourceBundleV1(members=_source_members())


def _validation_evidence(
    bundle: TransformOutputDispositionSourceBundleV1,
) -> tuple[TransformOutputDispositionValidationEvidenceV1, ...]:
    proof_input = bundle.members_for_role("proof_inputs")[0].member_sha256
    evidence = bundle.members_for_role("validation_evidence")[0].member_sha256
    return (
        TransformOutputDispositionValidationEvidenceV1(
            case_id="01-positive-reconstruction",
            validation_class="positive",
            proof_input_member_sha256=proof_input,
            evidence_member_sha256s=(evidence,),
            expected_outcome="accepted",
            observed_outcome="accepted",
        ),
        TransformOutputDispositionValidationEvidenceV1(
            case_id="02-negative-foreign-input",
            validation_class="negative",
            proof_input_member_sha256=proof_input,
            evidence_member_sha256s=(evidence,),
            expected_outcome="rejected",
            observed_outcome="rejected",
        ),
        TransformOutputDispositionValidationEvidenceV1(
            case_id="03-mutation-verifier-bytes",
            validation_class="mutation",
            proof_input_member_sha256=proof_input,
            evidence_member_sha256s=(evidence,),
            expected_outcome="rejected",
            observed_outcome="rejected",
        ),
    )


def _proof_pack() -> TransformOutputDispositionProofPackV1:
    bundle = _source_bundle()
    return TransformOutputDispositionProofPackV1(
        source_bundle=bundle,
        claimed_reconstructed_result_sha256=_sha("claimed-reconstructed-result"),
        validation_evidence=_validation_evidence(bundle),
    )


def test_canonical_codec_is_bounded_sorted_utf8_and_has_one_persisted_lf() -> None:
    value = {"z": "é", "a": [1, True, None, 1.5]}
    canonical = canonical_json_bytes_v1(value)

    assert canonical == b'{"a":[1,true,null,1.5],"z":"\xc3\xa9"}'
    assert canonical_json_sha256_v1(value) == hashlib.sha256(canonical).hexdigest()
    assert persisted_canonical_json_bytes_v1(value) == canonical + b"\n"
    assert decode_canonical_json_bytes_v1(canonical) == value
    assert decode_canonical_json_bytes_v1(canonical + b"\n", persisted=True) == value


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1, "b":2}',
        b'{"b":2,"a":1}',
        b'{"a":1,"a":1}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":1e0}',
        b"\xff",
    ],
)
def test_canonical_decoder_rejects_noncanonical_or_unsafe_bytes(raw: bytes) -> None:
    with pytest.raises(DispositionEvidenceError):
        decode_canonical_json_bytes_v1(raw)


def test_canonical_codec_rejects_foreign_types_numbers_structure_and_lf_shape() -> None:
    with pytest.raises(DispositionEvidenceError, match="foreign exact type"):
        canonical_json_bytes_v1(("tuple",))
    with pytest.raises(DispositionEvidenceError, match="non-finite"):
        canonical_json_bytes_v1({"number": float("inf")})
    with pytest.raises(DispositionEvidenceError, match="over-bound integer"):
        canonical_json_bytes_v1({"number": 1 << 63})
    with pytest.raises(DispositionEvidenceError, match="depth"):
        decode_canonical_json_bytes_v1(b"[" * 49 + b"0" + b"]" * 49)
    with pytest.raises(DispositionEvidenceError, match="persisted flag"):
        decode_canonical_json_bytes_v1(b"{}", persisted=1)  # type: ignore[arg-type]
    with pytest.raises(DispositionEvidenceError, match="one LF"):
        decode_canonical_json_bytes_v1(b"{}", persisted=True)
    with pytest.raises(DispositionEvidenceError, match="canonical byte form"):
        decode_canonical_json_bytes_v1(b"{}\n\n", persisted=True)


def test_canonical_codec_enforces_collection_and_string_bounds_before_encoding() -> None:
    with pytest.raises(DispositionEvidenceError, match="over-bound array"):
        canonical_json_bytes_v1([None] * 20_001)
    with pytest.raises(DispositionEvidenceError, match="over-bound string"):
        canonical_json_bytes_v1("x" * ((4 * 1024 * 1024) + 1))


def test_source_member_embeds_exact_bytes_or_immutable_typed_projection() -> None:
    embedded = TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
        normalized_path="verifier/current.py",
        role="verifier_source",
        media_type="text/x-python",
        content=b"def verify() -> bool:\n    return True\n",
    )
    projection = TransformOutputDispositionSourceMemberV1.from_typed_projection(
        normalized_path="projection/star-contracts.json",
        role="star_projection",
        media_type="application/json",
        projection={"tables": ["dim_player"], "version": 1},
    )

    assert embedded.content_bytes == b"def verify() -> bool:\n    return True\n"
    assert projection.typed_projection == {"tables": ["dim_player"], "version": 1}
    assert embedded.member_sha256 != projection.member_sha256
    assert embedded.canonical_bytes.endswith(b"\n")
    assert (
        TransformOutputDispositionSourceMemberV1.from_canonical_bytes(embedded.canonical_bytes)
        == embedded
    )
    assert (
        TransformOutputDispositionSourceMemberV1.from_canonical_bytes(projection.canonical_bytes)
        == projection
    )
    with pytest.raises(DispositionEvidenceError, match="do not expose"):
        _ = embedded.typed_projection


def test_versioned_source_bundle_bounds_cover_base64_metadata_and_member_count() -> None:
    assert SOURCE_BUNDLE_CANONICAL_MAX_BYTES_V1 == 32 * 1024 * 1024
    assert SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1 == 2 * 1024 * 1024
    assert SOURCE_BUNDLE_MAX_MEMBERS_V1 == 4_096
    assert len(REQUIRED_SOURCE_MEMBER_ROLES_V1) == (AUTHORED_SOURCE_BUNDLE_RESERVED_MEMBER_COUNT_V1)
    assert (
        AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1
        + AUTHORED_SOURCE_BUNDLE_RESERVED_MEMBER_COUNT_V1
        <= SOURCE_BUNDLE_MAX_MEMBERS_V1
    )

    content = b"x" * SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1
    boundary = TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
        normalized_path="evidence/member-boundary.bin",
        role="verifier_source",
        media_type="application/octet-stream",
        content=content,
    )
    assert len(boundary.embedded_bytes_base64 or "") == 4 * ((len(content) + 2) // 3)
    assert len(boundary.canonical_bytes) > len(content)

    with pytest.raises(DispositionEvidenceError, match="bounded bytes"):
        TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path="evidence/member-oversized.bin",
            role="verifier_source",
            media_type="application/octet-stream",
            content=content + b"x",
        )
    with pytest.raises(DispositionEvidenceError, match="bounded typed tuple"):
        TransformOutputDispositionSourceBundleV1(
            members=(boundary,) * (SOURCE_BUNDLE_MAX_MEMBERS_V1 + 1)
        )


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/member.json",
        "../escape.json",
        "safe/../escape.json",
        "safe/./member.json",
        "safe//member.json",
        "safe\\member.json",
        "safe/member.json/",
        "unicodé/member.json",
    ],
)
def test_source_member_rejects_unsafe_or_non_normalized_paths(path: str) -> None:
    with pytest.raises(DispositionEvidenceError, match="source member path"):
        TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path=path,
            role="verifier_source",
            media_type="text/x-python",
            content=b"pass\n",
        )


def test_source_member_rejects_content_shape_length_digest_and_media_mutations() -> None:
    member = _source_members()[0]

    with pytest.raises(DispositionEvidenceError, match="length"):
        replace(member, byte_length=member.byte_length + 1)
    with pytest.raises(DispositionEvidenceError, match="digest"):
        replace(member, content_sha256="0" * 64)
    with pytest.raises(DispositionEvidenceError, match="media_type"):
        replace(member, media_type="Application/JSON")
    with pytest.raises(DispositionEvidenceError, match="cannot also"):
        replace(member, embedded_bytes_base64="eA==")

    payload = member.to_dict()
    payload["member_sha256"] = "0" * 64
    with pytest.raises(DispositionEvidenceError, match="member digest"):
        TransformOutputDispositionSourceMemberV1.from_dict(payload)

    payload = member.to_dict()
    payload["schema_version"] = True
    with pytest.raises(DispositionEvidenceError, match="schema version"):
        TransformOutputDispositionSourceMemberV1.from_dict(payload)


def test_complete_source_bundle_covers_exact_required_roles_and_round_trips() -> None:
    bundle = _source_bundle()

    assert bundle.member_count == len(REQUIRED_SOURCE_MEMBER_ROLES_V1)
    assert {member.role for member in bundle.members} == REQUIRED_SOURCE_MEMBER_ROLES_V1
    assert len(bundle.member_inventory_root_sha256) == 64
    assert len(bundle.source_bundle_root_sha256) == 64
    assert (
        TransformOutputDispositionSourceBundleV1.from_canonical_bytes(bundle.canonical_bytes)
        == bundle
    )


def test_source_bundle_rejects_missing_unordered_and_duplicate_normalized_members() -> None:
    members = _source_members()
    with pytest.raises(DispositionEvidenceError, match="roles are incomplete"):
        TransformOutputDispositionSourceBundleV1(members=members[:-1])
    with pytest.raises(DispositionEvidenceError, match="sorted"):
        TransformOutputDispositionSourceBundleV1(members=tuple(reversed(members)))

    duplicate = replace(members[1], normalized_path=members[0].normalized_path)
    duplicated = tuple(
        sorted((members[0], duplicate, *members[2:]), key=lambda item: item.normalized_path)
    )
    with pytest.raises(DispositionEvidenceError, match="duplicate normalized path"):
        TransformOutputDispositionSourceBundleV1(members=duplicated)


def test_source_bundle_rejects_unknown_fields_and_resealed_derived_mutations() -> None:
    bundle = _source_bundle()
    payload = bundle.to_dict()
    payload["unknown"] = "foreign"
    with pytest.raises(DispositionEvidenceError, match="unexpected=unknown"):
        TransformOutputDispositionSourceBundleV1.from_dict(payload)

    payload = bundle.to_dict()
    payload["member_inventory_root_sha256"] = "0" * 64
    payload["source_bundle_root_sha256"] = _sha("resealed-foreign-bundle")
    with pytest.raises(DispositionEvidenceError, match="member inventory root"):
        TransformOutputDispositionSourceBundleV1.from_dict(payload)


def test_source_bundle_enforces_its_versioned_canonical_bound_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    members = _source_members()
    canonical_size = len(canonical_json_bytes_v1(_source_bundle().to_dict()))
    monkeypatch.setattr(
        evidence_module,
        "SOURCE_BUNDLE_CANONICAL_MAX_BYTES_V1",
        canonical_size - 1,
    )

    with pytest.raises(DispositionEvidenceError, match="versioned canonical byte bound"):
        TransformOutputDispositionSourceBundleV1(members=members)


def test_validation_evidence_binds_class_inputs_expected_result_and_digest() -> None:
    rows = _validation_evidence(_source_bundle())

    assert {row.validation_class for row in rows} == {"positive", "negative", "mutation"}
    assert all(row.passed for row in rows)
    assert len({row.evidence_sha256 for row in rows}) == 3

    positive = rows[0]
    with pytest.raises(DispositionEvidenceError, match="incompatible expected"):
        replace(positive, expected_outcome="rejected")

    payload = positive.to_dict()
    payload["passed"] = False
    with pytest.raises(DispositionEvidenceError, match="passed flag"):
        TransformOutputDispositionValidationEvidenceV1.from_dict(payload)


def test_validation_evidence_reference_bound_is_symmetric_for_constructor_and_replay() -> None:
    row = _validation_evidence(_source_bundle())[0]
    over_bound = tuple(_sha(f"evidence-{index}") for index in range(4_097))

    with pytest.raises(DispositionEvidenceError, match="nonempty tuple"):
        replace(row, evidence_member_sha256s=over_bound)

    payload = row.to_dict()
    payload["evidence_member_sha256s"] = list(over_bound)
    raw = persisted_canonical_json_bytes_v1(payload)
    with pytest.raises(DispositionEvidenceError, match="bounded array"):
        TransformOutputDispositionValidationEvidenceV1.from_dict(
            decode_canonical_json_bytes_v1(raw, persisted=True)
        )


@pytest.mark.parametrize(
    ("bound_name", "bound_value", "constructor_message", "replay_message"),
    [
        ("CANONICAL_JSON_MAX_BYTES", 512, "byte length", "over-bound"),
        (
            "_CANONICAL_JSON_MAX_NODES",
            8,
            "node bound",
            "lexical structure bound",
        ),
        (
            "_CANONICAL_JSON_MAX_TOTAL_STRING_BYTES",
            128,
            "string-byte bound",
            "string-byte bound",
        ),
    ],
)
def test_source_bundle_enforces_complete_canonical_bounds_eagerly_and_on_replay(
    monkeypatch: pytest.MonkeyPatch,
    bound_name: str,
    bound_value: int,
    constructor_message: str,
    replay_message: str,
) -> None:
    members = _source_members()
    canonical = _source_bundle().canonical_bytes
    monkeypatch.setattr(evidence_module, bound_name, bound_value)

    with pytest.raises(DispositionEvidenceError, match=constructor_message):
        TransformOutputDispositionSourceBundleV1(members=members)
    with pytest.raises(DispositionEvidenceError, match=replay_message):
        TransformOutputDispositionSourceBundleV1.from_canonical_bytes(canonical)


def test_proof_pack_closes_source_roles_validation_classes_and_round_trips() -> None:
    proof_pack = _proof_pack()

    assert len(proof_pack.verifier_source_member_sha256s) == 1
    assert len(proof_pack.proof_input_member_sha256s) == 1
    assert len(proof_pack.validation_evidence_member_sha256s) == 1
    assert len(proof_pack.validation_evidence_root_sha256) == 64
    assert len(proof_pack.proof_pack_root_sha256) == 64
    assert (
        TransformOutputDispositionProofPackV1.from_canonical_bytes(proof_pack.canonical_bytes)
        == proof_pack
    )


def test_proof_pack_enforces_complete_canonical_size_eagerly_and_on_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof_pack = _proof_pack()
    canonical = proof_pack.canonical_bytes
    bundle_size = len(canonical_json_bytes_v1(proof_pack.source_bundle.to_dict()))
    monkeypatch.setattr(evidence_module, "CANONICAL_JSON_MAX_BYTES", bundle_size + 64)

    with pytest.raises(DispositionEvidenceError, match="byte length"):
        replace(proof_pack)
    with pytest.raises(DispositionEvidenceError, match="over-bound"):
        TransformOutputDispositionProofPackV1.from_canonical_bytes(canonical)


def test_proof_pack_rejects_missing_failed_foreign_or_unused_evidence() -> None:
    bundle = _source_bundle()
    rows = _validation_evidence(bundle)
    kwargs = {
        "source_bundle": bundle,
        "claimed_reconstructed_result_sha256": _sha("result"),
    }

    with pytest.raises(DispositionEvidenceError, match="positive, negative, and mutation"):
        TransformOutputDispositionProofPackV1(
            **kwargs,
            validation_evidence=rows[:-1],
        )

    failed = replace(rows[0], observed_outcome="rejected")
    with pytest.raises(DispositionEvidenceError, match="did not pass"):
        TransformOutputDispositionProofPackV1(
            **kwargs,
            validation_evidence=(failed, *rows[1:]),
        )

    foreign = replace(rows[0], proof_input_member_sha256="0" * 64)
    with pytest.raises(DispositionEvidenceError, match="proof-input inventory"):
        TransformOutputDispositionProofPackV1(
            **kwargs,
            validation_evidence=(foreign, *rows[1:]),
        )

    extra = TransformOutputDispositionSourceMemberV1.from_typed_projection(
        normalized_path="evidence/99-unused-proof-input.json",
        role="proof_inputs",
        media_type="application/json",
        projection={"unused": True},
    )
    widened_bundle = TransformOutputDispositionSourceBundleV1(
        members=tuple(sorted((*bundle.members, extra), key=lambda item: item.normalized_path))
    )
    with pytest.raises(DispositionEvidenceError, match="proof-input inventory"):
        TransformOutputDispositionProofPackV1(
            source_bundle=widened_bundle,
            claimed_reconstructed_result_sha256=_sha("result"),
            validation_evidence=rows,
        )


def test_proof_pack_rejects_nested_digest_and_role_projection_substitution() -> None:
    proof_pack = _proof_pack()
    payload = proof_pack.to_dict()
    payload["validation_evidence_root_sha256"] = "0" * 64
    payload["proof_pack_root_sha256"] = _sha("resealed-foreign-proof")
    with pytest.raises(DispositionEvidenceError, match="validation_evidence_root_sha256"):
        TransformOutputDispositionProofPackV1.from_dict(payload)

    payload = proof_pack.to_dict()
    payload["verifier_source_member_sha256s"] = ["0" * 64]
    payload["proof_pack_root_sha256"] = _sha("resealed-foreign-proof")
    with pytest.raises(DispositionEvidenceError, match="verifier_source_member_sha256s"):
        TransformOutputDispositionProofPackV1.from_dict(payload)


def test_task_and_role_labels_are_separate_non_independence_audit_metadata() -> None:
    proof_pack = _proof_pack()
    same_labels = TransformOutputDispositionAuditMetadataV1(
        proof_pack_root_sha256=proof_pack.proof_pack_root_sha256,
        author_task_id="same-task",
        author_role="same-role",
        reviewer_task_id="same-task",
        reviewer_role="same-role",
    )
    changed_labels = replace(same_labels, reviewer_task_id="different-task")

    assert same_labels.establishes_independence is False
    assert same_labels.audit_metadata_sha256 != changed_labels.audit_metadata_sha256
    assert same_labels.proof_pack_root_sha256 == changed_labels.proof_pack_root_sha256
    assert proof_pack.proof_pack_root_sha256 not in {
        same_labels.audit_metadata_sha256,
        changed_labels.audit_metadata_sha256,
    }
    assert (
        TransformOutputDispositionAuditMetadataV1.from_canonical_bytes(same_labels.canonical_bytes)
        == same_labels
    )

    payload = same_labels.to_dict()
    payload["establishes_independence"] = True
    payload["audit_metadata_sha256"] = _sha("spoofed-independence")
    with pytest.raises(DispositionEvidenceError, match="cannot establish independence"):
        TransformOutputDispositionAuditMetadataV1.from_dict(payload)
