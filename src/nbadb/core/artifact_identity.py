from __future__ import annotations

import argparse
import errno
import gzip
import hashlib
import json
import os
import re
import secrets
import stat
import zlib
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

ASSURED_ARTIFACT_MANIFEST_NAME = "assured-artifact-manifest.json"
SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME = "terminal-assurance-report.json"
_EXCLUDED_INVENTORY_NAMES = frozenset(
    {
        ASSURED_ARTIFACT_MANIFEST_NAME,
        "dataset-metadata.json",
    }
)


def _is_lowercase_hex(value: object, *, length: int) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


_OPEN_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_OPEN_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_OPEN_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_MAX_PUBLIC_SENTINEL_CONTROL_BYTES = 64 * 1024 * 1024
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "chain_id",
        "source_sha",
        "coverage_fingerprint",
        "data_tree_fingerprint",
        "file_count",
        "bytes",
        "files",
    }
)
_MANIFEST_FILE_KEYS = frozenset({"path", "bytes", "sha256"})
_PRIVATE_CAPTURE_SENTINELS = (
    b"private_parser_input_generation",
    b"nbadb_exact_decoded_response_text_utf8",
    b"nba_api_static_canonical_json_utf8",
)
_MAX_PRIVATE_SENTINEL_BYTES = max(map(len, _PRIVATE_CAPTURE_SENTINELS))
_PRIVATE_CAPTURE_KIND_KEY = b'"kind"'
_PRIVATE_CAPTURE_KIND_VALUES = tuple(
    f'"{kind}"'.encode()
    for kind in (
        "response_attempt",
        "logical_call",
        "private_parser_input_generation",
    )
)
_JSON_NON_WHITESPACE = re.compile(rb"[^ \t\r\n]")
_PRIVATE_GZIP_READ_BYTES = 64 * 1024
_MAX_PRIVATE_GZIP_DECOMPRESSED_BYTES = 16 * 1024 * 1024
_MAX_PRIVATE_GZIP_EXPANSION_RATIO = 256
_MIN_PRIVATE_GZIP_DECOMPRESSED_BYTES = 1024 * 1024


class _PrivateCaptureMarkerScanner:
    """Recognize private markers without buffering attacker-controlled spacing."""

    def __init__(self) -> None:
        self._tail = b""
        self._kind_key_tail = b""
        self._kind_stage = "key"
        self._kind_value_candidates: tuple[bytes, ...] = ()
        self._kind_value_index = 0

    def feed(self, chunk: bytes) -> bool:
        """Return whether ``chunk`` completes a private-capture marker."""

        window = self._tail + chunk
        if any(marker in window for marker in _PRIVATE_CAPTURE_SENTINELS):
            return True
        self._tail = window[-(_MAX_PRIVATE_SENTINEL_BYTES - 1) :]
        return self._feed_kind(chunk)

    def _remember_kind_key_prefix(self, window: bytes) -> None:
        for length in range(min(len(window), len(_PRIVATE_CAPTURE_KIND_KEY) - 1), 0, -1):
            if window.endswith(_PRIVATE_CAPTURE_KIND_KEY[:length]):
                self._kind_key_tail = window[-length:]
                return
        self._kind_key_tail = b""

    def _feed_kind(self, chunk: bytes) -> bool:
        window = self._kind_key_tail + chunk if self._kind_stage == "key" else chunk
        self._kind_key_tail = b""
        position = 0
        while position < len(window):
            if self._kind_stage == "key":
                key_position = window.find(_PRIVATE_CAPTURE_KIND_KEY, position)
                if key_position < 0:
                    self._remember_kind_key_prefix(window)
                    return False
                self._kind_stage = "colon"
                position = key_position + len(_PRIVATE_CAPTURE_KIND_KEY)
                continue

            if self._kind_stage in {"colon", "value_start"}:
                match = _JSON_NON_WHITESPACE.search(window, position)
                if match is None:
                    return False
                position = match.start()
                if self._kind_stage == "colon":
                    if window[position] == ord(":"):
                        self._kind_stage = "value_start"
                        position += 1
                        continue
                    self._kind_stage = "key"
                    continue
                candidates = tuple(
                    value for value in _PRIVATE_CAPTURE_KIND_VALUES if value[0] == window[position]
                )
                if not candidates:
                    self._kind_stage = "key"
                    continue
                self._kind_stage = "value"
                self._kind_value_candidates = candidates
                self._kind_value_index = 1
                position += 1
                continue

            candidates = tuple(
                value
                for value in self._kind_value_candidates
                if value[self._kind_value_index] == window[position]
            )
            if not candidates:
                self._kind_stage = "key"
                self._kind_value_candidates = ()
                self._kind_value_index = 0
                continue
            position += 1
            self._kind_value_index += 1
            if any(self._kind_value_index == len(value) for value in candidates):
                return True
            self._kind_value_candidates = candidates
        if self._kind_stage == "key":
            self._remember_kind_key_prefix(window)
        return False


def _has_private_capture_layout(relative: PurePosixPath, *, is_directory: bool) -> bool:
    """Return whether a relative path has a private Bronze CAS signature."""

    parts = relative.parts
    if relative.name == ".capture.lock":
        return True
    if not is_directory and relative.name.endswith(".payload.gz"):
        return True
    if is_directory:
        return len(parts) >= 2 and parts[-2:] in {
            ("blobs", "sha256"),
            ("receipts", "attempts"),
            ("receipts", "calls"),
        }
    if (
        len(parts) >= 4
        and parts[-4:-2] == ("blobs", "sha256")
        and len(parts[-2]) == 2
        and len(parts[-1]) == 75
        and parts[-1].endswith(".payload.gz")
        and all(character in "0123456789abcdef" for character in parts[-1][:-11])
        and parts[-2] == parts[-1][:2]
    ):
        return True
    return bool(
        len(parts) >= 4
        and parts[-4] == "receipts"
        and parts[-3] in {"attempts", "calls"}
        and len(parts[-2]) == 2
        and len(parts[-1]) == 69
        and parts[-1].endswith(".json")
        and all(character in "0123456789abcdef" for character in parts[-1][:-5])
        and parts[-2] == parts[-1][:2]
    )


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _hash_regular_descriptor(descriptor: int, *, display_path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Assured artifact inventory path is not a regular file: {display_path}")
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    after = os.fstat(descriptor)
    if _stat_identity(before) != _stat_identity(after):
        raise ValueError(f"Assured artifact file changed while hashing: {display_path}")
    return before.st_size, digest.hexdigest()


def _open_child_descriptor(parent_descriptor: int, name: str, *, display_path: str) -> int:
    if not _OPEN_NOFOLLOW:
        raise RuntimeError("Assured artifact identity requires O_NOFOLLOW support")
    flags = os.O_RDONLY | _OPEN_NOFOLLOW | _OPEN_CLOEXEC | _OPEN_NONBLOCK
    try:
        return os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EMLINK}:
            raise ValueError(f"Assured artifact must not contain symlinks: {display_path}") from exc
        raise ValueError(f"Assured artifact changed while opening: {display_path}") from exc


def _inventory_from_descriptor(
    directory_descriptor: int,
    *,
    prefix: PurePosixPath | None = None,
    excluded_paths: frozenset[str] = _EXCLUDED_INVENTORY_NAMES,
) -> list[dict[str, Any]]:
    observations: dict[str, tuple[tuple[int, int, int, int, int], tuple[str, ...]]] = {}
    file_observations: dict[str, tuple[int, int, int, int, int]] = {}
    files = _inventory_directory_descriptor(
        directory_descriptor,
        prefix=prefix,
        excluded_paths=excluded_paths,
        observations=observations,
        file_observations=file_observations,
    )
    _verify_inventory_directory_observations(
        directory_descriptor,
        root_prefix=prefix,
        observations=observations,
        file_observations=file_observations,
    )
    return files


def _inventory_directory_descriptor(
    directory_descriptor: int,
    *,
    prefix: PurePosixPath | None,
    excluded_paths: frozenset[str],
    observations: dict[str, tuple[tuple[int, int, int, int, int], tuple[str, ...]]],
    file_observations: dict[str, tuple[int, int, int, int, int]],
) -> list[dict[str, Any]]:
    display_path = prefix.as_posix() if prefix is not None else "."
    before = os.fstat(directory_descriptor)
    if not stat.S_ISDIR(before.st_mode):
        raise ValueError(
            f"Assured artifact inventory path is not a regular directory: {display_path}"
        )
    try:
        with os.scandir(directory_descriptor) as iterator:
            names = tuple(sorted(entry.name for entry in iterator))
    except OSError as exc:
        raise ValueError(
            f"Assured artifact directory cannot be inventoried: {display_path}"
        ) from exc

    files: list[dict[str, Any]] = []
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
            mode = child_before.st_mode
            if stat.S_ISDIR(mode):
                files.extend(
                    _inventory_directory_descriptor(
                        descriptor,
                        prefix=relative,
                        excluded_paths=excluded_paths,
                        observations=observations,
                        file_observations=file_observations,
                    )
                )
                continue
            if relative_path in excluded_paths:
                if not stat.S_ISREG(mode):
                    raise ValueError(
                        "Assured artifact excluded inventory path is not a regular file: "
                        f"{relative_path}"
                    )
                file_observations[relative_path] = _stat_identity(os.fstat(descriptor))
                continue
            byte_count, sha256 = _hash_regular_descriptor(
                descriptor,
                display_path=relative_path,
            )
            child_after = os.fstat(descriptor)
            if _stat_identity(child_before) != _stat_identity(child_after):
                raise ValueError(
                    f"Assured artifact file changed while inventorying: {relative_path}"
                )
            files.append(
                {
                    "path": relative_path,
                    "bytes": byte_count,
                    "sha256": sha256,
                }
            )
            file_observations[relative_path] = _stat_identity(child_after)
        finally:
            os.close(descriptor)
    after = os.fstat(directory_descriptor)
    if _stat_identity(before) != _stat_identity(after):
        raise ValueError(f"Assured artifact directory changed while inventorying: {display_path}")
    try:
        with os.scandir(directory_descriptor) as iterator:
            after_names = tuple(sorted(entry.name for entry in iterator))
    except OSError as exc:
        raise ValueError(
            f"Assured artifact directory cannot be re-inventoried: {display_path}"
        ) from exc
    after_recheck = os.fstat(directory_descriptor)
    if names != after_names or _stat_identity(after) != _stat_identity(after_recheck):
        raise ValueError(f"Assured artifact directory changed while inventorying: {display_path}")
    observations[display_path] = (_stat_identity(after_recheck), after_names)
    return files


def _open_inventory_relative_directory(root_descriptor: int, relative_path: str) -> int:
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
            f"Assured artifact directory changed after inventory: {relative_path}"
        ) from exc


def _verify_inventory_directory_observations(
    root_descriptor: int,
    *,
    root_prefix: PurePosixPath | None,
    observations: dict[str, tuple[tuple[int, int, int, int, int], tuple[str, ...]]],
    file_observations: dict[str, tuple[int, int, int, int, int]],
) -> None:
    root_parts = () if root_prefix is None else root_prefix.parts
    for display_path, (expected_identity, expected_names) in sorted(observations.items()):
        display_parts = () if display_path == "." else PurePosixPath(display_path).parts
        if display_parts[: len(root_parts)] != root_parts:
            raise ValueError("Assured artifact directory observation escaped its root")
        relative_parts = display_parts[len(root_parts) :]
        relative_path = PurePosixPath(*relative_parts).as_posix() if relative_parts else "."
        descriptor = _open_inventory_relative_directory(root_descriptor, relative_path)
        try:
            before = os.fstat(descriptor)
            with os.scandir(descriptor) as iterator:
                observed_names = tuple(sorted(entry.name for entry in iterator))
            after = os.fstat(descriptor)
        except OSError as exc:
            raise ValueError(
                f"Assured artifact directory changed after inventory: {display_path}"
            ) from exc
        finally:
            os.close(descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or _stat_identity(before) != expected_identity
            or _stat_identity(after) != expected_identity
            or observed_names != expected_names
        ):
            raise ValueError(f"Assured artifact directory changed after inventory: {display_path}")

    for display_path, expected_identity in sorted(file_observations.items()):
        display_parts = PurePosixPath(display_path).parts
        if display_parts[: len(root_parts)] != root_parts:
            raise ValueError("Assured artifact file observation escaped its root")
        relative_parts = display_parts[len(root_parts) :]
        if not relative_parts:
            raise ValueError("Assured artifact file observation is invalid")
        parent_path = (
            PurePosixPath(*relative_parts[:-1]).as_posix() if len(relative_parts) > 1 else "."
        )
        parent_descriptor = _open_inventory_relative_directory(root_descriptor, parent_path)
        try:
            descriptor = _open_child_descriptor(
                parent_descriptor,
                relative_parts[-1],
                display_path=display_path,
            )
        finally:
            os.close(parent_descriptor)
        try:
            observed = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if not stat.S_ISREG(observed.st_mode) or _stat_identity(observed) != expected_identity:
            raise ValueError(f"Assured artifact file changed after inventory: {display_path}")


@contextmanager
def _open_artifact_root(
    root: Path,
    *,
    expected_root_identity: tuple[int, int] | None = None,
) -> Iterator[tuple[Path, int]]:
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise NotADirectoryError(f"Assured artifact root is not a directory: {root}") from exc
    if not _OPEN_NOFOLLOW:
        raise RuntimeError("Assured artifact identity requires O_NOFOLLOW support")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | _OPEN_NOFOLLOW
        | _OPEN_CLOEXEC
        | _OPEN_NONBLOCK
    )
    try:
        descriptor = os.open(resolved_root, flags)
    except OSError as exc:
        raise NotADirectoryError(f"Assured artifact root is not a directory: {root}") from exc
    try:
        opened = os.fstat(descriptor)
        named = os.stat(resolved_root, follow_symlinks=False)
        if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            named.st_dev,
            named.st_ino,
        ):
            raise NotADirectoryError(f"Assured artifact root is not a directory: {root}")
        if expected_root_identity is not None:
            if (
                type(expected_root_identity) is not tuple
                or len(expected_root_identity) != 2
                or any(type(value) is not int or value < 0 for value in expected_root_identity)
            ):
                raise ValueError("Assured artifact expected root identity is invalid")
            if (opened.st_dev, opened.st_ino) != expected_root_identity:
                raise ValueError("Assured artifact root differs from expected authority")
        yield resolved_root, descriptor
    finally:
        os.close(descriptor)


def _inventory_from_root_descriptor(root_descriptor: int) -> list[dict[str, Any]]:
    files = _inventory_from_descriptor(root_descriptor)
    if not files:
        raise ValueError("Assured artifact inventory is empty")
    files.sort(key=lambda item: item["path"])
    return files


def inventory_regular_tree(
    root: Path,
    *,
    excluded_paths: frozenset[str] = frozenset(),
    expected_root_identity: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    """Return a mutation-checked, symlink-safe regular-file inventory.

    This is the repository-owned low-level tree primitive shared by public
    artifact assurance and private parser-input generation. Callers retain
    ownership of their path schema and empty-inventory semantics.
    """

    with _open_artifact_root(
        root,
        expected_root_identity=expected_root_identity,
    ) as (_resolved_root, root_descriptor):
        files = _inventory_from_descriptor(
            root_descriptor,
            excluded_paths=excluded_paths,
        )
    files.sort(key=lambda item: item["path"])
    return files


def _scan_gzip_descriptor_for_private_capture(
    descriptor: int,
    *,
    stored_bytes: int,
    display_path: str,
) -> None:
    """Inspect gzip content under fixed decompressed-byte and expansion-ratio caps."""

    inspection_limit = min(
        _MAX_PRIVATE_GZIP_DECOMPRESSED_BYTES,
        max(
            _MIN_PRIVATE_GZIP_DECOMPRESSED_BYTES,
            stored_bytes * _MAX_PRIVATE_GZIP_EXPANSION_RATIO,
        ),
    )
    scanner = _PrivateCaptureMarkerScanner()
    os.lseek(descriptor, 0, os.SEEK_SET)
    duplicate = os.dup(descriptor)
    with os.fdopen(duplicate, "rb") as raw_handle:
        try:
            with gzip.GzipFile(fileobj=raw_handle, mode="rb") as gzip_handle:
                decompressed_bytes = 0
                while True:
                    remaining = inspection_limit - decompressed_bytes
                    chunk = gzip_handle.read(min(_PRIVATE_GZIP_READ_BYTES, remaining + 1))
                    if not chunk:
                        return
                    decompressed_bytes += len(chunk)
                    if scanner.feed(chunk):
                        raise ValueError(
                            "Public artifact contains a private parser-input sentinel: "
                            f"{display_path}"
                        )
                    if decompressed_bytes > inspection_limit:
                        raise ValueError(
                            "Public artifact gzip cannot be fully inspected within the safe "
                            f"private-sentinel limit: {display_path}"
                        )
        except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
            raise ValueError(
                f"Public artifact contains malformed or incomplete gzip content: {display_path}"
            ) from exc


def _scan_descriptor_for_private_capture(descriptor: int, *, display_path: str) -> None:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"Public artifact path is not a regular file: {display_path}")
    header = bytearray()
    scanner = _PrivateCaptureMarkerScanner()
    while chunk := os.read(descriptor, 1024 * 1024):
        if len(header) < 2:
            header.extend(chunk[: 2 - len(header)])
        if scanner.feed(chunk):
            raise ValueError(
                f"Public artifact contains a private parser-input sentinel: {display_path}"
            )
    if bytes(header) == b"\x1f\x8b":
        _scan_gzip_descriptor_for_private_capture(
            descriptor,
            stored_bytes=before.st_size,
            display_path=display_path,
        )
    after = os.fstat(descriptor)
    if _stat_identity(before) != _stat_identity(after):
        raise ValueError(f"Public artifact file changed while scanning: {display_path}")


def _validate_public_sentinel_control(descriptor: int, *, display_path: str) -> None:
    if display_path != SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME:
        raise ValueError(f"Unsupported public private-sentinel control: {display_path}")
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_PUBLIC_SENTINEL_CONTROL_BYTES:
        raise ValueError(f"Public private-sentinel control is invalid: {display_path}")
    chunks: list[bytes] = []
    total = 0
    while chunk := os.read(descriptor, 1024 * 1024):
        total += len(chunk)
        if total > _MAX_PUBLIC_SENTINEL_CONTROL_BYTES:
            raise ValueError(f"Public private-sentinel control is oversized: {display_path}")
        chunks.append(chunk)
    after = os.fstat(descriptor)
    if _stat_identity(before) != _stat_identity(after):
        raise ValueError(f"Public private-sentinel control changed: {display_path}")
    encoded = b"".join(chunks)
    try:
        from nbadb.orchestrate.successor_assurance import (
            validate_successor_terminal_assurance_report,
        )

        report = validate_successor_terminal_assurance_report(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Public private-sentinel control is not canonical assurance: {display_path}"
        ) from exc
    if report.canonical_bytes != encoded:
        raise ValueError(
            f"Public private-sentinel control is not canonical assurance: {display_path}"
        )


def _scan_public_tree_descriptor(
    directory_descriptor: int,
    *,
    prefix: PurePosixPath | None = None,
    sentinel_excluded_paths: frozenset[str] = frozenset(),
) -> None:
    observations: dict[str, tuple[tuple[int, int, int, int, int], tuple[str, ...]]] = {}
    file_observations: dict[str, tuple[int, int, int, int, int]] = {}
    _scan_public_directory_descriptor(
        directory_descriptor,
        prefix=prefix,
        sentinel_excluded_paths=sentinel_excluded_paths,
        observations=observations,
        file_observations=file_observations,
    )
    _verify_inventory_directory_observations(
        directory_descriptor,
        root_prefix=prefix,
        observations=observations,
        file_observations=file_observations,
    )


def _scan_public_directory_descriptor(
    directory_descriptor: int,
    *,
    prefix: PurePosixPath | None,
    sentinel_excluded_paths: frozenset[str],
    observations: dict[str, tuple[tuple[int, int, int, int, int], tuple[str, ...]]],
    file_observations: dict[str, tuple[int, int, int, int, int]],
) -> None:
    display_path = prefix.as_posix() if prefix is not None else "."
    before = os.fstat(directory_descriptor)
    if not stat.S_ISDIR(before.st_mode):
        raise ValueError(f"Public artifact path is not a regular directory: {display_path}")
    try:
        with os.scandir(directory_descriptor) as iterator:
            names = tuple(sorted(entry.name for entry in iterator))
    except OSError as exc:
        raise ValueError(f"Public artifact directory cannot be scanned: {display_path}") from exc

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
            mode = child_before.st_mode
            is_directory = stat.S_ISDIR(mode)
            if _has_private_capture_layout(relative, is_directory=is_directory):
                raise ValueError(
                    f"Public artifact contains a private parser-input layout path: {relative_path}"
                )
            if is_directory:
                if relative_path in sentinel_excluded_paths:
                    raise ValueError(
                        "Private-sentinel excluded public control is not a regular file: "
                        f"{relative_path}"
                    )
                _scan_public_directory_descriptor(
                    descriptor,
                    prefix=relative,
                    sentinel_excluded_paths=sentinel_excluded_paths,
                    observations=observations,
                    file_observations=file_observations,
                )
                child_after = os.fstat(descriptor)
                if _stat_identity(child_before) != _stat_identity(child_after):
                    raise ValueError(
                        f"Public artifact directory changed while scanning: {relative_path}"
                    )
                continue
            elif relative_path in sentinel_excluded_paths:
                _validate_public_sentinel_control(
                    descriptor,
                    display_path=relative_path,
                )
            else:
                _scan_descriptor_for_private_capture(
                    descriptor,
                    display_path=relative_path,
                )
            child_after = os.fstat(descriptor)
            if _stat_identity(child_before) != _stat_identity(child_after):
                raise ValueError(f"Public artifact file changed while scanning: {relative_path}")
            file_observations[relative_path] = _stat_identity(child_after)
        finally:
            os.close(descriptor)
    after = os.fstat(directory_descriptor)
    if _stat_identity(before) != _stat_identity(after):
        raise ValueError(f"Public artifact directory changed while scanning: {display_path}")
    try:
        with os.scandir(directory_descriptor) as iterator:
            after_names = tuple(sorted(entry.name for entry in iterator))
    except OSError as exc:
        raise ValueError(f"Public artifact directory cannot be re-scanned: {display_path}") from exc
    after_recheck = os.fstat(directory_descriptor)
    if names != after_names or _stat_identity(after) != _stat_identity(after_recheck):
        raise ValueError(f"Public artifact directory changed while scanning: {display_path}")
    observations[display_path] = (_stat_identity(after_recheck), after_names)


def assert_no_private_capture_sentinels(
    root: Path,
    *,
    expected_root_identity: tuple[int, int] | None = None,
    sentinel_excluded_paths: frozenset[str] = frozenset(),
) -> None:
    """Fail when a private parser-input marker reaches a public artifact tree."""

    if type(sentinel_excluded_paths) is not frozenset or not sentinel_excluded_paths.issubset(
        {SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME}
    ):
        raise ValueError("Private-sentinel exclusions contain an unsupported public control")

    with _open_artifact_root(
        root,
        expected_root_identity=expected_root_identity,
    ) as (_resolved_root, root_descriptor):
        _scan_public_tree_descriptor(
            root_descriptor,
            sentinel_excluded_paths=sentinel_excluded_paths,
        )


def _canonical_manifest_path(resolved_root: Path, manifest_path: Path | None) -> Path:
    canonical = resolved_root / ASSURED_ARTIFACT_MANIFEST_NAME
    requested = manifest_path or canonical
    if Path(os.path.abspath(requested)) != canonical:
        raise ValueError("Assured artifact manifest must use the canonical path inside its root")
    return canonical


def _atomic_write_manifest(
    root_descriptor: int,
    payload: bytes,
    *,
    replace_existing: bool,
) -> None:
    temporary_name = f".{ASSURED_ARTIFACT_MANIFEST_NAME}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_NOFOLLOW | _OPEN_CLOEXEC
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=root_descriptor)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short write while creating assured artifact manifest")
            view = view[written:]
        os.fchmod(descriptor, 0o644)
        os.fsync(descriptor)
        published_stat = os.fstat(descriptor)
        os.close(descriptor)
        descriptor = None
        if replace_existing:
            os.replace(
                temporary_name,
                ASSURED_ARTIFACT_MANIFEST_NAME,
                src_dir_fd=root_descriptor,
                dst_dir_fd=root_descriptor,
            )
        else:
            os.link(
                temporary_name,
                ASSURED_ARTIFACT_MANIFEST_NAME,
                src_dir_fd=root_descriptor,
                dst_dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        os.fsync(root_descriptor)
        published = _open_child_descriptor(
            root_descriptor,
            ASSURED_ARTIFACT_MANIFEST_NAME,
            display_path=ASSURED_ARTIFACT_MANIFEST_NAME,
        )
        try:
            observed = os.fstat(published)
            if (
                not stat.S_ISREG(observed.st_mode)
                or (observed.st_dev, observed.st_ino)
                != (published_stat.st_dev, published_stat.st_ino)
                or observed.st_size != len(payload)
                or stat.S_IMODE(observed.st_mode) != 0o644
            ):
                raise ValueError("Assured artifact manifest changed during atomic publication")
            chunks: list[bytes] = []
            while chunk := os.read(published, 1024 * 1024):
                chunks.append(chunk)
            after = os.fstat(published)
            if _stat_identity(observed) != _stat_identity(after):
                raise ValueError(
                    "Assured artifact manifest changed during publication verification"
                )
            observed_payload = b"".join(chunks)
            if observed_payload != payload:
                raise ValueError("Assured artifact manifest bytes differ after atomic publication")
            _validate_manifest_payload(
                _strict_json_object(observed_payload, label="Assured artifact manifest")
            )
        finally:
            os.close(published)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary_name, dir_fd=root_descriptor)


def _strict_json_object(encoded: bytes, *, label: str) -> dict[str, Any]:
    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate keys")
            result[key] = value
        return result

    try:
        decoded = json.loads(
            encoded,
            object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"{label} contains nonfinite JSON: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} cannot be read safely") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} has an unsupported schema")
    return cast("dict[str, Any]", decoded)


def _read_manifest(root_descriptor: int) -> tuple[dict[str, Any], bytes]:
    descriptor = _open_child_descriptor(
        root_descriptor,
        ASSURED_ARTIFACT_MANIFEST_NAME,
        display_path=ASSURED_ARTIFACT_MANIFEST_NAME,
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Assured artifact manifest is not a regular file")
        if before.st_size > _MAX_MANIFEST_BYTES:
            raise ValueError("Assured artifact manifest exceeds the safe size limit")
        chunks: list[bytes] = []
        total_bytes = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > _MAX_MANIFEST_BYTES:
                raise ValueError("Assured artifact manifest exceeds the safe size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if _stat_identity(before) != _stat_identity(after):
            raise ValueError("Assured artifact manifest changed while reading")
    finally:
        os.close(descriptor)
    encoded = b"".join(chunks)
    return _strict_json_object(encoded, label="Assured artifact manifest"), encoded


def _tree_fingerprint(files: list[dict[str, Any]]) -> str:
    source = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _validate_manifest_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Assured artifact manifest has an unsupported schema")
    payload_dict = cast("dict[str, Any]", payload)
    if set(payload_dict) != _MANIFEST_KEYS:
        raise ValueError("Assured artifact manifest fields are invalid")
    schema_version = payload_dict.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError("Assured artifact manifest has an unsupported schema")
    chain_id = payload_dict.get("chain_id")
    if not isinstance(chain_id, str) or not chain_id.strip():
        raise ValueError("Assured artifact manifest chain_id must be nonempty")
    if not _is_lowercase_hex(payload_dict.get("source_sha"), length=40):
        raise ValueError("Assured artifact manifest source_sha must be 40 lowercase hex characters")
    if not _is_lowercase_hex(payload_dict.get("coverage_fingerprint"), length=64):
        raise ValueError(
            "Assured artifact manifest coverage_fingerprint must be 64 lowercase hex characters"
        )
    if not _is_lowercase_hex(payload_dict.get("data_tree_fingerprint"), length=64):
        raise ValueError(
            "Assured artifact manifest data_tree_fingerprint must be 64 lowercase hex characters"
        )

    files = payload_dict.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Assured artifact manifest files must be a nonempty list")
    normalized_files: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for raw_file in files:
        if not isinstance(raw_file, dict):
            raise ValueError("Assured artifact manifest file entries must be objects")
        raw_file_dict = cast("dict[str, Any]", raw_file)
        if set(raw_file_dict) != _MANIFEST_FILE_KEYS:
            raise ValueError("Assured artifact manifest file fields are invalid")
        relative_path = raw_file_dict.get("path")
        if not isinstance(relative_path, str):
            raise ValueError("Assured artifact manifest contains an invalid or duplicate path")
        pure_path = PurePosixPath(relative_path)
        if (
            pure_path.is_absolute()
            or not pure_path.parts
            or ".." in pure_path.parts
            or relative_path in seen_paths
            or relative_path in _EXCLUDED_INVENTORY_NAMES
        ):
            raise ValueError("Assured artifact manifest contains an invalid or duplicate path")
        byte_count = raw_file_dict.get("bytes")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            raise ValueError("Assured artifact manifest file bytes must be nonnegative integers")
        if not _is_lowercase_hex(raw_file_dict.get("sha256"), length=64):
            raise ValueError("Assured artifact manifest file sha256 must be lowercase hex")
        seen_paths.add(relative_path)
        normalized_files.append(
            {
                "path": relative_path,
                "bytes": byte_count,
                "sha256": raw_file_dict["sha256"],
            }
        )
    normalized_files.sort(key=lambda item: item["path"])
    if normalized_files != files:
        raise ValueError("Assured artifact manifest files must be sorted by path")
    file_count = payload_dict.get("file_count")
    if (
        not isinstance(file_count, int)
        or isinstance(file_count, bool)
        or file_count != len(normalized_files)
    ):
        raise ValueError("Assured artifact manifest file count is inconsistent")
    byte_count = payload_dict.get("bytes")
    if (
        not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
        or byte_count < 0
        or byte_count != sum(item["bytes"] for item in normalized_files)
    ):
        raise ValueError("Assured artifact manifest byte count is inconsistent")
    if _tree_fingerprint(normalized_files) != payload_dict["data_tree_fingerprint"]:
        raise ValueError("Assured artifact manifest tree fingerprint is inconsistent")
    return payload_dict


def _assured_manifest_bytes_from_descriptor(
    root_descriptor: int,
    *,
    chain_id: str,
    source_sha: str,
    coverage_fingerprint: str,
) -> bytes:
    files = _inventory_from_root_descriptor(root_descriptor)
    payload = {
        "schema_version": 1,
        "chain_id": chain_id,
        "source_sha": source_sha,
        "coverage_fingerprint": coverage_fingerprint,
        "data_tree_fingerprint": _tree_fingerprint(files),
        "file_count": len(files),
        "bytes": sum(item["bytes"] for item in files),
        "files": files,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_assured_artifact_manifest_bytes(
    root: Path,
    *,
    chain_id: str,
    source_sha: str,
    coverage_fingerprint: str,
    expected_root_identity: tuple[int, int] | None = None,
    sentinel_excluded_paths: frozenset[str] = frozenset(),
) -> bytes:
    """Return exact schema-v1 manifest bytes without mutating ``root``."""

    if not chain_id.strip():
        raise ValueError("chain_id must be nonempty")
    if not _is_lowercase_hex(source_sha, length=40):
        raise ValueError("source_sha must be 40 lowercase hex characters")
    if not _is_lowercase_hex(coverage_fingerprint, length=64):
        raise ValueError("coverage_fingerprint must be 64 lowercase hex characters")
    assert_no_private_capture_sentinels(
        root,
        expected_root_identity=expected_root_identity,
        sentinel_excluded_paths=sentinel_excluded_paths,
    )
    with _open_artifact_root(
        root,
        expected_root_identity=expected_root_identity,
    ) as (_resolved_root, root_descriptor):
        return _assured_manifest_bytes_from_descriptor(
            root_descriptor,
            chain_id=chain_id,
            source_sha=source_sha,
            coverage_fingerprint=coverage_fingerprint,
        )


def build_assured_artifact_manifest(
    root: Path,
    *,
    chain_id: str,
    source_sha: str,
    coverage_fingerprint: str,
    manifest_path: Path | None = None,
    expected_root_identity: tuple[int, int] | None = None,
    replace_existing: bool = True,
    sentinel_excluded_paths: frozenset[str] = frozenset(),
) -> Path:
    if not chain_id.strip():
        raise ValueError("chain_id must be nonempty")
    if not _is_lowercase_hex(source_sha, length=40):
        raise ValueError("source_sha must be 40 lowercase hex characters")
    if not _is_lowercase_hex(coverage_fingerprint, length=64):
        raise ValueError("coverage_fingerprint must be 64 lowercase hex characters")

    assert_no_private_capture_sentinels(
        root,
        expected_root_identity=expected_root_identity,
        sentinel_excluded_paths=sentinel_excluded_paths,
    )
    with _open_artifact_root(
        root,
        expected_root_identity=expected_root_identity,
    ) as (resolved_root, root_descriptor):
        target = _canonical_manifest_path(resolved_root, manifest_path)
        encoded = _assured_manifest_bytes_from_descriptor(
            root_descriptor,
            chain_id=chain_id,
            source_sha=source_sha,
            coverage_fingerprint=coverage_fingerprint,
        )
        if type(replace_existing) is not bool:
            raise ValueError("replace_existing must be a boolean")
        _atomic_write_manifest(
            root_descriptor,
            encoded,
            replace_existing=replace_existing,
        )
        return target


def verify_assured_artifact_manifest(
    root: Path,
    *,
    expected_chain_id: str | None = None,
    expected_source_sha: str | None = None,
    expected_coverage_fingerprint: str | None = None,
    manifest_path: Path | None = None,
    expected_root_identity: tuple[int, int] | None = None,
    sentinel_excluded_paths: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    assert_no_private_capture_sentinels(
        root,
        expected_root_identity=expected_root_identity,
        sentinel_excluded_paths=sentinel_excluded_paths,
    )
    with _open_artifact_root(
        root,
        expected_root_identity=expected_root_identity,
    ) as (resolved_root, root_descriptor):
        _canonical_manifest_path(resolved_root, manifest_path)
        raw_manifest, manifest_bytes = _read_manifest(root_descriptor)
        manifest = _validate_manifest_payload(raw_manifest)
        canonical_manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        if manifest_bytes != canonical_manifest_bytes:
            raise ValueError("Assured artifact manifest bytes are not canonical")
        expectations = {
            "chain_id": expected_chain_id,
            "source_sha": expected_source_sha,
            "coverage_fingerprint": expected_coverage_fingerprint,
        }
        for field, expected in expectations.items():
            if expected is not None and manifest[field] != expected:
                raise ValueError(f"Assured artifact manifest {field} mismatch")

        observed_files = _inventory_from_root_descriptor(root_descriptor)
        if observed_files != manifest["files"]:
            raise ValueError("Assured artifact contents do not match the assured inventory")
        return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify an assured data artifact manifest"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--root", type=Path, required=True)
    build.add_argument("--chain-id", required=True)
    build.add_argument("--source-sha", required=True)
    build.add_argument("--coverage-fingerprint", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--chain-id", required=True)
    verify.add_argument("--source-sha", required=True)
    verify.add_argument("--coverage-fingerprint", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "build":
        path = build_assured_artifact_manifest(
            args.root,
            chain_id=args.chain_id,
            source_sha=args.source_sha,
            coverage_fingerprint=args.coverage_fingerprint,
        )
        print(path)
        return 0
    manifest = verify_assured_artifact_manifest(
        args.root,
        expected_chain_id=args.chain_id,
        expected_source_sha=args.source_sha,
        expected_coverage_fingerprint=args.coverage_fingerprint,
    )
    print(
        json.dumps(
            {
                "status": "verified",
                "chain_id": manifest["chain_id"],
                "source_sha": manifest["source_sha"],
                "coverage_fingerprint": manifest["coverage_fingerprint"],
                "data_tree_fingerprint": manifest["data_tree_fingerprint"],
                "file_count": manifest["file_count"],
                "bytes": manifest["bytes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
