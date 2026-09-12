from __future__ import annotations

import hashlib
import json
import os
from contextlib import suppress
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

import nbadb.contracts.model_authority_resources as resources_module
from nbadb.contracts.model_authority_resources import (
    AuthorityResourceError,
    AuthorityResourceManifestV1,
    AuthorityResourceRecordV1,
    LoadedAuthorityResourcesV1,
    load_authority_resource_manifest,
)

if TYPE_CHECKING:
    from pathlib import Path


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_authority_root(
    root: Path,
    *,
    resource_payload: dict[str, object] | None = None,
) -> AuthorityResourceManifestV1:
    payload = resource_payload or {
        "kind": "test_evidence",
        "schema_version": 1,
        "value": "exact",
    }
    raw = _canonical(payload)
    relative = "evidence/positive.json"
    resource_path = root / relative
    resource_path.parent.mkdir(parents=True, exist_ok=True)
    resource_path.write_bytes(raw)
    record = AuthorityResourceRecordV1(
        resource_id="evidence:positive",
        relative_path=relative,
        resource_role="validation:positive",
        content_sha256=_digest(raw),
        size_bytes=len(raw),
        evidence_sha256s=tuple(sorted({_digest(raw), "f" * 64})),
    )
    manifest = AuthorityResourceManifestV1(
        authority_id="model-authority:test",
        parent_sha256s=("a" * 64,),
        resources=(record,),
    )
    (root / "current-manifest.json").write_bytes(manifest.canonical_bytes)
    return manifest


def test_exact_resource_root_round_trips_and_resolves_declared_evidence(
    tmp_path: Path,
) -> None:
    manifest = _write_authority_root(tmp_path)

    first = load_authority_resource_manifest(
        tmp_path,
        expected_manifest_sha256=manifest.manifest_sha256,
    )
    second = load_authority_resource_manifest(
        tmp_path,
        expected_manifest_sha256=manifest.manifest_sha256,
    )

    assert first.manifest == manifest == second.manifest
    assert not hasattr(first, "resources_by_id")
    assert not hasattr(first, "resource_ids_by_evidence_sha256")
    for resource in manifest.resources:
        assert first.resource_bytes(
            resource.resource_id,
            expected_manifest_sha256=manifest.manifest_sha256,
        ) == second.resource_bytes(
            resource.resource_id,
            expected_manifest_sha256=manifest.manifest_sha256,
        )
    record, raw = first.resolve_evidence(
        "f" * 64,
        expected_manifest_sha256=manifest.manifest_sha256,
    )
    assert record.resource_id == "evidence:positive"
    assert raw == first.resource_bytes(
        record.resource_id,
        expected_manifest_sha256=manifest.manifest_sha256,
    )
    with pytest.raises(AuthorityResourceError, match="differs from its trust pin"):
        first.resource_bytes(
            record.resource_id,
            expected_manifest_sha256="0" * 64,
        )
    with pytest.raises(AuthorityResourceError, match="differs from its trust pin"):
        first.resolve_evidence(
            "f" * 64,
            expected_manifest_sha256="0" * 64,
        )
    with pytest.raises(AuthorityResourceError, match="evidence digest is not declared"):
        first.resolve_evidence(
            "e" * 64,
            expected_manifest_sha256=manifest.manifest_sha256,
        )
    with pytest.raises(AuthorityResourceError, match="resource ID is not declared"):
        first.resource_bytes(
            "evidence:missing",
            expected_manifest_sha256=manifest.manifest_sha256,
        )


@pytest.mark.parametrize(
    "relative_path",
    ["", "/absolute.json", "../escape.json", "a/../b.json", "./a.json", "a\\b.json"],
)
def test_resource_records_reject_unsafe_paths(relative_path: str) -> None:
    with pytest.raises(AuthorityResourceError, match="safe relative POSIX path"):
        AuthorityResourceRecordV1(
            resource_id="unsafe:path",
            relative_path=relative_path,
            resource_role="test",
            content_sha256="a" * 64,
            size_bytes=2,
            evidence_sha256s=("a" * 64,),
        )


def test_manifest_rejects_boolean_types_duplicate_evidence_and_post_init_mutation() -> None:
    raw = _canonical({"kind": "test", "schema_version": 1})
    record = AuthorityResourceRecordV1(
        resource_id="resource:one",
        relative_path="one.json",
        resource_role="test",
        content_sha256=_digest(raw),
        size_bytes=len(raw),
        evidence_sha256s=(_digest(raw),),
    )
    payload = record.to_dict()
    payload["size_bytes"] = True
    with pytest.raises(AuthorityResourceError, match="size_bytes must be an integer"):
        AuthorityResourceRecordV1.from_dict(payload)

    duplicate_evidence = replace(
        record,
        resource_id="resource:two",
        relative_path="two.json",
        content_sha256="b" * 64,
        evidence_sha256s=("b" * 64, _digest(raw)),
    )
    with pytest.raises(AuthorityResourceError, match="exactly one resource"):
        AuthorityResourceManifestV1(
            authority_id="authority:test",
            parent_sha256s=("a" * 64,),
            resources=(record, duplicate_evidence),
        )

    manifest = AuthorityResourceManifestV1(
        authority_id="authority:test",
        parent_sha256s=("a" * 64,),
        resources=(record,),
    )
    object.__setattr__(record, "relative_path", "../mutated.json")
    with pytest.raises(AuthorityResourceError, match="safe relative POSIX path"):
        AuthorityResourceManifestV1.from_dict(manifest.to_dict())


def test_loader_rejects_missing_extra_drifted_and_noncanonical_members(tmp_path: Path) -> None:
    manifest = _write_authority_root(tmp_path)
    resource = tmp_path / manifest.resources[0].relative_path

    resource.unlink()
    with pytest.raises(AuthorityResourceError, match="membership differs"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=manifest.manifest_sha256,
        )

    manifest = _write_authority_root(tmp_path)
    (tmp_path / "extra.json").write_bytes(_canonical({"extra": True}))
    with pytest.raises(AuthorityResourceError, match="membership differs"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=manifest.manifest_sha256,
        )
    (tmp_path / "extra.json").unlink()

    resource = tmp_path / manifest.resources[0].relative_path
    resource.write_bytes(_canonical({"kind": "drifted", "schema_version": 1}))
    with pytest.raises(AuthorityResourceError, match="differs from its receipt"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=manifest.manifest_sha256,
        )

    manifest = _write_authority_root(tmp_path)
    resource = tmp_path / manifest.resources[0].relative_path
    resource.write_bytes(json.dumps({"kind": "test", "schema_version": 1}, indent=2).encode())
    drifted = replace(
        manifest.resources[0],
        content_sha256=_digest(resource.read_bytes()),
        size_bytes=len(resource.read_bytes()),
        evidence_sha256s=tuple(sorted({_digest(resource.read_bytes()), "f" * 64})),
    )
    replacement = replace(manifest, resources=(drifted,))
    (tmp_path / "current-manifest.json").write_bytes(replacement.canonical_bytes)
    with pytest.raises(AuthorityResourceError, match="bytes are not canonical"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=replacement.manifest_sha256,
        )


def test_loader_rejects_noncanonical_duplicate_manifest_and_digest_pin(tmp_path: Path) -> None:
    manifest = _write_authority_root(tmp_path)
    path = tmp_path / "current-manifest.json"
    path.write_bytes(json.dumps(manifest.to_dict(), indent=2).encode())
    with pytest.raises(AuthorityResourceError, match="bytes are not canonical"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=manifest.manifest_sha256,
        )

    _write_authority_root(tmp_path)
    path.write_bytes(b'{"kind":"a","kind":"b"}')
    with pytest.raises(AuthorityResourceError, match="duplicate JSON key"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=manifest.manifest_sha256,
        )

    manifest = _write_authority_root(tmp_path)
    with pytest.raises(AuthorityResourceError, match="differs from its pin"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=("0" * 64),
        )
    assert manifest.manifest_sha256 != "0" * 64


def test_loader_rejects_symlinked_root_member_and_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    manifest = _write_authority_root(root)
    resource = root / manifest.resources[0].relative_path
    target = tmp_path / "target.json"
    target.write_bytes(resource.read_bytes())
    resource.unlink()
    resource.symlink_to(target)
    with pytest.raises(AuthorityResourceError, match="symlink or special"):
        load_authority_resource_manifest(
            root,
            expected_manifest_sha256=manifest.manifest_sha256,
        )

    link = tmp_path / "root-link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(AuthorityResourceError, match="non-symlink directory"):
        load_authority_resource_manifest(
            link,
            expected_manifest_sha256=manifest.manifest_sha256,
        )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO support is unavailable")
def test_loader_rejects_fifo_swap_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    manifest = _write_authority_root(root)
    resource = root / manifest.resources[0].relative_path
    original_open = os.open
    swapped = False

    def racing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "positive.json" and dir_fd is not None and not swapped:
            swapped = True
            assert flags & os.O_NONBLOCK
            resource.unlink()
            os.mkfifo(resource)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", racing_open)
    with pytest.raises(AuthorityResourceError, match="non-symlink regular file"):
        load_authority_resource_manifest(
            root,
            expected_manifest_sha256=manifest.manifest_sha256,
        )
    assert swapped


def test_loader_rejects_undeclared_empty_directories(tmp_path: Path) -> None:
    manifest = _write_authority_root(tmp_path)
    (tmp_path / "undeclared" / "nested" / "empty").mkdir(parents=True)

    with pytest.raises(AuthorityResourceError, match="membership differs"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=manifest.manifest_sha256,
        )


def test_manifest_resource_count_is_bounded() -> None:
    records = tuple(
        AuthorityResourceRecordV1(
            resource_id=f"resource:{index:04d}",
            relative_path=f"resources/{index:04d}.json",
            resource_role="test",
            content_sha256=hashlib.sha256(f"content:{index}".encode()).hexdigest(),
            size_bytes=2,
            evidence_sha256s=(hashlib.sha256(f"content:{index}".encode()).hexdigest(),),
        )
        for index in range(4097)
    )
    with pytest.raises(AuthorityResourceError, match="exact bounded tuple"):
        AuthorityResourceManifestV1(
            authority_id="authority:oversized",
            parent_sha256s=("a" * 64,),
            resources=records,
        )


def test_manifest_canonical_parser_rejects_schema_type_confusion() -> None:
    raw = _canonical({"kind": "test", "schema_version": 1})
    record = AuthorityResourceRecordV1(
        resource_id="resource:one",
        relative_path="one.json",
        resource_role="test",
        content_sha256=_digest(raw),
        size_bytes=len(raw),
        evidence_sha256s=(_digest(raw),),
    )
    manifest = AuthorityResourceManifestV1(
        authority_id="authority:test",
        parent_sha256s=("a" * 64,),
        resources=(record,),
    )
    payload = manifest.to_dict()
    payload["schema_version"] = True
    with pytest.raises(AuthorityResourceError, match="schema is invalid"):
        AuthorityResourceManifestV1.from_dict(payload)


def test_loaded_authority_is_factory_only_and_revalidates_mutated_indexes(
    tmp_path: Path,
) -> None:
    manifest = _write_authority_root(tmp_path)
    with pytest.raises(AuthorityResourceError, match="created only by"):
        LoadedAuthorityResourcesV1()

    loaded = load_authority_resource_manifest(
        tmp_path,
        expected_manifest_sha256=manifest.manifest_sha256,
    )
    with pytest.raises(AttributeError):
        object.__setattr__(
            loaded,
            "resources_by_id",
            MappingProxyType({manifest.resources[0].resource_id: b"evil"}),
        )
    object.__setattr__(
        loaded,
        "_resources_by_id",
        MappingProxyType({manifest.resources[0].resource_id: b"evil"}),
    )
    object.__setattr__(
        loaded,
        "_resource_ids_by_evidence_sha256",
        MappingProxyType({"f" * 64: manifest.resources[0].resource_id}),
    )
    with pytest.raises(AuthorityResourceError, match="bytes differ from receipt"):
        loaded.resolve_evidence(
            "f" * 64,
            expected_manifest_sha256=manifest.manifest_sha256,
        )


def test_manifest_mapping_rejects_hostile_equality_objects() -> None:
    raw = _canonical({"kind": "test", "schema_version": 1})
    record = AuthorityResourceRecordV1(
        resource_id="resource:one",
        relative_path="one.json",
        resource_role="test",
        content_sha256=_digest(raw),
        size_bytes=len(raw),
        evidence_sha256s=(_digest(raw),),
    )
    manifest = AuthorityResourceManifestV1(
        authority_id="authority:test",
        parent_sha256s=("a" * 64,),
        resources=(record,),
    )

    class AlwaysEqual:
        def __eq__(self, _other: object) -> bool:
            return True

        def __ne__(self, _other: object) -> bool:
            return False

    payload = manifest.to_dict()
    payload["kind"] = AlwaysEqual()
    payload["manifest_sha256"] = AlwaysEqual()
    with pytest.raises(AuthorityResourceError, match="schema is invalid"):
        AuthorityResourceManifestV1.from_dict(payload)

    class AlwaysEqualKey:
        def __hash__(self) -> int:
            return hash("kind")

        def __eq__(self, other: object) -> bool:
            return other == "kind"

    hostile_keys: dict[object, object] = {key: value for key, value in manifest.to_dict().items()}
    kind = hostile_keys.pop("kind")
    hostile_keys[AlwaysEqualKey()] = kind
    with pytest.raises(AuthorityResourceError, match="exact string keys"):
        AuthorityResourceManifestV1.from_dict(hostile_keys)


def test_parent_descriptor_is_closed_when_immediate_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "root"
    (parent / "evidence").mkdir(parents=True)
    root_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    original_open = os.open
    original_fstat = os.fstat
    captured: list[int] = []

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "evidence" and dir_fd is not None:
            captured.append(descriptor)
        return descriptor

    def failing_fstat(descriptor: int) -> os.stat_result:
        if descriptor in captured:
            raise OSError("injected fstat failure")
        return original_fstat(descriptor)

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(resources_module.os, "open", tracked_open)
            scoped.setattr(resources_module.os, "fstat", failing_fstat)
            with pytest.raises(AuthorityResourceError, match="parent cannot be opened"):
                resources_module._open_relative_parent(root_descriptor, ("evidence",))
        assert len(captured) == 1
        with pytest.raises(OSError):
            original_fstat(captured[0])
    finally:
        os.close(root_descriptor)


def test_child_descriptor_is_closed_when_previous_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "root"
    (parent / "evidence").mkdir(parents=True)
    root_descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
    original_dup = os.dup
    original_open = os.open
    original_close = os.close
    original_fstat = os.fstat
    previous_descriptors: list[int] = []
    child_descriptors: list[int] = []
    injected = False

    def tracked_dup(descriptor: int) -> int:
        duplicate = original_dup(descriptor)
        previous_descriptors.append(duplicate)
        return duplicate

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if path == "evidence" and dir_fd is not None:
            child_descriptors.append(descriptor)
        return descriptor

    def failing_close(descriptor: int) -> None:
        nonlocal injected
        if previous_descriptors and descriptor == previous_descriptors[0] and not injected:
            injected = True
            raise OSError("injected prior-descriptor close failure")
        original_close(descriptor)

    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(resources_module.os, "dup", tracked_dup)
            scoped.setattr(resources_module.os, "open", tracked_open)
            scoped.setattr(resources_module.os, "close", failing_close)
            with pytest.raises(AuthorityResourceError, match="parent cannot be opened"):
                resources_module._open_relative_parent(root_descriptor, ("evidence",))
        assert injected
        assert len(previous_descriptors) == len(child_descriptors) == 1
        with pytest.raises(OSError):
            original_fstat(child_descriptors[0])
    finally:
        for descriptor in previous_descriptors:
            with suppress(OSError):
                original_close(descriptor)
        original_close(root_descriptor)


def test_unsupported_descriptor_scandir_is_normalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _write_authority_root(tmp_path)
    monkeypatch.setattr(resources_module, "_HAS_DESCRIPTOR_SCANDIR", False)
    with pytest.raises(AuthorityResourceError, match="descriptor-relative no-follow"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=manifest.manifest_sha256,
        )

    monkeypatch.setattr(resources_module, "_HAS_DESCRIPTOR_SCANDIR", True)

    def unsupported_scandir(_descriptor: int) -> object:
        raise NotImplementedError("descriptor scandir is unavailable")

    monkeypatch.setattr(resources_module.os, "scandir", unsupported_scandir)
    with pytest.raises(AuthorityResourceError, match="membership cannot be scanned"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=manifest.manifest_sha256,
        )


def test_manifest_parent_inventory_and_encoded_bytes_are_bounded() -> None:
    raw = _canonical({"kind": "test", "schema_version": 1})
    record = AuthorityResourceRecordV1(
        resource_id="resource:one",
        relative_path="one.json",
        resource_role="test",
        content_sha256=_digest(raw),
        size_bytes=len(raw),
        evidence_sha256s=(_digest(raw),),
    )
    parents = tuple(f"{index:064x}" for index in range(4097))
    with pytest.raises(AuthorityResourceError, match="nonempty, bounded"):
        AuthorityResourceManifestV1(
            authority_id="authority:test",
            parent_sha256s=parents,
            resources=(record,),
        )


def test_loader_normalizes_oversized_integer_token_to_typed_error(tmp_path: Path) -> None:
    raw = b'{"kind":"test","value":' + (b"9" * 10_000) + b"}"
    resource = tmp_path / "evidence" / "positive.json"
    resource.parent.mkdir()
    resource.write_bytes(raw)
    record = AuthorityResourceRecordV1(
        resource_id="evidence:positive",
        relative_path="evidence/positive.json",
        resource_role="validation:positive",
        content_sha256=_digest(raw),
        size_bytes=len(raw),
        evidence_sha256s=(_digest(raw),),
    )
    manifest = AuthorityResourceManifestV1(
        authority_id="model-authority:test",
        parent_sha256s=("a" * 64,),
        resources=(record,),
    )
    (tmp_path / "current-manifest.json").write_bytes(manifest.canonical_bytes)
    with pytest.raises(AuthorityResourceError, match="integer token exceeds its bound"):
        load_authority_resource_manifest(
            tmp_path,
            expected_manifest_sha256=manifest.manifest_sha256,
        )


def test_descriptor_relative_read_rejects_ancestor_swap_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "root"
    alternate = tmp_path / "alternate"
    root.mkdir()
    alternate.mkdir()
    manifest = _write_authority_root(root, resource_payload={"value": "original"})
    _write_authority_root(alternate, resource_payload={"value": "alternate"})
    alternate_resource = alternate / manifest.resources[0].relative_path
    root_resource = root / manifest.resources[0].relative_path
    alternate_raw = alternate_resource.read_bytes()
    alternate_record = replace(
        manifest.resources[0],
        content_sha256=_digest(alternate_raw),
        size_bytes=len(alternate_raw),
        evidence_sha256s=tuple(sorted({_digest(alternate_raw), "f" * 64})),
    )
    alternate_manifest = replace(manifest, resources=(alternate_record,))
    (root / "current-manifest.json").write_bytes(alternate_manifest.canonical_bytes)
    original_open = os.open
    swapped = False

    def racing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "positive.json" and dir_fd is not None and not swapped:
            swapped = True
            backup = tmp_path / "original-backup"
            (root / "evidence").rename(backup)
            (alternate / "evidence").rename(root / "evidence")
            try:
                return original_open(path, flags, mode, dir_fd=dir_fd)
            finally:
                (root / "evidence").rename(alternate / "evidence")
                backup.rename(root / "evidence")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", racing_open)
    with pytest.raises(AuthorityResourceError, match="differs from its receipt"):
        load_authority_resource_manifest(
            root,
            expected_manifest_sha256=alternate_manifest.manifest_sha256,
        )
    assert root_resource.read_bytes() != alternate_raw

    if os.name != "nt":
        assert manifest.canonical_bytes == _canonical(manifest.to_dict())
