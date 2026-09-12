"""Concrete local assurance transaction for one successor candidate.

The coordinator holds the candidate-generation mutation lock while invoking
this builder.  The builder nevertheless carries one exact public-root inode
through every independent scanner, publication inventory, manifest, and
installed-tree measurement so a pathname substitution cannot join evidence
from different trees.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import stat
import sys
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME,
    canonical_assured_artifact_manifest_bytes,
    verify_assured_artifact_manifest,
)
from nbadb.core.nba_api_provenance import normalize_nba_api_provider_authority
from nbadb.orchestrate.capture_session import PrivateGenerationIdentity
from nbadb.orchestrate.successor_assurance import (
    SuccessorAssuranceContractError,
    SuccessorTerminalAssuranceReportV7,
    SuccessorTransformOutputAttestation,
    emit_successor_assurance_manifest,
    validate_successor_terminal_assurance_report,
    verify_successor_assurance_manifest,
)
from nbadb.orchestrate.successor_coordinator import SuccessorAssuranceBuildInput
from nbadb.orchestrate.successor_inventory import InstalledPublicTreeInventory
from nbadb.orchestrate.successor_publication_inventory import (
    SuccessorPublicationInventoryEvidence,
)
from nbadb.orchestrate.successor_scan_evidence import (
    SuccessorFullPublicationScanResult,
)
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    SuccessorAssuranceIdentity,
    canonical_json_bytes,
    canonical_sha256,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ExactSuccessorAssuranceBuilder",
    "SuccessorAssuranceBuilderError",
    "validate_successor_baseline_controls",
]

_REPORT_NAME: Final = SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME
_CONTROL_NAMES: Final = frozenset({_REPORT_NAME, ASSURED_ARTIFACT_MANIFEST_NAME})
_MAX_CONTROL_BYTES: Final = 64 * 1024 * 1024
_ROLLOVER_RECEIPT_KIND: Final = "successor_inherited_control_rollover"
_ROLLOVER_RECEIPT_SCHEMA_VERSION: Final = 1
_ROLLOVER_CLOSURE_KIND: Final = "successor_inherited_control_rollover_closure"
_ROLLOVER_CLOSURE_SCHEMA_VERSION: Final = 1
_LINUX_RENAME_NOREPLACE: Final = 1
_DARWIN_RENAME_EXCL: Final = 0x00000004
_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW | _CLOEXEC | _NONBLOCK
)
_COOPERATIVE_RETURN_LOCKS_GUARD: Final = threading.Lock()
_COOPERATIVE_RETURN_LOCKS: Final[dict[tuple[int, ...], threading.RLock]] = {}

type _FullStatIdentity = tuple[int, int, int, int, int, int, int, int, int, int]
type _TreeStatAuthority = tuple[tuple[str, str, _FullStatIdentity], ...]


class SuccessorAssuranceBuilderError(RuntimeError):
    """Raised when one successor cannot be proven DATA-GREEN."""


class _Scanner(Protocol):
    def __call__(
        self,
        public_root: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> SuccessorFullPublicationScanResult: ...


class _PublicationInventory(Protocol):
    def __call__(
        self,
        public_root: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> SuccessorPublicationInventoryEvidence: ...


class _InstalledTree(Protocol):
    def __call__(
        self,
        public_root: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> InstalledPublicTreeInventory: ...


class _PrivateGenerationResolver(Protocol):
    def verify(
        self,
        *,
        transaction: Any,
        planning_request: Any,
        candidate_public_root: Path,
        expected_public_root_identity: tuple[int, int],
        expected_identity: PrivateGenerationIdentity,
    ) -> PrivateGenerationIdentity: ...


def _canonical_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        encoded = canonical_json_bytes(value)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, RecursionError, json.JSONDecodeError) as exc:
        raise SuccessorAssuranceBuilderError("assurance authority is not canonical JSON") from exc
    if not isinstance(decoded, dict):
        raise SuccessorAssuranceBuilderError("assurance authority must be an object")
    return cast("dict[str, Any]", decoded)


def _require_safe_chain_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or value[0] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
            for character in value
        )
    ):
        raise SuccessorAssuranceBuilderError("chain_id must be a path-free safe token")
    return value


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _full_stat_identity(value: os.stat_result) -> _FullStatIdentity:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_flags if hasattr(value, "st_flags") else 0,
    )


def _cooperative_return_lock(*identities: tuple[int, int]) -> threading.RLock:
    """Serialize assurance builders that cooperate through this module.

    The production composition additionally holds the generation store's
    cross-process candidate-mutation lease across this builder and its return.
    This in-process lock makes standalone builder calls linearizable with one
    another, but intentionally makes no claim about arbitrary same-UID writers
    that ignore both cooperative authorities.
    """

    key = tuple(value for identity in identities for value in identity)
    with _COOPERATIVE_RETURN_LOCKS_GUARD:
        return _COOPERATIVE_RETURN_LOCKS.setdefault(key, threading.RLock())


def _open_directory(path: Path, *, label: str) -> tuple[int, os.stat_result]:
    if not path.is_absolute() or not _NOFOLLOW:
        raise SuccessorAssuranceBuilderError(f"{label} must be absolute on POSIX O_NOFOLLOW")
    try:
        descriptor = os.open(path, _DIRECTORY_FLAGS)
        opened = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise SuccessorAssuranceBuilderError(f"{label} cannot be opened safely") from exc
    if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
        named.st_dev,
        named.st_ino,
    ):
        os.close(descriptor)
        raise SuccessorAssuranceBuilderError(f"{label} changed while opening")
    return descriptor, opened


def _require_directory_identity(
    path: Path,
    descriptor: int,
    expected: tuple[int, int],
    *,
    label: str,
) -> None:
    try:
        opened = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorAssuranceBuilderError(f"{label} changed while held") from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or (opened.st_dev, opened.st_ino) != expected
        or (named.st_dev, named.st_ino) != expected
    ):
        raise SuccessorAssuranceBuilderError(f"{label} differs from its admitted inode")


def _snapshot_directory_authority(
    path: Path,
    descriptor: int,
    expected: tuple[int, int],
    *,
    label: str,
    parent_descriptor: int | None = None,
    child_name: str | None = None,
) -> _FullStatIdentity:
    """Capture one directory through its held, path, and parent-name authorities."""

    try:
        opened = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        parent_named = (
            None
            if parent_descriptor is None or child_name is None
            else os.stat(child_name, dir_fd=parent_descriptor, follow_symlinks=False)
        )
    except OSError as exc:
        raise SuccessorAssuranceBuilderError(f"{label} changed while snapshotting") from exc
    opened_identity = _full_stat_identity(opened)
    if (
        not stat.S_ISDIR(opened.st_mode)
        or (opened.st_dev, opened.st_ino) != expected
        or _full_stat_identity(named) != opened_identity
        or (parent_named is not None and _full_stat_identity(parent_named) != opened_identity)
    ):
        raise SuccessorAssuranceBuilderError(f"{label} full authority differs")
    return opened_identity


def _snapshot_root_authorities(
    *,
    staging_root: Path,
    staging_descriptor: int,
    staging_identity: tuple[int, int],
    candidate_root: Path,
    candidate_descriptor: int,
    candidate_identity: tuple[int, int],
    public_root: Path,
    public_descriptor: int,
    public_identity: tuple[int, int],
) -> tuple[_FullStatIdentity, _FullStatIdentity, _FullStatIdentity]:
    return (
        _snapshot_directory_authority(
            staging_root,
            staging_descriptor,
            staging_identity,
            label="successor assurance staging root",
        ),
        _snapshot_directory_authority(
            candidate_root,
            candidate_descriptor,
            candidate_identity,
            label="successor candidate root",
            parent_descriptor=staging_descriptor,
            child_name=candidate_root.name,
        ),
        _snapshot_directory_authority(
            public_root,
            public_descriptor,
            public_identity,
            label="successor public root",
            parent_descriptor=candidate_descriptor,
            child_name="public",
        ),
    )


def _snapshot_public_tree_stat_authority(public_descriptor: int) -> _TreeStatAuthority:
    """Capture exact metadata for every public-tree entry through held descriptors."""

    observations: list[tuple[str, str, _FullStatIdentity]] = []
    child_flags = os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK

    def _visit(directory_descriptor: int, prefix: PurePosixPath | None) -> None:
        display = "." if prefix is None else prefix.as_posix()
        directory_before = os.fstat(directory_descriptor)
        if not stat.S_ISDIR(directory_before.st_mode):
            raise SuccessorAssuranceBuilderError(
                f"successor public tree directory is invalid: {display}"
            )
        before_identity = _full_stat_identity(directory_before)
        try:
            with os.scandir(directory_descriptor) as iterator:
                names = sorted(entry.name for entry in iterator)
        except OSError as exc:
            raise SuccessorAssuranceBuilderError(
                f"successor public tree cannot be snapshotted: {display}"
            ) from exc
        for name in names:
            relative = PurePosixPath(name) if prefix is None else prefix / name
            relative_name = relative.as_posix()
            descriptor = -1
            try:
                descriptor = os.open(
                    name,
                    child_flags,
                    dir_fd=directory_descriptor,
                )
                child_before = os.fstat(descriptor)
                named_before = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                child_identity = _full_stat_identity(child_before)
                if _full_stat_identity(named_before) != child_identity:
                    raise SuccessorAssuranceBuilderError(
                        f"successor public tree entry changed while opening: {relative_name}"
                    )
                if stat.S_ISDIR(child_before.st_mode):
                    _visit(descriptor, relative)
                    kind = "directory"
                elif stat.S_ISREG(child_before.st_mode):
                    kind = "file"
                else:
                    raise SuccessorAssuranceBuilderError(
                        f"successor public tree entry is not regular: {relative_name}"
                    )
                child_after = os.fstat(descriptor)
                named_after = os.stat(
                    name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if (
                    _full_stat_identity(child_after) != child_identity
                    or _full_stat_identity(named_after) != child_identity
                ):
                    raise SuccessorAssuranceBuilderError(
                        f"successor public tree entry changed while snapshotting: {relative_name}"
                    )
                observations.append((relative_name, kind, child_identity))
            except OSError as exc:
                raise SuccessorAssuranceBuilderError(
                    f"successor public tree entry cannot be snapshotted: {relative_name}"
                ) from exc
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        directory_after = os.fstat(directory_descriptor)
        if _full_stat_identity(directory_after) != before_identity:
            raise SuccessorAssuranceBuilderError(
                f"successor public tree directory changed while snapshotting: {display}"
            )
        observations.append((display, "directory", before_identity))

    _visit(public_descriptor, None)
    return tuple(sorted(observations, key=lambda item: item[0]))


def _read_optional_regular_full_authority(
    root_descriptor: int,
    name: str,
    *,
    label: str,
    required_mode: int | None = None,
    required_links: int | None = None,
) -> tuple[bytes, _FullStatIdentity] | None:
    try:
        before = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        before = None
    except OSError as exc:
        raise SuccessorAssuranceBuilderError(f"{label} cannot be snapshotted") from exc
    authority = _read_optional_regular_authority(
        root_descriptor,
        name,
        label=label,
        required_mode=required_mode,
        required_links=required_links,
    )
    if before is None:
        if authority is not None:
            raise SuccessorAssuranceBuilderError(f"{label} appeared while snapshotting")
        return None
    try:
        after = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorAssuranceBuilderError(f"{label} changed while snapshotting") from exc
    full_identity = _full_stat_identity(before)
    if (
        authority is None
        or authority[1] != (before.st_dev, before.st_ino)
        or _full_stat_identity(after) != full_identity
    ):
        raise SuccessorAssuranceBuilderError(f"{label} changed while snapshotting")
    return authority[0], full_identity


def _read_optional_regular_authority(
    root_descriptor: int,
    name: str,
    *,
    label: str,
    required_mode: int | None = None,
    required_links: int | None = None,
) -> tuple[bytes, tuple[int, int]] | None:
    flags = os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK
    try:
        descriptor = os.open(name, flags, dir_fd=root_descriptor)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SuccessorAssuranceBuilderError(f"{label} cannot be opened") from exc
    try:
        before = os.fstat(descriptor)
        named = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
            or before.st_size > _MAX_CONTROL_BYTES
            or (required_mode is not None and stat.S_IMODE(before.st_mode) != required_mode)
            or (required_links is not None and before.st_nlink != required_links)
            or (os.name == "posix" and before.st_uid != os.geteuid())
        ):
            raise SuccessorAssuranceBuilderError(f"{label} inode authority is invalid")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            total += len(chunk)
            if total > _MAX_CONTROL_BYTES:
                raise SuccessorAssuranceBuilderError(f"{label} is oversized")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        named_after = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
        if _stat_identity(before) != _stat_identity(after) or (after.st_dev, after.st_ino) != (
            named_after.st_dev,
            named_after.st_ino,
        ):
            raise SuccessorAssuranceBuilderError(f"{label} changed while reading")
        return b"".join(chunks), (after.st_dev, after.st_ino)
    finally:
        os.close(descriptor)


def _read_optional_control_authority(
    root_descriptor: int,
    name: str,
) -> tuple[bytes, tuple[int, int]] | None:
    return _read_optional_regular_authority(
        root_descriptor,
        name,
        label=f"successor control {name}",
    )


def _read_optional_control(root_descriptor: int, name: str) -> bytes | None:
    authority = _read_optional_control_authority(root_descriptor, name)
    return None if authority is None else authority[0]


def _rename_no_replace(
    source_descriptor: int,
    source_name: str,
    target_descriptor: int,
    target_name: str,
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename: Any = library.renameatx_np
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        arguments = (
            source_descriptor,
            os.fsencode(source_name),
            target_descriptor,
            os.fsencode(target_name),
            _DARWIN_RENAME_EXCL,
        )
    elif sys.platform.startswith("linux"):
        try:
            rename = library.renameat2
        except AttributeError as exc:
            raise SuccessorAssuranceBuilderError(
                "exact-inode retirement requires renameat2"
            ) from exc
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        arguments = (
            source_descriptor,
            os.fsencode(source_name),
            target_descriptor,
            os.fsencode(target_name),
            _LINUX_RENAME_NOREPLACE,
        )
    else:
        raise SuccessorAssuranceBuilderError(
            "exact-inode retirement requires macOS or Linux no-replace rename"
        )
    ctypes.set_errno(0)
    if rename(*arguments) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), source_name, target_name)


def _retirement_names(
    *,
    candidate_name: str,
    name: str,
    expected: bytes,
    expected_inode: tuple[int, int],
) -> tuple[str, str]:
    identity = hashlib.sha256()
    identity.update(b"nbadb.successor-assurance-retired-authority.v1\0")
    identity.update(candidate_name.encode("ascii"))
    identity.update(b"\0")
    identity.update(name.encode("ascii"))
    identity.update(b"\0")
    identity.update(hashlib.sha256(expected).digest())
    identity.update(b"\0")
    identity.update(str(expected_inode[0]).encode("ascii"))
    identity.update(b":")
    identity.update(str(expected_inode[1]).encode("ascii"))
    token = identity.hexdigest()
    return (
        f".successor-assurance-authority-backup-{token}",
        f".successor-assurance-authority-retired-{token}",
    )


def _retire_exact_authority(
    source_descriptor: int,
    retention_descriptor: int,
    *,
    candidate_name: str,
    name: str,
    expected: bytes,
    expected_inode: tuple[int, int],
    label: str,
    required_mode: int | None = None,
) -> None:
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
            dir_fd=source_descriptor,
        )
    except FileNotFoundError as exc:
        raise SuccessorAssuranceBuilderError(f"{label} disappeared before retirement") from exc
    except OSError as exc:
        raise SuccessorAssuranceBuilderError(f"{label} cannot be opened for retirement") from exc
    try:
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=source_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != expected_inode
            or (named.st_dev, named.st_ino) != expected_inode
            or opened.st_nlink < 1
            or opened.st_size != len(expected)
            or (required_mode is not None and stat.S_IMODE(opened.st_mode) != required_mode)
            or (os.name == "posix" and opened.st_uid != os.geteuid())
        ):
            raise SuccessorAssuranceBuilderError(f"{label} changed before retirement")
        if _read_staging_payload(descriptor, expected_bytes=len(expected)) != expected:
            raise SuccessorAssuranceBuilderError(f"{label} bytes changed before retirement")

        backup_name, retired_name = _retirement_names(
            candidate_name=candidate_name,
            name=name,
            expected=expected,
            expected_inode=expected_inode,
        )
        backup_authority = _read_optional_regular_authority(
            retention_descriptor,
            backup_name,
            label=f"{label} retirement backup",
        )
        if backup_authority is None:
            try:
                os.link(
                    name,
                    backup_name,
                    src_dir_fd=source_descriptor,
                    dst_dir_fd=retention_descriptor,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise SuccessorAssuranceBuilderError(
                    f"{label} retirement backup cannot be installed"
                ) from exc
            os.fsync(retention_descriptor)
            backup_authority = _read_optional_regular_authority(
                retention_descriptor,
                backup_name,
                label=f"{label} retirement backup",
            )
        if backup_authority != (expected, expected_inode):
            raise SuccessorAssuranceBuilderError(
                f"{label} retirement backup differs from admitted inode"
            )

        try:
            _rename_no_replace(
                source_descriptor,
                name,
                retention_descriptor,
                retired_name,
            )
        except OSError as exc:
            raise SuccessorAssuranceBuilderError(
                f"{label} cannot be retired without replacement"
            ) from exc
        os.fsync(source_descriptor)
        if retention_descriptor != source_descriptor:
            os.fsync(retention_descriptor)

        retired_authority = _read_optional_regular_authority(
            retention_descriptor,
            retired_name,
            label=f"{label} retired authority",
        )
        if retired_authority != (expected, expected_inode):
            if retired_authority is not None:
                try:
                    _rename_no_replace(
                        retention_descriptor,
                        retired_name,
                        source_descriptor,
                        name,
                    )
                except OSError as exc:
                    raise SuccessorAssuranceBuilderError(
                        f"{label} replacement could not be restored after retirement race"
                    ) from exc
                os.fsync(source_descriptor)
                if retention_descriptor != source_descriptor:
                    os.fsync(retention_descriptor)
            raise SuccessorAssuranceBuilderError(f"{label} changed or was replaced at retirement")

        try:
            os.stat(name, dir_fd=source_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise SuccessorAssuranceBuilderError(
                f"{label} replacement appeared after exact retirement"
            )
        retired = os.fstat(descriptor)
        if (
            not stat.S_ISREG(retired.st_mode)
            or (retired.st_dev, retired.st_ino) != expected_inode
            or retired.st_nlink != 2
            or retired.st_size != len(expected)
            or (required_mode is not None and stat.S_IMODE(retired.st_mode) != required_mode)
            or _read_staging_payload(descriptor, expected_bytes=len(expected)) != expected
        ):
            raise SuccessorAssuranceBuilderError(
                f"{label} admitted inode changed during retirement"
            )
    finally:
        os.close(descriptor)


def _retire_control_if_exact(
    public_descriptor: int,
    staging_descriptor: int,
    *,
    candidate_name: str,
    name: str,
    expected: bytes,
    expected_inode: tuple[int, int],
) -> None:
    _retire_exact_authority(
        public_descriptor,
        staging_descriptor,
        candidate_name=candidate_name,
        name=name,
        expected=expected,
        expected_inode=expected_inode,
        label=f"successor control {name}",
    )


def _control_staging_name(
    *,
    candidate_name: str,
    control_name: str,
    encoded: bytes,
) -> str:
    identity = hashlib.sha256()
    identity.update(b"nbadb.successor-assurance-control-staging.v1\0")
    identity.update(candidate_name.encode("utf-8"))
    identity.update(b"\0")
    identity.update(control_name.encode("ascii"))
    identity.update(b"\0")
    identity.update(hashlib.sha256(encoded).digest())
    return f".successor-assurance-{identity.hexdigest()}.tmp"


def _read_staging_payload(descriptor: int, *, expected_bytes: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    observed_bytes = 0
    while chunk := os.read(descriptor, 1024 * 1024):
        observed_bytes += len(chunk)
        if observed_bytes > expected_bytes:
            raise SuccessorAssuranceBuilderError("successor control staging payload is oversized")
        chunks.append(chunk)
    return b"".join(chunks)


def _write_staging_payload(descriptor: int, encoded: bytes) -> os.stat_result:
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    offset = 0
    while offset < len(encoded):
        written = os.write(descriptor, encoded[offset:])
        if written <= 0:
            raise OSError("assurance control write made no progress")
        offset += written
    os.fchmod(descriptor, 0o644)
    os.fsync(descriptor)
    observed = os.fstat(descriptor)
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o644
        or observed.st_size != len(encoded)
        or _read_staging_payload(descriptor, expected_bytes=len(encoded)) != encoded
    ):
        raise SuccessorAssuranceBuilderError("successor control staging bytes differ")
    return observed


def _require_control_inode(
    public_descriptor: int,
    control_name: str,
    *,
    expected_inode: tuple[int, int] | None,
    expected_links: int,
) -> os.stat_result:
    try:
        observed = os.stat(
            control_name,
            dir_fd=public_descriptor,
            follow_symlinks=False,
        )
    except OSError as exc:
        raise SuccessorAssuranceBuilderError(
            f"successor control {control_name} cannot be stated safely"
        ) from exc
    if (
        not stat.S_ISREG(observed.st_mode)
        or stat.S_IMODE(observed.st_mode) != 0o644
        or observed.st_nlink != expected_links
        or (os.name == "posix" and observed.st_uid != os.geteuid())
        or (expected_inode is not None and (observed.st_dev, observed.st_ino) != expected_inode)
    ):
        raise SuccessorAssuranceBuilderError(
            f"successor control {control_name} inode authority is invalid"
        )
    return observed


def _publish_control_no_replace(
    staging_descriptor: int,
    public_descriptor: int,
    *,
    candidate_name: str,
    control_name: str,
    encoded: bytes,
) -> None:
    if control_name not in _CONTROL_NAMES:
        raise SuccessorAssuranceBuilderError("successor control name is unsupported")
    temporary_name = _control_staging_name(
        candidate_name=candidate_name,
        control_name=control_name,
        encoded=encoded,
    )
    existing_control = _read_optional_control(public_descriptor, control_name)
    if existing_control is not None and existing_control != encoded:
        raise SuccessorAssuranceBuilderError(
            f"existing successor control {control_name} differs from exact evidence"
        )
    if existing_control == encoded:
        try:
            os.stat(
                temporary_name,
                dir_fd=staging_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            _require_control_inode(
                public_descriptor,
                control_name,
                expected_inode=None,
                expected_links=1,
            )
            os.fsync(public_descriptor)
            os.fsync(staging_descriptor)
            if _read_optional_control(public_descriptor, control_name) != encoded:
                raise SuccessorAssuranceBuilderError(
                    f"successor control {control_name} changed during resume"
                ) from None
            return
    descriptor = -1
    try:
        try:
            descriptor = os.open(
                temporary_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
                0o600,
                dir_fd=staging_descriptor,
            )
            source = _write_staging_payload(descriptor, encoded)
        except FileExistsError:
            descriptor = os.open(
                temporary_name,
                os.O_RDWR | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
                dir_fd=staging_descriptor,
            )
            source = os.fstat(descriptor)
            named_source = os.stat(
                temporary_name,
                dir_fd=staging_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(source.st_mode)
                or (source.st_dev, source.st_ino) != (named_source.st_dev, named_source.st_ino)
                or source.st_nlink not in {1, 2}
                or (os.name == "posix" and source.st_uid != os.geteuid())
            ):
                raise SuccessorAssuranceBuilderError(
                    "successor control staging entry is invalid or aliased"
                ) from None
            mode = stat.S_IMODE(source.st_mode)
            if mode == 0o600 and source.st_nlink == 1:
                source = _write_staging_payload(descriptor, encoded)
            elif (
                mode != 0o644
                or source.st_size != len(encoded)
                or _read_staging_payload(descriptor, expected_bytes=len(encoded)) != encoded
            ):
                raise SuccessorAssuranceBuilderError(
                    "successor control staging entry differs from exact evidence"
                ) from None

        named_source = os.stat(
            temporary_name,
            dir_fd=staging_descriptor,
            follow_symlinks=False,
        )
        source = os.fstat(descriptor)
        if (
            (source.st_dev, source.st_ino) != (named_source.st_dev, named_source.st_ino)
            or stat.S_IMODE(source.st_mode) != 0o644
            or source.st_size != len(encoded)
        ):
            raise SuccessorAssuranceBuilderError(
                "successor control staging entry changed before publication"
            )

        existing_control = _read_optional_control(public_descriptor, control_name)
        if existing_control is None:
            if source.st_nlink != 1:
                raise SuccessorAssuranceBuilderError(
                    "successor control staging link count lacks its canonical target"
                )
            try:
                os.link(
                    temporary_name,
                    control_name,
                    src_dir_fd=staging_descriptor,
                    dst_dir_fd=public_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise SuccessorAssuranceBuilderError(
                    f"successor control {control_name} appeared during publication"
                ) from exc
            os.fsync(public_descriptor)
        elif existing_control != encoded:
            raise SuccessorAssuranceBuilderError(
                f"existing successor control {control_name} differs from exact evidence"
            )

        published_stat = _require_control_inode(
            public_descriptor,
            control_name,
            expected_inode=(source.st_dev, source.st_ino),
            expected_links=2,
        )
        source = os.fstat(descriptor)
        if (
            (published_stat.st_dev, published_stat.st_ino) != (source.st_dev, source.st_ino)
            or source.st_nlink != 2
            or _read_optional_control(public_descriptor, control_name) != encoded
        ):
            raise SuccessorAssuranceBuilderError(
                f"published successor control {control_name} differs from staging authority"
            )
        named_source = os.stat(
            temporary_name,
            dir_fd=staging_descriptor,
            follow_symlinks=False,
        )
        if (named_source.st_dev, named_source.st_ino) != (source.st_dev, source.st_ino):
            raise SuccessorAssuranceBuilderError(
                "successor control staging entry changed before cleanup"
            )
        os.unlink(temporary_name, dir_fd=staging_descriptor)
        os.fsync(staging_descriptor)
        _require_control_inode(
            public_descriptor,
            control_name,
            expected_inode=(source.st_dev, source.st_ino),
            expected_links=1,
        )
        if _read_optional_control(public_descriptor, control_name) != encoded:
            raise SuccessorAssuranceBuilderError(
                f"successor control {control_name} changed after staging cleanup"
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _without_controls(inventory: InstalledPublicTreeInventory) -> InstalledPublicTreeInventory:
    files = tuple(item for item in inventory.files if item[0] not in _CONTROL_NAMES)
    return InstalledPublicTreeInventory(files=files, directories=inventory.directories)


def _with_exact_controls(
    inventory: InstalledPublicTreeInventory,
    *,
    report_bytes: bytes,
    manifest_bytes: bytes,
) -> InstalledPublicTreeInventory:
    controls = (
        (_REPORT_NAME, len(report_bytes), hashlib.sha256(report_bytes).hexdigest()),
        (
            ASSURED_ARTIFACT_MANIFEST_NAME,
            len(manifest_bytes),
            hashlib.sha256(manifest_bytes).hexdigest(),
        ),
    )
    return InstalledPublicTreeInventory(
        files=tuple(sorted((*inventory.files, *controls), key=lambda item: item[0])),
        directories=inventory.directories,
    )


def _with_control_observations(
    inventory: InstalledPublicTreeInventory,
    controls: tuple[tuple[str, int, str], ...],
) -> InstalledPublicTreeInventory:
    if any(path in {item[0] for item in inventory.files} for path, _size, _sha in controls):
        raise SuccessorAssuranceBuilderError("rollover control inventory overlaps candidate data")
    return InstalledPublicTreeInventory(
        files=tuple(sorted((*inventory.files, *controls), key=lambda item: item[0])),
        directories=inventory.directories,
    )


def _strict_canonical_object(encoded: bytes, *, label: str) -> dict[str, Any]:
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
        raise SuccessorAssuranceBuilderError(f"{label} is not strict JSON") from exc
    if not isinstance(decoded, dict):
        raise SuccessorAssuranceBuilderError(f"{label} must be an object")
    return cast("dict[str, Any]", decoded)


def _rollover_receipt_name(*, candidate_name: str, generation_identity_sha256: str) -> str:
    identity = hashlib.sha256()
    identity.update(b"nbadb.successor-assurance-rollover-receipt.v1\0")
    identity.update(candidate_name.encode("ascii"))
    identity.update(b"\0")
    identity.update(generation_identity_sha256.encode("ascii"))
    return f".successor-assurance-rollover-{identity.hexdigest()}.json"


def _rollover_closure_name(*, candidate_name: str, generation_identity_sha256: str) -> str:
    identity = hashlib.sha256()
    identity.update(b"nbadb.successor-assurance-rollover-closure.v1\0")
    identity.update(candidate_name.encode("ascii"))
    identity.update(b"\0")
    identity.update(generation_identity_sha256.encode("ascii"))
    return f".successor-assurance-execution-closure-{identity.hexdigest()}.json"


def _rollover_closure_bytes(
    *,
    build_input: SuccessorAssuranceBuildInput,
    candidate_name: str,
    candidate_identity: tuple[int, int],
    public_identity: tuple[int, int],
    data_tree: InstalledPublicTreeInventory,
    report_bytes: bytes,
    manifest_bytes: bytes,
    final_tree: InstalledPublicTreeInventory,
    inherited_controls: tuple[tuple[str, int, str], ...],
) -> bytes:
    expected_final_tree = _with_exact_controls(
        data_tree,
        report_bytes=report_bytes,
        manifest_bytes=manifest_bytes,
    )
    if final_tree != expected_final_tree:
        raise SuccessorAssuranceBuilderError(
            "rollover closure final tree differs from its data and controls"
        )
    reconstructed_execution = _with_control_observations(data_tree, inherited_controls)
    if (
        reconstructed_execution.installed_public_tree_sha256
        != build_input.execution_installed_public_tree_sha256
    ):
        raise SuccessorAssuranceBuilderError(
            "rollover closure does not reconstruct completed execution authority"
        )
    return (
        canonical_json_bytes(
            {
                "schema_version": _ROLLOVER_CLOSURE_SCHEMA_VERSION,
                "kind": _ROLLOVER_CLOSURE_KIND,
                "candidate_name": candidate_name,
                "generation_identity_sha256": (build_input.transaction.generation_identity_sha256),
                "baseline_identity_sha256": build_input.baseline.identity_sha256,
                "execution_installed_public_tree_sha256": (
                    build_input.execution_installed_public_tree_sha256
                ),
                "data_installed_public_tree_sha256": (data_tree.installed_public_tree_sha256),
                "final_installed_public_tree_sha256": (final_tree.installed_public_tree_sha256),
                "candidate_root": {
                    "device": candidate_identity[0],
                    "inode": candidate_identity[1],
                },
                "public_root": {
                    "device": public_identity[0],
                    "inode": public_identity[1],
                },
                "inherited_controls": [
                    {"name": name, "bytes": byte_count, "sha256": sha256}
                    for name, byte_count, sha256 in inherited_controls
                ],
                "successor_controls": [
                    {
                        "name": name,
                        "bytes": len(encoded),
                        "sha256": hashlib.sha256(encoded).hexdigest(),
                    }
                    for name, encoded in sorted(
                        (
                            (_REPORT_NAME, report_bytes),
                            (ASSURED_ARTIFACT_MANIFEST_NAME, manifest_bytes),
                        )
                    )
                ],
            }
        )
        + b"\n"
    )


def _validate_rollover_closure(
    encoded: bytes,
    *,
    build_input: SuccessorAssuranceBuildInput,
    candidate_name: str,
    candidate_identity: tuple[int, int],
    public_identity: tuple[int, int],
    data_tree: InstalledPublicTreeInventory,
    report_bytes: bytes,
    manifest_bytes: bytes,
    final_tree: InstalledPublicTreeInventory,
) -> None:
    payload = _strict_canonical_object(encoded, label="rollover closure")
    if encoded != canonical_json_bytes(payload) + b"\n":
        raise SuccessorAssuranceBuilderError("rollover closure is not canonical")
    raw_inherited_controls = payload.get("inherited_controls")
    if not isinstance(raw_inherited_controls, list):
        raise SuccessorAssuranceBuilderError("rollover closure inherited controls are invalid")
    inherited_controls: list[tuple[str, int, str]] = []
    for raw in raw_inherited_controls:
        if not isinstance(raw, dict) or set(raw) != {"name", "bytes", "sha256"}:
            raise SuccessorAssuranceBuilderError("rollover closure inherited controls are invalid")
        name = raw["name"]
        byte_count = raw["bytes"]
        sha256 = raw["sha256"]
        if (
            not isinstance(name, str)
            or name not in _CONTROL_NAMES
            or type(byte_count) is not int
            or byte_count < 1
            or byte_count > _MAX_CONTROL_BYTES
            or not isinstance(sha256, str)
        ):
            raise SuccessorAssuranceBuilderError("rollover closure inherited controls are invalid")
        inherited_controls.append((name, byte_count, sha256))
    normalized_inherited_controls = tuple(sorted(inherited_controls, key=lambda item: item[0]))
    expected = _rollover_closure_bytes(
        build_input=build_input,
        candidate_name=candidate_name,
        candidate_identity=candidate_identity,
        public_identity=public_identity,
        data_tree=data_tree,
        report_bytes=report_bytes,
        manifest_bytes=manifest_bytes,
        final_tree=final_tree,
        inherited_controls=normalized_inherited_controls,
    )
    if encoded != expected:
        raise SuccessorAssuranceBuilderError(
            "rollover closure differs from the exact execution and successor controls"
        )


def _read_optional_rollover_receipt(
    staging_descriptor: int,
    name: str,
) -> tuple[bytes, tuple[int, int]] | None:
    return _read_optional_regular_authority(
        staging_descriptor,
        name,
        label="rollover receipt",
        required_mode=0o600,
        required_links=1,
    )


def _require_rollover_receipt_absent_stably(
    staging_descriptor: int,
    name: str,
) -> None:
    """Prove absence across an unchanged staging-directory observation."""

    before = os.fstat(staging_descriptor)
    if _read_optional_rollover_receipt(staging_descriptor, name) is not None:
        raise SuccessorAssuranceBuilderError("rollover receipt reappeared")
    after = os.fstat(staging_descriptor)
    if _full_stat_identity(after) != _full_stat_identity(before):
        raise SuccessorAssuranceBuilderError("rollover receipt absence was not stable")


def _read_optional_rollover_closure(
    staging_descriptor: int,
    name: str,
) -> tuple[bytes, tuple[int, int]] | None:
    return _read_optional_regular_authority(
        staging_descriptor,
        name,
        label="rollover closure",
        required_mode=0o600,
        required_links=1,
    )


def _read_optional_rollover_closure_full(
    staging_descriptor: int,
    name: str,
) -> tuple[bytes, _FullStatIdentity] | None:
    return _read_optional_regular_full_authority(
        staging_descriptor,
        name,
        label="rollover closure",
        required_mode=0o600,
        required_links=1,
    )


def _publish_rollover_receipt_no_replace(
    staging_descriptor: int,
    *,
    name: str,
    encoded: bytes,
) -> bytes:
    existing_authority = _read_optional_rollover_receipt(staging_descriptor, name)
    if existing_authority is not None:
        if existing_authority[0] != encoded:
            raise SuccessorAssuranceBuilderError("existing rollover receipt differs")
        return existing_authority[0]
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
            0o600,
            dir_fd=staging_descriptor,
        )
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("rollover receipt write made no progress")
            view = view[written:]
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_size != len(encoded)
            or observed.st_nlink != 1
        ):
            raise SuccessorAssuranceBuilderError("rollover receipt was not installed safely")
        os.fsync(staging_descriptor)
    except FileExistsError as exc:
        raise SuccessorAssuranceBuilderError(
            "rollover receipt appeared during publication"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    observed_authority = _read_optional_rollover_receipt(staging_descriptor, name)
    if observed_authority is None or observed_authority[0] != encoded:
        raise SuccessorAssuranceBuilderError("rollover receipt changed after publication")
    return encoded


def _publish_rollover_closure_no_replace(
    staging_descriptor: int,
    *,
    name: str,
    encoded: bytes,
) -> bytes:
    existing_authority = _read_optional_rollover_closure(staging_descriptor, name)
    if existing_authority is not None:
        if existing_authority[0] != encoded:
            raise SuccessorAssuranceBuilderError("existing rollover closure differs")
        return existing_authority[0]
    descriptor = -1
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
            0o600,
            dir_fd=staging_descriptor,
        )
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("rollover closure write made no progress")
            view = view[written:]
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_size != len(encoded)
            or observed.st_nlink != 1
        ):
            raise SuccessorAssuranceBuilderError("rollover closure was not installed safely")
        os.fsync(staging_descriptor)
    except FileExistsError as exc:
        raise SuccessorAssuranceBuilderError(
            "rollover closure appeared during publication"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    observed_authority = _read_optional_rollover_closure(staging_descriptor, name)
    if observed_authority is None or observed_authority[0] != encoded:
        raise SuccessorAssuranceBuilderError("rollover closure changed after publication")
    return encoded


def _validate_inherited_report(
    encoded: bytes,
    *,
    baseline: BaselineAssuranceIdentity,
) -> int:
    if hashlib.sha256(encoded).hexdigest() != baseline.terminal_assurance_report_sha256:
        raise SuccessorAssuranceBuilderError("inherited terminal report differs from baseline")
    payload = _strict_canonical_object(encoded, label="inherited terminal report")
    schema_version = payload.get("schema_version")
    if schema_version == 7:
        report = validate_successor_terminal_assurance_report(encoded)
        expected = {
            "chain_id": baseline.chain_id,
            "source_sha": baseline.source_sha,
            "coverage_fingerprint": baseline.coverage_fingerprint,
            "checkpoint_database_sha256": baseline.checkpoint_database_sha256,
            "checkpoint_report_sha256": baseline.checkpoint_report_sha256,
            "contract_blocked_evidence_sha256": baseline.contract_blocked_evidence_sha256,
            "provider_authority_sha256": baseline.provider_authority_sha256,
        }
        observed = {
            "chain_id": report.chain_id,
            "source_sha": report.source_sha,
            "coverage_fingerprint": report.coverage_fingerprint,
            "checkpoint_database_sha256": report.database_evidence.duckdb_sha256,
            "checkpoint_report_sha256": report.content_sha256,
            "contract_blocked_evidence_sha256": report.contract_blocked_evidence_sha256,
            "provider_authority_sha256": report.provider_authority_sha256,
        }
    elif schema_version == 3:
        canonical = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if encoded != canonical:
            raise SuccessorAssuranceBuilderError("inherited terminal report is not canonical")
        expected_keys = {
            "schema_version",
            "chain_id",
            "source_sha",
            "coverage_fingerprint",
            "checkpoint_artifact_name",
            "checkpoint_generation",
            "checkpoint_database_sha256",
            "checkpoint_report_sha256",
            "checkpoint_report",
            "contract_blocked_lane_count",
            "contract_blocked_evidence",
            "contract_blocked_evidence_sha256",
            "provider_authority",
            "provider_authority_sha256",
        }
        if set(payload) != expected_keys:
            raise SuccessorAssuranceBuilderError(
                "inherited schema-v3 terminal report fields are invalid"
            )
        checkpoint_report = payload["checkpoint_report"]
        if not isinstance(checkpoint_report, dict):
            raise SuccessorAssuranceBuilderError("inherited schema-v3 checkpoint report is invalid")
        checkpoint_generation = payload["checkpoint_generation"]
        if type(checkpoint_generation) is not int or checkpoint_generation < 1:
            raise SuccessorAssuranceBuilderError(
                "inherited schema-v3 checkpoint generation is invalid"
            )
        checkpoint_bytes = json.dumps(
            checkpoint_report,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if hashlib.sha256(checkpoint_bytes).hexdigest() != payload["checkpoint_report_sha256"]:
            raise SuccessorAssuranceBuilderError(
                "inherited schema-v3 checkpoint report digest differs"
            )
        try:
            normalized_provider = normalize_nba_api_provider_authority(
                payload["provider_authority"]
            )
            from nbadb.orchestrate.full_extraction_control import (
                _validated_checkpoint_contract_blocked_evidence,
            )

            blocked_rows, blocked_digest = _validated_checkpoint_contract_blocked_evidence(
                checkpoint_report
            )
        except (TypeError, ValueError) as exc:
            raise SuccessorAssuranceBuilderError(
                "inherited schema-v3 checkpoint authority is invalid"
            ) from exc
        if (
            normalized_provider.get("authority_sha256") != payload["provider_authority_sha256"]
            or payload["contract_blocked_lane_count"] != len(blocked_rows)
            or payload["contract_blocked_evidence"]
            != checkpoint_report.get("contract_blocked_evidence")
            or payload["contract_blocked_evidence_sha256"] != blocked_digest
        ):
            raise SuccessorAssuranceBuilderError(
                "inherited schema-v3 report authority does not close"
            )
        checkpoint_bindings = {
            "chain_id": payload["chain_id"],
            "source_sha": payload["source_sha"],
            "coverage_fingerprint": payload["coverage_fingerprint"],
            "artifact_name": payload["checkpoint_artifact_name"],
            "checkpoint_generation": checkpoint_generation,
            "database_sha256": payload["checkpoint_database_sha256"],
            "contract_blocked_lane_count": len(blocked_rows),
            "contract_blocked_evidence": payload["contract_blocked_evidence"],
            "contract_blocked_evidence_sha256": blocked_digest,
            "provider_authority": normalized_provider,
            "provider_authority_sha256": normalized_provider["authority_sha256"],
        }
        if any(checkpoint_report.get(key) != value for key, value in checkpoint_bindings.items()):
            raise SuccessorAssuranceBuilderError("inherited schema-v3 checkpoint bindings differ")
        if (
            payload["checkpoint_artifact_name"]
            != f"full-extraction-checkpoint-{payload['chain_id']}-iter-{checkpoint_generation}"
            or checkpoint_report.get("terminal_ready") is not True
            or checkpoint_report.get("active_lane_count") != 0
        ):
            raise SuccessorAssuranceBuilderError(
                "inherited schema-v3 checkpoint is not terminal-ready"
            )
        run_id = checkpoint_report.get("run_id")
        lane_ids = checkpoint_report.get("included_lane_ids")
        run_ids = checkpoint_report.get("included_run_ids")
        coverage_hashes = checkpoint_report.get("included_lane_coverage_hashes")
        if (
            not isinstance(run_id, str)
            or not run_id.isdecimal()
            or int(run_id) < 1
            or not isinstance(lane_ids, list)
            or not lane_ids
            or any(not isinstance(lane_id, str) or not lane_id for lane_id in lane_ids)
            or len(set(lane_ids)) != len(lane_ids)
            or not isinstance(run_ids, list)
            or not run_ids
            or any(
                not isinstance(included_run_id, str)
                or not included_run_id.isdecimal()
                or int(included_run_id) < 1
                for included_run_id in run_ids
            )
            or len(set(run_ids)) != len(run_ids)
            or run_id not in run_ids
            or not isinstance(coverage_hashes, dict)
            or set(coverage_hashes) != set(lane_ids)
            or any(
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                for digest in coverage_hashes.values()
            )
        ):
            raise SuccessorAssuranceBuilderError(
                "inherited schema-v3 checkpoint inventory is invalid"
            )
        complete_lane_count = checkpoint_report.get("complete_lane_count")
        manifest_lane_count = checkpoint_report.get("manifest_lane_count")
        if (
            type(complete_lane_count) is not int
            or complete_lane_count != len(lane_ids)
            or type(manifest_lane_count) is not int
            or manifest_lane_count != complete_lane_count + len(blocked_rows)
            or checkpoint_report.get("skipped_lane_count") != 0
            or any(
                not isinstance(checkpoint_report.get(field), (list, dict))
                or bool(checkpoint_report.get(field))
                for field in (
                    "missing_lane_ids",
                    "skipped_complete_lane_ids",
                    "current_lane_attestation_failures",
                    "workload_contract_errors",
                )
            )
        ):
            raise SuccessorAssuranceBuilderError(
                "inherited schema-v3 checkpoint closure is incomplete"
            )
        expected = {
            "chain_id": baseline.chain_id,
            "source_sha": baseline.source_sha,
            "coverage_fingerprint": baseline.coverage_fingerprint,
            "checkpoint_database_sha256": baseline.checkpoint_database_sha256,
            "checkpoint_report_sha256": baseline.checkpoint_report_sha256,
            "contract_blocked_evidence_sha256": baseline.contract_blocked_evidence_sha256,
            "provider_authority_sha256": baseline.provider_authority_sha256,
        }
        observed = {field: payload.get(field) for field in expected}
    else:
        raise SuccessorAssuranceBuilderError("inherited terminal report schema is unsupported")
    if observed != expected:
        raise SuccessorAssuranceBuilderError("inherited terminal report authority differs")
    return cast("int", schema_version)


def _retire_rollover_receipt_if_exact(
    staging_descriptor: int,
    *,
    candidate_name: str,
    name: str,
    expected: bytes,
    expected_inode: tuple[int, int],
) -> None:
    _retire_exact_authority(
        staging_descriptor,
        staging_descriptor,
        candidate_name=candidate_name,
        name=name,
        expected=expected,
        expected_inode=expected_inode,
        label="rollover receipt",
        required_mode=0o600,
    )


def _validate_inherited_manifest(
    encoded: bytes,
    *,
    report_bytes: bytes,
    baseline: BaselineAssuranceIdentity,
) -> None:
    if hashlib.sha256(encoded).hexdigest() != baseline.assured_manifest_sha256:
        raise SuccessorAssuranceBuilderError("inherited assured manifest differs from baseline")
    payload = _strict_canonical_object(encoded, label="inherited assured manifest")
    canonical = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if encoded != canonical:
        raise SuccessorAssuranceBuilderError("inherited assured manifest is not canonical")
    expected_keys = {
        "schema_version",
        "chain_id",
        "source_sha",
        "coverage_fingerprint",
        "data_tree_fingerprint",
        "file_count",
        "bytes",
        "files",
    }
    if set(payload) != expected_keys or payload["schema_version"] != 1:
        raise SuccessorAssuranceBuilderError("inherited assured manifest fields are invalid")
    if (
        payload["chain_id"] != baseline.chain_id
        or payload["source_sha"] != baseline.source_sha
        or payload["coverage_fingerprint"] != baseline.coverage_fingerprint
        or payload["data_tree_fingerprint"] != baseline.data_tree_fingerprint
    ):
        raise SuccessorAssuranceBuilderError("inherited assured manifest authority differs")
    raw_files = payload["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise SuccessorAssuranceBuilderError("inherited assured manifest files are invalid")
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict) or set(raw) != {"path", "bytes", "sha256"}:
            raise SuccessorAssuranceBuilderError("inherited assured manifest file entry is invalid")
        path = raw["path"]
        byte_count = raw["bytes"]
        sha256 = raw["sha256"]
        if not isinstance(path, str):
            raise SuccessorAssuranceBuilderError("inherited assured manifest file path is invalid")
        pure_path = PurePosixPath(path)
        if (
            pure_path.is_absolute()
            or not pure_path.parts
            or any(part in {"", ".", ".."} for part in pure_path.parts)
            or pure_path.as_posix() != path
            or path in seen
            or path in {ASSURED_ARTIFACT_MANIFEST_NAME, "dataset-metadata.json"}
        ):
            raise SuccessorAssuranceBuilderError("inherited assured manifest file path is invalid")
        if (
            type(byte_count) is not int
            or byte_count < 0
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise SuccessorAssuranceBuilderError(
                "inherited assured manifest file authority is invalid"
            )
        seen.add(path)
        normalized.append({"path": path, "bytes": byte_count, "sha256": sha256})
    if normalized != sorted(normalized, key=lambda item: cast("str", item["path"])):
        raise SuccessorAssuranceBuilderError("inherited assured manifest files are not sorted")
    if (
        payload["file_count"] != len(normalized)
        or payload["bytes"] != sum(cast("int", item["bytes"]) for item in normalized)
        or hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        != payload["data_tree_fingerprint"]
    ):
        raise SuccessorAssuranceBuilderError(
            "inherited assured manifest aggregate authority is invalid"
        )
    expected_report = {
        "path": _REPORT_NAME,
        "bytes": len(report_bytes),
        "sha256": hashlib.sha256(report_bytes).hexdigest(),
    }
    if [item for item in normalized if item["path"] == _REPORT_NAME] != [expected_report]:
        raise SuccessorAssuranceBuilderError(
            "inherited assured manifest does not bind its exact terminal report"
        )


def validate_successor_baseline_controls(
    *,
    baseline: BaselineAssuranceIdentity,
    terminal_assurance_report_bytes: bytes,
    assured_artifact_manifest_bytes: bytes,
) -> None:
    """Validate immutable baseline control bytes against one admitted identity.

    Callers retain responsibility for descriptor-safe reads.  This pure boundary
    returns no parsed authority and accepts neither paths nor mutable mappings.
    """
    if not isinstance(baseline, BaselineAssuranceIdentity):
        raise SuccessorAssuranceBuilderError("baseline must be fully validated")
    if not isinstance(terminal_assurance_report_bytes, bytes) or not isinstance(
        assured_artifact_manifest_bytes, bytes
    ):
        raise SuccessorAssuranceBuilderError("baseline controls must be immutable bytes")

    _validate_inherited_report(
        terminal_assurance_report_bytes,
        baseline=baseline,
    )
    _validate_inherited_manifest(
        assured_artifact_manifest_bytes,
        report_bytes=terminal_assurance_report_bytes,
        baseline=baseline,
    )


def _rollover_receipt_bytes(
    *,
    build_input: SuccessorAssuranceBuildInput,
    candidate_name: str,
    candidate_identity: tuple[int, int],
    public_identity: tuple[int, int],
    data_tree: InstalledPublicTreeInventory,
    report_bytes: bytes,
    manifest_bytes: bytes,
) -> bytes:
    controls = sorted(
        (
            {
                "name": _REPORT_NAME,
                "bytes": len(report_bytes),
                "sha256": hashlib.sha256(report_bytes).hexdigest(),
            },
            {
                "name": ASSURED_ARTIFACT_MANIFEST_NAME,
                "bytes": len(manifest_bytes),
                "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            },
        ),
        key=lambda item: item["name"],
    )
    return (
        canonical_json_bytes(
            {
                "schema_version": _ROLLOVER_RECEIPT_SCHEMA_VERSION,
                "kind": _ROLLOVER_RECEIPT_KIND,
                "candidate_name": candidate_name,
                "generation_identity_sha256": build_input.transaction.generation_identity_sha256,
                "baseline_identity_sha256": build_input.baseline.identity_sha256,
                "execution_installed_public_tree_sha256": (
                    build_input.execution_installed_public_tree_sha256
                ),
                "data_installed_public_tree_sha256": data_tree.installed_public_tree_sha256,
                "candidate_root": {
                    "device": candidate_identity[0],
                    "inode": candidate_identity[1],
                },
                "public_root": {
                    "device": public_identity[0],
                    "inode": public_identity[1],
                },
                "controls": controls,
            }
        )
        + b"\n"
    )


def _validate_rollover_receipt(
    encoded: bytes,
    *,
    build_input: SuccessorAssuranceBuildInput,
    candidate_name: str,
    candidate_identity: tuple[int, int],
    public_identity: tuple[int, int],
    data_tree: InstalledPublicTreeInventory,
) -> tuple[tuple[str, int, str], ...]:
    payload = _strict_canonical_object(encoded, label="rollover receipt")
    if encoded != canonical_json_bytes(payload) + b"\n":
        raise SuccessorAssuranceBuilderError("rollover receipt is not canonical")
    expected_keys = {
        "schema_version",
        "kind",
        "candidate_name",
        "generation_identity_sha256",
        "baseline_identity_sha256",
        "execution_installed_public_tree_sha256",
        "data_installed_public_tree_sha256",
        "candidate_root",
        "public_root",
        "controls",
    }
    if set(payload) != expected_keys:
        raise SuccessorAssuranceBuilderError("rollover receipt fields are invalid")
    expected_scalars: dict[str, object] = {
        "schema_version": _ROLLOVER_RECEIPT_SCHEMA_VERSION,
        "kind": _ROLLOVER_RECEIPT_KIND,
        "candidate_name": candidate_name,
        "generation_identity_sha256": build_input.transaction.generation_identity_sha256,
        "baseline_identity_sha256": build_input.baseline.identity_sha256,
        "execution_installed_public_tree_sha256": (
            build_input.execution_installed_public_tree_sha256
        ),
        "data_installed_public_tree_sha256": data_tree.installed_public_tree_sha256,
        "candidate_root": {"device": candidate_identity[0], "inode": candidate_identity[1]},
        "public_root": {"device": public_identity[0], "inode": public_identity[1]},
    }
    if any(payload[field] != value for field, value in expected_scalars.items()):
        raise SuccessorAssuranceBuilderError("rollover receipt authority differs")
    raw_controls = payload["controls"]
    if not isinstance(raw_controls, list) or len(raw_controls) != 2:
        raise SuccessorAssuranceBuilderError("rollover receipt control inventory is invalid")
    controls: list[tuple[str, int, str]] = []
    expected_hashes = {
        _REPORT_NAME: build_input.baseline.terminal_assurance_report_sha256,
        ASSURED_ARTIFACT_MANIFEST_NAME: build_input.baseline.assured_manifest_sha256,
    }
    for raw in raw_controls:
        if not isinstance(raw, dict) or set(raw) != {"name", "bytes", "sha256"}:
            raise SuccessorAssuranceBuilderError("rollover receipt control entry is invalid")
        name = raw["name"]
        byte_count = raw["bytes"]
        sha256 = raw["sha256"]
        if (
            not isinstance(name, str)
            or name not in expected_hashes
            or type(byte_count) is not int
            or byte_count < 1
            or byte_count > _MAX_CONTROL_BYTES
            or sha256 != expected_hashes[name]
        ):
            raise SuccessorAssuranceBuilderError("rollover receipt control authority differs")
        controls.append((name, byte_count, cast("str", sha256)))
    normalized = tuple(sorted(controls, key=lambda item: item[0]))
    if tuple(item["name"] for item in raw_controls) != tuple(item[0] for item in normalized):
        raise SuccessorAssuranceBuilderError("rollover receipt controls are not canonical")
    reconstructed = _with_control_observations(data_tree, normalized)
    if (
        reconstructed.installed_public_tree_sha256
        != build_input.execution_installed_public_tree_sha256
    ):
        raise SuccessorAssuranceBuilderError(
            "rollover receipt does not reconstruct completed execution authority"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class ExactSuccessorAssuranceBuilder:
    """Idempotently build schema-v7 assurance for one exact candidate."""

    chain_id: str
    contract_blocked_evidence: Mapping[str, Any]
    provider_authority: Mapping[str, Any]
    scanner: _Scanner
    inventory: _PublicationInventory
    installed_tree: _InstalledTree
    private_generation_resolver: _PrivateGenerationResolver

    def __post_init__(self) -> None:
        object.__setattr__(self, "chain_id", _require_safe_chain_id(self.chain_id))
        object.__setattr__(
            self,
            "contract_blocked_evidence",
            _canonical_copy(self.contract_blocked_evidence),
        )
        try:
            normalized_provider = normalize_nba_api_provider_authority(self.provider_authority)
        except ValueError as exc:
            raise SuccessorAssuranceBuilderError("provider authority is invalid") from exc
        object.__setattr__(self, "provider_authority", _canonical_copy(normalized_provider))
        if (
            not callable(self.scanner)
            or not callable(self.inventory)
            or not callable(self.installed_tree)
            or not callable(getattr(self.private_generation_resolver, "verify", None))
        ):
            raise SuccessorAssuranceBuilderError("assurance evidence dependencies must be callable")

    def _validate_inherited_authorities(self, build_input: SuccessorAssuranceBuildInput) -> None:
        from nbadb.orchestrate.full_extraction_control import (
            _validated_checkpoint_contract_blocked_evidence,
        )

        baseline = build_input.baseline
        private = build_input.update_private_generation
        provider_digest = self.provider_authority.get("authority_sha256")
        if (
            provider_digest != baseline.provider_authority_sha256
            or provider_digest != private.provider_authority_sha256
        ):
            raise SuccessorAssuranceBuilderError(
                "provider authority differs from baseline or private generation"
            )
        try:
            _rows, blocked_digest = _validated_checkpoint_contract_blocked_evidence(
                {
                    "contract_blocked_lane_count": len(
                        self.contract_blocked_evidence.get("contract_blocked_lanes", [])
                    ),
                    "contract_blocked_evidence": self.contract_blocked_evidence,
                    "contract_blocked_evidence_sha256": canonical_sha256(
                        self.contract_blocked_evidence
                    ),
                }
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise SuccessorAssuranceBuilderError("contract-blocked evidence is invalid") from exc
        if blocked_digest != baseline.contract_blocked_evidence_sha256:
            raise SuccessorAssuranceBuilderError(
                "contract-blocked evidence differs from the baseline"
            )
        if (
            private.chain_id != self.chain_id
            or private.semantic_source_sha != build_input.transaction.intent.source_sha
        ):
            raise SuccessorAssuranceBuilderError(
                "successor chain or semantic source differs from private authority"
            )

    def _measure(
        self,
        public_root: Path,
        expected_root_identity: tuple[int, int],
    ) -> InstalledPublicTreeInventory:
        result = self.installed_tree(
            public_root,
            expected_root_identity=expected_root_identity,
        )
        if not isinstance(result, InstalledPublicTreeInventory):
            raise SuccessorAssuranceBuilderError("installed tree dependency returned invalid data")
        return result

    def _rollover_inherited_controls(
        self,
        build_input: SuccessorAssuranceBuildInput,
        *,
        candidate_root: Path,
        public_root: Path,
        staging_descriptor: int,
        public_descriptor: int,
        candidate_identity: tuple[int, int],
        public_identity: tuple[int, int],
    ) -> InstalledPublicTreeInventory:
        observed_tree = self._measure(public_root, public_identity)
        data_tree = _without_controls(observed_tree)
        receipt_name = _rollover_receipt_name(
            candidate_name=candidate_root.name,
            generation_identity_sha256=(build_input.transaction.generation_identity_sha256),
        )
        receipt_authority = _read_optional_rollover_receipt(staging_descriptor, receipt_name)
        receipt_bytes = None if receipt_authority is None else receipt_authority[0]
        report_authority = _read_optional_control_authority(public_descriptor, _REPORT_NAME)
        manifest_authority = _read_optional_control_authority(
            public_descriptor,
            ASSURED_ARTIFACT_MANIFEST_NAME,
        )
        report_bytes = None if report_authority is None else report_authority[0]
        manifest_bytes = None if manifest_authority is None else manifest_authority[0]
        baseline = build_input.baseline
        report_is_inherited = (
            report_bytes is not None
            and hashlib.sha256(report_bytes).hexdigest()
            == baseline.terminal_assurance_report_sha256
        )
        manifest_is_inherited = (
            manifest_bytes is not None
            and hashlib.sha256(manifest_bytes).hexdigest() == baseline.assured_manifest_sha256
        )

        if receipt_bytes is None and report_is_inherited and manifest_is_inherited:
            assert report_bytes is not None and manifest_bytes is not None
            validate_successor_baseline_controls(
                baseline=build_input.baseline,
                terminal_assurance_report_bytes=report_bytes,
                assured_artifact_manifest_bytes=manifest_bytes,
            )
            if observed_tree.installed_public_tree_sha256 != (
                build_input.execution_installed_public_tree_sha256
            ):
                raise SuccessorAssuranceBuilderError(
                    "inherited candidate tree differs from completed execution authority"
                )
            receipt_bytes = _rollover_receipt_bytes(
                build_input=build_input,
                candidate_name=candidate_root.name,
                candidate_identity=candidate_identity,
                public_identity=public_identity,
                data_tree=data_tree,
                report_bytes=report_bytes,
                manifest_bytes=manifest_bytes,
            )
            _publish_rollover_receipt_no_replace(
                staging_descriptor,
                name=receipt_name,
                encoded=receipt_bytes,
            )
        elif receipt_bytes is None and (report_is_inherited or manifest_is_inherited):
            raise SuccessorAssuranceBuilderError(
                "inherited assurance controls are incomplete or mixed"
            )

        if receipt_bytes is not None:
            _validate_rollover_receipt(
                receipt_bytes,
                build_input=build_input,
                candidate_name=candidate_root.name,
                candidate_identity=candidate_identity,
                public_identity=public_identity,
                data_tree=data_tree,
            )
            if (
                report_is_inherited and manifest_bytes is not None and not manifest_is_inherited
            ) or (manifest_is_inherited and report_bytes is not None and not report_is_inherited):
                raise SuccessorAssuranceBuilderError(
                    "inherited assurance controls are mixed with foreign controls"
                )
            if report_is_inherited:
                assert report_bytes is not None
                _validate_inherited_report(report_bytes, baseline=build_input.baseline)
            if manifest_is_inherited and not report_is_inherited:
                raise SuccessorAssuranceBuilderError(
                    "inherited manifest cannot survive without its inherited report"
                )
            if manifest_is_inherited:
                assert manifest_bytes is not None and manifest_authority is not None
                _retire_control_if_exact(
                    public_descriptor,
                    staging_descriptor,
                    candidate_name=candidate_root.name,
                    name=ASSURED_ARTIFACT_MANIFEST_NAME,
                    expected=manifest_bytes,
                    expected_inode=manifest_authority[1],
                )
                if (
                    _read_optional_control(
                        public_descriptor,
                        ASSURED_ARTIFACT_MANIFEST_NAME,
                    )
                    is not None
                ):
                    raise SuccessorAssuranceBuilderError("inherited manifest survived rollover")
                manifest_bytes = None
            if report_is_inherited:
                assert report_bytes is not None and report_authority is not None
                _retire_control_if_exact(
                    public_descriptor,
                    staging_descriptor,
                    candidate_name=candidate_root.name,
                    name=_REPORT_NAME,
                    expected=report_bytes,
                    expected_inode=report_authority[1],
                )
                if _read_optional_control(public_descriptor, _REPORT_NAME) is not None:
                    raise SuccessorAssuranceBuilderError("inherited report survived rollover")
                report_bytes = None
            after_rollover = self._measure(public_root, public_identity)
            if _without_controls(after_rollover) != data_tree:
                raise SuccessorAssuranceBuilderError("candidate data changed during rollover")
            if manifest_bytes is not None and report_bytes is None:
                raise SuccessorAssuranceBuilderError(
                    "assured manifest cannot exist without its terminal report"
                )
            return data_tree

        if manifest_bytes is not None and report_bytes is None:
            raise SuccessorAssuranceBuilderError(
                "assured manifest cannot exist without its terminal report"
            )
        data_matches_execution = data_tree.installed_public_tree_sha256 == (
            build_input.execution_installed_public_tree_sha256
        )
        if not data_matches_execution:
            if report_bytes is None or manifest_bytes is None:
                raise SuccessorAssuranceBuilderError(
                    "candidate data tree differs from the completed execution authority"
                )
            closure_name = _rollover_closure_name(
                candidate_name=candidate_root.name,
                generation_identity_sha256=(build_input.transaction.generation_identity_sha256),
            )
            closure_authority = _read_optional_rollover_closure(
                staging_descriptor,
                closure_name,
            )
            if closure_authority is None:
                raise SuccessorAssuranceBuilderError(
                    "candidate data tree lacks durable rollover execution closure"
                )
            current_tree = _with_exact_controls(
                data_tree,
                report_bytes=report_bytes,
                manifest_bytes=manifest_bytes,
            )
            _validate_rollover_closure(
                closure_authority[0],
                build_input=build_input,
                candidate_name=candidate_root.name,
                candidate_identity=candidate_identity,
                public_identity=public_identity,
                data_tree=data_tree,
                report_bytes=report_bytes,
                manifest_bytes=manifest_bytes,
                final_tree=current_tree,
            )
        return data_tree

    def _require_final_return_authority(
        self,
        build_input: SuccessorAssuranceBuildInput,
        *,
        candidate_root: Path,
        public_root: Path,
        staging_descriptor: int,
        candidate_descriptor: int,
        public_descriptor: int,
        staging_identity: tuple[int, int],
        candidate_identity: tuple[int, int],
        public_identity: tuple[int, int],
        receipt_name: str,
        closure_name: str,
        expected_closure: tuple[bytes, _FullStatIdentity] | None,
        expected_roots: tuple[_FullStatIdentity, _FullStatIdentity, _FullStatIdentity],
        expected_tree_stats: _TreeStatAuthority,
        execution_tree: InstalledPublicTreeInventory,
        report_bytes: bytes,
        manifest_bytes: bytes,
        final_tree: InstalledPublicTreeInventory,
    ) -> None:
        """Re-prove every return authority after the final root/name checks."""

        def _require_closure() -> None:
            observed = _read_optional_rollover_closure_full(
                staging_descriptor,
                closure_name,
            )
            if observed != expected_closure:
                raise SuccessorAssuranceBuilderError(
                    "rollover closure changed at assurance return boundary"
                )
            if observed is not None:
                _validate_rollover_closure(
                    observed[0],
                    build_input=build_input,
                    candidate_name=candidate_root.name,
                    candidate_identity=candidate_identity,
                    public_identity=public_identity,
                    data_tree=execution_tree,
                    report_bytes=report_bytes,
                    manifest_bytes=manifest_bytes,
                    final_tree=final_tree,
                )

        def _require_receipt_absent() -> None:
            _require_rollover_receipt_absent_stably(
                staging_descriptor,
                receipt_name,
            )

        def _require_controls_and_tree() -> None:
            if (
                _read_optional_control(public_descriptor, _REPORT_NAME) != report_bytes
                or _read_optional_control(
                    public_descriptor,
                    ASSURED_ARTIFACT_MANIFEST_NAME,
                )
                != manifest_bytes
                or self._measure(public_root, public_identity) != final_tree
            ):
                raise SuccessorAssuranceBuilderError(
                    "successor controls or full tree changed at assurance return boundary"
                )

        # Two complete observations catch mutations injected by any individual
        # check.  Exact metadata snapshots additionally reject same-byte inode,
        # mode, ownership, link, size, mtime, or ctime changes.
        _require_closure()
        _require_receipt_absent()
        _require_controls_and_tree()
        _require_closure()
        _require_receipt_absent()
        _require_controls_and_tree()

        observed_tree_stats = _snapshot_public_tree_stat_authority(public_descriptor)
        if observed_tree_stats != expected_tree_stats:
            raise SuccessorAssuranceBuilderError(
                "successor public tree metadata changed at assurance return boundary"
            )
        observed_roots = _snapshot_root_authorities(
            staging_root=candidate_root.parent,
            staging_descriptor=staging_descriptor,
            staging_identity=staging_identity,
            candidate_root=candidate_root,
            candidate_descriptor=candidate_descriptor,
            candidate_identity=candidate_identity,
            public_root=public_root,
            public_descriptor=public_descriptor,
            public_identity=public_identity,
        )
        if observed_roots != expected_roots:
            raise SuccessorAssuranceBuilderError(
                "successor root metadata changed at assurance return boundary"
            )

    async def __call__(
        self,
        build_input: SuccessorAssuranceBuildInput,
    ) -> SuccessorAssuranceIdentity:
        if not isinstance(build_input, SuccessorAssuranceBuildInput):
            raise SuccessorAssuranceBuilderError("build_input is invalid")
        self._validate_inherited_authorities(build_input)
        candidate_root = build_input.candidate_root
        if (
            not isinstance(candidate_root, Path)
            or not candidate_root.is_absolute()
            or candidate_root.resolve(strict=True) != candidate_root
        ):
            raise SuccessorAssuranceBuilderError("candidate_root must be an exact absolute path")
        public_root = candidate_root / "public"
        staging_descriptor, staging_stat = _open_directory(
            candidate_root.parent,
            label="successor assurance staging root",
        )
        if os.name == "posix" and (
            staging_stat.st_uid != os.geteuid() or stat.S_IMODE(staging_stat.st_mode) != 0o700
        ):
            os.close(staging_descriptor)
            raise SuccessorAssuranceBuilderError(
                "successor assurance staging root must be owner-only 0700"
            )
        staging_identity = staging_stat.st_dev, staging_stat.st_ino
        candidate_descriptor, candidate_stat = _open_directory(
            candidate_root,
            label="successor candidate root",
        )
        public_descriptor = -1
        cooperative_lock: threading.RLock | None = None
        try:
            try:
                public_descriptor = os.open("public", _DIRECTORY_FLAGS, dir_fd=candidate_descriptor)
            except OSError as exc:
                raise SuccessorAssuranceBuilderError(
                    "successor public root cannot be opened as a direct child"
                ) from exc
            public_stat = os.fstat(public_descriptor)
            named_public = os.stat("public", dir_fd=candidate_descriptor, follow_symlinks=False)
            if not stat.S_ISDIR(public_stat.st_mode) or (
                public_stat.st_dev,
                public_stat.st_ino,
            ) != (named_public.st_dev, named_public.st_ino):
                raise SuccessorAssuranceBuilderError("successor public root identity is invalid")
            candidate_identity = candidate_stat.st_dev, candidate_stat.st_ino
            public_identity = public_stat.st_dev, public_stat.st_ino
            named_candidate = os.stat(
                candidate_root.name,
                dir_fd=staging_descriptor,
                follow_symlinks=False,
            )
            if (named_candidate.st_dev, named_candidate.st_ino) != candidate_identity:
                raise SuccessorAssuranceBuilderError(
                    "successor candidate root is not the admitted staging child"
                )
            cooperative_lock = _cooperative_return_lock(
                staging_identity,
                candidate_identity,
                public_identity,
            )
            cooperative_lock.acquire()
            _require_directory_identity(
                candidate_root.parent,
                staging_descriptor,
                staging_identity,
                label="successor assurance staging root",
            )
            _require_directory_identity(
                candidate_root,
                candidate_descriptor,
                candidate_identity,
                label="successor candidate root",
            )
            _require_directory_identity(
                public_root,
                public_descriptor,
                public_identity,
                label="successor public root",
            )

            restored_private = self.private_generation_resolver.verify(
                transaction=build_input.transaction,
                planning_request=build_input.planning_evidence.request,
                candidate_public_root=public_root,
                expected_public_root_identity=public_identity,
                expected_identity=build_input.update_private_generation,
            )
            if (
                not isinstance(restored_private, PrivateGenerationIdentity)
                or restored_private.canonical_bytes
                != build_input.update_private_generation.canonical_bytes
            ):
                raise SuccessorAssuranceBuilderError(
                    "retained private generation differs from assurance input"
                )

            execution_tree = self._rollover_inherited_controls(
                build_input,
                candidate_root=candidate_root,
                public_root=public_root,
                staging_descriptor=staging_descriptor,
                public_descriptor=public_descriptor,
                candidate_identity=candidate_identity,
                public_identity=public_identity,
            )
            report_before = _read_optional_control(public_descriptor, _REPORT_NAME)

            scan = self.scanner(
                public_root,
                expected_root_identity=public_identity,
            )
            if not isinstance(scan, SuccessorFullPublicationScanResult):
                raise SuccessorAssuranceBuilderError("scanner returned invalid evidence")
            inventory = self.inventory(
                public_root,
                expected_root_identity=public_identity,
            )
            if not isinstance(inventory, SuccessorPublicationInventoryEvidence):
                raise SuccessorAssuranceBuilderError("inventory returned invalid evidence")
            if (
                scan.database_sha256 != inventory.database_evidence.duckdb_sha256
                or scan.database_bytes != inventory.database_evidence.duckdb_bytes
            ):
                raise SuccessorAssuranceBuilderError(
                    "scan database differs from publication inventory"
                )
            independent_transforms = tuple(
                (
                    item.table_name,
                    item.row_count,
                    item.schema_sha256,
                    item.content_sha256,
                )
                for item in inventory.transform_outputs
            )
            requested_transforms = tuple(
                (
                    item.table_name,
                    item.row_count,
                    item.schema_sha256,
                    item.content_sha256,
                )
                for item in build_input.transform_outputs
            )
            if independent_transforms != requested_transforms:
                raise SuccessorAssuranceBuilderError(
                    "transform attestations differ from the candidate DuckDB authority"
                )
            build = build_input.transaction.build
            if build is None:
                raise SuccessorAssuranceBuilderError("built transaction lacks build authority")
            report = SuccessorTerminalAssuranceReportV7.create(
                chain_id=self.chain_id,
                source_sha=build_input.transaction.intent.source_sha,
                coverage_fingerprint=build_input.baseline.coverage_fingerprint,
                generation=build_input.transaction.generation,
                baseline=build_input.baseline,
                planning_evidence=build_input.planning_evidence,
                intent=build_input.transaction.intent,
                build=build,
                update_private_generation=restored_private,
                transform_outputs=tuple(
                    SuccessorTransformOutputAttestation(
                        table_name=item.table_name,
                        row_count=item.row_count,
                        schema_sha256=item.schema_sha256,
                        content_sha256=item.content_sha256,
                    )
                    for item in inventory.transform_outputs
                ),
                scan_evidence=scan.scan_evidence,
                public_evidence=inventory.public_evidence,
                database_evidence=inventory.database_evidence,
                w2_database_authority=scan.w2_database_authority,
                contract_blocked_evidence=self.contract_blocked_evidence,
                provider_authority=self.provider_authority,
            )
            if report_before is not None:
                existing_report = validate_successor_terminal_assurance_report(report_before)
                if existing_report != report or report_before != report.canonical_bytes:
                    raise SuccessorAssuranceBuilderError(
                        "existing terminal assurance report differs from current evidence"
                    )
            _publish_control_no_replace(
                staging_descriptor,
                public_descriptor,
                candidate_name=candidate_root.name,
                control_name=_REPORT_NAME,
                encoded=report.canonical_bytes,
            )
            _require_directory_identity(
                candidate_root,
                candidate_descriptor,
                candidate_identity,
                label="successor candidate root",
            )
            _require_directory_identity(
                public_root,
                public_descriptor,
                public_identity,
                label="successor public root",
            )

            expected_manifest_bytes = canonical_assured_artifact_manifest_bytes(
                public_root,
                chain_id=self.chain_id,
                source_sha=build_input.transaction.intent.source_sha,
                coverage_fingerprint=build_input.baseline.coverage_fingerprint,
                expected_root_identity=public_identity,
                sentinel_excluded_paths=frozenset({_REPORT_NAME}),
            )
            _publish_control_no_replace(
                staging_descriptor,
                public_descriptor,
                candidate_name=candidate_root.name,
                control_name=ASSURED_ARTIFACT_MANIFEST_NAME,
                encoded=expected_manifest_bytes,
            )
            manifest_candidate_bytes = _read_optional_control(
                public_descriptor,
                ASSURED_ARTIFACT_MANIFEST_NAME,
            )
            if manifest_candidate_bytes is None:
                raise SuccessorAssuranceBuilderError("assured manifest disappeared")
            manifest = verify_assured_artifact_manifest(
                public_root,
                expected_chain_id=self.chain_id,
                expected_source_sha=build_input.transaction.intent.source_sha,
                expected_coverage_fingerprint=build_input.baseline.coverage_fingerprint,
                expected_root_identity=public_identity,
                sentinel_excluded_paths=frozenset({_REPORT_NAME}),
            )
            manifest_paths = {cast("str", item["path"]) for item in manifest["files"]}
            if (
                _REPORT_NAME not in manifest_paths
                or ASSURED_ARTIFACT_MANIFEST_NAME in manifest_paths
            ):
                raise SuccessorAssuranceBuilderError(
                    "assured manifest control-file inventory is invalid"
                )
            manifest_bytes = _read_optional_control(
                public_descriptor,
                ASSURED_ARTIFACT_MANIFEST_NAME,
            )
            if manifest_bytes is None or manifest_bytes != manifest_candidate_bytes:
                raise SuccessorAssuranceBuilderError(
                    "assured manifest changed while being verified"
                )

            second_scan = self.scanner(
                public_root,
                expected_root_identity=public_identity,
            )
            second_inventory = self.inventory(
                public_root,
                expected_root_identity=public_identity,
            )
            if second_scan != scan or second_inventory != inventory:
                raise SuccessorAssuranceBuilderError(
                    "candidate scan or publication inventory changed during assurance"
                )
            report_after = _read_optional_control(public_descriptor, _REPORT_NAME)
            manifest_after = _read_optional_control(
                public_descriptor,
                ASSURED_ARTIFACT_MANIFEST_NAME,
            )
            if report_after != report.canonical_bytes or manifest_after != manifest_bytes:
                raise SuccessorAssuranceBuilderError(
                    "successor control bytes changed during assurance"
                )
            final_tree = self._measure(public_root, public_identity)
            expected_final_tree = _with_exact_controls(
                execution_tree,
                report_bytes=report.canonical_bytes,
                manifest_bytes=manifest_bytes,
            )
            if final_tree != expected_final_tree:
                raise SuccessorAssuranceBuilderError(
                    "candidate tree changed during terminal assurance"
                )
            if (
                _read_optional_control(public_descriptor, _REPORT_NAME) != report.canonical_bytes
                or _read_optional_control(
                    public_descriptor,
                    ASSURED_ARTIFACT_MANIFEST_NAME,
                )
                != manifest_bytes
            ):
                raise SuccessorAssuranceBuilderError(
                    "successor control bytes changed after final tree measurement"
                )
            assured_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
            try:
                successor_manifest = emit_successor_assurance_manifest(
                    report,
                    successor_assured_manifest_sha256=assured_manifest_sha256,
                    installed_public_tree_sha256=final_tree.installed_public_tree_sha256,
                )
                verified_report = validate_successor_terminal_assurance_report(
                    report.canonical_bytes
                )
                planning = build_input.planning_evidence
                verified_manifest = verify_successor_assurance_manifest(
                    successor_manifest.canonical_bytes,
                    report=verified_report,
                    successor_assured_manifest_sha256=assured_manifest_sha256,
                    installed_public_tree_sha256=final_tree.installed_public_tree_sha256,
                    expected_planning_generation_manifest_sha256=(
                        planning.planning_generation_manifest.identity_sha256
                    ),
                    expected_sealed_dispatch_inventory_sha256=(
                        planning.execution_plan.sealed_dispatch_inventory_sha256
                    ),
                    expected_logical_call_bindings_sha256=(
                        build_input.update_private_generation.done_call_bindings_sha256
                    ),
                )
            except SuccessorAssuranceContractError as exc:
                raise SuccessorAssuranceBuilderError(
                    "successor-assurance manifest emit or verify failed"
                ) from exc
            identity = verified_manifest.to_successor_assurance_identity()
            receipt_name = _rollover_receipt_name(
                candidate_name=candidate_root.name,
                generation_identity_sha256=(build_input.transaction.generation_identity_sha256),
            )
            receipt_authority = _read_optional_rollover_receipt(
                staging_descriptor,
                receipt_name,
            )
            closure_name = _rollover_closure_name(
                candidate_name=candidate_root.name,
                generation_identity_sha256=(build_input.transaction.generation_identity_sha256),
            )
            closure_authority = _read_optional_rollover_closure(
                staging_descriptor,
                closure_name,
            )
            expected_closure_authority: tuple[bytes, tuple[int, int]] | None = None
            if receipt_authority is not None:
                receipt_bytes, receipt_inode = receipt_authority
                inherited_controls = _validate_rollover_receipt(
                    receipt_bytes,
                    build_input=build_input,
                    candidate_name=candidate_root.name,
                    candidate_identity=candidate_identity,
                    public_identity=public_identity,
                    data_tree=execution_tree,
                )
                closure_bytes = _rollover_closure_bytes(
                    build_input=build_input,
                    candidate_name=candidate_root.name,
                    candidate_identity=candidate_identity,
                    public_identity=public_identity,
                    data_tree=execution_tree,
                    report_bytes=report.canonical_bytes,
                    manifest_bytes=manifest_bytes,
                    final_tree=final_tree,
                    inherited_controls=inherited_controls,
                )
                _publish_rollover_closure_no_replace(
                    staging_descriptor,
                    name=closure_name,
                    encoded=closure_bytes,
                )
                expected_closure_authority = _read_optional_rollover_closure(
                    staging_descriptor,
                    closure_name,
                )
                if (
                    expected_closure_authority is None
                    or expected_closure_authority[0] != closure_bytes
                ):
                    raise SuccessorAssuranceBuilderError(
                        "rollover closure changed before receipt retirement"
                    )
                _retire_rollover_receipt_if_exact(
                    staging_descriptor,
                    candidate_name=candidate_root.name,
                    name=receipt_name,
                    expected=receipt_bytes,
                    expected_inode=receipt_inode,
                )
            elif closure_authority is not None:
                _validate_rollover_closure(
                    closure_authority[0],
                    build_input=build_input,
                    candidate_name=candidate_root.name,
                    candidate_identity=candidate_identity,
                    public_identity=public_identity,
                    data_tree=execution_tree,
                    report_bytes=report.canonical_bytes,
                    manifest_bytes=manifest_bytes,
                    final_tree=final_tree,
                )
                expected_closure_authority = closure_authority
            if expected_closure_authority is not None:
                closure_after_retirement = _read_optional_rollover_closure(
                    staging_descriptor,
                    closure_name,
                )
                if closure_after_retirement != expected_closure_authority:
                    raise SuccessorAssuranceBuilderError(
                        "rollover closure changed during receipt retirement"
                    )
                assert closure_after_retirement is not None
                _validate_rollover_closure(
                    closure_after_retirement[0],
                    build_input=build_input,
                    candidate_name=candidate_root.name,
                    candidate_identity=candidate_identity,
                    public_identity=public_identity,
                    data_tree=execution_tree,
                    report_bytes=report.canonical_bytes,
                    manifest_bytes=manifest_bytes,
                    final_tree=final_tree,
                )
                if (
                    _read_optional_rollover_receipt(staging_descriptor, receipt_name) is not None
                    or _read_optional_control(public_descriptor, _REPORT_NAME)
                    != report.canonical_bytes
                    or _read_optional_control(
                        public_descriptor,
                        ASSURED_ARTIFACT_MANIFEST_NAME,
                    )
                    != manifest_bytes
                    or self._measure(public_root, public_identity) != final_tree
                ):
                    raise SuccessorAssuranceBuilderError(
                        "receipt absence, successor tree, or controls changed during retirement"
                    )

            expected_closure_full = _read_optional_rollover_closure_full(
                staging_descriptor,
                closure_name,
            )
            if expected_closure_authority is None:
                if expected_closure_full is not None:
                    raise SuccessorAssuranceBuilderError(
                        "unexpected rollover closure appeared before final bracket"
                    )
            elif (
                expected_closure_full is None
                or expected_closure_full[0] != expected_closure_authority[0]
                or expected_closure_full[1][:2] != expected_closure_authority[1]
            ):
                raise SuccessorAssuranceBuilderError(
                    "rollover closure differs before final bracket"
                )
            expected_tree_stats = _snapshot_public_tree_stat_authority(public_descriptor)
            if _snapshot_public_tree_stat_authority(public_descriptor) != expected_tree_stats:
                raise SuccessorAssuranceBuilderError(
                    "successor public tree metadata was not stable before final bracket"
                )
            expected_roots = _snapshot_root_authorities(
                staging_root=candidate_root.parent,
                staging_descriptor=staging_descriptor,
                staging_identity=staging_identity,
                candidate_root=candidate_root,
                candidate_descriptor=candidate_descriptor,
                candidate_identity=candidate_identity,
                public_root=public_root,
                public_descriptor=public_descriptor,
                public_identity=public_identity,
            )
            if (
                _snapshot_root_authorities(
                    staging_root=candidate_root.parent,
                    staging_descriptor=staging_descriptor,
                    staging_identity=staging_identity,
                    candidate_root=candidate_root,
                    candidate_descriptor=candidate_descriptor,
                    candidate_identity=candidate_identity,
                    public_root=public_root,
                    public_descriptor=public_descriptor,
                    public_identity=public_identity,
                )
                != expected_roots
            ):
                raise SuccessorAssuranceBuilderError(
                    "successor root metadata was not stable before final bracket"
                )
            _require_directory_identity(
                public_root,
                public_descriptor,
                public_identity,
                label="successor public root",
            )
            _require_directory_identity(
                candidate_root,
                candidate_descriptor,
                candidate_identity,
                label="successor candidate root",
            )
            _require_directory_identity(
                candidate_root.parent,
                staging_descriptor,
                staging_identity,
                label="successor assurance staging root",
            )
            named_candidate = os.stat(
                candidate_root.name,
                dir_fd=staging_descriptor,
                follow_symlinks=False,
            )
            if (named_candidate.st_dev, named_candidate.st_ino) != candidate_identity:
                raise SuccessorAssuranceBuilderError(
                    "successor candidate root changed under its staging authority"
                )
            _require_rollover_receipt_absent_stably(staging_descriptor, receipt_name)
            self._require_final_return_authority(
                build_input,
                candidate_root=candidate_root,
                public_root=public_root,
                staging_descriptor=staging_descriptor,
                candidate_descriptor=candidate_descriptor,
                public_descriptor=public_descriptor,
                staging_identity=staging_identity,
                candidate_identity=candidate_identity,
                public_identity=public_identity,
                receipt_name=receipt_name,
                closure_name=closure_name,
                expected_closure=expected_closure_full,
                expected_roots=expected_roots,
                expected_tree_stats=expected_tree_stats,
                execution_tree=execution_tree,
                report_bytes=report.canonical_bytes,
                manifest_bytes=manifest_bytes,
                final_tree=final_tree,
            )
            return identity
        except (SuccessorAssuranceBuilderError, OSError, TypeError, ValueError) as exc:
            if isinstance(exc, SuccessorAssuranceBuilderError):
                raise
            raise SuccessorAssuranceBuilderError("successor assurance transaction failed") from exc
        finally:
            if public_descriptor >= 0:
                os.close(public_descriptor)
            os.close(candidate_descriptor)
            os.close(staging_descriptor)
            if cooperative_lock is not None:
                cooperative_lock.release()
