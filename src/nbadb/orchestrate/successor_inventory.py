"""Descriptor-safe identity for an installed successor public tree.

Kaggle publication fingerprints describe a resource/metadata contract.  They
are deliberately a different digest domain from the exact files and directory
topology installed on disk.  This module owns the latter domain so callers
cannot accidentally reproduce it with publication-contract inputs.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final

__all__ = [
    "InstalledPublicTreeInventory",
    "measure_installed_public_tree",
]

_DIGEST_DOMAIN: Final = "nbadb.installed-public-tree.v2"
_OPEN_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_OPEN_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_OPEN_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)


def _canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_relative_path(value: str, *, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != value
    ):
        raise ValueError(f"installed public tree {label} path is unsafe: {value!r}")
    return path


@dataclass(frozen=True, slots=True)
class InstalledPublicTreeInventory:
    """One immutable measurement in the installed-tree digest domain."""

    files: tuple[tuple[str, int, str], ...]
    directories: tuple[str, ...] = ()
    file_count: int = field(init=False)
    directory_count: int = field(init=False)
    byte_count: int = field(init=False)
    installed_public_tree_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.files:
            raise ValueError("installed public tree inventory must not be empty")
        if tuple(sorted(self.files, key=lambda item: item[0])) != self.files:
            raise ValueError("installed public tree file inventory must be path-sorted")
        if tuple(sorted(self.directories)) != self.directories:
            raise ValueError("installed public tree directory inventory must be path-sorted")

        file_paths = [item[0] for item in self.files]
        if len(file_paths) != len(set(file_paths)):
            raise ValueError("installed public tree file inventory contains duplicate paths")
        if len(self.directories) != len(set(self.directories)):
            raise ValueError("installed public tree directory inventory contains duplicate paths")

        directory_paths = set(self.directories)
        for directory in self.directories:
            pure_directory = _require_relative_path(directory, label="directory")
            parent = pure_directory.parent
            if parent != PurePosixPath(".") and parent.as_posix() not in directory_paths:
                raise ValueError("installed public tree directory inventory has a missing parent")

        for path, byte_count, sha256 in self.files:
            pure_path = _require_relative_path(path, label="file")
            if path in directory_paths:
                raise ValueError("installed public tree path is both a file and a directory")
            if type(byte_count) is not int or byte_count < 0:
                raise ValueError("installed public tree file byte count is invalid")
            if (
                not isinstance(sha256, str)
                or len(sha256) != 64
                or any(character not in "0123456789abcdef" for character in sha256)
            ):
                raise ValueError("installed public tree file SHA-256 is invalid")
            parent = pure_path.parent
            if parent != PurePosixPath(".") and parent.as_posix() not in directory_paths:
                raise ValueError("installed public tree file inventory has a missing parent")

        inventory = self.to_inventory()
        object.__setattr__(self, "file_count", len(inventory))
        object.__setattr__(self, "directory_count", len(self.directories))
        object.__setattr__(self, "byte_count", sum(item["bytes"] for item in inventory))
        object.__setattr__(
            self,
            "installed_public_tree_sha256",
            hashlib.sha256(_canonical_json_bytes(self.to_digest_payload())).hexdigest(),
        )

    def to_inventory(self) -> list[dict[str, Any]]:
        """Return the regular-file inventory used by byte-copying callers."""

        return [
            {"path": path, "bytes": byte_count, "sha256": sha256}
            for path, byte_count, sha256 in self.files
        ]

    def to_digest_payload(self) -> dict[str, Any]:
        """Return the canonical installed-tree domain payload."""

        return {
            "digest_domain": _DIGEST_DOMAIN,
            "directories": [{"path": path} for path in self.directories],
            "files": self.to_inventory(),
        }


def _open_child_descriptor(parent_descriptor: int, name: str, *, display_path: str) -> int:
    if not _OPEN_NOFOLLOW:
        raise RuntimeError("installed public tree identity requires O_NOFOLLOW support")
    flags = os.O_RDONLY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK
    try:
        return os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise ValueError(
                f"installed public tree must not contain symlinks: {display_path}"
            ) from exc
        raise ValueError(f"installed public tree changed while opening: {display_path}") from exc


def _hash_regular_descriptor(descriptor: int, *, display_path: str) -> tuple[int, str]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"installed public tree path is not a regular file: {display_path}")
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    after = os.fstat(descriptor)
    if _stat_identity(before) != _stat_identity(after):
        raise ValueError(f"installed public tree file changed while hashing: {display_path}")
    return before.st_size, digest.hexdigest()


def _inventory_directory_descriptor(
    directory_descriptor: int,
    *,
    prefix: PurePosixPath | None,
    directory_observations: dict[str, tuple[int, int, int, int, int]],
    file_observations: dict[str, tuple[int, int, int, int, int]],
) -> tuple[list[str], list[tuple[str, int, str]]]:
    display_path = "." if prefix is None else prefix.as_posix()
    before = os.fstat(directory_descriptor)
    if not stat.S_ISDIR(before.st_mode):
        raise ValueError(f"installed public tree path is not a regular directory: {display_path}")
    try:
        with os.scandir(directory_descriptor) as iterator:
            names = sorted(entry.name for entry in iterator)
    except OSError as exc:
        raise ValueError(
            f"installed public tree directory cannot be inventoried: {display_path}"
        ) from exc

    directories: list[str] = []
    files: list[tuple[str, int, str]] = []
    for name in names:
        relative = PurePosixPath(name) if prefix is None else prefix / name
        relative_path = relative.as_posix()
        descriptor = _open_child_descriptor(
            directory_descriptor,
            name,
            display_path=relative_path,
        )
        try:
            child_before = os.fstat(descriptor)
            if stat.S_ISDIR(child_before.st_mode):
                directories.append(relative_path)
                child_directories, child_files = _inventory_directory_descriptor(
                    descriptor,
                    prefix=relative,
                    directory_observations=directory_observations,
                    file_observations=file_observations,
                )
                child_after = os.fstat(descriptor)
                if _stat_identity(child_before) != _stat_identity(child_after):
                    raise ValueError(
                        "installed public tree directory changed while inventorying: "
                        f"{relative_path}"
                    )
                directories.extend(child_directories)
                files.extend(child_files)
                continue
            if not stat.S_ISREG(child_before.st_mode):
                raise ValueError(
                    f"installed public tree contains a non-regular entry: {relative_path}"
                )
            byte_count, sha256 = _hash_regular_descriptor(
                descriptor,
                display_path=relative_path,
            )
            file_observations[relative_path] = _stat_identity(os.fstat(descriptor))
            files.append((relative_path, byte_count, sha256))
        finally:
            os.close(descriptor)

    after = os.fstat(directory_descriptor)
    if _stat_identity(before) != _stat_identity(after):
        raise ValueError(
            f"installed public tree directory changed while inventorying: {display_path}"
        )
    directory_observations[display_path] = _stat_identity(after)
    return directories, files


def _open_relative_directory(root_descriptor: int, relative_path: str) -> int:
    descriptor = os.dup(root_descriptor)
    if relative_path == ".":
        return descriptor
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | _OPEN_NOFOLLOW
        | _OPEN_CLOEXEC
        | _OPEN_NONBLOCK
    )
    try:
        for part in PurePosixPath(relative_path).parts:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise ValueError(
            f"installed public tree directory changed after inventory: {relative_path}"
        ) from exc


def _verify_directory_observations(
    root_descriptor: int,
    observations: dict[str, tuple[int, int, int, int, int]],
) -> None:
    """Recheck every scanned directory after the complete recursive snapshot."""

    for relative_path, expected in sorted(observations.items()):
        descriptor = _open_relative_directory(root_descriptor, relative_path)
        try:
            observed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if not stat.S_ISDIR(observed.st_mode) or _stat_identity(observed) != expected:
            raise ValueError(
                f"installed public tree directory changed after inventory: {relative_path}"
            )


def _open_relative_regular_file(root_descriptor: int, relative_path: str) -> int:
    """Open one final-pass regular file through the retained root authority."""

    pure_path = _require_relative_path(relative_path, label="file")
    parent_path = pure_path.parent.as_posix()
    parent_descriptor = _open_relative_directory(root_descriptor, parent_path)
    descriptor = -1
    try:
        descriptor = _open_child_descriptor(
            parent_descriptor,
            pure_path.name,
            display_path=relative_path,
        )
        opened = os.fstat(descriptor)
        named = os.stat(
            pure_path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise ValueError(
                f"installed public tree file changed before final reproof: {relative_path}"
            )
        return descriptor
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    finally:
        os.close(parent_descriptor)


def _verify_regular_file_observations(
    root_descriptor: int,
    files: list[tuple[str, int, str]],
    observations: dict[str, tuple[int, int, int, int, int]],
) -> None:
    """Reopen and rehash every file after the complete first-pass inventory.

    The caller owns the cooperative no-writer boundary.  This second exact
    pass establishes the linearization point within that boundary and catches
    a regular-file mutation that occurs after its first-pass hash without
    changing any parent directory entry.
    """

    if set(observations) != {path for path, _byte_count, _sha256 in files}:
        raise ValueError("installed public tree regular-file observations are incomplete")
    for relative_path, expected_bytes, expected_sha256 in files:
        descriptor = _open_relative_regular_file(root_descriptor, relative_path)
        try:
            before = os.fstat(descriptor)
            if _stat_identity(before) != observations[relative_path]:
                raise ValueError(
                    f"installed public tree file changed before final reproof: {relative_path}"
                )
            observed_bytes, observed_sha256 = _hash_regular_descriptor(
                descriptor,
                display_path=relative_path,
            )
            after = os.fstat(descriptor)
            if (
                _stat_identity(after) != observations[relative_path]
                or observed_bytes != expected_bytes
                or observed_sha256 != expected_sha256
            ):
                raise ValueError(
                    f"installed public tree file changed during final reproof: {relative_path}"
                )
        finally:
            os.close(descriptor)

        rechecked_descriptor = _open_relative_regular_file(root_descriptor, relative_path)
        try:
            if _stat_identity(os.fstat(rechecked_descriptor)) != observations[relative_path]:
                raise ValueError(
                    f"installed public tree file changed after final reproof: {relative_path}"
                )
        finally:
            os.close(rechecked_descriptor)


def measure_installed_public_tree(
    root: Path,
    *,
    expected_root_identity: tuple[int, int] | None = None,
) -> InstalledPublicTreeInventory:
    """Inventory exact installed bytes and topology through stable descriptors."""

    path = Path(root)
    before_path = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(before_path.st_mode):
        raise NotADirectoryError(f"installed public tree root is not a regular directory: {path}")
    if expected_root_identity is not None:
        if (
            type(expected_root_identity) is not tuple
            or len(expected_root_identity) != 2
            or any(type(value) is not int or value < 0 for value in expected_root_identity)
        ):
            raise ValueError("installed public tree expected root identity is invalid")
        if (before_path.st_dev, before_path.st_ino) != expected_root_identity:
            raise ValueError("installed public tree root differs from expected authority")
    if not _OPEN_NOFOLLOW:
        raise RuntimeError("installed public tree identity requires O_NOFOLLOW support")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | _OPEN_NOFOLLOW
        | _OPEN_CLOEXEC
        | _OPEN_NONBLOCK
    )
    try:
        root_descriptor = os.open(path, flags)
    except OSError as exc:
        raise NotADirectoryError(
            f"installed public tree root is not a regular directory: {path}"
        ) from exc
    try:
        opened_root = os.fstat(root_descriptor)
        if not stat.S_ISDIR(opened_root.st_mode) or (opened_root.st_dev, opened_root.st_ino) != (
            before_path.st_dev,
            before_path.st_ino,
        ):
            raise ValueError("installed public tree root changed before inventorying")
        directory_observations: dict[str, tuple[int, int, int, int, int]] = {}
        file_observations: dict[str, tuple[int, int, int, int, int]] = {}
        directories, files = _inventory_directory_descriptor(
            root_descriptor,
            prefix=None,
            directory_observations=directory_observations,
            file_observations=file_observations,
        )
        _verify_directory_observations(root_descriptor, directory_observations)
        _verify_regular_file_observations(root_descriptor, files, file_observations)
        _verify_directory_observations(root_descriptor, directory_observations)
        after_descriptor = os.fstat(root_descriptor)
        after_path = os.stat(path, follow_symlinks=False)
        expected_root = _stat_identity(opened_root)
        if (
            _stat_identity(after_descriptor) != expected_root
            or _stat_identity(after_path) != expected_root
        ):
            raise ValueError("installed public tree root changed while inventorying")
    finally:
        os.close(root_descriptor)

    return InstalledPublicTreeInventory(
        files=tuple(sorted(files, key=lambda item: item[0])),
        directories=tuple(sorted(directories)),
    )
