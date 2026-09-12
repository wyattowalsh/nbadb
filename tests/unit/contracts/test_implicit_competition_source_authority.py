from __future__ import annotations

import hashlib
import inspect
import itertools
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path, PurePath
from types import FunctionType
from typing import TypedDict

import pytest

from nbadb.contracts import implicit_competition_source_authority as subject
from nbadb.contracts.implicit_competition_source_authority import (
    SOURCE_PATHS,
    ImplicitCompetitionCurrentSourceAuthorityV1,
    ImplicitCompetitionSourceAuthorityError,
    ImplicitCompetitionSourceGenerationProofV1,
    admit_implicit_competition_current_source_authority,
    generate_implicit_competition_generation_proof,
    generate_implicit_competition_source_candidate,
    write_implicit_competition_current_source_authority,
)
from nbadb.contracts.review_evidence import (
    ReviewEvidenceError,
    ReviewReceiptV1,
    ReviewValidationReceiptV1,
)

_PROVIDER_SHA = "e5981c0223c99ecd4a483606781d1433cc23f22b26ec71c41a3b12b9ad827085"
_AUTHOR_TASK = "repair-12-author"
_AUTHOR_ROLE = "source-author"
_REVIEW_TASK = "repair-12-review"
_REVIEW_ROLE = "read-only-reviewer"
_GENERATION_IDENTITY = {
    "provider_authority_sha256": _PROVIDER_SHA,
    "author_task_id": _AUTHOR_TASK,
    "author_role": _AUTHOR_ROLE,
}
_EXPECTED_SOURCE_PATHS = (
    "src/nbadb/extract/live/endpoints.py",
    "src/nbadb/extract/static/players.py",
    "src/nbadb/extract/static/teams.py",
    "src/nbadb/extract/stats/box_scores.py",
    "src/nbadb/extract/stats/box_summary.py",
    "src/nbadb/extract/stats/hustle.py",
    "src/nbadb/extract/stats/legacy_versions.py",
    "src/nbadb/extract/stats/matchups.py",
    "src/nbadb/extract/stats/misc.py",
    "src/nbadb/extract/stats/play_by_play.py",
    "src/nbadb/extract/stats/player_info.py",
    "src/nbadb/extract/stats/team_info.py",
    "src/nbadb/extract/stats/win_probability.py",
)
_EXPECTED_FROZEN_BINDINGS = (
    (
        "a1_2c_endpoint_support_evidence",
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/competition_applicability/"
        "endpoint-support-evidence.json",
        "6db164143c588092acbd2c8497b068a770ff5a39501d1c05e28ef638b6fb6cfb",
    ),
    (
        "a1_2c_source_review",
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/competition_applicability/"
        "source-review.json",
        "accdd459d72d58be7c8b83f9c17e2e2086c058f3112b7714f4f0ea33e588f589",
    ),
    (
        "a1_2d_task_packet",
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/implicit_competition/A1.2d.json",
        "acc12887aa5525a0ed9cc8047264c7efda3da92da745c5145138b4eb2a72e1bb",
    ),
    (
        "a1_2d_root_evidence",
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/implicit_competition/"
        "implicit-competition-root-evidence.json",
        "ff848edf46d65bbfc5748e0b30a59d45e2be2a981a578fab73170089aa1c12ba",
    ),
    (
        "a1_2d_source_review",
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/implicit_competition/source-review.json",
        "d028c60baa78832991d83cbd977d0d555b32b6ebc38a281bb14e7592d76f37e8",
    ),
    (
        "a1_2d_implicit_resource",
        "src/nbadb/contracts/nba_api_implicit_competition_v1_11_4.json",
        "ed75be5cf84df8975cc32d50b51215648896b618584ed5b3b3aedcb8b6dc2111",
    ),
    (
        "a1_3a_repair_11_packet",
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/competition_identity/A1.3a-repair-11.json",
        "5f0cb0d04f9e46f412458489ba0d088193e18ba128f1739a2c03d87b4b5e57da",
    ),
)
_EXPECTED_POLICY_CONTRACT = {
    "candidate_derivation_count": 3,
    "candidate_equality": "canonical_minified_utf8_json_bytes",
    "cross_root_member_independence": {
        "corresponding_member_identity_fields": ["st_dev", "st_ino"],
        "required_distinct_identity_count": 3,
    },
    "root_distinctness": {
        "pairwise_nested_resolved_roots_rejected": True,
        "pairwise_samefile_rejected": True,
    },
    "source_snapshot": {
        "directory_metadata_excluded_from_edge_identity": ["st_mtime_ns", "st_ctime_ns"],
        "directory_open_flags": ["O_RDONLY", "O_DIRECTORY", "O_NOFOLLOW"],
        "file_open_flags": ["O_RDONLY", "O_NOFOLLOW", "O_NONBLOCK"],
        "file_stability_fields": [
            "st_dev",
            "st_ino",
            "st_mode",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        ],
        "member_size_bounds": {"maximum_bytes": 16 * 1024 * 1024, "minimum_bytes": 1},
        "path_edge_expected_kinds": {
            "anchor_and_directories": "S_IFDIR",
            "files": "S_IFREG",
        },
        "path_edge_identity_fields": ["st_dev", "st_ino", "S_IFMT(st_mode)"],
        "path_edge_scope": [
            "absolute_anchor",
            "every_absolute_resolved_component",
            "every_relative_member_directory",
            "every_relative_member_filename",
        ],
        "path_edge_validation_phases": [
            "immediately_after_open",
            "after_all_first_reads_before_second_reads",
            "after_second_reads_and_root_stat_before_return",
        ],
        "read_contract": {
            "chunk_bytes": 1024 * 1024,
            "descriptor_rewound_before_each_pass": True,
            "exact_byte_equality_required": True,
            "passes": 2,
        },
        "required_platform_flags": ["O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK"],
        "root_identity_fields": ["st_dev", "st_ino"],
        "root_resolution": "strict",
        "snapshot_maximum_bytes": 128 * 1024 * 1024,
    },
}


def _oracle_canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _oracle_digest(value: object) -> str:
    return hashlib.sha256(_oracle_canonical_bytes(value)).hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _copy_authority_root(destination: Path) -> Path:
    source = _repo_root()
    relative_paths = [*_EXPECTED_SOURCE_PATHS, *(row[1] for row in _EXPECTED_FROZEN_BINDINGS)]
    for relative in relative_paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    return destination


def _copy_authority_triple(parent: Path) -> tuple[Path, Path, Path]:
    roots = tuple(_copy_authority_root(parent / f"root-{index}") for index in range(3))
    return roots[0], roots[1], roots[2]


def _candidate(root: Path):
    return generate_implicit_competition_source_candidate(
        root,
        provider_authority_sha256=_PROVIDER_SHA,
        author_task_id=_AUTHOR_TASK,
        author_role=_AUTHOR_ROLE,
    )


def _generation_proof(parent: Path):
    roots = _copy_authority_triple(parent)
    proof = generate_implicit_competition_generation_proof(
        *roots,
        provider_authority_sha256=_PROVIDER_SHA,
        author_task_id=_AUTHOR_TASK,
        author_role=_AUTHOR_ROLE,
    )
    return proof, roots


def _literal_required_review_inputs(proof) -> tuple[str, ...]:
    candidate = proof.candidate
    candidate_bytes_sha256 = hashlib.sha256(
        _oracle_canonical_bytes(candidate.to_dict())
    ).hexdigest()
    assert proof.generation_candidate_bytes_sha256s == (candidate_bytes_sha256,) * 3
    flattened = (
        candidate.candidate_sha256,
        candidate.provider_authority_sha256,
        candidate.predecessor_receipt_sha256,
        candidate.semantic_projection_sha256,
        candidate.source_inventory_sha256,
        proof.proof_sha256,
        proof.generation_policy_sha256,
        *proof.generation_candidate_bytes_sha256s,
        *(item.sha256 for item in candidate.frozen_bindings),
        *(item.sha256 for item in candidate.source_bindings),
        *(item.semantic_sha256 for item in candidate.source_bindings),
    )
    assert len(flattened) == 43
    result = tuple(sorted(set(flattened)))
    assert len(result) == 41
    return result


def _review(proof):
    validations = tuple(
        sorted(
            ReviewValidationReceiptV1(
                receipt_id=f"repair-12-review:{validation_class}",
                validation_class=validation_class,
                command_sha256=character * 64,
                evidence_sha256={"d": "1", "e": "2", "f": "3"}[character] * 64,
                passed=True,
            )
            for validation_class, character in (
                ("positive", "d"),
                ("negative", "e"),
                ("mutation", "f"),
            )
        )
    )
    return ReviewReceiptV1(
        subject_kind=proof.candidate.kind,
        subject_semantic_sha256=proof.candidate.candidate_sha256,
        author_task_id=proof.candidate.author_task_id,
        author_role=proof.candidate.author_role,
        reviewer_task_id=_REVIEW_TASK,
        reviewer_role=_REVIEW_ROLE,
        independence_evidence_kind="independent_agent_review",
        independence_evidence_sha256="c" * 64,
        accepted_input_sha256s=_literal_required_review_inputs(proof),
        disposition="accepted",
        findings=(),
        validation_receipts=validations,
    )


class _ReplayRoots(TypedDict):
    first_root: Path
    second_root: Path
    third_root: Path


def _replay_kwargs(roots: tuple[Path, Path, Path]) -> _ReplayRoots:
    return {
        "first_root": roots[0],
        "second_root": roots[1],
        "third_root": roots[2],
    }


def _authority(parent: Path):
    proof, roots = _generation_proof(parent)
    review = _review(proof)
    authority = admit_implicit_competition_current_source_authority(
        proof.canonical_bytes,
        review.canonical_bytes,
        **_replay_kwargs(roots),
    )
    return authority, roots


def _fabricated_proof_from_one_root(root: Path):
    candidate = _candidate(root)
    candidate_bytes_sha256 = hashlib.sha256(
        _oracle_canonical_bytes(candidate.to_dict())
    ).hexdigest()
    policy_sha256 = _oracle_digest(
        {
            "candidate_bytes_sha256": candidate_bytes_sha256,
            "frozen_paths": [path for _name, path, _digest in _EXPECTED_FROZEN_BINDINGS],
            "policy": _EXPECTED_POLICY_CONTRACT,
            "policy_version": 2,
            "source_paths": list(_EXPECTED_SOURCE_PATHS),
        }
    )
    body = {
        "candidate": candidate.to_dict(),
        "generation_candidate_bytes_sha256s": [candidate_bytes_sha256] * 3,
        "generation_policy_sha256": policy_sha256,
        "kind": ImplicitCompetitionSourceGenerationProofV1.kind,
        "schema_version": ImplicitCompetitionSourceGenerationProofV1.schema_version,
    }
    return ImplicitCompetitionSourceGenerationProofV1(
        candidate=candidate,
        generation_candidate_bytes_sha256s=(
            candidate_bytes_sha256,
            candidate_bytes_sha256,
            candidate_bytes_sha256,
        ),
        generation_policy_sha256=policy_sha256,
        proof_sha256=_oracle_digest(body),
    )


def _direct_authority(proof, review):
    body = {
        "generation_proof": proof.to_dict(),
        "kind": ImplicitCompetitionCurrentSourceAuthorityV1.kind,
        "review": review.to_dict(),
        "schema_version": ImplicitCompetitionCurrentSourceAuthorityV1.schema_version,
    }
    return ImplicitCompetitionCurrentSourceAuthorityV1(
        generation_proof=proof,
        review=review,
        authority_sha256=_oracle_digest(body),
    )


def test_candidate_binds_exact_current_and_historical_inputs(tmp_path: Path) -> None:
    root = _copy_authority_root(tmp_path / "root")

    candidate = _candidate(root)

    assert SOURCE_PATHS == _EXPECTED_SOURCE_PATHS
    assert tuple(item.path for item in candidate.source_bindings) == _EXPECTED_SOURCE_PATHS
    assert len(candidate.source_bindings) == 13
    assert (
        tuple((item.name, item.path, item.sha256) for item in candidate.frozen_bindings)
        == _EXPECTED_FROZEN_BINDINGS
    )
    assert len(candidate.frozen_bindings) == 7
    assert candidate.candidate_sha256 != candidate.source_inventory_sha256
    assert candidate.semantic_projection_sha256 != candidate.source_inventory_sha256


def test_generation_is_identical_across_fresh_triples_and_all_permutations(
    tmp_path: Path,
) -> None:
    triples = (
        _copy_authority_triple(tmp_path / "generation-a"),
        _copy_authority_triple(tmp_path / "generation-b"),
    )
    all_roots = (*triples[0], *triples[1])
    for relative in (
        *(path for _name, path, _digest in _EXPECTED_FROZEN_BINDINGS),
        *_EXPECTED_SOURCE_PATHS,
    ):
        identities = {
            (
                (root / relative).stat(follow_symlinks=False).st_dev,
                (root / relative).stat(follow_symlinks=False).st_ino,
            )
            for root in all_roots
        }
        assert len(identities) == 6

    proofs = [
        generate_implicit_competition_generation_proof(
            *permutation,
            **_GENERATION_IDENTITY,
        )
        for triple in triples
        for permutation in itertools.permutations(triple)
    ]

    assert len(proofs) == 12
    assert all(proof == proofs[0] for proof in proofs)
    assert len({subject._canonical_bytes(proof.to_dict()) for proof in proofs}) == 1
    assert len({proof.proof_sha256 for proof in proofs}) == 1
    assert len(set(proofs[0].generation_candidate_bytes_sha256s)) == 1


def test_generation_policy_uses_complete_literal_non_circular_oracle(tmp_path: Path) -> None:
    proof, _ = _generation_proof(tmp_path / "policy")
    candidate_bytes_sha256 = hashlib.sha256(
        _oracle_canonical_bytes(proof.candidate.to_dict())
    ).hexdigest()
    expected = _oracle_digest(
        {
            "candidate_bytes_sha256": candidate_bytes_sha256,
            "frozen_paths": [path for _name, path, _digest in _EXPECTED_FROZEN_BINDINGS],
            "policy": _EXPECTED_POLICY_CONTRACT,
            "policy_version": 2,
            "source_paths": list(_EXPECTED_SOURCE_PATHS),
        }
    )

    assert proof.generation_policy_sha256 == expected
    assert len(_literal_required_review_inputs(proof)) == 41


def test_three_root_generation_rejects_same_root_and_symlink_alias(tmp_path: Path) -> None:
    root = _copy_authority_root(tmp_path / "root")
    second = _copy_authority_root(tmp_path / "second")
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)

    for third in (root, alias):
        with pytest.raises(
            ImplicitCompetitionSourceAuthorityError,
            match="three distinct source roots",
        ):
            generate_implicit_competition_generation_proof(
                root,
                second,
                third,
                provider_authority_sha256=_PROVIDER_SHA,
                author_task_id=_AUTHOR_TASK,
                author_role=_AUTHOR_ROLE,
            )


def test_generation_rejects_nested_roots_in_every_argument_order(
    tmp_path: Path,
) -> None:
    outer = _copy_authority_root(tmp_path / "outer")
    nested = _copy_authority_root(outer / "nested")
    separate = _copy_authority_root(tmp_path / "separate")

    for roots in itertools.permutations((outer, nested, separate)):
        with pytest.raises(
            ImplicitCompetitionSourceAuthorityError,
            match="nested source roots",
        ):
            generate_implicit_competition_generation_proof(
                *roots,
                **_GENERATION_IDENTITY,
            )


def test_generation_rejects_one_corresponding_cross_root_hardlink(
    tmp_path: Path,
) -> None:
    first, second, third = _copy_authority_triple(tmp_path / "roots")
    relative = SOURCE_PATHS[8]
    first_member = first / relative
    second_member = second / relative
    second_member.unlink()
    try:
        os.link(first_member, second_member)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable in tmp filesystem: {exc}")
    assert os.path.samefile(first_member, second_member)

    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="cross-root hardlinked source members",
    ):
        generate_implicit_competition_generation_proof(
            first,
            second,
            third,
            **_GENERATION_IDENTITY,
        )


def test_three_root_generation_rejects_one_byte_source_drift(tmp_path: Path) -> None:
    first = _copy_authority_root(tmp_path / "first")
    second = _copy_authority_root(tmp_path / "second")
    third = _copy_authority_root(tmp_path / "third")
    changed = third / SOURCE_PATHS[-1]
    changed.write_bytes(changed.read_bytes() + b"\n# drift\n")

    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="three independently generated source candidates differ",
    ):
        generate_implicit_competition_generation_proof(
            first,
            second,
            third,
            provider_authority_sha256=_PROVIDER_SHA,
            author_task_id=_AUTHOR_TASK,
            author_role=_AUTHOR_ROLE,
        )


def test_generation_rejects_frozen_input_drift(tmp_path: Path) -> None:
    root = _copy_authority_root(tmp_path / "root")
    frozen_path = root / _EXPECTED_FROZEN_BINDINGS[0][1]
    frozen_path.write_bytes(frozen_path.read_bytes() + b" ")

    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="frozen.*drifted"):
        _candidate(root)


def test_generation_rejects_symlink_and_nonregular_source_members(tmp_path: Path) -> None:
    for mode in ("symlink", "directory"):
        root = _copy_authority_root(tmp_path / mode)
        target = root / SOURCE_PATHS[0]
        original = target.with_suffix(".original")
        target.rename(original)
        if mode == "symlink":
            target.symlink_to(original.name)
        else:
            target.mkdir()

        with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="unsafe|regular"):
            _candidate(root)


def test_candidate_rejects_absolute_ancestor_rebind_immediately_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ancestor = tmp_path / "authority-absolute-ancestor"
    root = _copy_authority_root(ancestor / "root")
    moved = ancestor.with_name(f"{ancestor.name}-held")
    real_open = subject.os.open
    rebound = False

    def rebinding_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal rebound
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == ancestor.name and flags & os.O_DIRECTORY and not rebound:
            ancestor.rename(moved)
            ancestor.mkdir()
            rebound = True
        return descriptor

    monkeypatch.setattr(subject.os, "open", rebinding_open)
    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="pathname was rebound"):
        _candidate(root)
    assert rebound


def test_candidate_rejects_relative_member_directory_rebind_immediately_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _copy_authority_root(tmp_path / "member-directory-root")
    member_directory = root / "src/nbadb/extract"
    moved = member_directory.with_name("extract-held")
    real_open = subject.os.open
    rebound = False

    def rebinding_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal rebound
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == "extract" and flags & os.O_DIRECTORY and not rebound:
            member_directory.rename(moved)
            member_directory.mkdir()
            rebound = True
        return descriptor

    monkeypatch.setattr(subject.os, "open", rebinding_open)
    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="pathname was rebound"):
        _candidate(root)
    assert rebound


@pytest.mark.parametrize(
    "phase",
    [
        "after_all_first_reads_before_second_reads",
        "after_second_reads_and_root_stat_before_return",
    ],
)
def test_candidate_rejects_filename_rebind_at_each_lifecycle_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    root = _copy_authority_root(tmp_path / phase)
    target = root / _EXPECTED_SOURCE_PATHS[8]
    moved = target.with_suffix(f".{phase}.held")
    real_validate = subject._validate_path_edges
    rebound = False

    def rebinding_validate(edges, *, phase: str) -> None:
        nonlocal rebound
        if phase == phase_under_test and not rebound:
            target.rename(moved)
            shutil.copy2(moved, target)
            rebound = True
        real_validate(edges, phase=phase)

    phase_under_test = phase
    monkeypatch.setattr(subject, "_validate_path_edges", rebinding_validate)
    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="pathname was rebound"):
        _candidate(root)
    assert rebound


@pytest.mark.skipif(
    not all(hasattr(os, name) for name in ("mkfifo", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")),
    reason="descriptor-relative nonblocking FIFO test is unsupported",
)
def test_candidate_rejects_fifo_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _copy_authority_root(tmp_path / "fifo-root")
    target = root / SOURCE_PATHS[0]
    target.unlink()
    os.mkfifo(target, mode=0o600)
    real_open = subject.os.open
    observed_flags: list[int] = []

    def guarded_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == target.name and dir_fd is not None and not flags & os.O_DIRECTORY:
            assert flags & os.O_NONBLOCK
            observed_flags.append(flags)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(subject.os, "open", guarded_open)
    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="regular file"):
        _candidate(root)
    assert len(observed_flags) == 1


def test_candidate_rejects_sparse_file_over_per_member_bound(tmp_path: Path) -> None:
    root = _copy_authority_root(tmp_path / "oversize-root")
    target = root / SOURCE_PATHS[0]
    with target.open("r+b") as stream:
        stream.truncate(subject._MAX_SOURCE_FILE_BYTES + 1)

    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="size is outside the exact bound",
    ):
        _candidate(root)


def test_candidate_parser_rejects_missing_extra_and_unsafe_inventory_rows(
    tmp_path: Path,
) -> None:
    candidate = _candidate(_copy_authority_root(tmp_path / "root"))
    baseline = candidate.to_dict()

    missing = dict(baseline)
    missing["source_bindings"] = list(baseline["source_bindings"])[:-1]
    extra = dict(baseline)
    extra["source_bindings"] = [
        *list(baseline["source_bindings"]),
        dict(list(baseline["source_bindings"])[-1]),
    ]
    unsafe = dict(baseline)
    unsafe_rows = [dict(row) for row in list(baseline["source_bindings"])]
    unsafe_rows[0]["path"] = "../escape.py"
    unsafe["source_bindings"] = unsafe_rows
    self_referential = dict(baseline)
    self_referential["source_sha"] = "a" * 40

    assert "source_sha" not in baseline
    for payload in (missing, extra, unsafe, self_referential):
        with pytest.raises(ImplicitCompetitionSourceAuthorityError):
            subject.ImplicitCompetitionSourceCandidateV1.from_dict(payload)


def test_standard_review_requires_distinct_author_and_reviewer_identities(
    tmp_path: Path,
) -> None:
    proof, _ = _generation_proof(tmp_path / "proof")
    review = _review(proof)

    for changes in (
        {"reviewer_task_id": _AUTHOR_TASK},
        {"reviewer_role": _AUTHOR_ROLE},
    ):
        with pytest.raises(ReviewEvidenceError, match="must differ"):
            replace(review, **changes)


def test_final_authority_rejects_foreign_stale_and_rebound_review(tmp_path: Path) -> None:
    current, roots = _generation_proof(tmp_path / "proof")
    foreign = generate_implicit_competition_generation_proof(
        *roots,
        provider_authority_sha256="d" * 64,
        author_task_id=_AUTHOR_TASK,
        author_role=_AUTHOR_ROLE,
    )
    foreign_review = _review(foreign)

    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="foreign, stale, or rebound"):
        admit_implicit_competition_current_source_authority(
            current.canonical_bytes,
            foreign_review.canonical_bytes,
            **_replay_kwargs(roots),
        )

    valid_review = _review(current)
    rebound = replace(
        valid_review,
        accepted_input_sha256s=tuple(sorted({*valid_review.accepted_input_sha256s, "0" * 64})),
    )
    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="foreign, stale, or rebound"):
        admit_implicit_competition_current_source_authority(
            current.canonical_bytes,
            rebound.canonical_bytes,
            **_replay_kwargs(roots),
        )


def test_proof_and_authority_are_pure_structurally_valid_data(tmp_path: Path) -> None:
    proof, roots = _generation_proof(tmp_path / "proof")
    direct_proof = ImplicitCompetitionSourceGenerationProofV1(
        candidate=proof.candidate,
        generation_candidate_bytes_sha256s=proof.generation_candidate_bytes_sha256s,
        generation_policy_sha256=proof.generation_policy_sha256,
        proof_sha256=proof.proof_sha256,
    )
    review = _review(direct_proof)
    direct_authority = _direct_authority(direct_proof, review)
    authority = admit_implicit_competition_current_source_authority(
        direct_proof.canonical_bytes,
        review.canonical_bytes,
        **_replay_kwargs(roots),
    )

    assert direct_proof == proof
    assert replace(direct_proof) == direct_proof
    assert direct_authority == authority
    assert replace(direct_authority) == direct_authority


def test_proof_and_authority_parsers_require_bounded_exact_canonical_bytes(
    tmp_path: Path,
) -> None:
    authority, _roots = _authority(tmp_path / "strict-parser-roots")
    proof = authority.generation_proof
    parsed_proof = ImplicitCompetitionSourceGenerationProofV1.from_canonical_bytes(
        proof.canonical_bytes
    )
    parsed_authority = ImplicitCompetitionCurrentSourceAuthorityV1.from_canonical_bytes(
        authority.canonical_bytes
    )

    assert parsed_proof == proof
    assert parsed_proof is not proof
    assert parsed_proof.candidate is not proof.candidate
    assert parsed_authority == authority
    assert parsed_authority is not authority
    assert parsed_authority.generation_proof is not authority.generation_proof
    assert parsed_authority.review is not authority.review

    class BytesSubclass(bytes):
        pass

    integer_bomb = b'{"value":' + (b"9" * 5_000) + b"}"
    depth_bomb = b'{"value":' + (b"[" * 2_000) + b"0" + (b"]" * 2_000) + b"}"
    for parser, valid, maximum in (
        (
            ImplicitCompetitionSourceGenerationProofV1.from_canonical_bytes,
            proof.canonical_bytes,
            subject._MAX_PROOF_CANONICAL_BYTES,
        ),
        (
            ImplicitCompetitionCurrentSourceAuthorityV1.from_canonical_bytes,
            authority.canonical_bytes,
            subject._MAX_AUTHORITY_CANONICAL_BYTES,
        ),
    ):
        noncanonical = json.dumps(
            json.loads(valid),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        invalid_inputs = (
            BytesSubclass(valid),
            b"",
            b"x" * (maximum + 1),
            b'{"duplicate":1,"duplicate":1}',
            b'{"nonfinite":NaN}',
            b"\xff",
            noncanonical,
            integer_bomb,
            depth_bomb,
        )
        for invalid in invalid_inputs:
            with pytest.raises(ImplicitCompetitionSourceAuthorityError):
                parser(invalid)


def test_review_boundary_requires_bounded_exact_canonical_bytes(tmp_path: Path) -> None:
    proof, roots = _generation_proof(tmp_path / "strict-review-roots")
    review = _review(proof)

    class BytesSubclass(bytes):
        pass

    noncanonical = json.dumps(
        review.to_dict(),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    integer_bomb = b'{"value":' + (b"9" * 5_000) + b"}"
    depth_bomb = b'{"value":' + (b"[" * 2_000) + b"0" + (b"]" * 2_000) + b"}"
    invalid_reviews = (
        BytesSubclass(review.canonical_bytes),
        b"",
        b"x" * (subject._MAX_REVIEW_CANONICAL_BYTES + 1),
        b'{"duplicate":1,"duplicate":1}',
        b'{"nonfinite":Infinity}',
        b"\xff",
        noncanonical,
        integer_bomb,
        depth_bomb,
    )

    for invalid_review in invalid_reviews:
        with pytest.raises(ImplicitCompetitionSourceAuthorityError):
            admit_implicit_competition_current_source_authority(
                proof.canonical_bytes,
                invalid_review,
                **_replay_kwargs(roots),
            )


def test_trust_boundaries_reject_side_effect_graphs_without_callbacks_or_rebinding(
    tmp_path: Path,
) -> None:
    from nbadb.core import nba_api_provenance

    proof, roots = _generation_proof(tmp_path / "hostile-graph-roots")
    review = _review(proof)
    authority = _direct_authority(proof, review)
    calls: list[str] = []
    original_replayer = subject.generate_implicit_competition_generation_proof
    original_provider = nba_api_provenance.expected_nba_api_provider_authority

    class SideEffectGraph:
        def _attack(self, method: str) -> object:
            calls.append(method)
            subject.generate_implicit_competition_generation_proof = lambda *args, **kwargs: None  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
            nba_api_provenance.expected_nba_api_provider_authority = lambda: {}  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
            return False

        def __bytes__(self) -> bytes:
            return self._attack("__bytes__")  # type: ignore[return-value]  # ty: ignore[invalid-return-type]

        def __eq__(self, other: object) -> bool:
            return bool(self._attack("__eq__"))

        def __fspath__(self) -> str:
            return self._attack("__fspath__")  # type: ignore[return-value]  # ty: ignore[invalid-return-type]

        def __len__(self) -> int:
            return self._attack("__len__")  # type: ignore[return-value]  # ty: ignore[invalid-return-type]

        def to_dict(self) -> dict[str, object]:
            return self._attack("to_dict")  # type: ignore[return-value]  # ty: ignore[invalid-return-type]

    hostile = SideEffectGraph()
    admission_cases = (
        (hostile, review.canonical_bytes, roots),
        (proof.canonical_bytes, hostile, roots),
        (proof.canonical_bytes, review.canonical_bytes, (hostile, roots[1], roots[2])),
    )
    for proof_value, review_value, replay_roots in admission_cases:
        with pytest.raises(ImplicitCompetitionSourceAuthorityError):
            admit_implicit_competition_current_source_authority(
                proof_value,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
                review_value,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
                **_replay_kwargs(replay_roots),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            )
    writer_cases = (
        (hostile, tmp_path / "hostile-authority.json", roots),
        (authority.canonical_bytes, hostile, roots),
        (authority.canonical_bytes, tmp_path / "hostile-root.json", (roots[0], hostile, roots[2])),
    )
    for authority_value, destination, replay_roots in writer_cases:
        with pytest.raises(ImplicitCompetitionSourceAuthorityError):
            write_implicit_competition_current_source_authority(
                authority_value,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
                destination,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
                **_replay_kwargs(replay_roots),  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            )

    assert calls == []
    assert subject.generate_implicit_competition_generation_proof is original_replayer
    assert nba_api_provenance.expected_nba_api_provider_authority is original_provider


def test_trust_boundaries_reject_string_path_and_bytes_subclasses(tmp_path: Path) -> None:
    proof, roots = _generation_proof(tmp_path / "exact-type-roots")
    review = _review(proof)
    authority = _direct_authority(proof, review)

    class BytesSubclass(bytes):
        pass

    class StringSubclass(str):
        pass

    class ConcretePathSubclass(type(Path())):
        pass

    invalid_paths = (
        StringSubclass(str(roots[0])),
        ConcretePathSubclass(roots[0]),
        PurePath(roots[0]),
        os.fsencode(roots[0]),
    )
    for invalid_path in invalid_paths:
        with pytest.raises(
            ImplicitCompetitionSourceAuthorityError,
            match="exact string or concrete local Path",
        ):
            admit_implicit_competition_current_source_authority(
                proof.canonical_bytes,
                review.canonical_bytes,
                first_root=invalid_path,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
                second_root=roots[1],
                third_root=roots[2],
            )
        with pytest.raises(
            ImplicitCompetitionSourceAuthorityError,
            match="exact string or concrete local Path",
        ):
            write_implicit_competition_current_source_authority(
                authority.canonical_bytes,
                invalid_path,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
                **_replay_kwargs(roots),
            )

    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="exact built-in bytes"):
        admit_implicit_competition_current_source_authority(
            BytesSubclass(proof.canonical_bytes),
            review.canonical_bytes,
            **_replay_kwargs(roots),
        )
    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="exact built-in bytes"):
        write_implicit_competition_current_source_authority(
            BytesSubclass(authority.canonical_bytes),
            tmp_path / "bytes-subclass.json",
            **_replay_kwargs(roots),
        )

    admitted = admit_implicit_competition_current_source_authority(
        proof.canonical_bytes,
        review.canonical_bytes,
        first_root=str(roots[0]),
        second_root=str(roots[1]),
        third_root=str(roots[2]),
    )
    destination = str(tmp_path / "exact-string-destination.json")
    assert write_implicit_competition_current_source_authority(
        admitted.canonical_bytes,
        destination,
        first_root=str(roots[0]),
        second_root=str(roots[1]),
        third_root=str(roots[2]),
    )


def test_trust_boundary_has_no_tokens_origins_registries_closures_or_stack_checks() -> None:
    module_attributes = dict(vars(subject))
    proof_parameters = inspect.signature(generate_implicit_competition_generation_proof).parameters
    assert tuple(proof_parameters) == (
        "first_root",
        "second_root",
        "third_root",
        "provider_authority_sha256",
        "author_task_id",
        "author_role",
    )
    for data_type in (
        ImplicitCompetitionSourceGenerationProofV1,
        ImplicitCompetitionCurrentSourceAuthorityV1,
    ):
        assert "from_dict" in vars(data_type)
        assert "from_canonical_bytes" in vars(data_type)
        assert not any(
            fragment in name.lower()
            for name in vars(data_type)
            for fragment in ("token", "origin", "registry", "weak")
        )
    assert not any(
        fragment in name.lower()
        for name in module_attributes
        for fragment in ("token", "origin", "registry", "weakset", "stack")
    )
    assert not any(
        inspect.isfunction(value)
        and value.__module__ == subject.__name__
        and value.__closure__ is not None
        for value in module_attributes.values()
    )
    assert "inspect" not in module_attributes
    assert not hasattr(subject, "_decode_canonical")
    assert not hasattr(subject, "validate_implicit_competition_current_source_authority")
    assert (
        "source_sha"
        not in inspect.signature(generate_implicit_competition_source_candidate).parameters
    )
    assert (
        "source_sha"
        not in inspect.signature(generate_implicit_competition_generation_proof).parameters
    )
    assert (
        "expected_source_sha"
        not in inspect.signature(write_implicit_competition_current_source_authority).parameters
    )
    assert (
        "project_root"
        not in inspect.signature(write_implicit_competition_current_source_authority).parameters
    )
    assert tuple(
        inspect.signature(admit_implicit_competition_current_source_authority).parameters
    ) == (
        "generation_proof_bytes",
        "review_bytes",
        "first_root",
        "second_root",
        "third_root",
    )
    assert tuple(
        inspect.signature(write_implicit_competition_current_source_authority).parameters
    ) == (
        "authority_bytes",
        "path",
        "first_root",
        "second_root",
        "third_root",
        "check",
    )
    assert (
        "expected_provider_authority_sha256"
        not in inspect.signature(write_implicit_competition_current_source_authority).parameters
    )


def test_retrieved_module_surface_cannot_promote_one_root_data_without_replay(
    tmp_path: Path,
) -> None:
    retrieved_module_attributes = dict(vars(subject))
    first, second, third = _copy_authority_triple(tmp_path / "replay-roots")
    fabricated_proof = _fabricated_proof_from_one_root(first)
    fabricated_review = _review(fabricated_proof)
    fabricated_authority = _direct_authority(fabricated_proof, fabricated_review)
    alias = tmp_path / "first-root-alias"
    alias.symlink_to(first, target_is_directory=True)
    nested = _copy_authority_root(first / "nested-root")
    invalid_triples = (
        ("same", (first, second, first)),
        ("symlink", (first, second, alias)),
        ("nested", (first, nested, second)),
    )

    assert retrieved_module_attributes["admit_implicit_competition_current_source_authority"] is (
        admit_implicit_competition_current_source_authority
    )
    assert not any(
        "token" in name.lower() or "origin" in name.lower() for name in retrieved_module_attributes
    )
    for label, roots in invalid_triples:
        with pytest.raises(ImplicitCompetitionSourceAuthorityError):
            admit_implicit_competition_current_source_authority(
                fabricated_proof.canonical_bytes,
                fabricated_review.canonical_bytes,
                **_replay_kwargs(roots),
            )
        destination = tmp_path / f"{label}-must-not-write.json"
        with pytest.raises(ImplicitCompetitionSourceAuthorityError):
            write_implicit_competition_current_source_authority(
                fabricated_authority.canonical_bytes,
                destination,
                **_replay_kwargs(roots),
            )
        assert not destination.exists()

    admitted = admit_implicit_competition_current_source_authority(
        fabricated_proof.canonical_bytes,
        fabricated_review.canonical_bytes,
        **_replay_kwargs((first, second, third)),
    )
    assert admitted == fabricated_authority
    valid_destination = tmp_path / "valid-replay.json"
    assert write_implicit_competition_current_source_authority(
        fabricated_authority.canonical_bytes,
        valid_destination,
        **_replay_kwargs((first, second, third)),
    )
    assert valid_destination.read_bytes() == admitted.canonical_bytes

    changed = third / _EXPECTED_SOURCE_PATHS[-1]
    changed.write_bytes(changed.read_bytes() + b"\n# replay drift\n")
    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="three independently generated source candidates differ",
    ):
        admit_implicit_competition_current_source_authority(
            fabricated_proof.canonical_bytes,
            fabricated_review.canonical_bytes,
            **_replay_kwargs((first, second, third)),
        )
    drift_destination = tmp_path / "drift-must-not-write.json"
    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="three independently generated source candidates differ",
    ):
        write_implicit_competition_current_source_authority(
            fabricated_authority.canonical_bytes,
            drift_destination,
            **_replay_kwargs((first, second, third)),
        )
    assert not drift_destination.exists()


def test_structural_gates_never_invoke_hostile_equality(
    tmp_path: Path,
) -> None:
    class AlwaysEqual:
        def __init__(self) -> None:
            self.calls = 0

        def __eq__(self, other: object) -> bool:
            self.calls += 1
            return True

        def __ne__(self, other: object) -> bool:
            self.calls += 1
            return False

    proof, roots = _generation_proof(tmp_path / "proof-structure")
    review = _review(proof)
    proof_value = AlwaysEqual()
    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="exact built-in bytes"):
        admit_implicit_competition_current_source_authority(
            proof_value,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            review.canonical_bytes,
            **_replay_kwargs(roots),
        )
    assert proof_value.calls == 0

    authority, authority_roots = _authority(tmp_path / "authority-writer")
    authority_value = AlwaysEqual()
    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="exact built-in bytes"):
        write_implicit_competition_current_source_authority(
            authority_value,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            tmp_path / "must-not-write.json",
            **_replay_kwargs(authority_roots),
        )
    assert authority_value.calls == 0


@pytest.mark.parametrize("target", ["candidate", "proof", "review"])
def test_admission_recanonicalizes_object_setattr_mutations(
    tmp_path: Path,
    target: str,
) -> None:
    proof, roots = _generation_proof(tmp_path / target)
    review = _review(proof)
    if target == "candidate":
        proof_payload = proof.to_dict()
        candidate_payload = dict(proof_payload["candidate"])
        candidate_payload["candidate_sha256"] = "0" * 64
        proof_payload["candidate"] = candidate_payload
        proof_bytes = _oracle_canonical_bytes(proof_payload)
    elif target == "proof":
        proof_payload = proof.to_dict()
        proof_payload["generation_policy_sha256"] = "0" * 64
        proof_bytes = _oracle_canonical_bytes(proof_payload)
    else:
        proof_bytes = proof.canonical_bytes
        review_payload = review.to_dict()
        review_payload["reviewer_role"] = proof.candidate.author_role
        review = _oracle_canonical_bytes(review_payload)

    with pytest.raises(ImplicitCompetitionSourceAuthorityError):
        admit_implicit_competition_current_source_authority(
            proof_bytes,
            review if type(review) is bytes else review.canonical_bytes,  # ty: ignore[unresolved-attribute]
            **_replay_kwargs(roots),
        )


@pytest.mark.parametrize("target", ["candidate", "proof", "review", "authority"])
def test_write_recanonicalizes_mutated_authority_graph(
    tmp_path: Path,
    target: str,
) -> None:
    authority, roots = _authority(tmp_path / target)
    authority_payload = authority.to_dict()
    if target == "candidate":
        proof_payload = dict(authority_payload["generation_proof"])
        candidate_payload = dict(proof_payload["candidate"])
        candidate_payload["candidate_sha256"] = "0" * 64
        proof_payload["candidate"] = candidate_payload
        authority_payload["generation_proof"] = proof_payload
    elif target == "proof":
        proof_payload = dict(authority_payload["generation_proof"])
        proof_payload["generation_policy_sha256"] = "0" * 64
        authority_payload["generation_proof"] = proof_payload
    elif target == "review":
        review_payload = dict(authority_payload["review"])
        review_payload["reviewer_task_id"] = authority.candidate.author_task_id
        authority_payload["review"] = review_payload
    else:
        authority_payload["authority_sha256"] = "0" * 64

    destination = tmp_path / f"{target}.json"
    with pytest.raises(ImplicitCompetitionSourceAuthorityError):
        write_implicit_competition_current_source_authority(
            _oracle_canonical_bytes(authority_payload),
            destination,
            **_replay_kwargs(roots),
        )
    assert not destination.exists()


def test_write_once_check_rederives_and_exact_source_readback(
    tmp_path: Path,
) -> None:
    authority, roots = _authority(tmp_path / "authority-roots")
    path = tmp_path / "authority.json"

    write_kwargs = _replay_kwargs(roots)
    authority_bytes = authority.canonical_bytes
    assert write_implicit_competition_current_source_authority(
        authority_bytes,
        path,
        **write_kwargs,
    )
    assert write_implicit_competition_current_source_authority(
        authority_bytes,
        path,
        check=True,
        **write_kwargs,
    )
    assert path.read_bytes() == authority_bytes
    with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="already exists"):
        write_implicit_competition_current_source_authority(
            authority_bytes,
            path,
            **write_kwargs,
        )
    for non_boolean in (0, 1):
        with pytest.raises(ImplicitCompetitionSourceAuthorityError, match="exact boolean"):
            write_implicit_competition_current_source_authority(
                authority_bytes,
                path,
                check=non_boolean,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
                **write_kwargs,
            )

    changed = roots[2] / _EXPECTED_SOURCE_PATHS[-1]
    changed.write_bytes(changed.read_bytes() + b"\n# check replay drift\n")
    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="three independently generated source candidates differ",
    ):
        write_implicit_competition_current_source_authority(
            authority_bytes,
            path,
            check=True,
            **write_kwargs,
        )


def test_admit_and_write_resolve_provider_internally_without_caller_override(
    tmp_path: Path,
) -> None:
    roots = _copy_authority_triple(tmp_path / "foreign-provider-roots")
    foreign_proof = generate_implicit_competition_generation_proof(
        *roots,
        provider_authority_sha256="e" * 64,
        author_task_id=_AUTHOR_TASK,
        author_role=_AUTHOR_ROLE,
    )
    foreign_review = _review(foreign_proof)
    foreign_authority = _direct_authority(foreign_proof, foreign_review)

    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="provider binding differs",
    ):
        admit_implicit_competition_current_source_authority(
            foreign_proof.canonical_bytes,
            foreign_review.canonical_bytes,
            **_replay_kwargs(roots),
        )
    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="provider binding differs",
    ):
        write_implicit_competition_current_source_authority(
            foreign_authority.canonical_bytes,
            tmp_path / "wrong-provider.json",
            **_replay_kwargs(roots),
        )
    assert (
        "expected_provider_authority_sha256"
        not in inspect.signature(admit_implicit_competition_current_source_authority).parameters
    )
    assert (
        "expected_provider_authority_sha256"
        not in inspect.signature(write_implicit_competition_current_source_authority).parameters
    )


def test_provider_callback_cannot_redirect_captured_three_root_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nbadb.core import nba_api_provenance

    proof, roots = _generation_proof(tmp_path / "provider-callback-roots")
    review = _review(proof)
    original_replayer = subject.generate_implicit_competition_generation_proof
    original_path = subject.Path
    protected_globals = {
        "ImplicitCompetitionCurrentSourceAuthorityV1": (
            subject.ImplicitCompetitionCurrentSourceAuthorityV1
        ),
        "ImplicitCompetitionSourceAuthorityError": (
            subject.ImplicitCompetitionSourceAuthorityError
        ),
        "_canonical_bytes": subject._canonical_bytes,
        "_digest": subject._digest,
        "_fail": subject._fail,
        "_validate_review_binding": subject._validate_review_binding,
        "_validated_generation_proof_payload": subject._validated_generation_proof_payload,
        "os": subject.os,
    }
    replacement_calls: list[str] = []
    path_calls: list[str] = []

    def replacement_replayer(*args, **kwargs):
        replacement_calls.append("replacement")
        raise AssertionError("redirected replay must never run")

    def replacement_path(*args, **kwargs):
        path_calls.append("Path")
        raise AssertionError("provider callback must run after every Path lookup")

    def forbidden_global(*args, **kwargs):
        replacement_calls.append("forbidden_global")
        raise AssertionError("provider callback must be the last authority-module lookup")

    def provider_callback():
        callback_globals = globals()
        callback_globals[
            "_provider_test_subject"
        ].generate_implicit_competition_generation_proof = callback_globals[
            "_provider_test_replacement"
        ]
        callback_globals["_provider_test_subject"].Path = callback_globals["_provider_test_path"]
        for name, replacement in callback_globals["_provider_test_global_replacements"].items():
            setattr(callback_globals["_provider_test_subject"], name, replacement)
        return {"authority_sha256": callback_globals["_provider_test_sha256"]}

    provider_globals = vars(nba_api_provenance)
    monkeypatch.setitem(provider_globals, "_provider_test_subject", subject)
    monkeypatch.setitem(provider_globals, "_provider_test_replacement", replacement_replayer)
    monkeypatch.setitem(provider_globals, "_provider_test_path", replacement_path)
    monkeypatch.setitem(
        provider_globals,
        "_provider_test_global_replacements",
        {name: forbidden_global for name in protected_globals},
    )
    monkeypatch.setitem(provider_globals, "_provider_test_sha256", _PROVIDER_SHA)
    resolver_name = "expected_nba_api_provider_authority"
    resolver = FunctionType(
        provider_callback.__code__.replace(co_name=resolver_name, co_qualname=resolver_name),
        provider_globals,
        resolver_name,
    )
    resolver.__module__ = nba_api_provenance.__name__
    resolver.__qualname__ = resolver_name
    monkeypatch.setattr(nba_api_provenance, resolver_name, resolver)
    monkeypatch.setattr(
        subject, "generate_implicit_competition_generation_proof", original_replayer
    )
    monkeypatch.setattr(subject, "Path", original_path)
    for name, original in protected_globals.items():
        monkeypatch.setattr(subject, name, original)

    admitted = admit_implicit_competition_current_source_authority(
        proof.canonical_bytes,
        review.canonical_bytes,
        **_replay_kwargs(roots),
    )
    assert admitted.generation_proof == proof
    assert subject.generate_implicit_competition_generation_proof is replacement_replayer
    assert subject.Path is replacement_path
    assert replacement_calls == []
    assert path_calls == []

    subject.generate_implicit_competition_generation_proof = original_replayer
    subject.Path = original_path
    for name, original in protected_globals.items():
        setattr(subject, name, original)
    destination = tmp_path / "provider-callback-authority.json"
    assert write_implicit_competition_current_source_authority(
        admitted.canonical_bytes,
        destination,
        **_replay_kwargs(roots),
    )
    assert subject.generate_implicit_competition_generation_proof is replacement_replayer
    assert subject.Path is replacement_path
    assert replacement_calls == []
    assert path_calls == []


@pytest.mark.parametrize("invalid_provider_kind", ["dict_subclass", "digest_subclass"])
def test_provider_result_requires_exact_dict_and_exact_digest_string(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_provider_kind: str,
) -> None:
    from nbadb.core import nba_api_provenance

    proof, roots = _generation_proof(tmp_path / invalid_provider_kind)
    review = _review(proof)

    class DictSubclass(dict[str, object]):
        pass

    class StringSubclass(str):
        pass

    invalid_result: object
    if invalid_provider_kind == "dict_subclass":
        invalid_result = DictSubclass(authority_sha256=_PROVIDER_SHA)
    else:
        invalid_result = {"authority_sha256": StringSubclass(_PROVIDER_SHA)}

    def provider_result():
        return globals()["_provider_test_result"]

    provider_globals = vars(nba_api_provenance)
    monkeypatch.setitem(provider_globals, "_provider_test_result", invalid_result)
    resolver_name = "expected_nba_api_provider_authority"
    resolver = FunctionType(
        provider_result.__code__.replace(co_name=resolver_name, co_qualname=resolver_name),
        provider_globals,
        resolver_name,
    )
    resolver.__module__ = nba_api_provenance.__name__
    resolver.__qualname__ = resolver_name
    monkeypatch.setattr(nba_api_provenance, resolver_name, resolver)

    with pytest.raises(ImplicitCompetitionSourceAuthorityError):
        admit_implicit_competition_current_source_authority(
            proof.canonical_bytes,
            review.canonical_bytes,
            **_replay_kwargs(roots),
        )


def test_pre_entry_replay_function_replacement_is_detected_without_callbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof, roots = _generation_proof(tmp_path / "replay-result-roots")
    review = _review(proof)
    calls: list[str] = []

    class ReplayResult:
        def __eq__(self, other: object) -> bool:
            calls.append("__eq__")
            return True

        def to_dict(self) -> dict[str, object]:
            calls.append("to_dict")
            return {}

    replay_result = ReplayResult()

    def replay_callback(*args, **kwargs):
        return globals()["_replay_test_result"]

    module_globals = vars(subject)
    monkeypatch.setitem(module_globals, "_replay_test_result", replay_result)
    replayer_name = "generate_implicit_competition_generation_proof"
    replayer = FunctionType(
        replay_callback.__code__.replace(co_name=replayer_name, co_qualname=replayer_name),
        module_globals,
        replayer_name,
    )
    replayer.__module__ = subject.__name__
    replayer.__qualname__ = replayer_name
    monkeypatch.setattr(subject, replayer_name, replayer)

    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="replay dependencies are not exact trusted functions",
    ):
        admit_implicit_competition_current_source_authority(
            proof.canonical_bytes,
            review.canonical_bytes,
            **_replay_kwargs(roots),
        )
    assert calls == []


def test_pre_entry_metadata_shaped_stale_proof_replayer_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof, roots = _generation_proof(tmp_path / "stale-replay-roots")
    review = _review(proof)
    authority = _direct_authority(proof, review)
    changed = roots[2] / _EXPECTED_SOURCE_PATHS[-1]
    changed.write_bytes(changed.read_bytes() + b"\n# forged replay drift\n")

    def stale_replay(*args, **kwargs):
        return globals()["_replay_test_stale_proof"]

    module_globals = vars(subject)
    monkeypatch.setitem(module_globals, "_replay_test_stale_proof", proof)
    replayer_name = "generate_implicit_competition_generation_proof"
    forged_replayer = FunctionType(
        stale_replay.__code__.replace(co_name=replayer_name, co_qualname=replayer_name),
        module_globals,
        replayer_name,
    )
    forged_replayer.__module__ = subject.__name__
    forged_replayer.__qualname__ = replayer_name
    monkeypatch.setattr(subject, replayer_name, forged_replayer)

    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="replay dependencies are not exact trusted functions",
    ):
        admit_implicit_competition_current_source_authority(
            proof.canonical_bytes,
            review.canonical_bytes,
            **_replay_kwargs(roots),
        )
    destination = tmp_path / "forged-replay-must-not-write.json"
    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="replay dependencies are not exact trusted functions",
    ):
        write_implicit_competition_current_source_authority(
            authority.canonical_bytes,
            destination,
            **_replay_kwargs(roots),
        )
    assert not destination.exists()


def test_admit_and_write_fail_closed_if_internal_provider_identity_drifts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nbadb.core import nba_api_provenance

    proof, roots = _generation_proof(tmp_path / "provider-drift-roots")
    review = _review(proof)
    authority = _direct_authority(proof, review)
    monkeypatch.setattr(
        nba_api_provenance,
        "expected_nba_api_provider_authority",
        lambda: {"authority_sha256": "f" * 64},
    )

    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="replay dependencies are not exact trusted functions",
    ):
        admit_implicit_competition_current_source_authority(
            proof.canonical_bytes,
            review.canonical_bytes,
            **_replay_kwargs(roots),
        )
    destination = tmp_path / "provider-drift-must-not-write.json"
    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="replay dependencies are not exact trusted functions",
    ):
        write_implicit_competition_current_source_authority(
            authority.canonical_bytes,
            destination,
            **_replay_kwargs(roots),
        )
    assert not destination.exists()


def test_write_rejects_current_file_mutation_after_admission(tmp_path: Path) -> None:
    authority, roots = _authority(tmp_path / "authority-roots")
    root = roots[0]
    source = root / SOURCE_PATHS[8]
    source.write_bytes(source.read_bytes() + b"\n# changed after review\n")

    with pytest.raises(
        ImplicitCompetitionSourceAuthorityError,
        match="three independently generated source candidates differ|three-root replay",
    ):
        write_implicit_competition_current_source_authority(
            authority.canonical_bytes,
            tmp_path / "mutated-source.json",
            **_replay_kwargs(roots),
        )
