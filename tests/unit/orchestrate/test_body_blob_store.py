from __future__ import annotations

import errno
import hashlib
import inspect
import os
import stat
import threading
import traceback
from collections import Counter
from copy import copy
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import nbadb.orchestrate.body_blob_store as store_module
from nbadb.contracts.body_blob_inventory import (
    BodyBlobInventoryReadbackReceiptV1,
    BodyBlobInventoryV1,
    build_body_blob_inventory,
)
from nbadb.contracts.raw_request_authority import RawRequestAuthorityBundleV2
from nbadb.orchestrate.body_blob_store import BodyBlobStore, BodyBlobStoreError
from tests.unit.contracts.test_body_blob_inventory import _shared_body_bundle

if TYPE_CHECKING:
    from collections.abc import Iterator

_SOURCE_SHA = "1" * 40


class _ExplodingTuple(tuple[object, ...]):
    failure: BaseException
    iterations: int = 0

    def __iter__(self) -> Iterator[object]:
        self.iterations += 1
        raise self.failure


class _ExplodingList(list[object]):
    failure: BaseException
    iterations: int = 0

    def __iter__(self) -> Iterator[object]:
        self.iterations += 1
        raise self.failure


def _bundle_with_exploding_objects(
    bundle: RawRequestAuthorityBundleV2,
    *,
    failure: BaseException,
) -> tuple[RawRequestAuthorityBundleV2, _ExplodingTuple]:
    objects = _ExplodingTuple(bundle.objects)
    objects.failure = failure
    objects.iterations = 0
    candidate = copy(bundle)
    object.__setattr__(candidate, "objects", objects)
    return candidate, objects


def _receipt_with_exploding_count(
    receipt: BodyBlobInventoryReadbackReceiptV1,
    *,
    failure: BaseException,
) -> tuple[BodyBlobInventoryReadbackReceiptV1, _ExplodingList]:
    count = _ExplodingList([receipt.file_readback_count])
    count.failure = failure
    count.iterations = 0
    candidate = copy(receipt)
    object.__setattr__(candidate, "file_readback_count", count)
    return candidate, count


def _root(tmp_path: Path, name: str = "body-blob-run") -> Path:
    root = tmp_path / name
    root.mkdir(mode=0o700, parents=True)
    root.chmod(0o700)
    return root


def _store(root: Path, *, source_sha: str = _SOURCE_SHA) -> BodyBlobStore:
    return BodyBlobStore(
        root,
        source_sha=source_sha,
        run_id=101,
        run_attempt=1,
        chain_id="chain",
        lane_id="lane",
    )


def _authority() -> tuple[RawRequestAuthorityBundleV2, BodyBlobInventoryV1]:
    bundle = _shared_body_bundle()
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    return bundle, inventory


def _seal(
    store: BodyBlobStore,
    authority: tuple[RawRequestAuthorityBundleV2, BodyBlobInventoryV1],
) -> BodyBlobInventoryReadbackReceiptV1:
    bundle, inventory = authority
    return store.seal_inventory(
        bundle=bundle,
        inventory=inventory,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_inventory_sha256=inventory.inventory_sha256,
    )


def _readback(
    store: BodyBlobStore,
    authority: tuple[RawRequestAuthorityBundleV2, BodyBlobInventoryV1],
    receipt: BodyBlobInventoryReadbackReceiptV1,
) -> BodyBlobInventoryReadbackReceiptV1:
    bundle, inventory = authority
    return store.readback_inventory(
        bundle=bundle,
        inventory=inventory,
        receipt=receipt,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_inventory_sha256=inventory.inventory_sha256,
        expected_receipt_sha256=receipt.receipt_sha256,
    )


def _blob_path(root: Path, inventory: BodyBlobInventoryV1) -> Path:
    return root.joinpath(*inventory.descriptors[0].relative_resource_name.split("/"))


def _manifest_path(root: Path, inventory: BodyBlobInventoryV1) -> Path:
    relative = BodyBlobStore._manifest_relative_resource_name(inventory.inventory_sha256)
    return root.joinpath(*relative.split("/"))


def _safe_parent(root: Path, relative: str) -> Path:
    current = root
    for component in relative.split("/")[:-1]:
        current = current / component
        current.mkdir(mode=0o700, exist_ok=True)
        current.chmod(0o700)
    return current


@pytest.mark.parametrize(
    "failure_type",
    [KeyboardInterrupt, SystemExit, GeneratorExit],
)
@pytest.mark.parametrize(
    "cleanup_class",
    ["constructor", "locked-root", "parent-directory", "bound-file"],
)
def test_effect_then_raise_close_preserves_active_control_flow_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
    cleanup_class: str,
) -> None:
    original_close = store_module.os.close
    state = {
        "active": False,
        "remaining": 2 if cleanup_class in {"constructor", "locked-root"} else 1,
    }

    def effect_then_raise_close(descriptor: int) -> None:
        original_close(descriptor)
        if state["active"] and state["remaining"]:
            state["remaining"] -= 1
            raise OSError("private-close-sentinel")

    if cleanup_class == "constructor":

        def interrupted_fsync(_descriptor: int) -> None:
            state["active"] = True
            raise failure_type()

        monkeypatch.setattr(store_module.os, "fsync", interrupted_fsync)
        monkeypatch.setattr(store_module.os, "close", effect_then_raise_close)
        with pytest.raises(failure_type):
            _store(_root(tmp_path))
        assert state["remaining"] == 0
        return

    authority = _authority()
    root = _root(tmp_path)
    store = _store(root)
    monkeypatch.setattr(store_module.os, "close", effect_then_raise_close)
    if cleanup_class == "locked-root":
        with pytest.raises(failure_type), store._locked_root():
            state["active"] = True
            raise failure_type()
    elif cleanup_class == "parent-directory":
        root_descriptor, _identity = store._open_root()
        try:
            with (
                pytest.raises(failure_type),
                store._open_parent_directory(
                    root_descriptor,
                    ("body-blobs",),
                    create=True,
                ),
            ):
                state["active"] = True
                raise failure_type()
        finally:
            original_close(root_descriptor)
    else:
        _seal(store, authority)
        _bundle, inventory = authority
        descriptor = inventory.descriptors[0]
        blob_path = _blob_path(root, inventory)
        parent_descriptor = store_module.os.open(
            blob_path.parent,
            store_module._directory_flags(),
        )
        original_read = store_module.os.read

        def interrupted_read(_descriptor: int, _length: int) -> bytes:
            state["active"] = True
            raise failure_type()

        monkeypatch.setattr(store_module.os, "read", interrupted_read)
        try:
            with pytest.raises(failure_type):
                store._read_bound_file(
                    parent_descriptor,
                    blob_path.name,
                    expected_length=descriptor.stored_bytes,
                    maximum_length=descriptor.stored_bytes,
                )
        finally:
            monkeypatch.setattr(store_module.os, "read", original_read)
            original_close(parent_descriptor)
    assert state["remaining"] == 0


def test_close_fault_without_active_exception_is_fixed_and_sanitized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(_root(tmp_path))
    original_close = store_module.os.close
    remaining = 2
    active = False

    def effect_then_raise_close(descriptor: int) -> None:
        nonlocal active, remaining
        original_close(descriptor)
        if active and remaining:
            remaining -= 1
            raise OSError("private-close-sentinel")

    monkeypatch.setattr(store_module.os, "close", effect_then_raise_close)
    with (
        pytest.raises(
            BodyBlobStoreError,
            match="body-blob store descriptors cannot be released safely",
        ) as caught,
        store._locked_root(),
    ):
        active = True
    assert remaining == 0
    assert caught.value.__cause__ is None
    assert "private-close-sentinel" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "failure_type",
    [KeyboardInterrupt, SystemExit, GeneratorExit],
)
@pytest.mark.parametrize("acquisition", ["root", "child-directory"])
def test_fstat_control_flow_interruption_closes_every_acquired_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
    acquisition: str,
) -> None:
    root = _root(tmp_path)
    store = object.__new__(BodyBlobStore)
    store._root = root
    original_open = store_module.os.open
    original_close = store_module.os.close
    original_fstat = store_module.os.fstat
    opened: Counter[int] = Counter()
    closed: Counter[int] = Counter()

    def tracked_open(*args: object, **kwargs: object) -> int:
        descriptor = original_open(*args, **kwargs)
        opened[descriptor] += 1
        return descriptor

    def tracked_close(descriptor: int) -> None:
        closed[descriptor] += 1
        original_close(descriptor)

    def interrupted_fstat(_descriptor: int) -> os.stat_result:
        raise failure_type()

    parent_descriptor = -1
    if acquisition == "child-directory":
        parent_descriptor = original_open(root, store_module._directory_flags())
    monkeypatch.setattr(store_module.os, "open", tracked_open)
    monkeypatch.setattr(store_module.os, "close", tracked_close)
    monkeypatch.setattr(store_module.os, "fstat", interrupted_fstat)
    try:
        with pytest.raises(failure_type):
            if acquisition == "root":
                store._open_root()
            else:
                store._open_child_directory(
                    parent_descriptor,
                    "child",
                    create=True,
                )
    finally:
        monkeypatch.setattr(store_module.os, "open", original_open)
        monkeypatch.setattr(store_module.os, "close", original_close)
        monkeypatch.setattr(store_module.os, "fstat", original_fstat)
        leftovers = list((opened - closed).elements())
        for descriptor in leftovers:
            original_close(descriptor)
        if parent_descriptor >= 0:
            original_close(parent_descriptor)
    assert opened == closed


def test_persist_deduplicates_and_seal_commits_manifest_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    bundle, inventory = authority
    root = _root(tmp_path)
    store = _store(root)
    installed: list[str] = []
    original_install = store._install_immutable_file

    def record_install(
        parent_descriptor: int,
        *,
        final_name: str,
        content: bytes,
        maximum_length: int,
    ) -> bytes:
        installed.append(final_name)
        return original_install(
            parent_descriptor,
            final_name=final_name,
            content=content,
            maximum_length=maximum_length,
        )

    monkeypatch.setattr(store, "_install_immutable_file", record_install)
    files = store.persist_objects(
        bundle=bundle,
        inventory=inventory,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_inventory_sha256=inventory.inventory_sha256,
    )
    assert len(files) == 1
    assert files[0].readback_sha256 == bundle.objects[0].stored_sha256
    assert inventory.reference_count == 2

    receipt = _seal(store, authority)
    assert installed[-1].endswith(".json")
    assert receipt.file_readback_count == 1
    assert receipt.observation_readback_count == 2
    assert receipt.selected_observation_readback_count == 1
    assert receipt.incomplete_observation_readback_count == 1
    assert _readback(store, authority, receipt) == receipt
    assert _blob_path(root, inventory).read_bytes() == bundle.objects[0].stored_payload
    assert _manifest_path(root, inventory).read_bytes() == inventory.to_canonical_bytes()
    assert stat.S_IMODE(_blob_path(root, inventory).stat().st_mode) == 0o600
    assert stat.S_IMODE(_manifest_path(root, inventory).stat().st_mode) == 0o600
    relative_directories = inventory.descriptors[0].relative_resource_name.split("/")[:-1]
    current = root
    for component in relative_directories:
        current /= component
        assert stat.S_IMODE(current.stat().st_mode) == 0o700


def test_exact_replay_is_idempotent_without_repromotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    store = _store(_root(tmp_path))
    first = _seal(store, authority)

    def forbidden_link(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("exact replay must not republish immutable content")

    monkeypatch.setattr(store_module.os, "link", forbidden_link)
    second = _seal(store, authority)
    assert second.to_canonical_bytes() == first.to_canonical_bytes()
    assert _readback(store, authority, second) == first


def test_two_store_instances_converge_on_one_blob_and_manifest(tmp_path: Path) -> None:
    authority = _authority()
    _bundle, inventory = authority
    root = _root(tmp_path)
    stores = (_store(root), _store(root))
    receipts: list[BodyBlobInventoryReadbackReceiptV1] = []
    failures: list[BaseException] = []

    def run(store: BodyBlobStore) -> None:
        try:
            receipts.append(_seal(store, authority))
        except BaseException as exc:  # pragma: no cover - assertion reports the failure
            failures.append(exc)

    for _round in range(8):
        threads = [threading.Thread(target=run, args=(store,)) for store in stores]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
            assert not thread.is_alive()
    assert not failures
    assert len(receipts) == 16
    assert len({item.to_canonical_bytes() for item in receipts}) == 1
    assert _blob_path(root, inventory).stat().st_nlink == 1
    assert _manifest_path(root, inventory).stat().st_nlink == 1


def test_scoped_empty_inventory_seals_one_manifest_and_zero_receipt(tmp_path: Path) -> None:
    bundle = RawRequestAuthorityBundleV2.build(
        objects=[],
        observations=[],
        occurrences=[],
        landings=[],
    )
    inventory = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
    )
    authority = bundle, inventory
    root = _root(tmp_path)
    store = _store(root)
    assert (
        store.persist_objects(
            bundle=bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
        == ()
    )
    receipt = _seal(store, authority)
    assert receipt.file_readbacks == ()
    assert receipt.observation_readbacks == ()
    assert receipt.total_readback_bytes == 0
    assert _manifest_path(root, inventory).is_file()
    assert not (root / "body-blobs" / "sha256").exists()
    assert _readback(store, authority, receipt) == receipt


def test_public_api_has_no_caller_selected_resource_name() -> None:
    for method_name in ("persist_objects", "seal_inventory", "readback_inventory"):
        parameters = inspect.signature(getattr(BodyBlobStore, method_name)).parameters
        assert "path" not in parameters
        assert "name" not in parameters
        assert "relative_resource_name" not in parameters


@pytest.mark.parametrize(
    "relative",
    [
        "/body-blobs/sha256/aa/value.payload.gz",
        "../body-blobs/value.payload.gz",
        "body-blobs/../value.payload.gz",
        "body-blobs//value.payload.gz",
        "body-blobs\\sha256\\value.payload.gz",
        "./body-blobs/value.payload.gz",
    ],
)
def test_path_normalization_absolute_and_traversal_are_rejected(relative: str) -> None:
    with pytest.raises(BodyBlobStoreError):
        BodyBlobStore._resource_parts(relative)


def test_external_pins_types_and_namespace_fail_before_file_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, inventory = _authority()
    store = _store(_root(tmp_path))

    def forbidden_io(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("file IO preceded exact external-pin admission")

    monkeypatch.setattr(store, "_locked_root", forbidden_io)
    with pytest.raises(BodyBlobStoreError):
        store.persist_objects(
            bundle=bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256="not-a-sha",
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    with pytest.raises(BodyBlobStoreError):
        store.seal_inventory(
            bundle=bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256="f" * 64,
        )
    with pytest.raises(BodyBlobStoreError):
        store.persist_objects(
            bundle=bundle,
            inventory=object(),  # type: ignore[arg-type]
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    with pytest.raises(BodyBlobStoreError):
        store.persist_objects(
            bundle=object(),  # type: ignore[arg-type]
            inventory=inventory,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    with pytest.raises(BodyBlobStoreError):
        store.persist_objects(
            bundle=bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
            known_secrets=[b"{}"],
        )
    bombed_bundle, bombed_objects = _bundle_with_exploding_objects(
        bundle,
        failure=RuntimeError("private-bomb-detail"),
    )
    with pytest.raises(BodyBlobStoreError) as wrong_bundle_pin:
        store.persist_objects(
            bundle=bombed_bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256="0" * 64,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    assert bombed_objects.iterations == 0
    assert "private-bomb-detail" not in str(wrong_bundle_pin.value)
    assert wrong_bundle_pin.value.__cause__ is None
    with pytest.raises(BodyBlobStoreError) as hostile_bundle:
        store.persist_objects(
            bundle=bombed_bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    assert bombed_objects.iterations == 1
    assert "private-bomb-detail" not in str(hostile_bundle.value)
    assert hostile_bundle.value.__cause__ is None
    interrupted_bundle, interrupted_objects = _bundle_with_exploding_objects(
        bundle,
        failure=KeyboardInterrupt(),
    )
    with pytest.raises(KeyboardInterrupt):
        store.persist_objects(
            bundle=interrupted_bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )
    assert interrupted_objects.iterations == 1
    foreign_store = _store(_root(tmp_path, "foreign"), source_sha="2" * 40)
    monkeypatch.setattr(foreign_store, "_locked_root", forbidden_io)
    with pytest.raises(BodyBlobStoreError):
        foreign_store.persist_objects(
            bundle=bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
        )


def test_tampered_receipt_and_receipt_pin_fail_before_file_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    store = _store(_root(tmp_path))
    receipt = _seal(store, authority)
    tampered = replace(receipt)
    object.__setattr__(tampered, "total_readback_bytes", receipt.total_readback_bytes + 1)

    def forbidden_io(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("file IO preceded aggregate-receipt admission")

    monkeypatch.setattr(store, "_locked_root", forbidden_io)
    with pytest.raises(BodyBlobStoreError):
        _readback(store, authority, tampered)
    bundle, inventory = authority
    with pytest.raises(BodyBlobStoreError):
        store.readback_inventory(
            bundle=bundle,
            inventory=inventory,
            receipt=receipt,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
            expected_receipt_sha256="e" * 64,
        )
    bombed_bundle, bombed_objects = _bundle_with_exploding_objects(
        bundle,
        failure=RuntimeError("private-bomb-detail"),
    )
    with pytest.raises(BodyBlobStoreError) as wrong_receipt_pin:
        store.readback_inventory(
            bundle=bombed_bundle,
            inventory=inventory,
            receipt=receipt,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
            expected_receipt_sha256="e" * 64,
        )
    assert bombed_objects.iterations == 0
    assert "private-bomb-detail" not in str(wrong_receipt_pin.value)
    assert wrong_receipt_pin.value.__cause__ is None
    with pytest.raises(BodyBlobStoreError) as hostile_bundle:
        store.readback_inventory(
            bundle=bombed_bundle,
            inventory=inventory,
            receipt=receipt,
            expected_raw_authority_bundle_sha256=bundle.bundle_sha256,
            expected_inventory_sha256=inventory.inventory_sha256,
            expected_receipt_sha256=receipt.receipt_sha256,
        )
    assert bombed_objects.iterations == 1
    assert "private-bomb-detail" not in str(hostile_bundle.value)
    assert hostile_bundle.value.__cause__ is None


def test_hostile_exact_receipt_canonicalization_is_sanitized_before_file_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    store = _store(_root(tmp_path))
    receipt = _seal(store, authority)
    hostile, count = _receipt_with_exploding_count(
        receipt,
        failure=RuntimeError("private-receipt-bomb-detail"),
    )
    io_calls = 0

    def forbidden_io(*_args: object, **_kwargs: object) -> object:
        nonlocal io_calls
        io_calls += 1
        raise AssertionError("file IO preceded exact receipt reconstruction")

    monkeypatch.setattr(store, "_locked_root", forbidden_io)
    with pytest.raises(
        BodyBlobStoreError,
        match="body-blob inventory readback receipt failed exact reconstruction",
    ) as caught:
        _readback(store, authority, hostile)
    assert count.iterations == 1
    assert io_calls == 0
    assert "private-receipt-bomb-detail" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize(
    "failure_type",
    [KeyboardInterrupt, SystemExit, GeneratorExit],
)
def test_hostile_exact_receipt_base_exception_propagates_before_file_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    authority = _authority()
    store = _store(_root(tmp_path))
    receipt = _seal(store, authority)
    hostile, count = _receipt_with_exploding_count(
        receipt,
        failure=failure_type(),
    )
    io_calls = 0

    def forbidden_io(*_args: object, **_kwargs: object) -> object:
        nonlocal io_calls
        io_calls += 1
        raise AssertionError("file IO preceded exact receipt reconstruction")

    monkeypatch.setattr(store, "_locked_root", forbidden_io)
    with pytest.raises(failure_type):
        _readback(store, authority, hostile)
    assert count.iterations == 1
    assert io_calls == 0


def test_relative_symlink_and_open_permission_roots_fail_closed(tmp_path: Path) -> None:
    real = _root(tmp_path, "real")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(BodyBlobStoreError):
        _store(link)
    with pytest.raises(BodyBlobStoreError):
        _store(Path("relative-root"))
    real.chmod(0o755)
    with pytest.raises(BodyBlobStoreError):
        _store(real)


def test_symlinked_directory_component_fails_without_touching_target(tmp_path: Path) -> None:
    authority = _authority()
    root = _root(tmp_path)
    target = _root(tmp_path, "foreign-target")
    (root / "body-blobs").symlink_to(target, target_is_directory=True)
    with pytest.raises(BodyBlobStoreError):
        _seal(_store(root), authority)
    assert list(target.iterdir()) == []


def test_symlink_fifo_and_directory_blob_members_fail_closed(tmp_path: Path) -> None:
    authority = _authority()
    bundle, inventory = authority
    relative = inventory.descriptors[0].relative_resource_name

    symlink_root = _root(tmp_path, "symlink")
    symlink_parent = _safe_parent(symlink_root, relative)
    target = symlink_root / "target.gz"
    target.write_bytes(bundle.objects[0].stored_payload)
    (symlink_parent / relative.split("/")[-1]).symlink_to(target)
    with pytest.raises(BodyBlobStoreError):
        _seal(_store(symlink_root), authority)
    assert target.read_bytes() == bundle.objects[0].stored_payload

    fifo_root = _root(tmp_path, "fifo")
    fifo_parent = _safe_parent(fifo_root, relative)
    os.mkfifo(fifo_parent / relative.split("/")[-1], 0o600)
    with pytest.raises(BodyBlobStoreError):
        _seal(_store(fifo_root), authority)

    directory_root = _root(tmp_path, "directory")
    directory_parent = _safe_parent(directory_root, relative)
    member = directory_parent / relative.split("/")[-1]
    member.mkdir(mode=0o700)
    with pytest.raises(BodyBlobStoreError):
        _seal(_store(directory_root), authority)


def test_unexpected_hard_link_and_foreign_modes_fail_readback(tmp_path: Path) -> None:
    authority = _authority()
    _bundle, inventory = authority

    hardlink_root = _root(tmp_path, "hardlink")
    hardlink_store = _store(hardlink_root)
    hardlink_receipt = _seal(hardlink_store, authority)
    blob = _blob_path(hardlink_root, inventory)
    os.link(blob, hardlink_root / "unexpected-link")
    with pytest.raises(BodyBlobStoreError):
        _readback(hardlink_store, authority, hardlink_receipt)

    file_mode_root = _root(tmp_path, "file-mode")
    file_mode_store = _store(file_mode_root)
    file_mode_receipt = _seal(file_mode_store, authority)
    _blob_path(file_mode_root, inventory).chmod(0o644)
    with pytest.raises(BodyBlobStoreError):
        _readback(file_mode_store, authority, file_mode_receipt)

    directory_mode_root = _root(tmp_path, "directory-mode")
    directory_mode_store = _store(directory_mode_root)
    directory_mode_receipt = _seal(directory_mode_store, authority)
    _blob_path(directory_mode_root, inventory).parent.chmod(0o755)
    with pytest.raises(BodyBlobStoreError):
        _readback(directory_mode_store, authority, directory_mode_receipt)


@pytest.mark.parametrize("mutation", ["corrupt", "truncated", "trailing"])
def test_corrupt_truncated_and_trailing_gzip_fail_exact_readback(
    tmp_path: Path,
    mutation: str,
) -> None:
    authority = _authority()
    _bundle, inventory = authority
    root = _root(tmp_path)
    store = _store(root)
    receipt = _seal(store, authority)
    path = _blob_path(root, inventory)
    original = path.read_bytes()
    changed = {
        "corrupt": bytes([original[0] ^ 1]) + original[1:],
        "truncated": original[:-1],
        "trailing": original + b"x",
    }[mutation]
    path.write_bytes(changed)
    path.chmod(0o600)
    with pytest.raises(BodyBlobStoreError):
        _readback(store, authority, receipt)
    assert path.read_bytes() == changed


def test_same_key_different_content_is_never_overwritten(tmp_path: Path) -> None:
    authority = _authority()
    bundle, inventory = authority
    root = _root(tmp_path)
    relative = inventory.descriptors[0].relative_resource_name
    parent = _safe_parent(root, relative)
    original = bundle.objects[0].stored_payload
    foreign = bytes([original[0] ^ 1]) + original[1:]
    destination = parent / relative.split("/")[-1]
    destination.write_bytes(foreign)
    destination.chmod(0o600)
    with pytest.raises(BodyBlobStoreError):
        _seal(_store(root), authority)
    assert destination.read_bytes() == foreign


def test_missing_blob_and_manifest_fail_without_fabricating_state(tmp_path: Path) -> None:
    authority = _authority()
    _bundle, inventory = authority

    blob_root = _root(tmp_path, "missing-blob")
    blob_store = _store(blob_root)
    blob_receipt = _seal(blob_store, authority)
    _blob_path(blob_root, inventory).unlink()
    with pytest.raises(BodyBlobStoreError):
        _readback(blob_store, authority, blob_receipt)
    assert not _blob_path(blob_root, inventory).exists()

    manifest_root = _root(tmp_path, "missing-manifest")
    manifest_store = _store(manifest_root)
    manifest_receipt = _seal(manifest_store, authority)
    _manifest_path(manifest_root, inventory).unlink()
    with pytest.raises(BodyBlobStoreError):
        _readback(manifest_store, authority, manifest_receipt)
    assert not _manifest_path(manifest_root, inventory).exists()


def test_manifest_symlink_hardlink_and_corruption_fail_closed(tmp_path: Path) -> None:
    authority = _authority()
    _bundle, inventory = authority

    corrupt_root = _root(tmp_path, "manifest-corrupt")
    corrupt_store = _store(corrupt_root)
    corrupt_receipt = _seal(corrupt_store, authority)
    manifest = _manifest_path(corrupt_root, inventory)
    original = manifest.read_bytes()
    manifest.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    manifest.chmod(0o600)
    with pytest.raises(BodyBlobStoreError):
        _readback(corrupt_store, authority, corrupt_receipt)

    hardlink_root = _root(tmp_path, "manifest-hardlink")
    hardlink_store = _store(hardlink_root)
    hardlink_receipt = _seal(hardlink_store, authority)
    hardlink_manifest = _manifest_path(hardlink_root, inventory)
    os.link(hardlink_manifest, hardlink_root / "foreign-manifest-link")
    with pytest.raises(BodyBlobStoreError):
        _readback(hardlink_store, authority, hardlink_receipt)

    symlink_root = _root(tmp_path, "manifest-symlink")
    symlink_store = _store(symlink_root)
    symlink_receipt = _seal(symlink_store, authority)
    symlink_manifest = _manifest_path(symlink_root, inventory)
    target = symlink_root / "target.json"
    symlink_manifest.rename(target)
    symlink_manifest.symlink_to(target)
    with pytest.raises(BodyBlobStoreError):
        _readback(symlink_store, authority, symlink_receipt)
    assert target.read_bytes() == inventory.to_canonical_bytes()


def test_component_rebinding_during_promotion_fails_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _bundle, inventory = authority
    root = _root(tmp_path)
    store = _store(root)
    displaced = root / "body-blobs-displaced"
    original_link = store_module.os.link
    rebound = False

    def rebind_then_link(*args: object, **kwargs: object) -> None:
        nonlocal rebound
        if not rebound:
            (root / "body-blobs").rename(displaced)
            (root / "body-blobs").mkdir(mode=0o700)
            (root / "body-blobs").chmod(0o700)
            rebound = True
        original_link(*args, **kwargs)

    monkeypatch.setattr(store_module.os, "link", rebind_then_link)
    with pytest.raises(BodyBlobStoreError, match="rebound"):
        _seal(store, authority)
    assert not _blob_path(root, inventory).exists()
    displaced_blob = displaced.joinpath(
        *inventory.descriptors[0].relative_resource_name.split("/")[1:]
    )
    assert displaced_blob.read_bytes() == authority[0].objects[0].stored_payload


def test_write_enospc_and_keyboard_interrupt_cleanup_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _bundle, inventory = authority
    root = _root(tmp_path)
    store = _store(root)

    def no_space(_descriptor: int, _value: object) -> int:
        raise OSError(errno.ENOSPC, "secret-path-no-space")

    monkeypatch.setattr(store_module.os, "write", no_space)
    with pytest.raises(BodyBlobStoreError) as caught:
        _seal(store, authority)
    assert "secret-path-no-space" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert not _blob_path(root, inventory).exists()
    assert not list(root.rglob("*.tmp"))

    def interrupted(_descriptor: int, _value: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(store_module.os, "write", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _seal(store, authority)
    assert not _blob_path(root, inventory).exists()
    assert not list(root.rglob("*.tmp"))


@pytest.mark.parametrize("fault", ["link", "file-fsync", "directory-fsync"])
def test_install_interruption_points_fail_without_false_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    authority = _authority()
    _bundle, inventory = authority
    root = _root(tmp_path)
    store = _store(root)
    original_fsync = store_module.os.fsync

    if fault == "directory-fsync":
        _safe_parent(root, inventory.descriptors[0].relative_resource_name)

    if fault == "link":

        def fail_link(*_args: object, **_kwargs: object) -> None:
            raise OSError(errno.ENOSPC, "link failed")

        monkeypatch.setattr(store_module.os, "link", fail_link)
    else:

        def fail_fsync(descriptor: int) -> None:
            is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
            if (fault == "directory-fsync") == is_directory:
                raise OSError(errno.ENOSPC, "fsync failed")
            original_fsync(descriptor)

        monkeypatch.setattr(store_module.os, "fsync", fail_fsync)

    with pytest.raises(BodyBlobStoreError):
        _seal(store, authority)
    assert not _manifest_path(root, inventory).exists()
    if fault == "directory-fsync":
        assert _blob_path(root, inventory).is_file()
        monkeypatch.setattr(store_module.os, "fsync", original_fsync)
        assert _seal(store, authority).file_readback_count == 1


def test_effect_before_raise_and_temp_unlink_interruption_converge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    _bundle, inventory = authority
    root = _root(tmp_path)
    store = _store(root)
    original_link = store_module.os.link

    def effect_then_raise(*args: object, **kwargs: object) -> None:
        original_link(*args, **kwargs)
        raise OSError(errno.EIO, "post-link failure")

    monkeypatch.setattr(store_module.os, "link", effect_then_raise)
    with pytest.raises(BodyBlobStoreError):
        _seal(store, authority)
    assert _blob_path(root, inventory).is_file()
    monkeypatch.setattr(store_module.os, "link", original_link)
    assert _seal(store, authority).file_readback_count == 1

    second_root = _root(tmp_path, "unlink-interruption")
    second_store = _store(second_root)
    original_unlink = store_module.os.unlink

    def fail_temp_unlink(name: str, *, dir_fd: int | None = None) -> None:
        if name.endswith(".tmp"):
            raise OSError(errno.EIO, "temporary unlink failed")
        original_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(store_module.os, "unlink", fail_temp_unlink)
    with pytest.raises(BodyBlobStoreError):
        _seal(second_store, authority)
    blob = _blob_path(second_root, inventory)
    assert blob.is_file()
    assert blob.stat().st_nlink == 2
    monkeypatch.setattr(store_module.os, "unlink", original_unlink)
    assert _seal(second_store, authority).file_readback_count == 1
    assert blob.stat().st_nlink == 1
    assert not list(second_root.rglob("*.tmp"))


def test_racing_foreign_destination_is_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    bundle, inventory = authority
    root = _root(tmp_path)
    store = _store(root)
    original_link = store_module.os.link
    payload = bundle.objects[0].stored_payload
    foreign = bytes([payload[0] ^ 1]) + payload[1:]

    def racing_link(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
        follow_symlinks: bool,
    ) -> None:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=dst_dir_fd,
        )
        try:
            os.write(descriptor, foreign)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(store_module.os, "link", racing_link)
    with pytest.raises(BodyBlobStoreError):
        _seal(store, authority)
    assert _blob_path(root, inventory).read_bytes() == foreign


def test_root_rebinding_after_open_fails_without_public_path_leak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    root = _root(tmp_path)
    store = _store(root)
    displaced = root.with_name("body-blob-displaced")
    original_link = store_module.os.link
    rebound = False

    def rebind_root_then_link(*args: object, **kwargs: object) -> None:
        nonlocal rebound
        if not rebound:
            root.rename(displaced)
            root.mkdir(mode=0o700)
            root.chmod(0o700)
            rebound = True
        original_link(*args, **kwargs)

    monkeypatch.setattr(store_module.os, "link", rebind_root_then_link)
    with pytest.raises(BodyBlobStoreError) as caught:
        _seal(store, authority)
    assert "rebound" in str(caught.value)
    assert str(root) not in str(caught.value)
    assert caught.value.__cause__ is None


def test_required_descriptor_relative_nonblocking_nofollow_flags_are_used(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    store = _store(_root(tmp_path))
    original_open = store_module.os.open
    observed: list[int] = []

    def record_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        observed.append(flags)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(store_module.os, "open", record_open)
    _seal(store, authority)
    relevant = [flags for flags in observed if flags & os.O_NOFOLLOW]
    assert relevant
    assert all(flags & os.O_CLOEXEC for flags in relevant)
    assert all(flags & os.O_NONBLOCK for flags in relevant)
    assert any(flags & os.O_DIRECTORY for flags in relevant)


def test_blob_and_manifest_hashes_are_content_addressed(tmp_path: Path) -> None:
    authority = _authority()
    bundle, inventory = authority
    root = _root(tmp_path)
    receipt = _seal(_store(root), authority)
    blob = _blob_path(root, inventory)
    manifest = _manifest_path(root, inventory)
    assert hashlib.sha256(blob.read_bytes()).hexdigest() == inventory.descriptors[0].blob_sha256
    assert manifest.stem == inventory.inventory_sha256
    assert receipt.inventory_sha256 == inventory.inventory_sha256
    assert receipt.total_readback_bytes == bundle.objects[0].stored_bytes
