"""Deterministic current-source authority for implicit competition semantics.

The historical A1.2d evidence and its later repair packets are immutable inputs,
not mutable hash manifests.  This module adds a small current-source authority
whose candidate is generated from exact repository bytes, whose review is a
separate identity, and whose final admission recomputes both objects.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar, Self, cast

from nbadb.contracts.review_evidence import ReviewEvidenceError, ReviewReceiptV1


class ImplicitCompetitionSourceAuthorityError(ValueError):
    """The current implicit-competition source authority is invalid."""


SOURCE_PATHS = (
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

_FROZEN_BINDINGS = (
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
_REPAIR_11_RECEIPT_SHA256 = "5d4f632aba3d9fc362df169f39822476aff05c4e8735dfc70e53097985b2fc14"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_ROOT_INDEPENDENCE_CONTRACT = {
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
        "member_size_bounds": {
            "maximum_bytes": 16 * 1024 * 1024,
            "minimum_bytes": 1,
        },
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
_HISTORICAL_BARRIERS = (
    (
        "artifacts/assurance/complete-nba-api-sink/A1.2c/source-inputs/"
        "endpoint-support-evidence.json",
        "6db164143c588092acbd2c8497b068a770ff5a39501d1c05e28ef638b6fb6cfb",
    ),
    (
        "artifacts/assurance/complete-nba-api-sink/A1.2c/source-inputs/source-review.json",
        "accdd459d72d58be7c8b83f9c17e2e2086c058f3112b7714f4f0ea33e588f589",
    ),
    (
        "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2d.json",
        "acc12887aa5525a0ed9cc8047264c7efda3da92da745c5145138b4eb2a72e1bb",
    ),
    (
        "artifacts/assurance/complete-nba-api-sink/A1.2d/source-inputs/"
        "implicit-competition-root-evidence.json",
        "ff848edf46d65bbfc5748e0b30a59d45e2be2a981a578fab73170089aa1c12ba",
    ),
    (
        "artifacts/assurance/complete-nba-api-sink/A1.2d/source-inputs/source-review.json",
        "d028c60baa78832991d83cbd977d0d555b32b6ebc38a281bb14e7592d76f37e8",
    ),
    (
        "src/nbadb/contracts/nba_api_implicit_competition_v1_11_4.json",
        "ed75be5cf84df8975cc32d50b51215648896b618584ed5b3b3aedcb8b6dc2111",
    ),
)
_SUCCESSOR_RECONCILIATIONS = (
    (
        "A1.2c",
        (
            "src/nbadb/core/nba_api_request_surface.py",
            "src/nbadb/core/nba_api_request_surface_verifier.py",
            "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
            "src/nbadb/contracts/nba_api_competition_occurrences_v1_11_4.json",
        ),
        "99bd793926effc6edaa01c8796c3016410d45040a54e83ff881359f4055f782b",
    ),
    (
        "A1.2d",
        (
            "src/nbadb/core/nba_api_request_surface.py",
            "src/nbadb/core/nba_api_request_surface_verifier.py",
            "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
            "src/nbadb/contracts/nba_api_competition_occurrences_v1_11_4.json",
            "src/nbadb/core/nba_api_competition_applicability.py",
            "src/nbadb/core/nba_api_competition_applicability_verifier.py",
            "src/nbadb/contracts/nba_api_competition_applicability_v1_11_4.json",
        ),
        "ff9e7db0ac7f7e2d6845f36ff21facc04ca9479cf7cfe6bbc639e70e7451c2c1",
    ),
)
_SUCCESSOR_TASK_PACKETS = {
    "A1.2c": (
        "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2c.json",
        "d2f668cd0627562508849423c5df5d8e0e120a2fecc270a44699c9fe4458bf91",
    ),
    "A1.2d": (
        "artifacts/assurance/complete-nba-api-sink/J0F/task-packets/A1.2d.json",
        "acc12887aa5525a0ed9cc8047264c7efda3da92da745c5145138b4eb2a72e1bb",
    ),
}
_SUCCESSOR_OPENING_ROWS = {
    "A1.2c": (
        (
            "src/nbadb/core/nba_api_request_surface.py",
            "ff5f5bc589876a5b624f93692f8a43021cf3a2465a9cdd18475c3497dab0fc96",
        ),
        (
            "src/nbadb/core/nba_api_request_surface_verifier.py",
            "e85960d3577daf967136ef31f519ea03f27c849d58e1450ee86ab88cf5959308",
        ),
        (
            "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
            "c5b1de0b1e6e05541eec90df9c92ce3ca9e3c1cae490fe6723410137f947e608",
        ),
        (
            "src/nbadb/contracts/nba_api_competition_occurrences_v1_11_4.json",
            "28f72468be47dce5b13429e43140f96277422892ee8dc21ab723ef1c606bc700",
        ),
    ),
    "A1.2d": (
        (
            "src/nbadb/core/nba_api_request_surface.py",
            "ff5f5bc589876a5b624f93692f8a43021cf3a2465a9cdd18475c3497dab0fc96",
        ),
        (
            "src/nbadb/core/nba_api_request_surface_verifier.py",
            "e85960d3577daf967136ef31f519ea03f27c849d58e1450ee86ab88cf5959308",
        ),
        (
            "src/nbadb/contracts/nba_api_request_surface_v1_11_4.json",
            "c5b1de0b1e6e05541eec90df9c92ce3ca9e3c1cae490fe6723410137f947e608",
        ),
        (
            "src/nbadb/contracts/nba_api_competition_occurrences_v1_11_4.json",
            "28f72468be47dce5b13429e43140f96277422892ee8dc21ab723ef1c606bc700",
        ),
        (
            "src/nbadb/core/nba_api_competition_applicability.py",
            "271bfa9855bf4c3e8f51bc3eaff82d6225c5a89569fdc319a7d43856d0085cda",
        ),
        (
            "src/nbadb/core/nba_api_competition_applicability_verifier.py",
            "a847dff632338981aa522646ce766a2e029aa43a95c4adcc3e0fb427e06a7ebd",
        ),
        (
            "src/nbadb/contracts/nba_api_competition_applicability_v1_11_4.json",
            "2542f2b0a5fd0ba3faefc8ce7b4bf2b1f1870b12beb6d98172cdd7e3857e1b53",
        ),
    ),
}
_SUCCESSOR_OPENING_SHA256S = {
    "A1.2c": "a94f22cba94539250b6a1e1c8be199dcf903b102f5290ee5ed4ece343bfcac90",
    "A1.2d": "923d931c5f8e58f6a74d29aa4d245fcaa9a9df1a52b1e632e1b0a3bc772cb653",
}
_HISTORICAL_SEMANTIC_PROJECTION_FIELDS = (
    "endpoint_bindings",
    "alias_bindings",
    "physical_competition_cells",
    "alias_competition_cells",
    "denominator_counts",
    "receipt_bound_root_policy",
)
_HISTORICAL_LIFECYCLE_FLAGS = {
    "current_paths_never_reinterpreted_as_historical_bytes": True,
    "generic_or_implicit_fallback_permitted": False,
    "implicit_checked_resource_mutation_permitted": False,
    "implicit_supersession_proof_authority_depends_on_future_receipt": False,
    "implicit_supersession_proof_public_output": False,
    "sealed_and_current_stable_projection_required": True,
    "w5_double_derivation_required": True,
    "w6_binds_finalized_proof_digest_without_receipt_dependency": True,
    "w8_third_replay_required": True,
    "w9_recomputation_or_rebinding_permitted": False,
    "w9_records_but_does_not_authorize_proof": True,
}


def _fail(message: str) -> None:
    raise ImplicitCompetitionSourceAuthorityError(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ImplicitCompetitionSourceAuthorityError(
            "implicit source authority is not canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("implicit source authority contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    _fail(f"implicit source authority contains non-finite JSON: {value}")


def _decode_strict_object(raw: bytes, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ImplicitCompetitionSourceAuthorityError(f"{label} is not strict UTF-8 JSON") from exc
    if type(payload) is not dict:
        _fail(f"{label} root must be an object")
    return payload


def _require_exact_keys(payload: dict[str, object], expected: set[str], *, label: str) -> None:
    if set(payload) != expected:
        _fail(f"{label} keys differ from the exact schema")


def _require_string(value: object, *, field: str) -> str:
    if type(value) is not str or not value:
        _fail(f"{field} must be a nonempty string")
    return cast("str", value)


def _require_identifier(value: object, *, field: str) -> str:
    result = _require_string(value, field=field)
    if _IDENTIFIER_RE.fullmatch(result) is None or not result.isascii():
        _fail(f"{field} is not a safe ASCII identifier")
    return result


def _require_sha256(value: object, *, field: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field} must be a lowercase SHA-256")
    return cast("str", value)


def _safe_relative_path(value: object) -> str:
    path_string = _require_string(value, field="source path")
    path = PurePosixPath(path_string)
    if (
        not path_string.isascii()
        or "\\" in path_string
        or path.is_absolute()
        or path.as_posix() != path_string
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _fail("source path is not a safe normalized relative POSIX path")
    return path_string


_MAX_SOURCE_FILE_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_SNAPSHOT_BYTES = 128 * 1024 * 1024
_MAX_PROOF_CANONICAL_BYTES = 4 * 1024 * 1024
_MAX_REVIEW_CANONICAL_BYTES = 2 * 1024 * 1024
_MAX_AUTHORITY_CANONICAL_BYTES = 8 * 1024 * 1024
_CONCRETE_PATH_TYPE = type(Path())


def _decode_bounded_canonical_object(
    raw: bytes,
    *,
    label: str,
    maximum_bytes: int,
) -> dict[str, object]:
    if type(raw) is not bytes:
        _fail(f"{label} must be exact built-in bytes")
    if not raw or len(raw) > maximum_bytes:
        _fail(f"{label} size is outside the exact bound")
    payload = _decode_strict_object(raw, label=label)
    if _canonical_bytes(payload) != raw:
        _fail(f"{label} bytes are not canonical")
    return payload


@dataclass(frozen=True, slots=True)
class _SourceRootSnapshot:
    resolved_root: Path
    root_identity: tuple[int, int]
    contents: tuple[tuple[str, bytes], ...]
    member_identities: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True, slots=True)
class _HeldPathEdge:
    parent_fd: int
    name: str
    child_fd: int
    expected_kind: int
    label: str


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _path_edge_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode))


def _validate_path_edge(edge: _HeldPathEdge) -> None:
    named = os.stat(
        edge.name,
        dir_fd=edge.parent_fd,
        follow_symlinks=False,
    )
    held = os.fstat(edge.child_fd)
    expected_description = "directory" if edge.expected_kind == stat.S_IFDIR else "regular file"
    if (
        stat.S_IFMT(named.st_mode) != edge.expected_kind
        or stat.S_IFMT(held.st_mode) != edge.expected_kind
    ):
        _fail(f"{edge.label} path edge is not the expected {expected_description}")
    if _path_edge_identity(named) != _path_edge_identity(held):
        _fail(f"{edge.label} pathname was rebound during the coherent snapshot")


def _hold_path_edge(
    edges: list[_HeldPathEdge],
    *,
    parent_fd: int,
    name: str,
    child_fd: int,
    expected_kind: int,
    label: str,
) -> None:
    edge = _HeldPathEdge(
        parent_fd=parent_fd,
        name=name,
        child_fd=child_fd,
        expected_kind=expected_kind,
        label=label,
    )
    _validate_path_edge(edge)
    edges.append(edge)


def _validate_path_edges(edges: list[_HeldPathEdge], *, phase: str) -> None:
    if phase not in {
        "after_all_first_reads_before_second_reads",
        "after_second_reads_and_root_stat_before_return",
    }:
        _fail("source snapshot path-edge validation phase is invalid")
    for edge in edges:
        _validate_path_edge(edge)


def _read_fd_bytes(descriptor: int, *, relative: str) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while chunk := os.read(descriptor, 1024 * 1024):
        total += len(chunk)
        if total > _MAX_SOURCE_FILE_BYTES:
            _fail(f"source inventory member exceeds its size bound: {relative}")
        chunks.append(chunk)
    return b"".join(chunks)


def _read_source_root_snapshot(
    root: Path,
    relative_paths: tuple[str, ...],
) -> _SourceRootSnapshot:
    """Read one coherent bounded snapshot through held no-follow descriptors."""

    if len(relative_paths) != len(set(relative_paths)):
        _fail("source snapshot inventory contains duplicate paths")
    required_flags = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, name) for name in required_flags):
        _fail("platform lacks required no-follow source snapshot flags")
    try:
        original_before = root.stat(follow_symlinks=False)
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise ImplicitCompetitionSourceAuthorityError(
            "source root cannot be authenticated"
        ) from exc
    if not stat.S_ISDIR(original_before.st_mode):
        _fail("source root must be a non-symlink directory")

    opened: list[int] = []
    held_files: list[tuple[str, int, os.stat_result, bytes]] = []
    held_edges: list[_HeldPathEdge] = []
    try:
        anchor = os.open(
            resolved.anchor,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        opened.append(anchor)
        _hold_path_edge(
            held_edges,
            parent_fd=anchor,
            name=".",
            child_fd=anchor,
            expected_kind=stat.S_IFDIR,
            label="source root absolute anchor",
        )
        directory_fd = anchor
        for component in resolved.parts[1:]:
            parent_fd = directory_fd
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            opened.append(next_fd)
            _hold_path_edge(
                held_edges,
                parent_fd=parent_fd,
                name=component,
                child_fd=next_fd,
                expected_kind=stat.S_IFDIR,
                label="source root absolute component",
            )
            directory_fd = next_fd
        root_fd = directory_fd
        opened_root_before = os.fstat(root_fd)
        if (original_before.st_dev, original_before.st_ino) != (
            opened_root_before.st_dev,
            opened_root_before.st_ino,
        ):
            _fail("source root changed during authenticated descriptor walk")

        total_bytes = 0
        for relative in relative_paths:
            safe = PurePosixPath(_safe_relative_path(relative))
            member_directory_fd = os.dup(root_fd)
            opened.append(member_directory_fd)
            for component in safe.parts[:-1]:
                parent_fd = member_directory_fd
                next_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
                opened.append(next_fd)
                _hold_path_edge(
                    held_edges,
                    parent_fd=parent_fd,
                    name=component,
                    child_fd=next_fd,
                    expected_kind=stat.S_IFDIR,
                    label=f"source inventory member directory: {relative}",
                )
                member_directory_fd = next_fd
            file_fd = os.open(
                safe.parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=member_directory_fd,
            )
            opened.append(file_fd)
            _hold_path_edge(
                held_edges,
                parent_fd=member_directory_fd,
                name=safe.parts[-1],
                child_fd=file_fd,
                expected_kind=stat.S_IFREG,
                label=f"source inventory member: {relative}",
            )
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                _fail("source inventory member is not a regular file")
            if before.st_size <= 0 or before.st_size > _MAX_SOURCE_FILE_BYTES:
                _fail("source inventory member size is outside the exact bound")
            raw = _read_fd_bytes(file_fd, relative=relative)
            total_bytes += len(raw)
            if total_bytes > _MAX_SOURCE_SNAPSHOT_BYTES:
                _fail("source snapshot exceeds its total size bound")
            if len(raw) != before.st_size or _stat_identity(os.fstat(file_fd)) != (
                _stat_identity(before)
            ):
                _fail("source inventory member changed during initial read")
            held_files.append((relative, file_fd, before, raw))

        _validate_path_edges(
            held_edges,
            phase="after_all_first_reads_before_second_reads",
        )
        for relative, file_fd, before, first_raw in held_files:
            second_raw = _read_fd_bytes(file_fd, relative=relative)
            after = os.fstat(file_fd)
            if first_raw != second_raw or _stat_identity(before) != _stat_identity(after):
                _fail("source inventory member changed across the coherent snapshot")
        opened_root_after = os.fstat(root_fd)
        try:
            original_after = root.stat(follow_symlinks=False)
        except OSError as exc:
            raise ImplicitCompetitionSourceAuthorityError(
                "source root changed after snapshot"
            ) from exc
        if (opened_root_before.st_dev, opened_root_before.st_ino) != (
            opened_root_after.st_dev,
            opened_root_after.st_ino,
        ) or (original_before.st_dev, original_before.st_ino) != (
            original_after.st_dev,
            original_after.st_ino,
        ):
            _fail("source root changed across the coherent snapshot")
        _validate_path_edges(
            held_edges,
            phase="after_second_reads_and_root_stat_before_return",
        )
        return _SourceRootSnapshot(
            resolved_root=resolved,
            root_identity=(opened_root_before.st_dev, opened_root_before.st_ino),
            contents=tuple((path, raw) for path, _fd, _stat, raw in held_files),
            member_identities=tuple(
                (path, before.st_dev, before.st_ino) for path, _fd, before, _raw in held_files
            ),
        )
    except OSError as exc:
        raise ImplicitCompetitionSourceAuthorityError(
            "source snapshot is unsafe or unreadable"
        ) from exc
    finally:
        for descriptor in reversed(opened):
            with suppress(OSError):
                os.close(descriptor)


def _python_semantic_sha256(raw: bytes, *, path: str) -> str:
    try:
        tree = ast.parse(raw, filename=path)
    except (SyntaxError, UnicodeDecodeError) as exc:
        raise ImplicitCompetitionSourceAuthorityError(
            f"source inventory member is not valid Python: {path}"
        ) from exc
    return hashlib.sha256(
        ast.dump(tree, annotate_fields=True, include_attributes=False).encode("utf-8")
    ).hexdigest()


def _validate_repair_11_historical_contract(raw: bytes) -> None:
    """Authenticate the exact historical barriers and ordered successor commitments."""

    payload = _decode_strict_object(raw, label="repair-11 packet")
    if payload.get("schema") != "TaskPacketV1" or payload.get("task_id") != ("A1.3a-repair-11"):
        _fail("repair-11 packet identity drifted")
    checked = payload.get("checked_resource_contracts")
    if type(checked) is not dict:
        _fail("repair-11 checked-resource contract is missing")
    historical = cast("dict[str, object]", checked).get("historical_supersession_contract")
    if type(historical) is not dict:
        _fail("repair-11 historical supersession contract is missing")
    historical_contract = cast("dict[str, object]", historical)
    expected_barriers = [{"path": path, "sha256": digest} for path, digest in _HISTORICAL_BARRIERS]
    if historical_contract.get("historical_barriers") != expected_barriers:
        _fail("repair-11 historical barrier membership or order drifted")
    if historical_contract.get("implicit_current_semantic_projection_fields") != list(
        _HISTORICAL_SEMANTIC_PROJECTION_FIELDS
    ):
        _fail("repair-11 semantic projection field order drifted")
    if historical_contract.get("digest_convention") != (
        "SHA-256 of canonical minified UTF-8 JSON for the exact ordered path-string or "
        "{path,sha256} row array with object keys sorted, ensure_ascii=false, nonfinite "
        "values rejected, and no trailing LF"
    ):
        _fail("repair-11 canonical digest convention drifted")
    reconciliations = historical_contract.get("successor_reconciliations")
    if type(reconciliations) is not list or len(reconciliations) != len(_SUCCESSOR_RECONCILIATIONS):
        _fail("repair-11 successor reconciliation inventory drifted")
    reconciliation_rows = cast("list[object]", reconciliations)
    for row, (task_id, paths, paths_sha256) in zip(
        reconciliation_rows,
        _SUCCESSOR_RECONCILIATIONS,
        strict=True,
    ):
        if type(row) is not dict:
            _fail("repair-11 successor reconciliation row is invalid")
        reconciliation = cast("dict[str, object]", row)
        task_packet = reconciliation.get("historical_task_packet")
        if type(task_packet) is not dict:
            _fail("repair-11 successor task-packet binding is missing")
        task_packet_binding = cast("dict[str, object]", task_packet)
        expected_task_packet_path, expected_task_packet_digest = _SUCCESSOR_TASK_PACKETS[task_id]
        opening_rows = _SUCCESSOR_OPENING_ROWS[task_id]
        expected_opening_rows = [{"path": path, "sha256": digest} for path, digest in opening_rows]
        expected_opening_sha256 = _SUCCESSOR_OPENING_SHA256S[task_id]
        if (
            reconciliation.get("historical_task_id") != task_id
            or task_packet_binding.get("path") != expected_task_packet_path
            or type(reconciliation.get("successor_path_count")) is not int
            or reconciliation.get("successor_path_count") != len(paths)
            or reconciliation.get("opening_rows") != expected_opening_rows
            or reconciliation.get("opening_rows_sha256") != expected_opening_sha256
            or _digest(expected_opening_rows) != expected_opening_sha256
            or reconciliation.get("successor_paths") != list(paths)
            or reconciliation.get("successor_paths_sha256") != paths_sha256
            or _digest(list(paths)) != paths_sha256
            or task_packet_binding.get("sha256") != expected_task_packet_digest
        ):
            _fail("repair-11 ordered successor commitment drifted")
    if any(
        historical_contract.get(name) is not value
        for name, value in _HISTORICAL_LIFECYCLE_FLAGS.items()
    ):
        _fail("repair-11 proof lifecycle contract drifted")


@dataclass(frozen=True, slots=True)
class FrozenSourceBindingV1:
    name: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _require_identifier(self.name, field="frozen binding name")
        _safe_relative_path(self.path)
        _require_sha256(self.sha256, field="frozen binding sha256")

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "path": self.path, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, payload: object) -> Self:
        if type(payload) is not dict:
            _fail("frozen binding must be an object")
        item = cast("dict[str, object]", payload)
        _require_exact_keys(item, {"name", "path", "sha256"}, label="frozen binding")
        return cls(
            name=_require_identifier(item["name"], field="frozen binding name"),
            path=_safe_relative_path(item["path"]),
            sha256=_require_sha256(item["sha256"], field="frozen binding sha256"),
        )


@dataclass(frozen=True, slots=True)
class CurrentSourceBindingV1:
    path: str
    byte_count: int
    sha256: str
    semantic_sha256: str

    def __post_init__(self) -> None:
        _safe_relative_path(self.path)
        if type(self.byte_count) is not int or self.byte_count <= 0:
            _fail("source byte_count must be a positive exact integer")
        _require_sha256(self.sha256, field="source sha256")
        _require_sha256(self.semantic_sha256, field="source semantic_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "byte_count": self.byte_count,
            "path": self.path,
            "semantic_sha256": self.semantic_sha256,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, payload: object) -> Self:
        if type(payload) is not dict:
            _fail("source binding must be an object")
        item = cast("dict[str, object]", payload)
        _require_exact_keys(
            item,
            {"byte_count", "path", "semantic_sha256", "sha256"},
            label="source binding",
        )
        byte_count = item["byte_count"]
        if type(byte_count) is not int:
            _fail("source byte_count must be an exact integer")
        return cls(
            path=_safe_relative_path(item["path"]),
            byte_count=cast("int", byte_count),
            sha256=_require_sha256(item["sha256"], field="source sha256"),
            semantic_sha256=_require_sha256(
                item["semantic_sha256"], field="source semantic_sha256"
            ),
        )


_EXPECTED_FROZEN_BINDINGS = tuple(FrozenSourceBindingV1(*row) for row in _FROZEN_BINDINGS)


@dataclass(frozen=True, slots=True)
class ImplicitCompetitionSourceCandidateV1:
    provider_authority_sha256: str
    predecessor_receipt_sha256: str
    author_task_id: str
    author_role: str
    frozen_bindings: tuple[FrozenSourceBindingV1, ...]
    source_bindings: tuple[CurrentSourceBindingV1, ...]
    source_inventory_sha256: str
    semantic_projection_sha256: str
    candidate_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_implicit_competition_source_candidate"

    def __post_init__(self) -> None:
        _require_sha256(self.provider_authority_sha256, field="provider_authority_sha256")
        if self.predecessor_receipt_sha256 != _REPAIR_11_RECEIPT_SHA256:
            _fail("candidate predecessor receipt binding drifted")
        _require_identifier(self.author_task_id, field="author_task_id")
        _require_identifier(self.author_role, field="author_role")
        if type(self.frozen_bindings) is not tuple or any(
            type(item) is not FrozenSourceBindingV1 for item in self.frozen_bindings
        ):
            _fail("candidate frozen bindings differ from immutable history")
        for item in self.frozen_bindings:
            FrozenSourceBindingV1.from_dict(item.to_dict())
        if tuple(item.to_dict() for item in self.frozen_bindings) != tuple(
            item.to_dict() for item in _EXPECTED_FROZEN_BINDINGS
        ):
            _fail("candidate frozen bindings differ from immutable history")
        if type(self.source_bindings) is not tuple or any(
            type(item) is not CurrentSourceBindingV1 for item in self.source_bindings
        ):
            _fail("candidate source inventory differs from the exact 13-file order")
        for item in self.source_bindings:
            CurrentSourceBindingV1.from_dict(item.to_dict())
        if tuple(item.path for item in self.source_bindings) != SOURCE_PATHS:
            _fail("candidate source inventory differs from the exact 13-file order")
        inventory = [item.to_dict() for item in self.source_bindings]
        expected_inventory = _digest(inventory)
        expected_semantic = _digest(
            [
                {"path": item.path, "semantic_sha256": item.semantic_sha256}
                for item in self.source_bindings
            ]
        )
        if self.source_inventory_sha256 != expected_inventory:
            _fail("candidate source inventory digest drifted")
        if self.semantic_projection_sha256 != expected_semantic:
            _fail("candidate semantic projection digest drifted")
        if self.candidate_sha256 != _digest(self._body()):
            _fail("candidate digest drifted")

    def _body(self) -> dict[str, object]:
        return {
            "author_role": self.author_role,
            "author_task_id": self.author_task_id,
            "frozen_bindings": [item.to_dict() for item in self.frozen_bindings],
            "kind": self.kind,
            "predecessor_receipt_sha256": self.predecessor_receipt_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "schema_version": self.schema_version,
            "semantic_projection_sha256": self.semantic_projection_sha256,
            "source_bindings": [item.to_dict() for item in self.source_bindings],
            "source_inventory_sha256": self.source_inventory_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "candidate_sha256": self.candidate_sha256}

    @classmethod
    def from_dict(cls, payload: object) -> Self:
        if type(payload) is not dict:
            _fail("candidate must be an object")
        item = cast("dict[str, object]", payload)
        expected = {
            "author_role",
            "author_task_id",
            "candidate_sha256",
            "frozen_bindings",
            "kind",
            "predecessor_receipt_sha256",
            "provider_authority_sha256",
            "schema_version",
            "semantic_projection_sha256",
            "source_bindings",
            "source_inventory_sha256",
        }
        _require_exact_keys(item, expected, label="candidate")
        if (
            item["kind"] != cls.kind
            or type(item["schema_version"]) is not int
            or item["schema_version"] != cls.schema_version
        ):
            _fail("candidate schema identity is invalid")
        frozen = item["frozen_bindings"]
        sources = item["source_bindings"]
        if type(frozen) is not list or type(sources) is not list:
            _fail("candidate binding inventories must be arrays")
        frozen_rows = cast("list[object]", frozen)
        source_rows = cast("list[object]", sources)
        return cls(
            provider_authority_sha256=_require_sha256(
                item["provider_authority_sha256"], field="provider_authority_sha256"
            ),
            predecessor_receipt_sha256=_require_sha256(
                item["predecessor_receipt_sha256"],
                field="predecessor_receipt_sha256",
            ),
            author_task_id=_require_identifier(item["author_task_id"], field="author_task_id"),
            author_role=_require_identifier(item["author_role"], field="author_role"),
            frozen_bindings=tuple(FrozenSourceBindingV1.from_dict(row) for row in frozen_rows),
            source_bindings=tuple(CurrentSourceBindingV1.from_dict(row) for row in source_rows),
            source_inventory_sha256=_require_sha256(
                item["source_inventory_sha256"], field="source_inventory_sha256"
            ),
            semantic_projection_sha256=_require_sha256(
                item["semantic_projection_sha256"], field="semantic_projection_sha256"
            ),
            candidate_sha256=_require_sha256(item["candidate_sha256"], field="candidate_sha256"),
        )


def _generation_policy_sha256(candidate_bytes_sha256: str) -> str:
    """Bind the deterministic read policy, not ephemeral physical-root history."""

    return _digest(
        {
            "candidate_bytes_sha256": _require_sha256(
                candidate_bytes_sha256,
                field="candidate_bytes_sha256",
            ),
            "frozen_paths": [row[1] for row in _FROZEN_BINDINGS],
            "policy": _ROOT_INDEPENDENCE_CONTRACT,
            "policy_version": 2,
            "source_paths": list(SOURCE_PATHS),
        }
    )


@dataclass(frozen=True, slots=True)
class ImplicitCompetitionSourceGenerationProofV1:
    """Structurally valid proof data whose construction does not confer admission."""

    candidate: ImplicitCompetitionSourceCandidateV1
    generation_candidate_bytes_sha256s: tuple[str, str, str]
    generation_policy_sha256: str
    proof_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_implicit_competition_source_generation_proof"

    def __post_init__(self) -> None:
        _validated_generation_proof_payload(self)

    def _body(self) -> dict[str, object]:
        return {
            "candidate": self.candidate.to_dict(),
            "generation_candidate_bytes_sha256s": list(self.generation_candidate_bytes_sha256s),
            "generation_policy_sha256": self.generation_policy_sha256,
            "kind": self.kind,
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "proof_sha256": self.proof_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: object) -> Self:
        if type(payload) is not dict:
            _fail("generation proof must be an object")
        item = cast("dict[str, object]", payload)
        _require_exact_keys(
            item,
            {
                "candidate",
                "generation_candidate_bytes_sha256s",
                "generation_policy_sha256",
                "kind",
                "proof_sha256",
                "schema_version",
            },
            label="generation proof",
        )
        if (
            item["kind"] != cls.kind
            or type(item["schema_version"]) is not int
            or item["schema_version"] != cls.schema_version
        ):
            _fail("generation proof schema identity is invalid")
        derivations = item["generation_candidate_bytes_sha256s"]
        if type(derivations) is not list or len(derivations) != 3:
            _fail("generation proof derivation inventory is invalid")
        rows = cast("list[object]", derivations)
        return cls(
            candidate=ImplicitCompetitionSourceCandidateV1.from_dict(item["candidate"]),
            generation_candidate_bytes_sha256s=cast(
                "tuple[str, str, str]",
                tuple(
                    _require_sha256(value, field="generation candidate bytes sha256")
                    for value in rows
                ),
            ),
            generation_policy_sha256=_require_sha256(
                item["generation_policy_sha256"],
                field="generation_policy_sha256",
            ),
            proof_sha256=_require_sha256(item["proof_sha256"], field="proof_sha256"),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(
            _decode_bounded_canonical_object(
                raw,
                label="generation proof",
                maximum_bytes=_MAX_PROOF_CANONICAL_BYTES,
            )
        )


def _validated_candidate_payload(
    candidate: ImplicitCompetitionSourceCandidateV1,
) -> dict[str, object]:
    if type(candidate) is not ImplicitCompetitionSourceCandidateV1:
        _fail("generation proof candidate has an invalid type")
    raw = _canonical_bytes(candidate.to_dict())
    normalized = ImplicitCompetitionSourceCandidateV1.from_dict(
        _decode_strict_object(raw, label="current source candidate")
    )
    normalized_payload = normalized.to_dict()
    if _canonical_bytes(normalized_payload) != raw:
        _fail("generation proof candidate failed exact structural revalidation")
    return normalized_payload


def _validated_generation_proof_payload(
    proof: ImplicitCompetitionSourceGenerationProofV1,
) -> dict[str, object]:
    if type(proof) is not ImplicitCompetitionSourceGenerationProofV1:
        _fail("generation proof has an invalid type")
    candidate_payload = _validated_candidate_payload(proof.candidate)
    expected_bytes_sha256 = hashlib.sha256(_canonical_bytes(candidate_payload)).hexdigest()
    if (
        type(proof.generation_candidate_bytes_sha256s) is not tuple
        or len(proof.generation_candidate_bytes_sha256s) != 3
        or any(
            type(value) is not str
            or _SHA256_RE.fullmatch(value) is None
            or value != expected_bytes_sha256
            for value in proof.generation_candidate_bytes_sha256s
        )
    ):
        _fail("generation proof does not contain three identical derivations")
    generation_policy_sha256 = _require_sha256(
        proof.generation_policy_sha256,
        field="generation_policy_sha256",
    )
    if generation_policy_sha256 != _generation_policy_sha256(expected_bytes_sha256):
        _fail("generation proof policy commitment drifted")
    body = {
        "candidate": candidate_payload,
        "generation_candidate_bytes_sha256s": list(proof.generation_candidate_bytes_sha256s),
        "generation_policy_sha256": generation_policy_sha256,
        "kind": ImplicitCompetitionSourceGenerationProofV1.kind,
        "schema_version": ImplicitCompetitionSourceGenerationProofV1.schema_version,
    }
    proof_sha256 = _require_sha256(proof.proof_sha256, field="proof_sha256")
    if proof_sha256 != _digest(body):
        _fail("generation proof digest drifted")
    return {**body, "proof_sha256": proof_sha256}


def _required_review_input_sha256s(
    proof_payload: dict[str, object],
) -> tuple[str, ...]:
    candidate = cast("dict[str, object]", proof_payload["candidate"])
    frozen_bindings = cast("list[dict[str, object]]", candidate["frozen_bindings"])
    source_bindings = cast("list[dict[str, object]]", candidate["source_bindings"])
    values = {
        cast("str", candidate["candidate_sha256"]),
        cast("str", candidate["provider_authority_sha256"]),
        cast("str", candidate["predecessor_receipt_sha256"]),
        cast("str", candidate["semantic_projection_sha256"]),
        cast("str", candidate["source_inventory_sha256"]),
        cast("str", proof_payload["proof_sha256"]),
        cast("str", proof_payload["generation_policy_sha256"]),
        *cast("list[str]", proof_payload["generation_candidate_bytes_sha256s"]),
        *(cast("str", item["sha256"]) for item in frozen_bindings),
        *(cast("str", item["sha256"]) for item in source_bindings),
        *(cast("str", item["semantic_sha256"]) for item in source_bindings),
    }
    return tuple(sorted(values))


@dataclass(frozen=True, slots=True)
class ImplicitCompetitionCurrentSourceAuthorityV1:
    """Structurally valid authority data whose construction does not confer trust."""

    generation_proof: ImplicitCompetitionSourceGenerationProofV1
    review: ReviewReceiptV1
    authority_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_implicit_competition_current_source_authority"

    @property
    def candidate(self) -> ImplicitCompetitionSourceCandidateV1:
        return self.generation_proof.candidate

    def __post_init__(self) -> None:
        _validated_authority_payload(self)

    def _body(self) -> dict[str, object]:
        return {
            "generation_proof": self.generation_proof.to_dict(),
            "kind": self.kind,
            "review": self.review.to_dict(),
            "schema_version": self.schema_version,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "authority_sha256": self.authority_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: object) -> Self:
        if type(payload) is not dict:
            _fail("current source authority must be an object")
        item = cast("dict[str, object]", payload)
        _require_exact_keys(
            item,
            {
                "authority_sha256",
                "generation_proof",
                "kind",
                "review",
                "schema_version",
            },
            label="current source authority",
        )
        if (
            item["kind"] != cls.kind
            or type(item["schema_version"]) is not int
            or item["schema_version"] != cls.schema_version
        ):
            _fail("current source authority schema identity is invalid")
        try:
            review = ReviewReceiptV1.from_dict(item["review"])
        except ReviewEvidenceError as exc:
            raise ImplicitCompetitionSourceAuthorityError(
                "current source review receipt is invalid"
            ) from exc
        return cls(
            generation_proof=ImplicitCompetitionSourceGenerationProofV1.from_dict(
                item["generation_proof"]
            ),
            review=review,
            authority_sha256=_require_sha256(
                item["authority_sha256"],
                field="authority_sha256",
            ),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        return cls.from_dict(
            _decode_bounded_canonical_object(
                raw,
                label="current source authority",
                maximum_bytes=_MAX_AUTHORITY_CANONICAL_BYTES,
            )
        )


def _normalized_review(
    review: ReviewReceiptV1,
) -> tuple[ReviewReceiptV1, dict[str, object]]:
    if type(review) is not ReviewReceiptV1:
        _fail("source authority requires an exact review receipt")
    raw = _canonical_bytes(review.to_dict())
    try:
        normalized = ReviewReceiptV1.from_dict(
            _decode_strict_object(raw, label="current source review")
        )
    except ReviewEvidenceError as exc:
        raise ImplicitCompetitionSourceAuthorityError(
            "current source review receipt is invalid"
        ) from exc
    payload = normalized.to_dict()
    if _canonical_bytes(payload) != raw:
        _fail("current source review failed exact structural revalidation")
    return normalized, payload


def _review_from_canonical_bytes(raw: bytes) -> ReviewReceiptV1:
    if type(raw) is not bytes:
        _fail("current source review must be exact built-in bytes")
    if not raw or len(raw) > _MAX_REVIEW_CANONICAL_BYTES:
        _fail("current source review size is outside the exact bound")
    _decode_bounded_canonical_object(
        raw,
        label="current source review",
        maximum_bytes=_MAX_REVIEW_CANONICAL_BYTES,
    )
    try:
        review = ReviewReceiptV1.from_canonical_bytes(raw)
    except ReviewEvidenceError as exc:
        raise ImplicitCompetitionSourceAuthorityError(
            "current source review receipt is invalid"
        ) from exc
    if review.canonical_bytes != raw:
        _fail("current source review bytes are not canonical")
    return review


def _validate_review_binding(
    proof_payload: dict[str, object],
    review_payload: dict[str, object],
) -> None:
    candidate_payload = cast("dict[str, object]", proof_payload["candidate"])
    if (
        review_payload["subject_kind"] != candidate_payload["kind"]
        or review_payload["subject_semantic_sha256"] != candidate_payload["candidate_sha256"]
        or review_payload["author_task_id"] != candidate_payload["author_task_id"]
        or review_payload["author_role"] != candidate_payload["author_role"]
        or review_payload["disposition"] != "accepted"
        or review_payload["findings"] != []
        or tuple(cast("list[str]", review_payload["accepted_input_sha256s"]))
        != _required_review_input_sha256s(proof_payload)
    ):
        _fail("source review is incomplete, foreign, stale, or rebound")


def _validated_authority_payload(
    authority: ImplicitCompetitionCurrentSourceAuthorityV1,
) -> dict[str, object]:
    if type(authority) is not ImplicitCompetitionCurrentSourceAuthorityV1:
        _fail("current source authority has an invalid type")
    proof_payload = _validated_generation_proof_payload(authority.generation_proof)
    _normalized, review_payload = _normalized_review(authority.review)
    _validate_review_binding(proof_payload, review_payload)
    body = {
        "generation_proof": proof_payload,
        "kind": ImplicitCompetitionCurrentSourceAuthorityV1.kind,
        "review": review_payload,
        "schema_version": ImplicitCompetitionCurrentSourceAuthorityV1.schema_version,
    }
    authority_sha256 = _require_sha256(
        authority.authority_sha256,
        field="authority_sha256",
    )
    if authority_sha256 != _digest(body):
        _fail("current source authority digest drifted")
    return {**body, "authority_sha256": authority_sha256}


def _candidate_from_snapshot(
    snapshot: _SourceRootSnapshot,
    *,
    provider_authority_sha256: str,
    author_task_id: str,
    author_role: str,
) -> ImplicitCompetitionSourceCandidateV1:
    by_path = dict(snapshot.contents)
    frozen: list[FrozenSourceBindingV1] = []
    for expected in _EXPECTED_FROZEN_BINDINGS:
        raw = by_path[expected.path]
        if hashlib.sha256(raw).hexdigest() != expected.sha256:
            _fail(f"frozen source binding drifted: {expected.name}")
        if expected.name == "a1_3a_repair_11_packet":
            _validate_repair_11_historical_contract(raw)
        frozen.append(expected)
    sources: list[CurrentSourceBindingV1] = []
    for relative in SOURCE_PATHS:
        raw = by_path[relative]
        sources.append(
            CurrentSourceBindingV1(
                path=relative,
                byte_count=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                semantic_sha256=_python_semantic_sha256(raw, path=relative),
            )
        )
    inventory = [item.to_dict() for item in sources]
    semantic = [{"path": item.path, "semantic_sha256": item.semantic_sha256} for item in sources]
    body = {
        "author_role": _require_identifier(author_role, field="author_role"),
        "author_task_id": _require_identifier(author_task_id, field="author_task_id"),
        "frozen_bindings": [item.to_dict() for item in frozen],
        "kind": ImplicitCompetitionSourceCandidateV1.kind,
        "predecessor_receipt_sha256": _REPAIR_11_RECEIPT_SHA256,
        "provider_authority_sha256": _require_sha256(
            provider_authority_sha256, field="provider_authority_sha256"
        ),
        "schema_version": ImplicitCompetitionSourceCandidateV1.schema_version,
        "semantic_projection_sha256": _digest(semantic),
        "source_bindings": inventory,
        "source_inventory_sha256": _digest(inventory),
    }
    return ImplicitCompetitionSourceCandidateV1(
        provider_authority_sha256=body["provider_authority_sha256"],
        predecessor_receipt_sha256=body["predecessor_receipt_sha256"],
        author_task_id=body["author_task_id"],
        author_role=body["author_role"],
        frozen_bindings=tuple(frozen),
        source_bindings=tuple(sources),
        source_inventory_sha256=body["source_inventory_sha256"],
        semantic_projection_sha256=body["semantic_projection_sha256"],
        candidate_sha256=_digest(body),
    )


def _generate_implicit_competition_candidate_snapshot(
    project_root: Path | str,
    *,
    provider_authority_sha256: str,
    author_task_id: str,
    author_role: str,
) -> tuple[ImplicitCompetitionSourceCandidateV1, _SourceRootSnapshot]:
    root = Path(project_root)
    paths = tuple(row[1] for row in _FROZEN_BINDINGS) + SOURCE_PATHS
    snapshot = _read_source_root_snapshot(root, paths)
    return (
        _candidate_from_snapshot(
            snapshot,
            provider_authority_sha256=provider_authority_sha256,
            author_task_id=author_task_id,
            author_role=author_role,
        ),
        snapshot,
    )


def generate_implicit_competition_source_candidate(
    project_root: Path | str,
    *,
    provider_authority_sha256: str,
    author_task_id: str,
    author_role: str,
) -> ImplicitCompetitionSourceCandidateV1:
    """Generate one candidate from one coherent exact source-root snapshot."""

    candidate, _snapshot = _generate_implicit_competition_candidate_snapshot(
        project_root,
        provider_authority_sha256=provider_authority_sha256,
        author_task_id=author_task_id,
        author_role=author_role,
    )
    return candidate


def admit_implicit_competition_current_source_authority(
    generation_proof_bytes: bytes,
    review_bytes: bytes,
    *,
    first_root: Path | str,
    second_root: Path | str,
    third_root: Path | str,
) -> ImplicitCompetitionCurrentSourceAuthorityV1:
    """Admit only after independently replaying the exact three-root derivation."""

    from pathlib import Path as TrustedPath

    concrete_path_type = type(TrustedPath())
    if _CONCRETE_PATH_TYPE is not concrete_path_type:
        _fail("source authority concrete Path type drifted")
    if type(generation_proof_bytes) is not bytes:
        _fail("generation proof must be exact built-in bytes")
    if type(review_bytes) is not bytes:
        _fail("current source review must be exact built-in bytes")
    for label, value in (
        ("first_root", first_root),
        ("second_root", second_root),
        ("third_root", third_root),
    ):
        if type(value) is not str and type(value) is not concrete_path_type:
            _fail(f"{label} must be an exact string or concrete local Path")
    if not generation_proof_bytes or len(generation_proof_bytes) > _MAX_PROOF_CANONICAL_BYTES:
        _fail("generation proof size is outside the exact bound")
    if not review_bytes or len(review_bytes) > _MAX_REVIEW_CANONICAL_BYTES:
        _fail("current source review size is outside the exact bound")
    proof = ImplicitCompetitionSourceGenerationProofV1.from_canonical_bytes(generation_proof_bytes)
    review = _review_from_canonical_bytes(review_bytes)
    proof_payload = _validated_generation_proof_payload(proof)
    candidate_payload = cast("dict[str, object]", proof_payload["candidate"])
    normalized_review, review_payload = _normalized_review(review)
    _validate_review_binding(proof_payload, review_payload)

    from types import FunctionType, ModuleType

    from nbadb.core import nba_api_provenance as provider_module

    provider_resolver = provider_module.expected_nba_api_provider_authority
    generation_replayer = generate_implicit_competition_generation_proof
    module_state = globals()
    expected_provider = "e5981c0223c99ecd4a483606781d1433cc23f22b26ec71c41a3b12b9ad827085"
    if (
        type(provider_module) is not ModuleType
        or provider_module.__name__ != "nbadb.core.nba_api_provenance"
        or type(provider_resolver) is not FunctionType
        or provider_resolver.__module__ != "nbadb.core.nba_api_provenance"
        or provider_resolver.__name__ != "expected_nba_api_provider_authority"
        or provider_resolver.__qualname__ != "expected_nba_api_provider_authority"
        or provider_resolver.__code__.co_name != "expected_nba_api_provider_authority"
        or provider_resolver.__globals__ is not vars(provider_module)
        or type(generation_replayer) is not FunctionType
        or generation_replayer.__module__ != __name__
        or generation_replayer.__name__ != "generate_implicit_competition_generation_proof"
        or generation_replayer.__qualname__ != "generate_implicit_competition_generation_proof"
        or generation_replayer.__code__.co_name != "generate_implicit_competition_generation_proof"
        or generation_replayer.__globals__ is not module_state
        or generation_replayer is not _IMPORT_TIME_GENERATION_REPLAYER
        or generation_replayer.__code__ is not _IMPORT_TIME_GENERATION_REPLAYER_CODE
    ):
        _fail("source authority replay dependencies are not exact trusted functions")
    if candidate_payload["provider_authority_sha256"] != expected_provider:
        _fail("source authority provider binding differs from the expected authority")
    normalized_roots = tuple(
        TrustedPath(value) if type(value) is str else cast("Path", value)
        for value in (first_root, second_root, third_root)
    )
    rederived_proof = generation_replayer(
        normalized_roots[0],
        normalized_roots[1],
        normalized_roots[2],
        provider_authority_sha256=expected_provider,
        author_task_id=cast("str", candidate_payload["author_task_id"]),
        author_role=cast("str", candidate_payload["author_role"]),
    )
    rederived_payload = _validated_generation_proof_payload(rederived_proof)
    if _canonical_bytes(proof_payload) != _canonical_bytes(rederived_payload):
        _fail("source authority proof differs from the independent three-root replay")
    _validate_review_binding(rederived_payload, review_payload)
    body = {
        "generation_proof": rederived_payload,
        "kind": ImplicitCompetitionCurrentSourceAuthorityV1.kind,
        "review": review_payload,
        "schema_version": ImplicitCompetitionCurrentSourceAuthorityV1.schema_version,
    }
    rebuilt = ImplicitCompetitionCurrentSourceAuthorityV1(
        generation_proof=rederived_proof,
        review=normalized_review,
        authority_sha256=_digest(body),
    )
    _rebuilt_canonical_bytes = rebuilt.canonical_bytes

    # This is deliberately the final callback.  Everything below uses only
    # exact types, values, and exception classes captured before it runs.
    exact_type = type
    exact_dict_type = dict
    exact_str_type = str
    authority_error = ImplicitCompetitionSourceAuthorityError
    provider_authority = provider_resolver()
    if exact_type(provider_authority) is not exact_dict_type:
        raise authority_error("expected provider authority has an invalid type")
    provided_sha256 = provider_authority.get("authority_sha256")
    if exact_type(provided_sha256) is not exact_str_type:
        raise authority_error("expected provider authority sha256 must be a lowercase SHA-256")
    if provided_sha256 != expected_provider:
        raise authority_error("expected provider authority identity drifted")
    return rebuilt


def generate_implicit_competition_generation_proof(
    first_root: Path | str,
    second_root: Path | str,
    third_root: Path | str,
    *,
    provider_authority_sha256: str,
    author_task_id: str,
    author_role: str,
) -> ImplicitCompetitionSourceGenerationProofV1:
    """Derive byte-identical candidates from three authenticated distinct roots."""

    try:
        roots = tuple(
            Path(value).resolve(strict=True) for value in (first_root, second_root, third_root)
        )
    except OSError as exc:
        raise ImplicitCompetitionSourceAuthorityError(
            "generation roots cannot be authenticated"
        ) from exc
    try:
        if any(
            os.path.samefile(roots[left], roots[right])
            for left in range(3)
            for right in range(left + 1, 3)
        ):
            _fail("generation proof requires three distinct source roots")
        if any(
            roots[left] in roots[right].parents or roots[right] in roots[left].parents
            for left in range(3)
            for right in range(left + 1, 3)
        ):
            _fail("generation proof rejects nested source roots")
    except OSError as exc:
        raise ImplicitCompetitionSourceAuthorityError(
            "generation roots cannot be authenticated"
        ) from exc
    generated = tuple(
        _generate_implicit_competition_candidate_snapshot(
            root,
            provider_authority_sha256=provider_authority_sha256,
            author_task_id=author_task_id,
            author_role=author_role,
        )
        for root in roots
    )
    candidates = tuple(candidate for candidate, _snapshot in generated)
    snapshots = tuple(snapshot for _candidate, snapshot in generated)
    for path in tuple(row[1] for row in _FROZEN_BINDINGS) + SOURCE_PATHS:
        identities = {
            (device, inode)
            for snapshot in snapshots
            for member_path, device, inode in snapshot.member_identities
            if member_path == path
        }
        if len(identities) != 3:
            _fail("generation proof rejects cross-root hardlinked source members")
    candidate_bytes = tuple(_canonical_bytes(candidate.to_dict()) for candidate in candidates)
    if len(set(candidate_bytes)) != 1:
        _fail("three independently generated source candidates differ")
    candidate_bytes_sha256s = cast(
        "tuple[str, str, str]",
        tuple(hashlib.sha256(raw).hexdigest() for raw in candidate_bytes),
    )
    generation_policy_sha256 = _generation_policy_sha256(candidate_bytes_sha256s[0])
    body = {
        "candidate": candidates[0].to_dict(),
        "generation_candidate_bytes_sha256s": list(candidate_bytes_sha256s),
        "generation_policy_sha256": generation_policy_sha256,
        "kind": ImplicitCompetitionSourceGenerationProofV1.kind,
        "schema_version": ImplicitCompetitionSourceGenerationProofV1.schema_version,
    }
    return ImplicitCompetitionSourceGenerationProofV1(
        candidate=candidates[0],
        generation_candidate_bytes_sha256s=candidate_bytes_sha256s,
        generation_policy_sha256=generation_policy_sha256,
        proof_sha256=_digest(body),
    )


# This detects ordinary pre-entry replacement of the public replay function,
# including a metadata-shaped FunctionType with forged code.  It is a tamper
# indicator, not a security boundary against arbitrary code already executing
# inside this Python process: such code can replace both retained references.
_IMPORT_TIME_GENERATION_REPLAYER = generate_implicit_competition_generation_proof
_IMPORT_TIME_GENERATION_REPLAYER_CODE = generate_implicit_competition_generation_proof.__code__


def write_implicit_competition_current_source_authority(
    authority_bytes: bytes,
    path: Path | str,
    *,
    first_root: Path | str,
    second_root: Path | str,
    third_root: Path | str,
    check: bool = False,
) -> bool:
    """Write once, or check that an existing authority is byte-identical."""

    from pathlib import Path as TrustedPath

    concrete_path_type = type(TrustedPath())
    if _CONCRETE_PATH_TYPE is not concrete_path_type:
        _fail("source authority concrete Path type drifted")
    if type(check) is not bool:
        _fail("authority check flag must be an exact boolean")
    if type(authority_bytes) is not bytes:
        _fail("current source authority must be exact built-in bytes")
    for label, value in (
        ("first_root", first_root),
        ("second_root", second_root),
        ("third_root", third_root),
        ("path", path),
    ):
        if type(value) is not str and type(value) is not concrete_path_type:
            _fail(f"{label} must be an exact string or concrete local Path")
    if not authority_bytes or len(authority_bytes) > _MAX_AUTHORITY_CANONICAL_BYTES:
        _fail("current source authority size is outside the exact bound")
    authority = ImplicitCompetitionCurrentSourceAuthorityV1.from_canonical_bytes(authority_bytes)
    authority_payload = _validated_authority_payload(authority)
    proof_payload = cast("dict[str, object]", authority_payload["generation_proof"])
    candidate_payload = cast("dict[str, object]", proof_payload["candidate"])

    from types import FunctionType, ModuleType

    from nbadb.core import nba_api_provenance as provider_module

    provider_resolver = provider_module.expected_nba_api_provider_authority
    generation_replayer = generate_implicit_competition_generation_proof
    module_state = globals()
    expected_provider = "e5981c0223c99ecd4a483606781d1433cc23f22b26ec71c41a3b12b9ad827085"
    if (
        type(provider_module) is not ModuleType
        or provider_module.__name__ != "nbadb.core.nba_api_provenance"
        or type(provider_resolver) is not FunctionType
        or provider_resolver.__module__ != "nbadb.core.nba_api_provenance"
        or provider_resolver.__name__ != "expected_nba_api_provider_authority"
        or provider_resolver.__qualname__ != "expected_nba_api_provider_authority"
        or provider_resolver.__code__.co_name != "expected_nba_api_provider_authority"
        or provider_resolver.__globals__ is not vars(provider_module)
        or type(generation_replayer) is not FunctionType
        or generation_replayer.__module__ != __name__
        or generation_replayer.__name__ != "generate_implicit_competition_generation_proof"
        or generation_replayer.__qualname__ != "generate_implicit_competition_generation_proof"
        or generation_replayer.__code__.co_name != "generate_implicit_competition_generation_proof"
        or generation_replayer.__globals__ is not module_state
        or generation_replayer is not _IMPORT_TIME_GENERATION_REPLAYER
        or generation_replayer.__code__ is not _IMPORT_TIME_GENERATION_REPLAYER_CODE
    ):
        _fail("source authority replay dependencies are not exact trusted functions")
    if candidate_payload["provider_authority_sha256"] != expected_provider:
        _fail("source authority provider binding differs from the expected authority")
    normalized_roots = tuple(
        TrustedPath(value) if type(value) is str else cast("Path", value)
        for value in (first_root, second_root, third_root)
    )
    rederived_proof = generation_replayer(
        normalized_roots[0],
        normalized_roots[1],
        normalized_roots[2],
        provider_authority_sha256=expected_provider,
        author_task_id=cast("str", candidate_payload["author_task_id"]),
        author_role=cast("str", candidate_payload["author_role"]),
    )
    rederived_payload = _validated_generation_proof_payload(rederived_proof)
    if _canonical_bytes(proof_payload) != _canonical_bytes(rederived_payload):
        _fail("source authority proof differs from the independent three-root replay")
    normalized_review, review_payload = _normalized_review(authority.review)
    _validate_review_binding(rederived_payload, review_payload)
    body = {
        "generation_proof": rederived_payload,
        "kind": ImplicitCompetitionCurrentSourceAuthorityV1.kind,
        "review": review_payload,
        "schema_version": ImplicitCompetitionCurrentSourceAuthorityV1.schema_version,
    }
    rebuilt = ImplicitCompetitionCurrentSourceAuthorityV1(
        generation_proof=rederived_proof,
        review=normalized_review,
        authority_sha256=_digest(body),
    )
    rebuilt_payload = _validated_authority_payload(rebuilt)
    expected = _canonical_bytes(rebuilt_payload)
    if authority_bytes != expected:
        _fail("current source authority differs from the independent three-root replay")
    destination = TrustedPath(path) if type(path) is str else cast("Path", path)
    destination_read_bytes = destination.read_bytes
    destination_parent_mkdir = destination.parent.mkdir
    destination_open = destination.open
    exact_type = type
    exact_dict_type = dict
    exact_str_type = str
    authority_error = ImplicitCompetitionSourceAuthorityError
    file_exists_error = FileExistsError
    fsync = os.fsync

    # No mutable authority-module global is consulted after this callback.
    provider_authority = provider_resolver()
    if exact_type(provider_authority) is not exact_dict_type:
        raise authority_error("expected provider authority has an invalid type")
    provided_sha256 = provider_authority.get("authority_sha256")
    if exact_type(provided_sha256) is not exact_str_type:
        raise authority_error("expected provider authority sha256 must be a lowercase SHA-256")
    if provided_sha256 != expected_provider:
        raise authority_error("expected provider authority identity drifted")
    if check:
        if destination_read_bytes() != expected:
            raise authority_error("checked current source authority differs")
        return True
    destination_parent_mkdir(parents=True, exist_ok=True)
    try:
        with destination_open("xb") as handle:
            handle.write(expected)
            handle.flush()
            fsync(handle.fileno())
    except file_exists_error as exc:
        raise authority_error("current source authority destination already exists") from exc
    if destination_read_bytes() != expected:
        raise authority_error("written current source authority failed exact readback")
    return True


__all__ = [
    "CurrentSourceBindingV1",
    "FrozenSourceBindingV1",
    "ImplicitCompetitionCurrentSourceAuthorityV1",
    "ImplicitCompetitionSourceAuthorityError",
    "ImplicitCompetitionSourceCandidateV1",
    "ImplicitCompetitionSourceGenerationProofV1",
    "SOURCE_PATHS",
    "admit_implicit_competition_current_source_authority",
    "generate_implicit_competition_generation_proof",
    "generate_implicit_competition_source_candidate",
    "write_implicit_competition_current_source_authority",
]
