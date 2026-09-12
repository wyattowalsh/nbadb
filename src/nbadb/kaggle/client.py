from __future__ import annotations

import csv
import ctypes
import errno
import hashlib
import importlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO, Protocol

    from nbadb.kaggle.publication_ledger import (
        ExecutionReceipt,
        PublicationLedger,
    )
    from nbadb.orchestrate.successor_generation_store import SuccessorGenerationStore
    from nbadb.orchestrate.successor_update_contract import (
        BaselineAssuranceIdentity,
        SuccessorAssuranceIdentity,
    )

    class _FcntlModule(Protocol):
        LOCK_EX: int
        LOCK_NB: int
        LOCK_UN: int

        def flock(self, file_descriptor: int, operation: int) -> None: ...

    class _MsvcrtModule(Protocol):
        LK_NBLCK: int
        LK_UNLCK: int

        def locking(self, file_descriptor: int, mode: int, byte_count: int) -> None: ...


from loguru import logger

from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    assert_no_private_capture_sentinels,
    verify_assured_artifact_manifest,
)
from nbadb.core.config import get_settings
from nbadb.core.nba_api_provenance import normalize_nba_api_provider_authority
from nbadb.core.types import validate_sql_identifier
from nbadb.kaggle.publication_ledger import PublicationIntent
from nbadb.kaggle.publication_rights import assert_public_kaggle_publication_admitted
from nbadb.orchestrate.successor_inventory import (
    InstalledPublicTreeInventory,
    measure_installed_public_tree,
)

PUBLICATION_MARKER_NAME = "nbadb-publication.json"
PUBLICATION_STATE_NAME = "kaggle-publication-state.json"
TERMINAL_ASSURANCE_REPORT_NAME = "terminal-assurance-report.json"
PUBLIC_BASELINE_RECEIPT_NAME = "nbadb-public-baseline-receipt.json"
UPLOAD_SERIALIZATION_CONTRACT = {
    "mechanism": "process_mutex_and_advisory_file_lock",
    "scope": "same_process_and_same_host_shared_log_directory",
    "cross_host_supported": False,
    "cross_host_guard": "remote_marker_and_exact_version_reconciliation",
}
_PUBLICATION_RECORD_STATES = frozenset({"failed", "resolved", "unresolved"})
_REMOTE_FILE_LIST_PAGE_SIZE = 1000
_DISK_SAFETY_RESERVE_BYTES = 1024 * 1024 * 1024
_MAX_SIGNED_63 = (1 << 63) - 1
_LINUX_RENAME_NOREPLACE = 1
_DARWIN_RENAME_EXCL = 0x00000004
_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NONBLOCK", 0)
)
_FILE_READ_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_FILE_CREATE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)

_PROCESS_UPLOAD_LOCK = threading.Lock()
_AUTHORIZATION_BEARER_RE = re.compile(
    r"(?i)(\bauthorization\b[\"']?\s*(?::|=)?\s*[\"']?bearer\s+)([^\"'\s,;}]+)"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|kaggle[_-]?(?:key|token|secret)|"
    r"(?:[a-z0-9]+[_-])?(?:token|secret|password))\b[\"']?\s*(?:=|:)\s*)"
    r"([\"']?)([^\"'\s&,;}\]]+)([\"']?)"
)
_SECRET_FLAG_RE = re.compile(
    r"(?i)((?:--)(?:api[_-]?key|(?:[a-z0-9]+[_-])?(?:token|secret|password))\s+)"
    r"([\"']?)([^\"'\s,;}]+)([\"']?)"
)


class KagglePublicationPendingError(RuntimeError):
    def __init__(self, message: str, publication: dict[str, Any]) -> None:
        self.publication = publication
        super().__init__(message)


def _directory_identity(value: os.stat_result) -> tuple[int, int]:
    return value.st_dev, value.st_ino


def _open_stable_directory(path: Path, *, label: str) -> int:
    before = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise RuntimeError(f"{label} must be a regular directory")
    descriptor = os.open(path, _DIRECTORY_OPEN_FLAGS)
    try:
        opened = os.fstat(descriptor)
        after = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _directory_identity(opened) != _directory_identity(before)
            or _directory_identity(after) != _directory_identity(before)
        ):
            raise RuntimeError(f"{label} changed while opening")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _open_stable_named_directory(
    parent_descriptor: int,
    name: str,
    *,
    label: str,
) -> int:
    before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise RuntimeError(f"{label} must be a regular directory")
    descriptor = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_descriptor)
    try:
        opened = os.fstat(descriptor)
        after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _directory_identity(opened) != _directory_identity(before)
            or _directory_identity(after) != _directory_identity(before)
        ):
            raise RuntimeError(f"{label} changed while opening")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _require_named_directory_authority(
    parent_descriptor: int,
    name: str,
    retained_descriptor: int,
    *,
    expected_identity: tuple[int, int],
    label: str,
) -> None:
    observed_descriptor = -1
    try:
        retained = os.fstat(retained_descriptor)
        named_before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        observed_descriptor = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_descriptor)
        opened = os.fstat(observed_descriptor)
        named_after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise RuntimeError(f"{label} is missing or unsafe") from exc
    finally:
        if observed_descriptor >= 0:
            os.close(observed_descriptor)
    if (
        not stat.S_ISDIR(retained.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(named_before.st_mode)
        or not stat.S_ISDIR(named_after.st_mode)
        or _directory_identity(retained) != expected_identity
        or _directory_identity(opened) != expected_identity
        or _directory_identity(named_before) != expected_identity
        or _directory_identity(named_after) != expected_identity
    ):
        raise RuntimeError(f"{label} differs from the admitted directory authority")


def _fsync_directory_tree(directory_descriptor: int, *, label: str) -> None:
    """Durably flush every directory entry in one already-open safe tree."""

    visited: set[tuple[int, int]] = set()

    def visit(descriptor: int, relative_label: str) -> None:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise RuntimeError(f"{relative_label} must be a regular directory")
        identity = _directory_identity(opened)
        if identity in visited:
            raise RuntimeError(f"{relative_label} contains a directory cycle")
        visited.add(identity)

        for name in sorted(os.listdir(descriptor)):
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISREG(before.st_mode):
                continue
            if not stat.S_ISDIR(before.st_mode):
                raise RuntimeError(f"{relative_label} contains a non-regular entry")
            child_descriptor = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
            try:
                child_opened = os.fstat(child_descriptor)
                after = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if (
                    not stat.S_ISDIR(child_opened.st_mode)
                    or _directory_identity(child_opened) != _directory_identity(before)
                    or _directory_identity(after) != _directory_identity(before)
                ):
                    raise RuntimeError(f"{relative_label}/{name} changed while opening")
                visit(child_descriptor, f"{relative_label}/{name}")
            finally:
                os.close(child_descriptor)
        os.fsync(descriptor)

    visit(directory_descriptor, label)


def _require_named_regular_file_authority(
    parent_descriptor: int,
    name: str,
    *,
    expected_identity: tuple[int, int],
    label: str,
) -> None:
    """Require one named regular file to retain the admitted inode."""

    observed_descriptor = -1
    try:
        before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or _directory_identity(before) != expected_identity:
            raise RuntimeError(f"{label} differs from the admitted file authority")
        observed_descriptor = os.open(
            name,
            _FILE_READ_FLAGS | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_descriptor,
        )
        opened = os.fstat(observed_descriptor)
        after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _directory_identity(opened) != expected_identity
            or _directory_identity(after) != expected_identity
        ):
            raise RuntimeError(f"{label} changed while opening")
    finally:
        if observed_descriptor >= 0:
            os.close(observed_descriptor)


def _unlink_named_regular_file_authority(
    parent_descriptor: int,
    name: str,
    *,
    expected_identity: tuple[int, int],
    label: str,
) -> None:
    """Retire only the exact regular-file inode published by this process."""

    quarantine_name, quarantine_descriptor, quarantine_identity = _create_rollback_quarantine(
        parent_descriptor,
        target_name=name,
    )
    quarantine_entry = "receipt"
    moved_descriptor = -1
    preserve_quarantine = False

    def restore_substituted_entry() -> None:
        nonlocal preserve_quarantine
        try:
            _rename_directory_no_replace(
                quarantine_descriptor,
                quarantine_entry,
                parent_descriptor,
                name,
            )
        except OSError as exc:
            preserve_quarantine = True
            os.fsync(quarantine_descriptor)
            os.fsync(parent_descriptor)
            raise RuntimeError(
                f"{label} cleanup retained a substituted file in owner-only quarantine"
            ) from exc
        os.fsync(quarantine_descriptor)
        os.fsync(parent_descriptor)
        raise RuntimeError(f"{label} cleanup restored a substituted file")

    try:
        _rename_directory_no_replace(
            parent_descriptor,
            name,
            quarantine_descriptor,
            quarantine_entry,
        )
        os.fsync(parent_descriptor)
        os.fsync(quarantine_descriptor)
        moved_before = os.stat(
            quarantine_entry,
            dir_fd=quarantine_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(moved_before.st_mode)
            or _directory_identity(moved_before) != expected_identity
        ):
            restore_substituted_entry()
        try:
            moved_descriptor = os.open(
                quarantine_entry,
                _FILE_READ_FLAGS | getattr(os, "O_NONBLOCK", 0),
                dir_fd=quarantine_descriptor,
            )
        except OSError:
            restore_substituted_entry()
        moved = os.fstat(moved_descriptor)
        moved_after = os.stat(
            quarantine_entry,
            dir_fd=quarantine_descriptor,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(moved.st_mode)
            or _directory_identity(moved) != expected_identity
            or not stat.S_ISREG(moved_after.st_mode)
            or _directory_identity(moved_after) != expected_identity
        ):
            restore_substituted_entry()

        os.unlink(quarantine_entry, dir_fd=quarantine_descriptor)
        os.fsync(quarantine_descriptor)
        try:
            os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RuntimeError(f"{label} cleanup observed a foreign replacement")
    finally:
        if moved_descriptor >= 0:
            os.close(moved_descriptor)
        if not preserve_quarantine:
            _remove_empty_rollback_quarantine(
                parent_descriptor,
                quarantine_name,
                quarantine_descriptor,
                expected_identity=quarantine_identity,
            )
        os.close(quarantine_descriptor)


@contextmanager
def _public_baseline_workspace(*, prefix: str, parent: Path) -> Iterator[Path]:
    """Keep temporary cleanup outside the baseline transaction outcome."""

    workspace = tempfile.TemporaryDirectory(
        prefix=prefix,
        dir=parent,
        ignore_cleanup_errors=True,
    )
    try:
        yield Path(workspace.name)
    finally:
        try:
            workspace.cleanup()
        except OSError as exc:
            logger.warning(
                "Verified public baseline workspace cleanup failed after transaction outcome: {}",
                type(exc).__name__,
            )


def _rename_directory_no_replace(
    source_descriptor: int,
    source_name: str,
    target_descriptor: int,
    target_name: str,
) -> None:
    """Move one name without replacing a destination on supported local POSIX hosts."""

    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        rename = library.renameatx_np
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
            raise RuntimeError("successor baseline no-replace rename requires renameat2") from exc
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
        raise RuntimeError("successor baseline no-replace rename requires macOS or Linux")
    ctypes.set_errno(0)
    if rename(*arguments) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), source_name, target_name)


def _create_rollback_quarantine(
    parent_descriptor: int,
    *,
    target_name: str,
) -> tuple[str, int, tuple[int, int]]:
    for _attempt in range(16):
        name = f".{target_name}.successor-baseline-rollback-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            continue
        descriptor = _open_stable_named_directory(
            parent_descriptor,
            name,
            label="successor baseline rollback quarantine",
        )
        observed = os.fstat(descriptor)
        if stat.S_IMODE(observed.st_mode) != 0o700 or (
            os.name == "posix" and observed.st_uid != os.geteuid()
        ):
            os.close(descriptor)
            raise RuntimeError("successor baseline rollback quarantine is not owner-only")
        os.fsync(parent_descriptor)
        return name, descriptor, _directory_identity(observed)
    raise RuntimeError("successor baseline rollback quarantine name allocation failed")


def _remove_empty_rollback_quarantine(
    parent_descriptor: int,
    name: str,
    descriptor: int,
    *,
    expected_identity: tuple[int, int],
) -> None:
    with os.scandir(descriptor) as iterator:
        if next(iterator, None) is not None:
            raise RuntimeError("successor baseline rollback quarantine is not empty")
    _require_named_directory_authority(
        parent_descriptor,
        name,
        descriptor,
        expected_identity=expected_identity,
        label="successor baseline rollback quarantine",
    )
    retired_name = ""
    for _attempt in range(16):
        candidate = f".{name}.retired-{secrets.token_hex(16)}"
        try:
            _rename_directory_no_replace(
                parent_descriptor,
                name,
                parent_descriptor,
                candidate,
            )
        except FileExistsError:
            continue
        retired_name = candidate
        break
    if not retired_name:
        raise RuntimeError("successor baseline rollback retirement name allocation failed")
    os.fsync(parent_descriptor)

    moved_descriptor = -1
    try:
        moved_descriptor = _open_stable_named_directory(
            parent_descriptor,
            retired_name,
            label="retired successor baseline rollback quarantine",
        )
        moved_identity = _directory_identity(os.fstat(moved_descriptor))
        if moved_identity != expected_identity:
            try:
                _rename_directory_no_replace(
                    parent_descriptor,
                    retired_name,
                    parent_descriptor,
                    name,
                )
            except OSError as exc:
                os.fsync(parent_descriptor)
                raise RuntimeError(
                    "successor baseline rollback retained a substituted quarantine as "
                    f"{retired_name}"
                ) from exc
            os.fsync(parent_descriptor)
            _require_named_directory_authority(
                parent_descriptor,
                name,
                moved_descriptor,
                expected_identity=moved_identity,
                label="restored substituted successor baseline rollback quarantine",
            )
            raise RuntimeError(
                "successor baseline rollback observed and restored a substituted quarantine"
            )

        with os.scandir(moved_descriptor) as iterator:
            if next(iterator, None) is not None:
                raise RuntimeError("retired successor baseline rollback quarantine is not empty")
        os.rmdir(retired_name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
    finally:
        if moved_descriptor >= 0:
            os.close(moved_descriptor)


def _rollback_renamed_successor_baseline(
    *,
    target_parent_descriptor: int,
    target_name: str,
    staging_parent_descriptor: int,
    staged_name: str,
    staged_descriptor: int,
    admitted_identity: tuple[int, int],
) -> None:
    """Retire only the directory inode actually moved from the target name.

    Native no-replace rename prevents destination clobbering, and the private
    quarantine lets us inspect the inode moved at the syscall boundary.  POSIX
    rename is not an inode compare-and-swap: this protects cooperative local
    writers, while a same-UID actor that keeps racing names can force a
    fail-closed retained quarantine instead of data deletion.
    """

    quarantine_name, quarantine_descriptor, quarantine_identity = _create_rollback_quarantine(
        target_parent_descriptor,
        target_name=target_name,
    )
    moved_descriptor = -1
    preserve_quarantine = False
    quarantine_entry = "renamed-target"
    try:
        _require_named_directory_authority(
            target_parent_descriptor,
            target_name,
            staged_descriptor,
            expected_identity=admitted_identity,
            label="installed successor baseline rollback target",
        )
        _rename_directory_no_replace(
            target_parent_descriptor,
            target_name,
            quarantine_descriptor,
            quarantine_entry,
        )
        os.fsync(target_parent_descriptor)
        os.fsync(quarantine_descriptor)
        moved_descriptor = _open_stable_named_directory(
            quarantine_descriptor,
            quarantine_entry,
            label="quarantined successor baseline rollback target",
        )
        moved_identity = _directory_identity(os.fstat(moved_descriptor))
        if moved_identity != admitted_identity:
            try:
                _rename_directory_no_replace(
                    quarantine_descriptor,
                    quarantine_entry,
                    target_parent_descriptor,
                    target_name,
                )
            except OSError as exc:
                preserve_quarantine = True
                os.fsync(quarantine_descriptor)
                os.fsync(target_parent_descriptor)
                raise RuntimeError(
                    "successor baseline rollback retained a substituted target in "
                    f"owner-only quarantine {quarantine_name}"
                ) from exc
            os.fsync(quarantine_descriptor)
            os.fsync(target_parent_descriptor)
            _require_named_directory_authority(
                target_parent_descriptor,
                target_name,
                moved_descriptor,
                expected_identity=moved_identity,
                label="restored substituted successor baseline target",
            )
            raise RuntimeError(
                "successor baseline rollback observed and restored a substituted target"
            )

        try:
            os.stat(staged_name, dir_fd=staging_parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            preserve_quarantine = True
            raise RuntimeError("successor baseline rollback staging name is unexpectedly occupied")
        _rename_directory_no_replace(
            quarantine_descriptor,
            quarantine_entry,
            staging_parent_descriptor,
            staged_name,
        )
        os.fsync(quarantine_descriptor)
        os.fsync(staging_parent_descriptor)
        try:
            _require_named_directory_authority(
                staging_parent_descriptor,
                staged_name,
                staged_descriptor,
                expected_identity=admitted_identity,
                label="rolled-back successor baseline staging directory",
            )
        except BaseException:
            try:
                _rename_directory_no_replace(
                    staging_parent_descriptor,
                    staged_name,
                    quarantine_descriptor,
                    quarantine_entry,
                )
            except BaseException:
                preserve_quarantine = True
                raise
            preserve_quarantine = True
            os.fsync(staging_parent_descriptor)
            os.fsync(quarantine_descriptor)
            raise
    finally:
        if moved_descriptor >= 0:
            os.close(moved_descriptor)
        if not preserve_quarantine:
            _remove_empty_rollback_quarantine(
                target_parent_descriptor,
                quarantine_name,
                quarantine_descriptor,
                expected_identity=quarantine_identity,
            )
        os.close(quarantine_descriptor)


class _PosixAdvisoryFileLock:
    @staticmethod
    def acquire(handle: BinaryIO) -> None:
        fcntl = cast("_FcntlModule", importlib.import_module("fcntl"))

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def release(handle: BinaryIO) -> None:
        fcntl = cast("_FcntlModule", importlib.import_module("fcntl"))

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class _WindowsAdvisoryFileLock:
    @staticmethod
    def acquire(handle: BinaryIO) -> None:
        msvcrt = cast("_MsvcrtModule", importlib.import_module("msvcrt"))

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError("The advisory lock is already held") from exc

    @staticmethod
    def release(handle: BinaryIO) -> None:
        msvcrt = cast("_MsvcrtModule", importlib.import_module("msvcrt"))

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _advisory_file_lock_backend() -> type[_PosixAdvisoryFileLock] | type[_WindowsAdvisoryFileLock]:
    if os.name == "posix":
        return _PosixAdvisoryFileLock
    if os.name == "nt":
        return _WindowsAdvisoryFileLock
    msg = f"Kaggle advisory file locking is unsupported on os.name={os.name!r}"
    raise RuntimeError(msg)


class KaggleClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._dataset = self._settings.kaggle_dataset

    def download(self, target_dir: Path | None = None) -> Path:
        """Download latest dataset from Kaggle and copy to data dir."""
        import shutil

        import kagglehub

        path = kagglehub.dataset_download(self._dataset)
        download_path = Path(path)
        logger.info(f"Downloaded dataset to {download_path}")

        dest = Path(target_dir) if target_dir else self._settings.data_dir
        dest.mkdir(parents=True, exist_ok=True)

        # Copy downloaded files into the working data directory
        copied = 0
        copied_names: set[str] = set()
        for src_file in download_path.iterdir():
            if src_file.is_file():
                shutil.copy2(src_file, dest / src_file.name)
                copied_names.add(src_file.name)
                size_mb = src_file.stat().st_size / 1_048_576
                logger.info(f"  copied file: {src_file.name} ({size_mb:.1f} MB)")
                copied += 1
            elif src_file.is_dir():
                dst_sub = dest / src_file.name
                if dst_sub.exists():
                    shutil.rmtree(dst_sub)
                shutil.copytree(src_file, dst_sub)
                logger.info(f"  copied dir: {src_file.name}/")
                copied += 1
        logger.info(f"Copied {copied} items from Kaggle cache to {dest}")

        self._sync_duckdb_after_download(dest, copied_names=copied_names)

        return dest

    def download_verified_public_baseline(
        self,
        target_dir: Path | None = None,
        *,
        dataset_version: int,
        receipt_path: Path | None = None,
        remote_timeout_seconds: float = 3600.0,
        publication_ledger: PublicationLedger | None = None,
        require_durable_reconciliation: bool = False,
    ) -> tuple[Path, Path]:
        """Install one exact caller-selected, fully assured Kaggle publication.

        This is the authority path for recurring updates.  It resolves one
        caller-supplied positive dataset version, downloads the complete API
        inventory from that immutable version, verifies every byte against the public publication
        marker and the strict full-publication validators, reconciles an
        unresolved durable publication intent when present, binds the exact
        versioned dataset handle into the receipt, and only then publishes the
        isolated candidate with a no-replace directory rename.

        The generic :meth:`download` helper remains available for interactive
        convenience, but does not provide this assurance contract.
        """
        from kagglehub.handle import parse_dataset_handle

        from nbadb.kaggle.publication_ledger import PublicationLedgerPendingError

        exact_version = self._require_exact_dataset_version(
            dataset_version,
            source="caller-supplied verified baseline",
        )
        base_handle = parse_dataset_handle(self._dataset)
        if base_handle.is_versioned():
            raise ValueError(
                "verified public baseline dataset configuration must not contain a version"
            )
        exact_dataset_handle = str(base_handle.with_version(exact_version))
        if not math.isfinite(remote_timeout_seconds) or remote_timeout_seconds <= 0:
            raise ValueError("remote_timeout_seconds must be > 0")
        if require_durable_reconciliation and publication_ledger is None:
            raise ValueError(
                "Verified public baseline requires the GitHub Deployment publication ledger"
            )

        target = Path(target_dir) if target_dir is not None else self._settings.data_dir
        if target.exists() or target.is_symlink():
            raise FileExistsError("verified public baseline target must not already exist")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink():
            raise ValueError("verified public baseline target parent must not be a symlink")

        receipt = (
            Path(receipt_path)
            if receipt_path is not None
            else target.parent / PUBLIC_BASELINE_RECEIPT_NAME
        )
        receipt.parent.mkdir(parents=True, exist_ok=True)
        if receipt.exists() or receipt.is_symlink():
            raise FileExistsError("verified public baseline receipt must not already exist")
        if receipt.parent.is_symlink():
            raise ValueError("verified public baseline receipt parent must not be a symlink")
        try:
            receipt.absolute().relative_to(target.absolute())
        except ValueError:
            pass
        else:
            raise ValueError("verified public baseline receipt must be outside the data root")

        unresolved_before: tuple[object, ...] = ()
        if publication_ledger is not None:
            ledger_inventory = publication_ledger.scan_dataset(self._dataset)
            unresolved_before = tuple(ledger_inventory.unresolved)

        deadline = self._monotonic() + remote_timeout_seconds
        self._require_verification_deadline(deadline, operation="baseline inventory listing")
        api_inventory = self._list_remote_dataset_files(exact_version)
        self._require_verification_deadline(deadline, operation="baseline inventory listing")
        required_bytes = self._validate_verified_download_inventory(api_inventory)
        if required_bytes > (_MAX_SIGNED_63 - _DISK_SAFETY_RESERVE_BYTES) // 2:
            raise OverflowError("verified public baseline capacity requirement exceeds int64")
        self._require_disk_capacity(
            target.parent,
            required_bytes=(required_bytes * 2) + _DISK_SAFETY_RESERVE_BYTES,
            operation="verified public baseline download",
        )

        with _public_baseline_workspace(
            prefix=f".{target.name}.verified-public-baseline-",
            parent=target.parent,
        ) as temporary_root:
            scratch = temporary_root / "kagglehub-scratch"
            scratch.mkdir(mode=0o700)
            staged = temporary_root / "public"
            staged.mkdir(mode=0o700)
            for remote_file in api_inventory:
                relative_path = str(remote_file["path"])
                self._require_verification_deadline(
                    deadline,
                    operation="verified public baseline file download",
                )
                downloaded, resolved_version = self._download_remote_dataset_file(
                    scratch,
                    exact_version,
                    relative_path,
                )
                if resolved_version != exact_version:
                    raise RuntimeError(
                        "Kaggle verified public baseline file resolved the wrong version: "
                        f"expected={exact_version}, resolved={resolved_version}, "
                        f"path={relative_path}"
                    )
                expected_path = (scratch / relative_path).resolve()
                if downloaded != expected_path:
                    raise ValueError(
                        "Kaggle verified public baseline file resolved the wrong path: "
                        f"{relative_path}"
                    )
                candidate_path = staged / relative_path
                self._copy_verified_download_file(downloaded, candidate_path)
                byte_count = candidate_path.stat().st_size
                if byte_count != remote_file["bytes"]:
                    raise ValueError(
                        f"Kaggle verified public baseline file has the wrong size: {relative_path}"
                    )
                self._require_verification_deadline(
                    deadline,
                    operation="verified public baseline file hashing",
                )

            remote_tree = self._snapshot_tree(staged)
            self._require_verification_deadline(
                deadline,
                operation="verified public baseline tree hashing",
            )
            self._assert_remote_file_inventory_matches(
                remote_tree["files"],
                api_inventory,
                compare_sha256=False,
            )
            marker_path = staged / PUBLICATION_MARKER_NAME
            if not marker_path.is_file() or marker_path.is_symlink():
                raise FileNotFoundError(
                    "verified public baseline publication marker is missing or unsafe"
                )
            if marker_path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("verified public baseline publication marker exceeds safe size")
            try:
                marker = json.loads(marker_path.read_bytes())
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "verified public baseline publication marker is invalid JSON"
                ) from exc
            if not isinstance(marker, dict):
                raise ValueError("verified public baseline publication marker must be an object")
            marker = cast("dict[str, Any]", marker)
            self._validate_publication_marker(marker)
            self._assert_remote_marker_inventory_matches(
                marker,
                remote_tree["files"],
                compare_sha256=True,
            )
            snapshot = self._snapshot_upload_bundle(
                staged,
                require_assured=True,
                require_terminal_assurance=True,
            )
            self._require_verification_deadline(
                deadline,
                operation="verified public baseline assurance validation",
            )

            durable_resolution: dict[str, Any] | None = None
            if unresolved_before:
                self._require_verification_deadline(
                    deadline,
                    operation="durable baseline reconciliation",
                )
                durable_resolution = self._reconcile_durable_publication(
                    publication_ledger=publication_ledger,
                    marker=marker,
                    resolved_version=exact_version,
                    resource_verification={"fingerprint": remote_tree["fingerprint"]},
                )
                if durable_resolution is None:
                    raise PublicationLedgerPendingError(
                        "The unresolved Kaggle publication intent does not match the exact "
                        "verified public baseline"
                    )
                if publication_ledger is None:
                    raise AssertionError("durable reconciliation lost its publication ledger")
                if publication_ledger.scan_dataset(self._dataset).unresolved:
                    raise PublicationLedgerPendingError(
                        "The Kaggle publication intent remains unresolved after reconciliation"
                    )
                self._require_verification_deadline(
                    deadline,
                    operation="durable baseline reconciliation",
                )

            self._require_verification_deadline(
                deadline,
                operation="verified public baseline promotion",
            )

            staging_parent_descriptor = _open_stable_directory(
                staged.parent,
                label="verified public baseline staging parent",
            )
            target_parent_descriptor = _open_stable_directory(
                target.parent,
                label="verified public baseline target parent",
            )
            staged_descriptor = -1
            try:
                staged_descriptor = _open_stable_named_directory(
                    staging_parent_descriptor,
                    staged.name,
                    label="verified public baseline staged directory",
                )
                admitted_identity = _directory_identity(os.fstat(staged_descriptor))
                _require_named_directory_authority(
                    staging_parent_descriptor,
                    staged.name,
                    staged_descriptor,
                    expected_identity=admitted_identity,
                    label="verified public baseline staged directory",
                )
                _fsync_directory_tree(
                    staged_descriptor,
                    label="verified public baseline staged directory",
                )
                _rename_directory_no_replace(
                    staging_parent_descriptor,
                    staged.name,
                    target_parent_descriptor,
                    target.name,
                )
                try:
                    _require_named_directory_authority(
                        target_parent_descriptor,
                        target.name,
                        staged_descriptor,
                        expected_identity=admitted_identity,
                        label="installed verified public baseline directory",
                    )
                    os.fsync(staging_parent_descriptor)
                    os.fsync(target_parent_descriptor)
                    installed_tree = measure_installed_public_tree(
                        target,
                        expected_root_identity=admitted_identity,
                    )
                    if (
                        installed_tree.installed_public_tree_sha256
                        != snapshot["installed_public_tree_sha256"]
                        or installed_tree.byte_count != snapshot["installed_public_tree_bytes"]
                    ):
                        raise RuntimeError(
                            "verified public baseline changed during atomic installation"
                        )
                    shutil.rmtree(scratch)
                    os.fsync(staging_parent_descriptor)
                    _require_named_directory_authority(
                        target_parent_descriptor,
                        target.name,
                        staged_descriptor,
                        expected_identity=admitted_identity,
                        label="admitted verified public baseline directory",
                    )
                    receipt_payload = self._public_baseline_receipt_payload(
                        exact_version=exact_version,
                        exact_dataset_handle=exact_dataset_handle,
                        marker=marker,
                        remote_tree=remote_tree,
                        snapshot=snapshot,
                        installed_tree=installed_tree,
                        durable_ledger_checked=publication_ledger is not None,
                        durable_resolution=durable_resolution,
                    )
                    self._atomic_write_canonical_json_no_replace(receipt, receipt_payload)
                except BaseException:
                    try:
                        _rollback_renamed_successor_baseline(
                            target_parent_descriptor=target_parent_descriptor,
                            target_name=target.name,
                            staging_parent_descriptor=staging_parent_descriptor,
                            staged_name=staged.name,
                            staged_descriptor=staged_descriptor,
                            admitted_identity=admitted_identity,
                        )
                    except BaseException as rollback_error:
                        raise RuntimeError(
                            "verified public baseline finalization failed and exact rollback "
                            "could not complete without replacing another target"
                        ) from rollback_error
                    raise
            finally:
                if staged_descriptor >= 0:
                    os.close(staged_descriptor)
                os.close(target_parent_descriptor)
                os.close(staging_parent_descriptor)

        return target, receipt

    def _download_successor_baseline_compat(
        self,
        target_dir: Path,
        *,
        remote_dataset_version: int,
        private_baseline_receipt_sha256: str,
    ) -> BaselineAssuranceIdentity:
        """Compatibility-only private-receipt baseline admission.

        Every file is fetched from the explicitly versioned Kaggle handle,
        verified against the marker and strict full-publication contract, and
        staged on the destination filesystem.  ``target_dir`` appears only
        after all validation and a final remote-head recheck succeed.

        Recurring and public callers must use
        :meth:`download_verified_public_baseline`; this private helper remains
        only for the isolated successor-contract compatibility tests.
        """
        from nbadb.orchestrate.successor_baseline import (
            baseline_identity_from_verified_publication,
        )

        expected_version = self._require_exact_dataset_version(
            remote_dataset_version,
            source="successor baseline",
        )
        if not self._is_lowercase_hex(private_baseline_receipt_sha256, length=64):
            raise ValueError("private_baseline_receipt_sha256 must be lowercase hex")
        target = Path(target_dir)
        if target.exists() or target.is_symlink():
            raise FileExistsError("successor baseline target must not already exist")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.parent.is_symlink():
            raise ValueError("successor baseline target parent must not be a symlink")

        before_version = self._resolve_remote_dataset_version()
        if before_version != expected_version:
            msg = (
                "Successor baseline remote version changed before download: "
                f"expected={expected_version}, observed={before_version}"
            )
            raise RuntimeError(msg)
        api_inventory = self._list_remote_dataset_files(expected_version)
        required_bytes = sum(int(item["bytes"]) for item in api_inventory)
        self._require_disk_capacity(
            target.parent,
            required_bytes=required_bytes + _DISK_SAFETY_RESERVE_BYTES,
            operation="successor baseline download",
        )

        with tempfile.TemporaryDirectory(
            prefix=f".{target.name}.successor-baseline-",
            dir=target.parent,
        ) as temporary_root:
            staged = Path(temporary_root) / "public"
            staged.mkdir()
            observed_files: list[dict[str, Any]] = []
            for remote_file in api_inventory:
                relative_path = str(remote_file["path"])
                downloaded, _resolved_version = self._download_remote_dataset_file(
                    staged,
                    expected_version,
                    relative_path,
                )
                byte_count = downloaded.stat().st_size
                if byte_count != remote_file["bytes"]:
                    raise ValueError(
                        "Kaggle downloaded successor baseline file has the wrong size: "
                        f"{relative_path}"
                    )
                observed_files.append(
                    {
                        "path": relative_path,
                        "bytes": byte_count,
                        "sha256": self._file_sha256(downloaded),
                    }
                )
            observed_files.sort(key=lambda item: item["path"])

            marker_path = staged / PUBLICATION_MARKER_NAME
            if not marker_path.is_file() or marker_path.is_symlink():
                raise FileNotFoundError(
                    "successor baseline publication marker is missing or unsafe"
                )
            if marker_path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("successor baseline publication marker exceeds safe size")
            try:
                marker = json.loads(marker_path.read_bytes())
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("successor baseline publication marker is invalid JSON") from exc
            if not isinstance(marker, dict):
                raise ValueError("successor baseline publication marker must be an object")
            marker = cast("dict[str, Any]", marker)
            self._validate_publication_marker(marker)
            self._assert_remote_marker_inventory_matches(
                marker,
                observed_files,
                compare_sha256=True,
            )
            snapshot = self._snapshot_upload_bundle(
                staged,
                require_assured=True,
                require_terminal_assurance=True,
            )
            after_version = self._resolve_remote_dataset_version()
            if after_version != expected_version:
                msg = (
                    "Successor baseline remote version changed during download: "
                    f"expected={expected_version}, observed={after_version}"
                )
                raise RuntimeError(msg)
            staging_parent_descriptor = _open_stable_directory(
                staged.parent,
                label="successor baseline staging parent",
            )
            target_parent_descriptor = _open_stable_directory(
                target.parent,
                label="successor baseline target parent",
            )
            staged_descriptor = -1
            try:
                staged_descriptor = _open_stable_named_directory(
                    staging_parent_descriptor,
                    staged.name,
                    label="successor baseline staged directory",
                )
                admitted_identity = _directory_identity(os.fstat(staged_descriptor))
                _require_named_directory_authority(
                    staging_parent_descriptor,
                    staged.name,
                    staged_descriptor,
                    expected_identity=admitted_identity,
                    label="successor baseline staged directory",
                )
                _rename_directory_no_replace(
                    staging_parent_descriptor,
                    staged.name,
                    target_parent_descriptor,
                    target.name,
                )
                try:
                    _require_named_directory_authority(
                        target_parent_descriptor,
                        target.name,
                        staged_descriptor,
                        expected_identity=admitted_identity,
                        label="installed successor baseline directory",
                    )
                    os.fsync(staging_parent_descriptor)
                    os.fsync(target_parent_descriptor)
                    installed_tree = measure_installed_public_tree(
                        target,
                        expected_root_identity=admitted_identity,
                    )
                    if installed_tree.installed_public_tree_sha256 != snapshot[
                        "installed_public_tree_sha256"
                    ] or installed_tree.byte_count != snapshot.get("installed_public_tree_bytes"):
                        raise RuntimeError(
                            "successor baseline installed public tree changed during atomic staging"
                        )
                    snapshot["installed_public_tree_sha256"] = (
                        installed_tree.installed_public_tree_sha256
                    )
                    snapshot["installed_public_tree_bytes"] = installed_tree.byte_count
                    identity = baseline_identity_from_verified_publication(
                        snapshot,
                        remote_dataset_version=expected_version,
                        private_baseline_receipt_sha256=private_baseline_receipt_sha256,
                    )
                    _require_named_directory_authority(
                        target_parent_descriptor,
                        target.name,
                        staged_descriptor,
                        expected_identity=admitted_identity,
                        label="admitted successor baseline directory",
                    )
                except BaseException:
                    try:
                        _rollback_renamed_successor_baseline(
                            target_parent_descriptor=target_parent_descriptor,
                            target_name=target.name,
                            staging_parent_descriptor=staging_parent_descriptor,
                            staged_name=staged.name,
                            staged_descriptor=staged_descriptor,
                            admitted_identity=admitted_identity,
                        )
                    except BaseException as rollback_error:
                        raise RuntimeError(
                            "successor baseline post-rename finalization failed and exact "
                            "rollback could not complete without replacing another target"
                        ) from rollback_error
                    raise
            finally:
                if staged_descriptor >= 0:
                    os.close(staged_descriptor)
                os.close(target_parent_descriptor)
                os.close(staging_parent_descriptor)
        return identity

    def publication_preflight(self) -> dict[str, Any]:
        """Read and classify exact remote publication evidence without uploading."""
        try:
            with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-preflight-") as temp_dir:
                marker, marker_version = self._download_remote_publication_marker(Path(temp_dir))
        except Exception as exc:
            if not self._is_publication_marker_not_found(exc):
                raise
            version = self._resolve_remote_dataset_version()
            return {
                "acceptable": True,
                "dataset": self._dataset,
                "state": "bootstrap_marker_missing",
                "marker_status_code": int(HTTPStatus.NOT_FOUND),
                "version": version,
            }

        self._validate_publication_marker(marker)
        metadata_version = self._resolve_remote_dataset_version()
        if marker_version != metadata_version:
            msg = (
                "Kaggle publication preflight resolved ambiguous dataset versions: "
                f"marker={marker_version}, metadata={metadata_version}"
            )
            raise RuntimeError(msg)
        return {
            "acceptable": True,
            "dataset": self._dataset,
            "state": "marker_present",
            "version": marker_version,
            "publish_key": marker["publish_key"],
            "bundle_fingerprint": marker["bundle_fingerprint"],
        }

    @staticmethod
    def _sync_duckdb_after_download(dest: Path, *, copied_names: set[str]) -> None:
        """Ensure DuckDB reflects the freshly downloaded bundle."""
        duckdb_path = dest / "nba.duckdb"
        sqlite_path = dest / "nba.sqlite"
        if "nba.duckdb" in copied_names or "nba.sqlite" not in copied_names:
            return
        if duckdb_path.exists():
            logger.info("Replacing stale local nba.duckdb from freshly downloaded nba.sqlite")
            duckdb_path.unlink()
        KaggleClient._seed_duckdb_from_sqlite(sqlite_path, duckdb_path)

    @staticmethod
    def _seed_duckdb_from_sqlite(sqlite_path: Path, duckdb_path: Path) -> None:
        """Import all tables from SQLite into a new DuckDB file."""
        import duckdb

        logger.info(f"Seeding DuckDB from {sqlite_path.name}...")
        conn = duckdb.connect(str(duckdb_path))
        try:
            conn.execute("INSTALL sqlite; LOAD sqlite;")
            # Use parameterized path to prevent single-quote injection
            safe_path = str(sqlite_path).replace("'", "''")
            conn.execute(f"ATTACH '{safe_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_db.sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            total_rows = 0
            for table in tables:
                validate_sql_identifier(table)
                # Quote identifiers to prevent SQL injection from table names
                quoted = f'"{table}"'
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {quoted} AS SELECT * FROM sqlite_db.{quoted}"
                )
                row_count = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
                if row_count is None:
                    msg = f"Failed to read row count for table {table}"
                    raise RuntimeError(msg)
                rows = row_count[0]
                total_rows += rows
                logger.debug(f"  seeded {table}: {rows:,} rows")
            conn.execute("DETACH sqlite_db")
            logger.info(f"Seeded DuckDB: {len(tables)} tables, {total_rows:,} rows total")
        finally:
            conn.close()

    def upload(
        self,
        data_dir: Path | None = None,
        version_notes: str = "Automated update via nbadb",
        verify_remote: bool = False,
        require_assured: bool = False,
        full_publication: bool = False,
        remote_timeout_seconds: float = 3600.0,
        remote_poll_interval_seconds: float = 15.0,
        publication_ledger: PublicationLedger | None = None,
        require_durable_intent: bool = False,
        successor_generation_store: SuccessorGenerationStore | None = None,
    ) -> Path:
        """Upload with local serialization and optional crash-durable intent.

        The advisory file claim coordinates processes that share this client's local
        log directory. Durable mode additionally records a verified GitHub Deployment
        intent before entering Kaggle's non-idempotent upload call.
        Full-publication mode additionally requires assured terminal extraction evidence.
        A schema-v7 successor publication additionally requires the explicit generation
        store whose current frozen public directory is supplied as ``data_dir``.
        """
        assert_public_kaggle_publication_admitted()
        with self._local_upload_claim():
            return self._upload_claimed(
                data_dir=data_dir,
                version_notes=version_notes,
                verify_remote=verify_remote,
                require_assured=require_assured,
                full_publication=full_publication,
                remote_timeout_seconds=remote_timeout_seconds,
                remote_poll_interval_seconds=remote_poll_interval_seconds,
                publication_ledger=publication_ledger,
                require_durable_intent=require_durable_intent,
                successor_generation_store=successor_generation_store,
            )

    def _upload_claimed(
        self,
        data_dir: Path | None = None,
        version_notes: str = "Automated update via nbadb",
        verify_remote: bool = False,
        require_assured: bool = False,
        full_publication: bool = False,
        remote_timeout_seconds: float = 3600.0,
        remote_poll_interval_seconds: float = 15.0,
        publication_ledger: PublicationLedger | None = None,
        require_durable_intent: bool = False,
        successor_generation_store: SuccessorGenerationStore | None = None,
    ) -> Path:
        """Validate and upload a bundle while the local upload claim is held."""
        assert_public_kaggle_publication_admitted()
        import kagglehub

        upload_dir = data_dir or self._settings.data_dir
        if not upload_dir.exists():
            msg = f"Data directory does not exist: {upload_dir}"
            raise FileNotFoundError(msg)
        if not upload_dir.is_dir():
            msg = f"Data path is not a directory: {upload_dir}"
            raise NotADirectoryError(msg)
        if upload_dir.is_symlink():
            msg = f"Data directory must not be a symlink: {upload_dir}"
            raise ValueError(msg)
        if not math.isfinite(remote_timeout_seconds) or remote_timeout_seconds < 0:
            msg = "remote_timeout_seconds must be >= 0"
            raise ValueError(msg)
        if not math.isfinite(remote_poll_interval_seconds) or remote_poll_interval_seconds <= 0:
            msg = "remote_poll_interval_seconds must be > 0"
            raise ValueError(msg)

        verify_remote = verify_remote or full_publication
        require_assured = require_assured or full_publication
        if require_durable_intent and publication_ledger is None:
            msg = "Durable Kaggle publication requires an external publication ledger"
            raise ValueError(msg)
        if publication_ledger is not None and not verify_remote:
            msg = "Durable Kaggle publication requires exact remote verification"
            raise ValueError(msg)
        from nbadb.orchestrate.successor_publication_authority import (
            require_successor_durable_publication,
            successor_publication_requested,
        )

        if successor_publication_requested(
            upload_dir,
            successor_generation_store=successor_generation_store,
        ):
            require_successor_durable_publication(
                upload_dir,
                full_publication=full_publication,
                verify_remote=verify_remote,
                require_durable_intent=require_durable_intent,
                publication_ledger=publication_ledger,
                successor_generation_store=successor_generation_store,
            )
        preflight = self._snapshot_upload_bundle(
            upload_dir,
            require_assured=require_assured,
            require_terminal_assurance=full_publication,
            successor_generation_store=successor_generation_store,
            require_successor_current_authority=full_publication,
        )
        with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-upload-") as temp_dir:
            staged_dir = Path(temp_dir) / "dataset"
            staged_dir.mkdir(parents=True)
            try:
                staged = self._stage_upload_bundle(upload_dir, staged_dir, preflight)
            except Exception as exc:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="staging_failed",
                    preflight=preflight,
                    error=self._redacted_error(exc),
                )
                raise
            expected_data_tree = self._expected_staged_tree_snapshot(preflight, staged_dir)
            preflight["staged"] = staged
            publish_key = hashlib.sha256(
                f"{self._dataset}:{preflight['fingerprint']}".encode()
            ).hexdigest()[:20]
            publication_marker = self._publication_marker_payload(
                preflight=preflight,
                publish_key=publish_key,
                data_tree_fingerprint=expected_data_tree["fingerprint"],
            )
            self._write_publication_marker(staged_dir, publication_marker)
            staged = self._snapshot_tree(staged_dir)
            expected_staged = self._expected_staged_tree_snapshot(
                preflight,
                staged_dir,
                publication_marker=publication_marker,
            )
            preflight["staged"] = staged
            preflight["expected_staged"] = expected_staged
            publication: dict[str, Any] = {
                "publish_key": publish_key,
                "expected_fingerprint": expected_staged["fingerprint"],
                "expected_bundle_fingerprint": preflight["fingerprint"],
                "verification_mode": "publication_marker",
                "resource_verification_mode": "exact_api_inventory_and_sha256_full_readback",
                "upload_attempts": 0,
                "verification_attempts": 0,
                "observations": [],
                "result": "pending",
                "durable_intent_required": require_durable_intent,
            }
            if staged["fingerprint"] != expected_staged["fingerprint"]:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="staged_pre_upload_mismatch",
                    preflight=preflight,
                    post_upload=staged,
                )
                msg = "Kaggle staged upload bundle does not match the validated preflight inventory"
                raise RuntimeError(msg)

            try:
                source_before_upload = self._snapshot_upload_bundle(
                    upload_dir,
                    require_assured=require_assured,
                    require_terminal_assurance=full_publication,
                    successor_generation_store=successor_generation_store,
                    require_successor_current_authority=full_publication,
                )
            except Exception as exc:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="source_validation_failed_before_upload",
                    preflight=preflight,
                    post_upload=staged,
                    error=self._redacted_error(exc),
                )
                raise
            preflight["source_before_upload"] = source_before_upload
            if source_before_upload["fingerprint"] != preflight["fingerprint"]:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="source_changed_before_upload",
                    preflight=preflight,
                    post_upload=staged,
                )
                msg = "Kaggle upload source bundle changed before upload"
                raise RuntimeError(msg)

            durable_intent: PublicationIntent | None = None
            if publication_ledger is not None:
                durable_intent = self._build_publication_intent(
                    preflight=preflight,
                    expected_staged=expected_staged,
                    publication_marker=publication_marker,
                    publication_ledger=publication_ledger,
                    verify_remote=verify_remote,
                    full_publication=full_publication,
                )
                publication["durable_intent"] = {
                    "intent_id": durable_intent.intent_id,
                    "source_sha": durable_intent.source_sha,
                    "ledger": "github_deployment",
                    "state": "not_prepared",
                }

            try:
                prior_unresolved = self._prior_unresolved_publication(publish_key=publish_key)
            except Exception as exc:
                publication["local_state"] = {
                    "state": "reconciliation_failed",
                    "error": self._redacted_error(exc),
                }
                publication["result"] = "local_state_reconciliation_failed"
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="local_state_reconciliation_failed",
                    preflight=preflight,
                    post_upload=staged,
                    publication=publication,
                    error=self._redacted_error(exc),
                )
                raise

            if prior_unresolved is not None and not verify_remote:
                publication["prior_unresolved_publication"] = prior_unresolved
                publication["result"] = "publication_reconciliation_required"
                msg = (
                    "Kaggle has a prior unresolved upload attempt; remote verification is "
                    "required before another upload"
                )
                pending = KagglePublicationPendingError(msg, publication)
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="publication_reconciliation_required",
                    preflight=preflight,
                    post_upload=staged,
                    publication=publication,
                    error=self._redacted_error(pending),
                )
                raise pending

            bootstrap_baseline_version: int | None = None
            marker_baseline: tuple[dict[str, Any], int] | None = None
            baseline_resource_verification: dict[str, Any] | None = None
            if verify_remote:
                try:
                    with tempfile.TemporaryDirectory(
                        prefix="nbadb-kaggle-baseline-"
                    ) as baseline_dir:
                        baseline_marker, baseline_version = (
                            self._download_remote_publication_marker(Path(baseline_dir))
                        )
                except Exception as exc:
                    if not self._is_publication_marker_not_found(exc):
                        publication["baseline"] = {
                            "state": "reconciliation_failed",
                            "error": self._redacted_error(exc),
                        }
                        publication["result"] = "baseline_reconciliation_failed"
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="baseline_reconciliation_failed",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(exc),
                        )
                        raise

                    try:
                        baseline_version = self._resolve_remote_dataset_version()
                    except Exception as bootstrap_exc:
                        publication["baseline"] = {
                            "state": "bootstrap_version_resolution_failed",
                            "marker_status_code": int(HTTPStatus.NOT_FOUND),
                            "error": self._redacted_error(bootstrap_exc),
                        }
                        publication["result"] = "baseline_reconciliation_failed"
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="baseline_reconciliation_failed",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(bootstrap_exc),
                        )
                        raise

                    publication["baseline"] = {
                        "state": "bootstrap_marker_missing",
                        "marker_status_code": int(HTTPStatus.NOT_FOUND),
                        "version": baseline_version,
                        "matches_expected": False,
                        "upload_allowed": prior_unresolved is None,
                    }
                    if prior_unresolved is not None:
                        publication["prior_unresolved_publication"] = prior_unresolved
                        publication["result"] = "bootstrap_reconciliation_required"
                        msg = (
                            "Kaggle has a prior unresolved upload attempt and the remote "
                            "publication marker is absent; refusing another upload"
                        )
                        pending = KagglePublicationPendingError(msg, publication)
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="bootstrap_reconciliation_required",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(pending),
                        )
                        raise pending from exc
                    bootstrap_baseline_version = baseline_version
                else:
                    baseline_matches = self._publication_marker_matches(
                        baseline_marker,
                        expected=publication_marker,
                    )
                    durable_baseline_receipt = (
                        publication_ledger.find_remote_match(
                            baseline_marker,
                            marker_sha256=hashlib.sha256(
                                self._publication_marker_bytes(baseline_marker)
                            ).hexdigest(),
                        )
                        if publication_ledger is not None
                        else None
                    )
                    prior_matches = prior_unresolved is not None and (
                        self._publication_marker_matches_record(
                            baseline_marker,
                            record=prior_unresolved,
                        )
                    )
                    publication["baseline"] = {
                        "state": "marker_present",
                        "publish_key": baseline_marker.get("publish_key"),
                        "bundle_fingerprint": baseline_marker.get("bundle_fingerprint"),
                        "version": baseline_version,
                        "matches_expected": baseline_matches,
                        "upload_allowed": prior_unresolved is None,
                    }
                    if prior_unresolved is not None and not prior_matches:
                        publication["prior_unresolved_publication"] = prior_unresolved
                        publication["result"] = "publication_reconciliation_required"
                        msg = (
                            "Kaggle has a prior unresolved upload attempt and the remote "
                            "publication marker does not resolve that exact record; refusing "
                            "another upload"
                        )
                        pending = KagglePublicationPendingError(msg, publication)
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="publication_reconciliation_required",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(pending),
                        )
                        raise pending
                    baseline_deadline = self._monotonic() + remote_timeout_seconds
                    metadata_version = self._resolve_remote_dataset_version()
                    self._require_verification_deadline(
                        baseline_deadline,
                        operation="baseline version resolution",
                    )
                    publication["baseline"]["metadata_version"] = metadata_version
                    publication["baseline"]["versions_agree"] = baseline_version == metadata_version
                    if baseline_version != metadata_version:
                        publication["baseline"]["upload_allowed"] = False
                        publication["result"] = "baseline_reconciliation_failed"
                        msg = (
                            "Kaggle publication marker is not from the current dataset version: "
                            f"marker={baseline_version}, metadata={metadata_version}"
                        )
                        error = RuntimeError(msg)
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="baseline_reconciliation_failed",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(error),
                        )
                        raise error
                    if prior_matches or baseline_matches or durable_baseline_receipt is not None:
                        try:
                            baseline_resource_verification = self._verify_remote_bundle(
                                expected_staged if baseline_matches else None,
                                expected_marker=baseline_marker,
                                version=baseline_version,
                                deadline=baseline_deadline,
                            )
                            post_readback_version = self._resolve_remote_dataset_version()
                            self._require_verification_deadline(
                                baseline_deadline,
                                operation="baseline version stabilization",
                            )
                            if post_readback_version != baseline_version:
                                msg = (
                                    "Kaggle current dataset version changed during baseline "
                                    "resource verification: "
                                    f"marker={baseline_version}, current={post_readback_version}"
                                )
                                raise RuntimeError(msg)
                            durable_reconciliation = self._reconcile_durable_publication(
                                publication_ledger=publication_ledger,
                                marker=baseline_marker,
                                resolved_version=baseline_version,
                                resource_verification=baseline_resource_verification,
                            )
                        except Exception as exc:
                            if self._is_local_resource_error(exc):
                                raise
                            publication["baseline"]["resource_verification_error"] = (
                                self._redacted_error(exc)
                            )
                            publication["baseline"]["upload_allowed"] = False
                            publication["result"] = "baseline_reconciliation_failed"
                            self._write_upload_manifest(
                                data_dir=upload_dir,
                                staged_dir=staged_dir,
                                version_notes=version_notes,
                                status="baseline_reconciliation_failed",
                                preflight=preflight,
                                post_upload=staged,
                                publication=publication,
                                error=self._redacted_error(exc),
                            )
                            raise
                        publication["baseline"]["resource_verification"] = (
                            baseline_resource_verification
                        )
                        if durable_reconciliation is not None:
                            publication["durable_reconciliation"] = durable_reconciliation
                    else:
                        marker_baseline = (baseline_marker, baseline_version)
                    if (
                        prior_unresolved is not None
                        and prior_unresolved.get("publish_key") != publish_key
                    ):
                        publication["prior_unresolved_publication"] = prior_unresolved
                        publication["prior_unresolved_reconciliation"] = {
                            "state": "resolved",
                            "status": "reconciled_prior_remote",
                            "resolved_version": baseline_version,
                        }
                        self._transition_publication_state(
                            prior_unresolved,
                            state_name="resolved",
                            status="reconciled_prior_remote",
                            resolved_version=baseline_version,
                        )
                        prior_unresolved = None
                    publication["baseline"]["upload_allowed"] = (
                        prior_unresolved is None or baseline_matches
                    )
                    if baseline_matches:
                        publication.update(
                            {
                                "result": "reconciled_existing_remote",
                                "resolved_version": baseline_version,
                                "verification_attempts": 1,
                            }
                        )
                        self._transition_publication_state(
                            publication,
                            state_name="resolved",
                            status="reconciled_existing_remote",
                            resolved_version=baseline_version,
                        )
                        manifest_path = self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="reconciled_existing_remote",
                            preflight=preflight,
                            post_upload=staged,
                            remote_readback={
                                **baseline_marker,
                                "verification_mode": "publication_marker",
                                "resource_verification": baseline_resource_verification,
                                "verification_attempts": 1,
                                "verification_elapsed_seconds": 0.0,
                                "resolved_version": baseline_version,
                            },
                            publication=publication,
                        )
                        logger.info("Kaggle already exposes the staged bundle; upload skipped")
                        return manifest_path
                    if prior_unresolved is not None:
                        publication["prior_unresolved_publication"] = prior_unresolved
                        publication["result"] = "publication_reconciliation_required"
                        msg = (
                            "Kaggle has a prior unresolved upload attempt and the remote "
                            "publication marker is present but nonmatching; refusing another upload"
                        )
                        pending = KagglePublicationPendingError(msg, publication)
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="publication_reconciliation_required",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(pending),
                        )
                        raise pending

            manifest_path = self._write_upload_manifest(
                data_dir=upload_dir,
                staged_dir=staged_dir,
                version_notes=version_notes,
                status="preflight_passed",
                preflight=preflight,
                publication=publication,
            )
            if bootstrap_baseline_version is not None:
                try:
                    bootstrap_recheck = self._reconcile_bootstrap_before_upload(
                        expected_marker=publication_marker,
                        baseline_version=bootstrap_baseline_version,
                    )
                except Exception as exc:
                    publication["bootstrap_pre_upload"] = {
                        "state": "reconciliation_failed",
                        "baseline_version": bootstrap_baseline_version,
                        "error": self._redacted_error(exc),
                    }
                    publication["result"] = "bootstrap_pre_upload_reconciliation_failed"
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="bootstrap_pre_upload_reconciliation_failed",
                        preflight=preflight,
                        post_upload=staged,
                        publication=publication,
                        error=self._redacted_error(exc),
                    )
                    raise
                publication["bootstrap_pre_upload"] = bootstrap_recheck
                if (
                    bootstrap_recheck["state"] == "marker_present"
                    and bootstrap_recheck["upload_allowed"]
                ):
                    bootstrap_deadline = self._monotonic() + remote_timeout_seconds
                    resolved_version = self._require_exact_dataset_version(
                        bootstrap_recheck["marker_version"],
                        source="bootstrap pre-upload marker",
                    )
                    remote_marker = cast("dict[str, Any]", bootstrap_recheck["marker"])
                    try:
                        resource_verification = self._verify_remote_bundle(
                            expected_staged,
                            expected_marker=remote_marker,
                            version=resolved_version,
                            deadline=bootstrap_deadline,
                        )
                        post_readback_version = self._resolve_remote_dataset_version()
                        self._require_verification_deadline(
                            bootstrap_deadline,
                            operation="bootstrap version stabilization",
                        )
                        if post_readback_version != resolved_version:
                            msg = (
                                "Kaggle current dataset version changed during bootstrap "
                                "resource verification: "
                                f"marker={resolved_version}, current={post_readback_version}"
                            )
                            raise RuntimeError(msg)
                    except Exception as exc:
                        if self._is_local_resource_error(exc):
                            raise
                        publication["bootstrap_pre_upload"]["resource_verification_error"] = (
                            self._redacted_error(exc)
                        )
                        publication["result"] = "bootstrap_pre_upload_reconciliation_failed"
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="bootstrap_pre_upload_reconciliation_failed",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(exc),
                        )
                        raise
                    publication["bootstrap_pre_upload"]["resource_verification"] = (
                        resource_verification
                    )
                    durable_reconciliation = self._reconcile_durable_publication(
                        publication_ledger=publication_ledger,
                        marker=remote_marker,
                        resolved_version=resolved_version,
                        resource_verification=resource_verification,
                    )
                    if durable_reconciliation is not None:
                        publication["durable_reconciliation"] = durable_reconciliation
                    publication.update(
                        {
                            "result": "reconciled_existing_remote",
                            "resolved_version": resolved_version,
                            "verification_attempts": 1,
                        }
                    )
                    self._transition_publication_state(
                        publication,
                        state_name="resolved",
                        status="reconciled_existing_remote",
                        resolved_version=resolved_version,
                    )
                    manifest_path = self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="reconciled_existing_remote",
                        preflight=preflight,
                        post_upload=staged,
                        remote_readback={
                            **remote_marker,
                            "verification_mode": "publication_marker",
                            "resource_verification": resource_verification,
                            "verification_attempts": 1,
                            "verification_elapsed_seconds": 0.0,
                            "resolved_version": resolved_version,
                        },
                        publication=publication,
                    )
                    logger.info("Kaggle bootstrap recheck found the staged bundle; upload skipped")
                    return manifest_path
                if not bootstrap_recheck["upload_allowed"]:
                    publication["result"] = "bootstrap_pre_upload_reconciliation_required"
                    msg = (
                        "Kaggle remote publication evidence changed or became ambiguous after "
                        "the marker-specific 404; refusing upload"
                    )
                    pending = KagglePublicationPendingError(msg, publication)
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="bootstrap_pre_upload_reconciliation_required",
                        preflight=preflight,
                        post_upload=staged,
                        publication=publication,
                        error=self._redacted_error(pending),
                    )
                    raise pending

            if marker_baseline is not None:
                baseline_marker, baseline_version = marker_baseline
                try:
                    marker_recheck = self._reconcile_marker_baseline_before_upload(
                        expected_marker=publication_marker,
                        baseline_marker=baseline_marker,
                        baseline_version=baseline_version,
                    )
                except Exception as exc:
                    publication["marker_pre_upload"] = {
                        "state": "reconciliation_failed",
                        "baseline_version": baseline_version,
                        "error": self._redacted_error(exc),
                    }
                    publication["result"] = "marker_pre_upload_reconciliation_failed"
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="marker_pre_upload_reconciliation_failed",
                        preflight=preflight,
                        post_upload=staged,
                        publication=publication,
                        error=self._redacted_error(exc),
                    )
                    raise
                publication["marker_pre_upload"] = marker_recheck
                if marker_recheck["matches_expected"]:
                    marker_deadline = self._monotonic() + remote_timeout_seconds
                    resolved_version = self._require_exact_dataset_version(
                        marker_recheck["marker_version"],
                        source="marker pre-upload reconciliation",
                    )
                    remote_marker = cast("dict[str, Any]", marker_recheck["marker"])
                    resource_verification = self._verify_remote_bundle(
                        expected_staged,
                        expected_marker=remote_marker,
                        version=resolved_version,
                        deadline=marker_deadline,
                    )
                    post_readback_version = self._resolve_remote_dataset_version()
                    self._require_verification_deadline(
                        marker_deadline,
                        operation="marker pre-upload version stabilization",
                    )
                    if post_readback_version != resolved_version:
                        msg = (
                            "Kaggle current dataset version changed during marker pre-upload "
                            f"verification: marker={resolved_version}, "
                            f"current={post_readback_version}"
                        )
                        raise RuntimeError(msg)
                    durable_reconciliation = self._reconcile_durable_publication(
                        publication_ledger=publication_ledger,
                        marker=remote_marker,
                        resolved_version=resolved_version,
                        resource_verification=resource_verification,
                    )
                    if durable_reconciliation is not None:
                        publication["durable_reconciliation"] = durable_reconciliation
                    publication.update(
                        {
                            "result": "reconciled_existing_remote",
                            "resolved_version": resolved_version,
                            "verification_attempts": 1,
                        }
                    )
                    self._transition_publication_state(
                        publication,
                        state_name="resolved",
                        status="reconciled_existing_remote",
                        resolved_version=resolved_version,
                    )
                    return self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="reconciled_existing_remote",
                        preflight=preflight,
                        post_upload=staged,
                        remote_readback={
                            **remote_marker,
                            "verification_mode": "publication_marker",
                            "resource_verification": resource_verification,
                            "verification_attempts": 1,
                            "verification_elapsed_seconds": 0.0,
                            "resolved_version": resolved_version,
                        },
                        publication=publication,
                    )
                if not marker_recheck["upload_allowed"]:
                    publication["result"] = "marker_pre_upload_reconciliation_required"
                    msg = (
                        "Kaggle marker or dataset version changed after baseline verification; "
                        "refusing upload"
                    )
                    pending = KagglePublicationPendingError(msg, publication)
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="marker_pre_upload_reconciliation_required",
                        preflight=preflight,
                        post_upload=staged,
                        publication=publication,
                        error=self._redacted_error(pending),
                    )
                    raise pending

            try:
                self._require_disk_capacity(
                    staged_dir,
                    required_bytes=int(staged["bytes"]) + _DISK_SAFETY_RESERVE_BYTES,
                    operation="upload archive creation",
                )
            except OSError as exc:
                publication["result"] = "upload_capacity_failed"
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="upload_capacity_failed",
                    preflight=preflight,
                    post_upload=staged,
                    publication=publication,
                    error=self._redacted_error(exc),
                )
                raise
            durable_receipt = None
            if publication_ledger is not None:
                if durable_intent is None:
                    raise AssertionError("Durable publication intent was not initialized")
                try:
                    durable_receipt = publication_ledger.prepare(durable_intent)
                except Exception as exc:
                    publication["result"] = "durable_intent_reconciliation_required"
                    durable_publication = cast(
                        "dict[str, Any]",
                        publication["durable_intent"],
                    )
                    durable_publication["state"] = "reconciliation_required"
                    durable_publication["error"] = self._redacted_error(exc)
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="durable_intent_reconciliation_required",
                        preflight=preflight,
                        post_upload=staged,
                        publication=publication,
                        error=self._redacted_error(exc),
                    )
                    raise
                durable_publication = cast(
                    "dict[str, Any]",
                    publication["durable_intent"],
                )
                durable_publication.update(
                    {
                        "state": "pending",
                        "deployment": durable_receipt.to_dict(),
                    }
                )
                self._transition_publication_state(
                    publication,
                    state_name="unresolved",
                    status="durable_intent_pending",
                )
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="durable_intent_pending",
                    preflight=preflight,
                    post_upload=staged,
                    publication=publication,
                )

            upload_error: Exception | None = None
            execution_receipt: ExecutionReceipt | None = None
            publication["upload_attempts"] = 1
            if publication_ledger is None:
                self._transition_publication_state(
                    publication,
                    state_name="unresolved",
                    status="upload_attempt_started",
                )
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="upload_attempt_started",
                    preflight=preflight,
                    post_upload=staged,
                    publication=publication,
                )
            try:
                if publication_ledger is not None:
                    if durable_receipt is None:
                        raise AssertionError("Durable publication receipt was not initialized")
                    execution_receipt = publication_ledger.claim_pending(durable_receipt)
                    kagglehub.dataset_upload(
                        handle=self._dataset,
                        local_dataset_dir=str(staged_dir),
                        version_notes=version_notes,
                    )
                else:
                    kagglehub.dataset_upload(
                        handle=self._dataset,
                        local_dataset_dir=str(staged_dir),
                        version_notes=version_notes,
                    )
            except Exception as exc:
                upload_error = exc
                if execution_receipt is not None:
                    publication["durable_execution"] = execution_receipt.to_dict()
                    durable_publication = cast(
                        "dict[str, Any]",
                        publication["durable_intent"],
                    )
                    durable_publication["state"] = "in_progress"
                publication["upload_error"] = self._redacted_error(exc)
                publication["result"] = "upload_ambiguous"
                self._transition_publication_state(
                    publication,
                    state_name="unresolved",
                    status="upload_ambiguous",
                    error=self._redacted_error(exc),
                )
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="upload_ambiguous_reconciling" if verify_remote else "upload_ambiguous",
                    preflight=preflight,
                    publication=publication,
                    error=self._redacted_error(exc),
                )
                if not verify_remote:
                    raise
            else:
                if execution_receipt is not None:
                    publication["durable_execution"] = execution_receipt.to_dict()
                    durable_publication = cast(
                        "dict[str, Any]",
                        publication["durable_intent"],
                    )
                    durable_publication["state"] = "in_progress"

            post_upload = self._snapshot_tree(staged_dir)
            if post_upload["fingerprint"] != staged["fingerprint"]:
                self._transition_publication_state(
                    publication,
                    state_name="unresolved",
                    status="post_upload_mismatch_remote_may_exist",
                )
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="post_upload_mismatch_remote_may_exist",
                    preflight=preflight,
                    post_upload=post_upload,
                    publication=publication,
                )
                msg = (
                    "Kaggle upload bundle changed during upload; the remote Kaggle "
                    "version may already have been created"
                )
                raise RuntimeError(msg)

            remote_readback = None
            if verify_remote:
                try:
                    remote_readback = self._verify_remote_upload(
                        publication_marker,
                        expected_tree=expected_staged,
                        timeout_seconds=remote_timeout_seconds,
                        poll_interval_seconds=remote_poll_interval_seconds,
                        publication=publication,
                    )
                except KagglePublicationPendingError as exc:
                    publication = exc.publication
                    publication["result"] = "publication_reconciliation_required"
                    self._transition_publication_state(
                        publication,
                        state_name="unresolved",
                        status="publication_reconciliation_required",
                        error=self._redacted_error(exc),
                    )
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="publication_reconciliation_required",
                        preflight=preflight,
                        post_upload=post_upload,
                        publication=publication,
                        error=self._redacted_error(exc),
                    )
                    raise
                if publication_ledger is not None:
                    if execution_receipt is None:
                        raise AssertionError(
                            "Durable publication execution receipt was not initialized"
                        )
                    resource_verification = cast(
                        "dict[str, Any]",
                        remote_readback["resource_verification"],
                    )
                    resolution_receipt = publication_ledger.mark_resolved(
                        execution_receipt,
                        resolved_version=self._require_exact_dataset_version(
                            publication.get("resolved_version"),
                            source="durable publication resolution",
                        ),
                        publication_marker_sha256=hashlib.sha256(
                            self._publication_marker_bytes(publication_marker)
                        ).hexdigest(),
                        readback_fingerprint=str(resource_verification["fingerprint"]),
                    )
                    publication["durable_resolution"] = resolution_receipt.to_dict()
                    durable_publication = cast(
                        "dict[str, Any]",
                        publication["durable_intent"],
                    )
                    durable_publication["state"] = "success"
                publication["result"] = (
                    "reconciled_after_upload_error" if upload_error is not None else "verified"
                )
                self._transition_publication_state(
                    publication,
                    state_name="resolved",
                    status="uploaded_remote_verified",
                    resolved_version=publication.get("resolved_version"),
                )
            else:
                publication["result"] = "uploaded_unverified"
                self._transition_publication_state(
                    publication,
                    state_name="unresolved",
                    status="uploaded_unverified",
                )

            manifest_path = self._write_upload_manifest(
                data_dir=upload_dir,
                staged_dir=staged_dir,
                version_notes=version_notes,
                status=("uploaded_remote_verified" if verify_remote else "uploaded_unverified"),
                preflight=preflight,
                post_upload=post_upload,
                remote_readback=remote_readback,
                publication=publication,
            )
        logger.info(f"Uploaded dataset from {upload_dir}")
        logger.info(f"Wrote Kaggle upload manifest to {manifest_path}")
        return manifest_path

    def ensure_metadata(
        self,
        data_dir: Path | None = None,
        *,
        include_assurance_resources: bool = False,
    ) -> Path:
        """Ensure dataset-metadata.json exists in data dir."""
        from nbadb.kaggle.metadata import generate_metadata

        resolved_data_dir = data_dir or self._settings.data_dir
        target = resolved_data_dir / "dataset-metadata.json"
        generate_metadata(
            target,
            data_dir=resolved_data_dir,
            include_assurance_resources=include_assurance_resources,
        )
        return target

    @contextmanager
    def _local_upload_claim(self) -> Iterator[None]:
        """Claim this host/log root; separate hosts still require remote reconciliation."""
        if not _PROCESS_UPLOAD_LOCK.acquire(blocking=False):
            msg = "Another Kaggle upload is already active in this process"
            raise RuntimeError(msg)

        lock_handle = None
        lock_backend = None
        file_claimed = False
        try:
            lock_dir = self._settings.log_dir / "kaggle"
            lock_dir.mkdir(parents=True, exist_ok=True)
            dataset_key = hashlib.sha256(self._dataset.encode("utf-8")).hexdigest()[:16]
            lock_path = lock_dir / f"kaggle-upload-{dataset_key}.lock"
            lock_path.touch(exist_ok=True)
            lock_handle = lock_path.open("r+b")
            lock_backend = _advisory_file_lock_backend()
            try:
                lock_backend.acquire(lock_handle)
            except BlockingIOError as exc:
                msg = (
                    "Another Kaggle upload is already active on this host for the shared "
                    "log directory"
                )
                raise RuntimeError(msg) from exc
            file_claimed = True
            lock_handle.seek(0)
            lock_handle.write(
                (
                    json.dumps(
                        {
                            "dataset": self._dataset,
                            "process_id": os.getpid(),
                            "claimed_at": datetime.now(UTC).isoformat(),
                            "serialization": UPLOAD_SERIALIZATION_CONTRACT,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            lock_handle.truncate()
            lock_handle.flush()
            os.fsync(lock_handle.fileno())
            yield
        finally:
            try:
                if lock_handle is not None:
                    try:
                        if file_claimed and lock_backend is not None:
                            lock_backend.release(lock_handle)
                    finally:
                        lock_handle.close()
            finally:
                _PROCESS_UPLOAD_LOCK.release()

    def _publication_state_path(self) -> Path:
        return self._settings.log_dir / "kaggle" / PUBLICATION_STATE_NAME

    @staticmethod
    def _is_lowercase_hex(value: Any, *, length: int) -> bool:
        return (
            isinstance(value, str)
            and len(value) == length
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _require_nonempty_record_string(
        record: dict[str, Any],
        field: str,
        *,
        context: str,
    ) -> None:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            msg = f"Kaggle publication record {context} must have a nonempty {field}"
            raise RuntimeError(msg)

    @classmethod
    def _validate_publication_record(
        cls,
        *,
        dataset_key: str,
        stored_key: str,
        record: dict[str, Any],
    ) -> None:
        if record.get("dataset") != dataset_key or record.get("publish_key") != stored_key:
            msg = "Kaggle publication record identity is inconsistent"
            raise RuntimeError(msg)
        if not cls._is_lowercase_hex(stored_key, length=20):
            msg = "Kaggle publication record publish_key must be 20 lowercase hex characters"
            raise RuntimeError(msg)
        if not cls._is_lowercase_hex(record.get("bundle_fingerprint"), length=64):
            msg = "Kaggle publication record bundle_fingerprint must be lowercase hex"
            raise RuntimeError(msg)

        state_name = record.get("state")
        if state_name not in _PUBLICATION_RECORD_STATES:
            msg = "Kaggle publication record has an unsupported state"
            raise RuntimeError(msg)
        context = f"{dataset_key}/{stored_key}"
        cls._require_nonempty_record_string(record, "last_status", context=context)
        cls._require_nonempty_record_string(record, "last_transition_at", context=context)
        if record.get("serialization") != UPLOAD_SERIALIZATION_CONTRACT:
            msg = "Kaggle publication record serialization contract is invalid"
            raise RuntimeError(msg)

        state_timestamp_fields = {
            "failed": "failed_at",
            "resolved": "resolved_at",
            "unresolved": "first_unresolved_at",
        }
        cls._require_nonempty_record_string(
            record,
            state_timestamp_fields[cast("str", state_name)],
            context=context,
        )
        for timestamp_field in state_timestamp_fields.values():
            if timestamp_field in record:
                cls._require_nonempty_record_string(
                    record,
                    timestamp_field,
                    context=context,
                )
        if state_name == "resolved":
            resolved_version = record.get("resolved_version")
            if (
                not isinstance(resolved_version, int)
                or isinstance(resolved_version, bool)
                or resolved_version <= 0
            ):
                msg = "Kaggle resolved publication record requires a positive resolved_version"
                raise RuntimeError(msg)

    @classmethod
    def _validate_publication_state(cls, state: dict[str, Any]) -> None:
        datasets = state.get("datasets")
        if not isinstance(datasets, dict):
            msg = "Kaggle publication state datasets must be an object"
            raise RuntimeError(msg)
        for dataset_key, dataset_state in datasets.items():
            if not isinstance(dataset_key, str) or not dataset_key.strip():
                msg = "Kaggle publication state dataset key must be nonempty"
                raise RuntimeError(msg)
            if not isinstance(dataset_state, dict):
                msg = "Kaggle publication dataset state must be an object"
                raise RuntimeError(msg)
            publications = dataset_state.get("publications")
            if not isinstance(publications, dict):
                msg = "Kaggle publication records must be an object"
                raise RuntimeError(msg)
            for stored_key, raw_record in publications.items():
                if not isinstance(stored_key, str) or not isinstance(raw_record, dict):
                    msg = "Kaggle publication record must be an object with a string key"
                    raise RuntimeError(msg)
                cls._validate_publication_record(
                    dataset_key=dataset_key,
                    stored_key=stored_key,
                    record=cast("dict[str, Any]", raw_record),
                )

    def _read_publication_state(self) -> dict[str, Any]:
        state_path = self._publication_state_path()
        if not state_path.is_file():
            return {"schema_version": 1, "datasets": {}}
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = "Kaggle publication state cannot be read safely"
            raise RuntimeError(msg) from exc
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            msg = "Kaggle publication state has an unsupported schema"
            raise RuntimeError(msg)
        validated_state = cast("dict[str, Any]", state)
        self._validate_publication_state(validated_state)
        return validated_state

    def _prior_unresolved_publication(self, *, publish_key: str) -> dict[str, Any] | None:
        state = self._read_publication_state()
        dataset_state = state["datasets"].get(self._dataset)
        if dataset_state is None:
            return None
        if not isinstance(dataset_state, dict):
            msg = "Kaggle publication dataset state must be an object"
            raise RuntimeError(msg)
        publications = dataset_state.get("publications")
        if not isinstance(publications, dict):
            msg = "Kaggle publication records must be an object"
            raise RuntimeError(msg)
        unresolved: list[dict[str, Any]] = []
        for raw_record in publications.values():
            record = cast("dict[str, Any]", raw_record)
            if record.get("state") == "unresolved":
                unresolved.append(record)
        if len(unresolved) > 1:
            keys = sorted(str(record.get("publish_key") or "") for record in unresolved)
            msg = "Kaggle publication state has multiple unresolved dataset uploads: " + ", ".join(
                keys
            )
            raise RuntimeError(msg)
        if not unresolved:
            return None
        record = unresolved[0]
        if record.get("publish_key") != publish_key:
            logger.warning(
                "Kaggle dataset has an unresolved publication for a different bundle: {}",
                record.get("publish_key"),
            )
        return record

    def _transition_publication_state(
        self,
        publication: dict[str, Any],
        *,
        state_name: str,
        status: str,
        resolved_version: int | None = None,
        error: str | None = None,
    ) -> None:
        if state_name not in _PUBLICATION_RECORD_STATES:
            msg = f"Unsupported Kaggle publication state transition: {state_name}"
            raise RuntimeError(msg)
        publish_key = publication.get("publish_key")
        bundle_fingerprint = publication.get("expected_bundle_fingerprint") or publication.get(
            "bundle_fingerprint"
        )
        if not isinstance(publish_key, str) or not isinstance(bundle_fingerprint, str):
            msg = "Kaggle publication transition requires exact local identity"
            raise RuntimeError(msg)

        state = self._read_publication_state()
        datasets = state["datasets"]
        dataset_state = datasets.setdefault(self._dataset, {"publications": {}})
        if not isinstance(dataset_state, dict):
            msg = "Kaggle publication dataset state must be an object"
            raise RuntimeError(msg)
        publications = dataset_state.setdefault("publications", {})
        if not isinstance(publications, dict):
            msg = "Kaggle publication records must be an object"
            raise RuntimeError(msg)
        existing = publications.get(publish_key)
        if existing is not None and not isinstance(existing, dict):
            msg = "Kaggle publication record must be an object"
            raise RuntimeError(msg)

        transitioned_at = datetime.now(UTC).isoformat()
        record: dict[str, Any] = {
            **(existing or {}),
            "dataset": self._dataset,
            "publish_key": publish_key,
            "bundle_fingerprint": bundle_fingerprint,
            "state": state_name,
            "last_status": status,
            "last_transition_at": transitioned_at,
            "serialization": UPLOAD_SERIALIZATION_CONTRACT,
        }
        if state_name == "unresolved":
            record.setdefault("first_unresolved_at", transitioned_at)
            record["baseline"] = publication.get("baseline")
            record["result"] = publication.get("result")
        elif state_name == "resolved":
            record["resolved_at"] = transitioned_at
            record["resolved_version"] = self._require_exact_dataset_version(
                resolved_version,
                source="publication state resolution",
            )
        else:
            record["failed_at"] = transitioned_at
        if error is not None:
            record["error"] = self._redact_sensitive_text(error)
        publications[publish_key] = record
        state["updated_at"] = transitioned_at
        self._validate_publication_state(state)
        self._atomic_write_json(self._publication_state_path(), state)

    def _snapshot_upload_bundle(
        self,
        data_dir: Path,
        *,
        require_assured: bool = False,
        require_terminal_assurance: bool = False,
        successor_generation_store: SuccessorGenerationStore | None = None,
        require_successor_current_authority: bool = False,
    ) -> dict[str, Any]:
        assert_no_private_capture_sentinels(data_dir)
        metadata_path = data_dir / "dataset-metadata.json"
        if not metadata_path.is_file():
            msg = f"Kaggle metadata file does not exist: {metadata_path}"
            raise FileNotFoundError(msg)
        if metadata_path.is_symlink():
            msg = f"Kaggle metadata file must not be a symlink: {metadata_path}"
            raise ValueError(msg)
        metadata_bytes = metadata_path.read_bytes()
        try:
            metadata = json.loads(metadata_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            msg = f"Kaggle metadata file is not valid JSON: {metadata_path}"
            raise ValueError(msg) from exc
        if metadata.get("id") != self._dataset:
            msg = (
                "Kaggle metadata dataset id does not match configured dataset: "
                f"{metadata.get('id')!r} != {self._dataset!r}"
            )
            raise ValueError(msg)

        resources = metadata.get("resources")
        if not isinstance(resources, list):
            msg = "Kaggle metadata resources must be a list"
            raise ValueError(msg)
        if not resources:
            msg = "Kaggle upload bundle has no declared data resources"
            raise ValueError(msg)

        resource_inventory: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        seen_resolved_paths: set[Path] = set()
        data_root = data_dir.resolve()
        for index, resource in enumerate(resources):
            if not isinstance(resource, dict):
                msg = f"Kaggle resource entry {index} must be an object"
                raise ValueError(msg)
            resource = cast("dict[str, Any]", resource)
            raw_path = resource.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                msg = f"Kaggle resource entry {index} is missing a non-empty path"
                raise ValueError(msg)
            normalized_path = self._normalize_resource_path(raw_path)
            if normalized_path in seen_paths:
                msg = f"Kaggle metadata declares duplicate resource path: {normalized_path}"
                raise ValueError(msg)
            overlapping_path = next(
                (
                    seen_path
                    for seen_path in seen_paths
                    if self._resource_paths_overlap(normalized_path, seen_path)
                ),
                None,
            )
            if overlapping_path is not None:
                msg = (
                    "Kaggle metadata declares overlapping resource paths: "
                    f"{normalized_path} and {overlapping_path}"
                )
                raise ValueError(msg)
            seen_paths.add(normalized_path)
            resource_path = Path(normalized_path)
            current_path = data_root
            has_symlink_component = False
            for part in resource_path.parts:
                current_path /= part
                if current_path.is_symlink():
                    has_symlink_component = True
                    break
            if has_symlink_component:
                msg = f"Kaggle resource path must not be a symlink: {normalized_path}"
                raise ValueError(msg)
            resolved_resource_path = (data_root / resource_path).resolve()
            try:
                resolved_resource_path.relative_to(data_root)
            except ValueError as exc:
                msg = f"Kaggle resource path escapes data directory: {raw_path}"
                raise ValueError(msg) from exc
            if resolved_resource_path in seen_resolved_paths:
                msg = f"Kaggle metadata declares duplicate resolved resource: {normalized_path}"
                raise ValueError(msg)
            seen_resolved_paths.add(resolved_resource_path)
            if resolved_resource_path.is_file():
                database_validation = self._database_validation_for_resource(
                    resolved_resource_path,
                    normalized_path,
                )
                parquet_validation = self._parquet_validation_for_resource(
                    resolved_resource_path,
                    normalized_path,
                )
                csv_validation = (
                    self._validate_csv_file(resolved_resource_path, normalized_path)
                    if require_terminal_assurance
                    and PurePosixPath(normalized_path).suffix.lower() == ".csv"
                    else None
                )
                inventory: dict[str, Any] = {
                    "path": normalized_path,
                    "source_path": str(resolved_resource_path),
                    "kind": "file",
                    "bytes": resolved_resource_path.stat().st_size,
                    "sha256": self._file_sha256(resolved_resource_path),
                }
                if database_validation is not None:
                    inventory["database_validation"] = database_validation
                if parquet_validation is not None:
                    inventory["parquet_validation"] = parquet_validation
                if csv_validation is not None:
                    inventory["csv_validation"] = csv_validation
                resource_inventory.append(inventory)
                continue
            if resolved_resource_path.is_dir():
                directory_inventory = self._directory_inventory(resolved_resource_path)
                self._validate_directory_resource_inventory(
                    normalized_path,
                    directory_inventory,
                    resolved_resource_path,
                )
                resource_inventory.append(
                    {
                        "path": normalized_path,
                        "source_path": str(resolved_resource_path),
                        "kind": "directory",
                        "bytes": directory_inventory["bytes"],
                        "file_count": directory_inventory["file_count"],
                        "sha256": directory_inventory["fingerprint"],
                        "files": directory_inventory["files"],
                    }
                )
                continue
            if not resolved_resource_path.exists():
                msg = f"Kaggle resource path does not exist: {raw_path}"
                raise FileNotFoundError(msg)
            msg = f"Kaggle resource path is not a file or directory: {raw_path}"
            raise ValueError(msg)

        self._validate_database_resource_parity(resource_inventory)
        require_assured = require_assured or require_terminal_assurance
        provenance: dict[str, Any] | None = None
        assured_manifest: dict[str, Any] | None = None
        if require_assured and ASSURED_ARTIFACT_MANIFEST_NAME not in seen_paths:
            msg = (
                "Assured Kaggle publication requires a declared "
                f"{ASSURED_ARTIFACT_MANIFEST_NAME} resource"
            )
            raise ValueError(msg)
        if ASSURED_ARTIFACT_MANIFEST_NAME in seen_paths:
            assured_manifest = verify_assured_artifact_manifest(data_root)
            declared_files = self._flatten_resource_file_inventory(resource_inventory)
            if declared_files != assured_manifest["files"]:
                msg = (
                    "Assured artifact inventory does not exactly match declared "
                    "Kaggle data resources"
                )
                raise ValueError(msg)
            provenance = {
                "chain_id": assured_manifest["chain_id"],
                "source_sha": assured_manifest["source_sha"],
                "coverage_fingerprint": assured_manifest["coverage_fingerprint"],
                "data_tree_fingerprint": assured_manifest["data_tree_fingerprint"],
            }
        terminal_assurance: dict[str, Any] | None = None
        prevalidation_installed_public_tree_sha256: str | None = None
        if require_terminal_assurance:
            if TERMINAL_ASSURANCE_REPORT_NAME not in seen_paths:
                msg = (
                    "Full Kaggle publication requires a declared "
                    f"{TERMINAL_ASSURANCE_REPORT_NAME} resource"
                )
                raise ValueError(msg)
            if assured_manifest is None:
                msg = "Full Kaggle publication requires a valid assured artifact manifest"
                raise ValueError(msg)
            prevalidation_installed_public_tree_sha256 = measure_installed_public_tree(
                data_root
            ).installed_public_tree_sha256
            terminal_assurance = self._validate_terminal_assurance_report(
                data_root / TERMINAL_ASSURANCE_REPORT_NAME,
                assured_manifest=assured_manifest,
                resource_inventory=resource_inventory,
                installed_public_tree_sha256=(prevalidation_installed_public_tree_sha256),
                successor_generation_store=successor_generation_store,
                successor_data_root=data_root,
                require_successor_current_authority=(require_successor_current_authority),
            )
            from nbadb.kaggle.metadata import expected_full_publication_resource_contract

            expected_contract = expected_full_publication_resource_contract(data_root)
            expected_paths = set(expected_contract)
            missing_paths = sorted(expected_paths - seen_paths)
            unexpected_paths = sorted(seen_paths - expected_paths)
            if missing_paths or unexpected_paths:
                msg = (
                    "Full Kaggle publication resource inventory is incomplete or unexpected: "
                    f"missing={missing_paths}; unexpected={unexpected_paths}"
                )
                raise ValueError(msg)
            actual_contract = {
                str(resource["path"]): str(resource["kind"]) for resource in resource_inventory
            }
            kind_mismatches = {
                path: {"expected": expected_contract[path], "actual": actual_contract[path]}
                for path in sorted(expected_paths)
                if actual_contract[path] != expected_contract[path]
            }
            if kind_mismatches:
                msg = (
                    "Full Kaggle publication resource kinds do not match the required contract: "
                    f"{kind_mismatches}"
                )
                raise ValueError(msg)
            self._validate_full_publication_format_parity(
                resource_inventory,
                require_authoritative_values=True,
            )
        installed_public_tree = measure_installed_public_tree(data_root)
        installed_public_tree_sha256 = installed_public_tree.installed_public_tree_sha256
        if (
            prevalidation_installed_public_tree_sha256 is not None
            and installed_public_tree_sha256 != prevalidation_installed_public_tree_sha256
        ):
            raise ValueError("Kaggle public tree changed during full publication validation")
        self._assert_snapshot_resources_match_installed_tree(
            installed_public_tree,
            metadata_bytes=metadata_bytes,
            resource_inventory=resource_inventory,
        )
        identity_resources = [
            {
                "path": resource["path"],
                "kind": resource["kind"],
                "bytes": resource["bytes"],
                "sha256": resource["sha256"],
                **(
                    {
                        "file_count": resource["file_count"],
                        "files": resource["files"],
                    }
                    if resource["kind"] == "directory"
                    else {}
                ),
            }
            for resource in resource_inventory
        ]
        fingerprint_payload = {
            "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
            "resources": sorted(identity_resources, key=lambda resource: resource["path"]),
        }
        fingerprint_source = json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        resource_bytes = 0
        for resource in resource_inventory:
            byte_count = resource["bytes"]
            if type(byte_count) is not int or byte_count < 0:
                raise ValueError("Kaggle declared resource byte count is invalid")
            if byte_count > _MAX_SIGNED_63 - resource_bytes:
                raise ValueError("Kaggle declared resource bytes exceed signed-63-bit range")
            resource_bytes += byte_count
        return {
            "dataset": self._dataset,
            "metadata_path": str(metadata_path),
            "metadata_bytes": len(metadata_bytes),
            "metadata_sha256": fingerprint_payload["metadata_sha256"],
            "resource_count": len(resource_inventory),
            "resource_bytes": resource_bytes,
            "resources": sorted(resource_inventory, key=lambda resource: resource["path"]),
            "fingerprint": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
            "installed_public_tree_sha256": installed_public_tree_sha256,
            "installed_public_tree_bytes": installed_public_tree.byte_count,
            "provenance": provenance,
            "terminal_assurance": terminal_assurance,
        }

    @staticmethod
    def _assert_snapshot_resources_match_installed_tree(
        installed_public_tree: InstalledPublicTreeInventory,
        *,
        metadata_bytes: bytes,
        resource_inventory: list[dict[str, Any]],
    ) -> None:
        """Bind declared resource evidence to the same final tree inventory.

        Resource validators intentionally run before the final complete-tree
        measurement.  This exact subset comparison prevents a same-length
        mutation between those phases from pairing stale resource evidence
        with a newer installed-tree digest.
        """

        installed_files = {
            str(item["path"]): {
                "bytes": int(item["bytes"]),
                "sha256": str(item["sha256"]),
            }
            for item in installed_public_tree.to_inventory()
        }
        expected_metadata = {
            "bytes": len(metadata_bytes),
            "sha256": hashlib.sha256(metadata_bytes).hexdigest(),
        }
        if installed_files.get("dataset-metadata.json") != expected_metadata:
            raise ValueError("Kaggle metadata changed before the final installed-tree inventory")

        for resource in resource_inventory:
            resource_path = str(resource["path"])
            if resource["kind"] == "file":
                expected_file = {
                    "bytes": int(resource["bytes"]),
                    "sha256": str(resource["sha256"]),
                }
                if installed_files.get(resource_path) != expected_file:
                    raise ValueError(
                        "Kaggle declared resource changed before the final installed-tree "
                        f"inventory: {resource_path}"
                    )
                continue

            prefix = f"{resource_path}/"
            expected_children = {
                f"{resource_path}/{child['path']}": {
                    "bytes": int(child["bytes"]),
                    "sha256": str(child["sha256"]),
                }
                for child in resource["files"]
            }
            observed_children = {
                path: evidence
                for path, evidence in installed_files.items()
                if path.startswith(prefix)
            }
            if observed_children != expected_children:
                raise ValueError(
                    "Kaggle declared directory resource changed before the final "
                    f"installed-tree inventory: {resource_path}"
                )

    @classmethod
    def _validate_terminal_assurance_report(
        cls,
        report_path: Path,
        *,
        assured_manifest: dict[str, Any],
        resource_inventory: list[dict[str, Any]] | None = None,
        installed_public_tree_sha256: str | None = None,
        successor_generation_store: SuccessorGenerationStore | None = None,
        successor_data_root: Path | None = None,
        require_successor_current_authority: bool = False,
    ) -> dict[str, Any]:
        try:
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            msg = "Terminal assurance report is not valid JSON"
            raise ValueError(msg) from exc
        if not isinstance(report, dict) or type(report.get("schema_version")) is not int:
            msg = "Terminal assurance report has an unsupported schema"
            raise ValueError(msg)
        report = cast("dict[str, Any]", report)
        if successor_generation_store is not None and report["schema_version"] != 7:
            msg = (
                "Schema-v7 successor authority is required when a successor "
                "generation store is supplied; leftover full-extraction terminal "
                "report cannot substitute"
            )
            raise ValueError(msg)
        if report["schema_version"] == 7:
            if require_successor_current_authority and successor_generation_store is None:
                msg = (
                    "Schema-v7 successor publication requires an explicit current generation store"
                )
                raise ValueError(msg)
            if not cls._is_lowercase_hex(installed_public_tree_sha256, length=64):
                msg = (
                    "Successor terminal assurance requires an external installed public tree "
                    "SHA-256"
                )
                raise ValueError(msg)
            return cls._validate_successor_terminal_assurance_report(
                report_bytes,
                assured_manifest=assured_manifest,
                resource_inventory=resource_inventory,
                installed_public_tree_sha256=cast("str", installed_public_tree_sha256),
                successor_generation_store=successor_generation_store,
                successor_data_root=successor_data_root,
                require_successor_current_authority=(require_successor_current_authority),
            )
        if report["schema_version"] != 3:
            msg = "Terminal assurance report has an unsupported schema"
            raise ValueError(msg)

        try:
            provider_authority = normalize_nba_api_provider_authority(
                report.get("provider_authority")
            )
        except ValueError as exc:
            msg = f"Terminal assurance report provider authority is invalid: {exc}"
            raise ValueError(msg) from exc
        if report.get("provider_authority_sha256") != provider_authority["authority_sha256"]:
            msg = "Terminal assurance report provider authority digest does not match"
            raise ValueError(msg)

        chain_id = report.get("chain_id")
        if not isinstance(chain_id, str) or not chain_id.strip():
            msg = "Terminal assurance report chain_id is invalid"
            raise ValueError(msg)
        for field, length in {
            "source_sha": 40,
            "coverage_fingerprint": 64,
            "checkpoint_database_sha256": 64,
            "checkpoint_report_sha256": 64,
            "contract_blocked_evidence_sha256": 64,
        }.items():
            if not cls._is_lowercase_hex(report.get(field), length=length):
                msg = f"Terminal assurance report {field} is invalid"
                raise ValueError(msg)

        checkpoint_artifact_name = report.get("checkpoint_artifact_name")
        if not isinstance(checkpoint_artifact_name, str) or not checkpoint_artifact_name.strip():
            msg = "Terminal assurance report checkpoint_artifact_name is invalid"
            raise ValueError(msg)
        checkpoint_generation = report.get("checkpoint_generation")
        if type(checkpoint_generation) is not int or cast("int", checkpoint_generation) <= 0:
            msg = "Terminal assurance report checkpoint_generation is invalid"
            raise ValueError(msg)
        checkpoint_report = report.get("checkpoint_report")
        if not isinstance(checkpoint_report, dict):
            msg = "Terminal assurance report checkpoint_report is invalid"
            raise ValueError(msg)
        checkpoint_report = cast("dict[str, Any]", checkpoint_report)
        if checkpoint_report.get("provider_authority") != provider_authority:
            msg = "Terminal assurance checkpoint provider authority does not match"
            raise ValueError(msg)
        if (
            checkpoint_report.get("provider_authority_sha256")
            != provider_authority["authority_sha256"]
        ):
            msg = "Terminal assurance checkpoint provider authority digest does not match"
            raise ValueError(msg)
        checkpoint_report_sha256 = hashlib.sha256(
            json.dumps(
                checkpoint_report,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if report["checkpoint_report_sha256"] != checkpoint_report_sha256:
            msg = "Terminal assurance embedded checkpoint report digest does not match"
            raise ValueError(msg)

        from nbadb.orchestrate.full_extraction_control import (
            _validated_checkpoint_contract_blocked_evidence,
        )

        try:
            blocked_rows, evidence_sha256 = _validated_checkpoint_contract_blocked_evidence(
                checkpoint_report
            )
        except ValueError as exc:
            msg = f"Terminal assurance contract-blocked evidence is invalid: {exc}"
            raise ValueError(msg) from exc
        blocked_lane_count = len(blocked_rows)
        blocked_evidence = checkpoint_report.get("contract_blocked_evidence")
        checkpoint_bindings = {
            "chain_id": report["chain_id"],
            "source_sha": report["source_sha"],
            "coverage_fingerprint": report["coverage_fingerprint"],
            "artifact_name": checkpoint_artifact_name,
            "checkpoint_generation": checkpoint_generation,
            "database_sha256": report["checkpoint_database_sha256"],
            "contract_blocked_lane_count": blocked_lane_count,
            "contract_blocked_evidence": blocked_evidence,
            "contract_blocked_evidence_sha256": evidence_sha256,
            "provider_authority": provider_authority,
            "provider_authority_sha256": provider_authority["authority_sha256"],
        }
        for field, expected in checkpoint_bindings.items():
            if checkpoint_report.get(field) != expected:
                msg = f"Terminal assurance checkpoint report {field} does not match"
                raise ValueError(msg)
        expected_checkpoint_artifact_name = (
            f"full-extraction-checkpoint-{chain_id}-iter-{checkpoint_generation}"
        )
        if checkpoint_artifact_name != expected_checkpoint_artifact_name:
            msg = "Terminal assurance report checkpoint_artifact_name is not canonical"
            raise ValueError(msg)
        if checkpoint_report.get("terminal_ready") is not True:
            msg = "Terminal assurance checkpoint report is not terminal-ready"
            raise ValueError(msg)
        if checkpoint_report.get("active_lane_count") != 0:
            msg = "Terminal assurance checkpoint report still has active lanes"
            raise ValueError(msg)

        run_id = checkpoint_report.get("run_id")
        if not isinstance(run_id, str) or re.fullmatch(r"[1-9][0-9]*", run_id) is None:
            msg = "Terminal assurance checkpoint report run_id is invalid"
            raise ValueError(msg)
        raw_lane_ids = checkpoint_report.get("included_lane_ids")
        if not isinstance(raw_lane_ids, list) or not raw_lane_ids:
            msg = "Terminal assurance checkpoint report included_lane_ids must be non-empty"
            raise ValueError(msg)
        if any(not isinstance(lane_id, str) or not lane_id.strip() for lane_id in raw_lane_ids):
            msg = "Terminal assurance checkpoint report included_lane_ids are invalid"
            raise ValueError(msg)
        included_lane_ids = cast("list[str]", raw_lane_ids)
        if len(set(included_lane_ids)) != len(included_lane_ids):
            msg = "Terminal assurance checkpoint report included_lane_ids must be unique"
            raise ValueError(msg)

        raw_run_ids = checkpoint_report.get("included_run_ids")
        if not isinstance(raw_run_ids, list) or not raw_run_ids:
            msg = "Terminal assurance checkpoint report included_run_ids must be non-empty"
            raise ValueError(msg)
        if any(
            not isinstance(included_run_id, str)
            or re.fullmatch(r"[1-9][0-9]*", included_run_id) is None
            for included_run_id in raw_run_ids
        ):
            msg = "Terminal assurance checkpoint report included_run_ids must be positive integers"
            raise ValueError(msg)
        included_run_ids = cast("list[str]", raw_run_ids)
        if len(set(included_run_ids)) != len(included_run_ids) or run_id not in included_run_ids:
            msg = (
                "Terminal assurance checkpoint report included_run_ids must be unique and "
                "contain run_id"
            )
            raise ValueError(msg)

        raw_coverage_hashes = checkpoint_report.get("included_lane_coverage_hashes")
        if not isinstance(raw_coverage_hashes, dict):
            msg = "Terminal assurance checkpoint report included_lane_coverage_hashes is invalid"
            raise ValueError(msg)
        coverage_hashes = cast("dict[object, object]", raw_coverage_hashes)
        if set(coverage_hashes) != set(included_lane_ids):
            msg = (
                "Terminal assurance checkpoint report lane coverage hash inventory does not "
                "exactly match included_lane_ids"
            )
            raise ValueError(msg)
        invalid_coverage_hashes = sorted(
            str(lane_id)
            for lane_id, coverage_hash in coverage_hashes.items()
            if not isinstance(lane_id, str) or not cls._is_lowercase_hex(coverage_hash, length=64)
        )
        if invalid_coverage_hashes:
            msg = (
                "Terminal assurance checkpoint report has invalid lane coverage hashes: "
                + ", ".join(invalid_coverage_hashes)
            )
            raise ValueError(msg)

        complete_lane_count = checkpoint_report.get("complete_lane_count")
        manifest_lane_count = checkpoint_report.get("manifest_lane_count")
        if (
            type(complete_lane_count) is not int
            or complete_lane_count <= 0
            or complete_lane_count != len(included_lane_ids)
        ):
            msg = "Terminal assurance checkpoint report complete_lane_count is invalid"
            raise ValueError(msg)
        if (
            type(manifest_lane_count) is not int
            or manifest_lane_count != complete_lane_count + blocked_lane_count
        ):
            msg = (
                "Terminal assurance checkpoint report manifest_lane_count does not equal "
                "complete plus contract-blocked lanes"
            )
            raise ValueError(msg)

        empty_fields = (
            "missing_lane_ids",
            "skipped_complete_lane_ids",
            "current_lane_attestation_failures",
            "workload_contract_errors",
        )
        for field in empty_fields:
            value = checkpoint_report.get(field)
            if not isinstance(value, (list, dict)) or value:
                msg = f"Terminal assurance checkpoint report {field} must be empty"
                raise ValueError(msg)
        if checkpoint_report.get("skipped_lane_count") != 0:
            msg = "Terminal assurance checkpoint report skipped_lane_count must be zero"
            raise ValueError(msg)

        if report.get("contract_blocked_lane_count") != blocked_lane_count:
            msg = "Terminal assurance report contract-blocked evidence count does not match"
            raise ValueError(msg)
        if report.get("contract_blocked_evidence") != blocked_evidence:
            msg = "Terminal assurance report contract-blocked evidence does not match checkpoint"
            raise ValueError(msg)
        if report["contract_blocked_evidence_sha256"] != evidence_sha256:
            msg = "Terminal assurance report contract-blocked evidence digest does not match"
            raise ValueError(msg)

        for field in ("chain_id", "source_sha", "coverage_fingerprint"):
            if report[field] != assured_manifest[field]:
                msg = f"Terminal assurance report {field} does not match assured manifest"
                raise ValueError(msg)
        return {
            "schema_version": report["schema_version"],
            "chain_id": report["chain_id"],
            "source_sha": report["source_sha"],
            "coverage_fingerprint": report["coverage_fingerprint"],
            "checkpoint_artifact_name": checkpoint_artifact_name,
            "checkpoint_generation": checkpoint_generation,
            "checkpoint_database_sha256": report["checkpoint_database_sha256"],
            "checkpoint_report_sha256": checkpoint_report_sha256,
            "checkpoint_run_id": run_id,
            "included_lane_count": len(included_lane_ids),
            "included_run_count": len(included_run_ids),
            "contract_blocked_lane_count": blocked_lane_count,
            "contract_blocked_evidence_sha256": evidence_sha256,
            "provider_authority_sha256": provider_authority["authority_sha256"],
        }

    @classmethod
    def _validate_successor_terminal_assurance_report(
        cls,
        report_bytes: bytes,
        *,
        assured_manifest: dict[str, Any],
        resource_inventory: list[dict[str, Any]] | None,
        installed_public_tree_sha256: str,
        successor_generation_store: SuccessorGenerationStore | None,
        successor_data_root: Path | None,
        require_successor_current_authority: bool,
    ) -> dict[str, Any]:
        """Bind one canonical successor report to its exact public controls."""
        from nbadb.orchestrate.successor_assurance import (
            SuccessorAssuranceContractError,
            validate_successor_terminal_assurance_report,
        )

        if resource_inventory is None:
            msg = "Successor terminal assurance requires the strict resource inventory"
            raise ValueError(msg)
        try:
            report = validate_successor_terminal_assurance_report(report_bytes)
        except SuccessorAssuranceContractError as exc:
            msg = f"Successor terminal assurance report is invalid: {exc}"
            raise ValueError(msg) from exc

        for field in ("chain_id", "source_sha", "coverage_fingerprint"):
            if getattr(report, field) != assured_manifest.get(field):
                msg = f"Successor terminal assurance report {field} does not match assured manifest"
                raise ValueError(msg)
        assured_data_tree_fingerprint = assured_manifest.get("data_tree_fingerprint")
        if not cls._is_lowercase_hex(assured_data_tree_fingerprint, length=64):
            msg = "Successor assured manifest data_tree_fingerprint is invalid"
            raise ValueError(msg)

        normalized_resources: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        for index, resource in enumerate(resource_inventory):
            path = resource.get("path")
            kind = resource.get("kind")
            byte_count = resource.get("bytes")
            sha256 = resource.get("sha256")
            if not isinstance(path, str) or not path:
                msg = f"Successor strict resource {index} path is invalid"
                raise ValueError(msg)
            if path in seen_paths:
                msg = f"Successor strict resource inventory contains duplicate path: {path}"
                raise ValueError(msg)
            seen_paths.add(path)
            if not isinstance(kind, str) or not kind:
                msg = f"Successor strict resource {path} kind is invalid"
                raise ValueError(msg)
            if type(byte_count) is not int or cast("int", byte_count) < 0:
                msg = f"Successor strict resource {path} byte count is invalid"
                raise ValueError(msg)
            if not cls._is_lowercase_hex(sha256, length=64):
                msg = f"Successor strict resource {path} SHA-256 is invalid"
                raise ValueError(msg)
            normalized_resources.append(
                {
                    "path": path,
                    "kind": kind,
                    "bytes": byte_count,
                    "sha256": sha256,
                }
            )
        normalized_resources.sort(key=lambda item: item["path"])

        control_paths = {
            ASSURED_ARTIFACT_MANIFEST_NAME,
            TERMINAL_ASSURANCE_REPORT_NAME,
        }
        controls = {
            str(resource["path"]): resource
            for resource in normalized_resources
            if resource["path"] in control_paths
        }
        if set(controls) != control_paths:
            msg = "Successor strict resource inventory lacks the exact assurance controls"
            raise ValueError(msg)
        if any(control["kind"] != "file" for control in controls.values()):
            msg = "Successor assurance controls must both be regular file resources"
            raise ValueError(msg)

        actual_data_resources = [
            resource for resource in normalized_resources if resource["path"] not in control_paths
        ]
        expected_data_resources = [
            {
                "path": resource.resource_id,
                "kind": resource.kind,
                "bytes": resource.bytes,
                "sha256": resource.sha256,
            }
            for resource in report.public_evidence.resources
        ]
        if actual_data_resources != expected_data_resources:
            msg = (
                "Successor terminal assurance data resources do not exactly match "
                "the strict Kaggle inventory"
            )
            raise ValueError(msg)

        try:
            flattened_resources = cls._flatten_resource_file_inventory(resource_inventory)
        except (KeyError, TypeError, ValueError) as exc:
            msg = "Successor strict resource inventory cannot be flattened safely"
            raise ValueError(msg) from exc
        if flattened_resources != assured_manifest.get("files"):
            msg = (
                "Successor assured manifest file hashes do not exactly match "
                "the strict Kaggle inventory"
            )
            raise ValueError(msg)

        report_resource = controls[TERMINAL_ASSURANCE_REPORT_NAME]
        report_sha256 = hashlib.sha256(report_bytes).hexdigest()
        if (
            report_resource["bytes"] != len(report_bytes)
            or report_resource["sha256"] != report_sha256
            or report.content_sha256 != report_sha256
        ):
            msg = "Successor terminal assurance report resource hash does not match its bytes"
            raise ValueError(msg)
        manifest_report_entries = [
            item
            for item in cast("list[dict[str, Any]]", assured_manifest["files"])
            if item.get("path") == TERMINAL_ASSURANCE_REPORT_NAME
        ]
        expected_report_entry = {
            "path": TERMINAL_ASSURANCE_REPORT_NAME,
            "bytes": report_resource["bytes"],
            "sha256": report_resource["sha256"],
        }
        if manifest_report_entries != [expected_report_entry]:
            msg = "Successor assured manifest does not bind the exact terminal report resource"
            raise ValueError(msg)

        manifest_resource = controls[ASSURED_ARTIFACT_MANIFEST_NAME]
        assurance_identity = report.to_successor_assurance_identity(
            successor_assured_manifest_sha256=cast("str", manifest_resource["sha256"]),
            installed_public_tree_sha256=installed_public_tree_sha256,
        )
        if (
            assurance_identity.successor_validation_report_sha256 != report_resource["sha256"]
            or assurance_identity.successor_assured_manifest_sha256 != manifest_resource["sha256"]
            or assurance_identity.planned_route_replacement_bindings_sha256
            != report.planned_route_replacement_bindings_sha256
        ):
            msg = "Successor report, route bindings, and control-resource identity do not reconcile"
            raise ValueError(msg)
        if require_successor_current_authority:
            if successor_generation_store is None or successor_data_root is None:
                msg = (
                    "Schema-v7 successor publication requires an explicit current "
                    "generation store and public root"
                )
                raise ValueError(msg)
            cls._require_successor_current_publication_authority(
                data_root=successor_data_root,
                generation_store=successor_generation_store,
                assurance_identity=assurance_identity,
                installed_public_tree_sha256=installed_public_tree_sha256,
            )

        baseline = report.baseline
        normalized: dict[str, Any] = assurance_identity.to_dict()
        normalized.update(
            {
                "schema_version": report.schema_version,
                "kind": report.kind,
                "model_green": report.model_green,
                "data_green": report.data_green,
                "chain_id": report.chain_id,
                "coverage_fingerprint": report.coverage_fingerprint,
                # BaselineAssuranceIdentity retains these legacy field names, but a
                # successor publication must bind its newly installed DuckDB and
                # canonical report rather than silently reusing its parent's bytes.
                "checkpoint_database_sha256": report.database_evidence.duckdb_sha256,
                "checkpoint_report_sha256": report.content_sha256,
                "inherited_baseline_checkpoint_database_sha256": (
                    baseline.checkpoint_database_sha256
                ),
                "inherited_baseline_checkpoint_report_sha256": (baseline.checkpoint_report_sha256),
                "contract_blocked_lane_count": report.contract_blocked_lane_count,
                "contract_blocked_evidence_sha256": (baseline.contract_blocked_evidence_sha256),
                "provider_authority_sha256": baseline.provider_authority_sha256,
                "planning_generation_manifest_sha256": (report.planning_generation_manifest_sha256),
                "execution_plan_sha256": report.execution_plan_sha256,
                "planning_artifact_identity_sha256": (
                    report.planning_evidence.execution_plan.planning_artifact_identity_sha256
                ),
                "planning_manifest_sha256": (
                    report.planning_evidence.execution_plan.planning_manifest_sha256
                ),
                "sealed_dispatch_inventory_sha256": (
                    report.planning_evidence.execution_plan.sealed_dispatch_inventory_sha256
                ),
                "planning_generation_id": (
                    report.planning_evidence.execution_plan.planning_generation_id
                ),
                "build_sha256": report.build_sha256,
                "delta_coverage_sha256": report.delta_coverage_sha256,
                "transform_output_count": report.transform_output_count,
                "assured_manifest_data_tree_fingerprint": (assured_data_tree_fingerprint),
                "successor_assurance_identity_sha256": assurance_identity.identity_sha256,
            }
        )
        return normalized

    @classmethod
    def _require_successor_current_publication_authority(
        cls,
        *,
        data_root: Path,
        generation_store: SuccessorGenerationStore,
        assurance_identity: SuccessorAssuranceIdentity,
        installed_public_tree_sha256: str,
    ) -> None:
        """Bind schema-v7 publication to the store's exact frozen current tree."""

        from nbadb.orchestrate.successor_publication_authority import (
            require_successor_current_publication_authority,
        )

        require_successor_current_publication_authority(
            data_root=data_root,
            generation_store=generation_store,
            assurance_identity=assurance_identity,
            installed_public_tree_sha256=installed_public_tree_sha256,
        )

    @staticmethod
    def _flatten_resource_file_inventory(
        resource_inventory: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for resource in resource_inventory:
            resource_path = str(resource["path"])
            if resource_path == ASSURED_ARTIFACT_MANIFEST_NAME:
                continue
            if resource["kind"] == "file":
                files.append(
                    {
                        "path": resource_path,
                        "bytes": resource["bytes"],
                        "sha256": resource["sha256"],
                    }
                )
                continue
            for child in resource["files"]:
                files.append(
                    {
                        "path": f"{resource_path}/{child['path']}",
                        "bytes": child["bytes"],
                        "sha256": child["sha256"],
                    }
                )
        return sorted(files, key=lambda item: item["path"])

    def _stage_upload_bundle(
        self,
        source_dir: Path,
        staged_dir: Path,
        preflight: dict[str, Any],
    ) -> dict[str, Any]:
        self._stage_file_from_inventory(
            source_path=source_dir / "dataset-metadata.json",
            destination=staged_dir / "dataset-metadata.json",
            inventory={
                "path": "dataset-metadata.json",
                "bytes": preflight["metadata_bytes"],
                "sha256": preflight["metadata_sha256"],
            },
        )
        staged_paths: set[str] = {"dataset-metadata.json"}
        for resource in preflight["resources"]:
            relative_path = resource["path"]
            if relative_path in staged_paths:
                msg = f"Kaggle staged bundle path collision: {relative_path}"
                raise ValueError(msg)
            staged_paths.add(relative_path)
            source_path = Path(resource["source_path"])
            destination = staged_dir / relative_path
            if resource["kind"] == "file":
                self._stage_file_from_inventory(
                    source_path=source_path,
                    destination=destination,
                    inventory=resource,
                )
            elif resource["kind"] == "directory":
                for file_inventory in resource["files"]:
                    child_relative_path = file_inventory["path"]
                    staged_child_path = f"{relative_path}/{child_relative_path}"
                    self._stage_file_from_inventory(
                        source_path=source_path / child_relative_path,
                        destination=staged_dir / staged_child_path,
                        inventory={
                            "path": staged_child_path,
                            "bytes": file_inventory["bytes"],
                            "sha256": file_inventory["sha256"],
                        },
                    )
            else:
                msg = f"Unsupported Kaggle resource kind: {resource['kind']}"
                raise ValueError(msg)
        return self._snapshot_tree(staged_dir)

    def _write_upload_manifest(
        self,
        *,
        data_dir: Path,
        staged_dir: Path | None = None,
        version_notes: str,
        status: str,
        preflight: dict[str, Any],
        post_upload: dict[str, Any] | None = None,
        remote_readback: dict[str, Any] | None = None,
        publication: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Path:
        manifest_dir = self._settings.log_dir / "kaggle"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "kaggle-upload-manifest.json"
        manifest: dict[str, Any] = {
            "schema_version": 2,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": status,
            "dataset": self._dataset,
            "data_dir": "<data-root>",
            "staged_dir": "<staged-upload-root>" if staged_dir is not None else None,
            "version_notes": version_notes,
            "preflight": self._persistable_preflight(preflight),
            "serialization": UPLOAD_SERIALIZATION_CONTRACT,
        }
        if post_upload is not None:
            manifest["post_upload"] = self._persistable_tree_snapshot(post_upload)
        if remote_readback is not None:
            manifest["remote_readback"] = remote_readback
        if publication is not None:
            manifest["publication"] = publication
        if error is not None:
            manifest["error"] = error
        sanitized = self._redact_persisted_error_fields(manifest)
        sanitized = self._redact_local_authority(
            sanitized,
            data_dir=data_dir,
            staged_dir=staged_dir,
        )
        self._atomic_write_json(manifest_path, cast("dict[str, Any]", sanitized))
        return manifest_path

    @classmethod
    def _persistable_preflight(cls, value: Any) -> Any:
        """Remove local filesystem authority from the diagnostic upload manifest."""

        if isinstance(value, dict):
            persisted: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key)
                if normalized_key == "source_path":
                    continue
                if normalized_key == "metadata_path":
                    persisted[normalized_key] = "dataset-metadata.json"
                    continue
                if normalized_key == "root":
                    persisted[normalized_key] = "<staged-upload-root>"
                    continue
                persisted[normalized_key] = cls._persistable_preflight(item)
            return persisted
        if isinstance(value, (list, tuple)):
            return [cls._persistable_preflight(item) for item in value]
        return value

    @staticmethod
    def _persistable_tree_snapshot(value: dict[str, Any]) -> dict[str, Any]:
        persisted = dict(value)
        if "root" in persisted:
            persisted["root"] = "<staged-upload-root>"
        return persisted

    @classmethod
    def _redact_local_authority(
        cls,
        value: Any,
        *,
        data_dir: Path,
        staged_dir: Path | None,
    ) -> Any:
        """Replace known local roots before diagnostic state is persisted."""

        replacements = sorted(
            (
                (str(path), label)
                for path, label in (
                    (data_dir, "<data-root>"),
                    (staged_dir, "<staged-upload-root>"),
                )
                if path is not None and path.is_absolute()
            ),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        if isinstance(value, dict):
            return {
                key: cls._redact_local_authority(
                    item,
                    data_dir=data_dir,
                    staged_dir=staged_dir,
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                cls._redact_local_authority(
                    item,
                    data_dir=data_dir,
                    staged_dir=staged_dir,
                )
                for item in value
            ]
        if isinstance(value, str):
            for local_root, label in replacements:
                value = value.replace(local_root, label)
        return value

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _atomic_write_canonical_json_no_replace(
        path: Path,
        payload: dict[str, Any],
    ) -> None:
        """Publish canonical JSON atomically without replacing prior authority."""
        path.parent.mkdir(parents=True, exist_ok=True)
        canonical_bytes = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        parent_descriptor = -1
        named_temporary_descriptor = -1
        temporary_identity: tuple[int, int] | None = None
        published_identity: tuple[int, int] | None = None

        def require_owner_only_regular_file(
            observed: os.stat_result,
            *,
            expected_identity: tuple[int, int],
            expected_links: int,
            label: str,
        ) -> None:
            if (
                not stat.S_ISREG(observed.st_mode)
                or _directory_identity(observed) != expected_identity
                or observed.st_nlink != expected_links
                or stat.S_IMODE(observed.st_mode) != 0o600
                or (os.name == "posix" and observed.st_uid != os.geteuid())
            ):
                raise RuntimeError(f"{label} differs from the admitted file authority")

        canonical_sha256 = hashlib.sha256(canonical_bytes).digest()

        def require_canonical_descriptor(
            descriptor: int,
            *,
            expected_identity: tuple[int, int],
            expected_links: int,
            label: str,
        ) -> None:
            before = os.fstat(descriptor)
            require_owner_only_regular_file(
                before,
                expected_identity=expected_identity,
                expected_links=expected_links,
                label=label,
            )
            if before.st_size != len(canonical_bytes):
                raise RuntimeError(f"{label} content changed")
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            remaining = len(canonical_bytes) + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            observed_bytes = b"".join(chunks)
            after = os.fstat(descriptor)
            require_owner_only_regular_file(
                after,
                expected_identity=expected_identity,
                expected_links=expected_links,
                label=label,
            )
            if (
                after.st_size != len(canonical_bytes)
                or not secrets.compare_digest(
                    hashlib.sha256(observed_bytes).digest(),
                    canonical_sha256,
                )
                or observed_bytes != canonical_bytes
            ):
                raise RuntimeError(f"{label} content changed")

        def require_named_canonical_file(
            name: str,
            *,
            expected_identity: tuple[int, int],
            expected_links: int,
            label: str,
        ) -> None:
            nonlocal named_temporary_descriptor
            before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            require_owner_only_regular_file(
                before,
                expected_identity=expected_identity,
                expected_links=expected_links,
                label=label,
            )
            named_temporary_descriptor = os.open(
                name,
                _FILE_READ_FLAGS | getattr(os, "O_NONBLOCK", 0),
                dir_fd=parent_descriptor,
            )
            try:
                require_canonical_descriptor(
                    named_temporary_descriptor,
                    expected_identity=expected_identity,
                    expected_links=expected_links,
                    label=label,
                )
                after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
                require_owner_only_regular_file(
                    after,
                    expected_identity=expected_identity,
                    expected_links=expected_links,
                    label=label,
                )
            finally:
                os.close(named_temporary_descriptor)
                named_temporary_descriptor = -1

        def require_retained_parent_path() -> None:
            retained_parent = os.fstat(parent_descriptor)
            retained_identity = _directory_identity(retained_parent)
            before = os.stat(path.parent, follow_symlinks=False)
            observed_descriptor = _open_stable_directory(
                path.parent,
                label="verified public baseline receipt final parent",
            )
            try:
                opened = os.fstat(observed_descriptor)
                after = os.stat(path.parent, follow_symlinks=False)
                if (
                    not stat.S_ISDIR(retained_parent.st_mode)
                    or not stat.S_ISDIR(before.st_mode)
                    or not stat.S_ISDIR(opened.st_mode)
                    or not stat.S_ISDIR(after.st_mode)
                    or _directory_identity(before) != retained_identity
                    or _directory_identity(opened) != retained_identity
                    or _directory_identity(after) != retained_identity
                ):
                    raise RuntimeError(
                        "verified public baseline receipt parent changed during finalization"
                    )
            finally:
                os.close(observed_descriptor)

        def close_non_authoritative(descriptor: int, *, label: str) -> None:
            try:
                os.close(descriptor)
            except OSError as exc:
                logger.warning(
                    "Verified public baseline receipt {} descriptor cleanup failed: {}",
                    label,
                    type(exc).__name__,
                )

        def retire_temporary_name(*, required: bool) -> None:
            nonlocal parent_descriptor
            if temporary_identity is None:
                if required:
                    raise RuntimeError(
                        "verified public baseline receipt temporary authority is unavailable"
                    )
                return
            if parent_descriptor < 0:
                try:
                    parent_descriptor = _open_stable_directory(
                        path.parent,
                        label="verified public baseline receipt cleanup parent",
                    )
                except (OSError, RuntimeError):
                    if required:
                        raise RuntimeError(
                            "verified public baseline receipt temporary cleanup parent is "
                            "unavailable"
                        ) from None
                    return
            try:
                named = os.stat(
                    temporary_path.name,
                    dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                if required:
                    raise RuntimeError(
                        "verified public baseline receipt temporary is missing"
                    ) from None
                return
            if not stat.S_ISREG(named.st_mode) or _directory_identity(named) != temporary_identity:
                if required:
                    raise RuntimeError(
                        "verified public baseline receipt temporary differs from the admitted "
                        "file authority"
                    )
                return
            if required:
                require_owner_only_regular_file(
                    named,
                    expected_identity=temporary_identity,
                    expected_links=2,
                    label="verified public baseline receipt temporary",
                )
            _unlink_named_regular_file_authority(
                parent_descriptor,
                temporary_path.name,
                expected_identity=temporary_identity,
                label="verified public baseline receipt temporary",
            )

        try:
            retained = os.fstat(file_descriptor)
            temporary_identity = _directory_identity(retained)
            require_owner_only_regular_file(
                retained,
                expected_identity=temporary_identity,
                expected_links=1,
                label="verified public baseline receipt retained temporary",
            )
            os.fchmod(file_descriptor, 0o600)
            pending = memoryview(canonical_bytes)
            while pending:
                written = os.write(file_descriptor, pending)
                if written <= 0:
                    raise OSError(errno.EIO, "canonical receipt write made no progress")
                pending = pending[written:]
            os.fsync(file_descriptor)
            retained = os.fstat(file_descriptor)
            require_owner_only_regular_file(
                retained,
                expected_identity=temporary_identity,
                expected_links=1,
                label="verified public baseline receipt retained temporary",
            )
            require_canonical_descriptor(
                file_descriptor,
                expected_identity=temporary_identity,
                expected_links=1,
                label="verified public baseline receipt retained temporary",
            )
            parent_descriptor = _open_stable_directory(
                path.parent,
                label="verified public baseline receipt parent",
            )
            require_named_canonical_file(
                temporary_path.name,
                expected_identity=temporary_identity,
                expected_links=1,
                label="verified public baseline receipt temporary",
            )
            require_canonical_descriptor(
                file_descriptor,
                expected_identity=temporary_identity,
                expected_links=1,
                label="verified public baseline receipt retained temporary",
            )
            os.link(
                temporary_path.name,
                path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            published_identity = temporary_identity
            require_named_canonical_file(
                path.name,
                expected_identity=published_identity,
                expected_links=2,
                label="verified public baseline receipt",
            )
            os.fsync(parent_descriptor)
            require_named_canonical_file(
                path.name,
                expected_identity=published_identity,
                expected_links=2,
                label="verified public baseline receipt",
            )
            retire_temporary_name(required=True)
            os.fsync(parent_descriptor)
            _require_named_regular_file_authority(
                parent_descriptor,
                path.name,
                expected_identity=published_identity,
                label="verified public baseline receipt",
            )
            require_named_canonical_file(
                path.name,
                expected_identity=published_identity,
                expected_links=1,
                label="verified public baseline receipt",
            )
            require_canonical_descriptor(
                file_descriptor,
                expected_identity=published_identity,
                expected_links=1,
                label="verified public baseline receipt retained temporary",
            )
            require_retained_parent_path()
            published_identity = None
        except BaseException:
            cleanup_error: BaseException | None = None
            if published_identity is not None and parent_descriptor >= 0:
                try:
                    _unlink_named_regular_file_authority(
                        parent_descriptor,
                        path.name,
                        expected_identity=published_identity,
                        label="verified public baseline receipt",
                    )
                except BaseException as exc:
                    cleanup_error = exc
            try:
                retire_temporary_name(required=False)
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
            if cleanup_error is not None:
                raise RuntimeError(
                    "verified public baseline receipt finalization and exact cleanup failed"
                ) from cleanup_error
            raise
        finally:
            if named_temporary_descriptor >= 0:
                close_non_authoritative(
                    named_temporary_descriptor,
                    label="named file",
                )
            if parent_descriptor >= 0:
                close_non_authoritative(parent_descriptor, label="parent")
            close_non_authoritative(file_descriptor, label="retained file")

    def _public_baseline_receipt_payload(
        self,
        *,
        exact_version: int,
        exact_dataset_handle: str,
        marker: dict[str, Any],
        remote_tree: dict[str, Any],
        snapshot: dict[str, Any],
        installed_tree: InstalledPublicTreeInventory,
        durable_ledger_checked: bool,
        durable_resolution: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build the canonical, public-only baseline receipt envelope."""
        provenance = snapshot.get("provenance")
        terminal_assurance = snapshot.get("terminal_assurance")
        if not isinstance(provenance, dict) or not isinstance(terminal_assurance, dict):
            raise ValueError("verified public baseline lacks complete assurance provenance")
        resource_index = {
            str(resource["path"]): resource
            for resource in cast("list[dict[str, Any]]", snapshot["resources"])
        }
        assured_resource = resource_index.get(ASSURED_ARTIFACT_MANIFEST_NAME)
        terminal_resource = resource_index.get(TERMINAL_ASSURANCE_REPORT_NAME)
        if assured_resource is None or terminal_resource is None:
            raise ValueError("verified public baseline lacks exact assurance control resources")

        body = {
            "dataset": self._dataset,
            "exact_dataset_handle": exact_dataset_handle,
            "remote_dataset_version": exact_version,
            "publication_marker_sha256": hashlib.sha256(
                self._publication_marker_bytes(marker)
            ).hexdigest(),
            "publish_key": marker["publish_key"],
            "remote_inventory": {
                "file_count": remote_tree["file_count"],
                "bytes": remote_tree["bytes"],
                "sha256": remote_tree["fingerprint"],
                "content_identity": "exact_api_inventory_and_sha256_full_readback",
            },
            "validated_bundle": {
                "resource_count": snapshot["resource_count"],
                "resource_bytes": snapshot["resource_bytes"],
                "fingerprint_sha256": snapshot["fingerprint"],
                "installed_public_tree_sha256": (installed_tree.installed_public_tree_sha256),
                "installed_public_tree_bytes": installed_tree.byte_count,
                "assured_manifest_sha256": assured_resource["sha256"],
                "terminal_assurance_report_sha256": terminal_resource["sha256"],
            },
            "provenance": provenance,
            "terminal_assurance": {
                field: terminal_assurance[field]
                for field in (
                    "chain_id",
                    "source_sha",
                    "coverage_fingerprint",
                    "checkpoint_database_sha256",
                    "checkpoint_report_sha256",
                    "contract_blocked_evidence_sha256",
                    "provider_authority_sha256",
                )
            },
            "durable_reconciliation": {
                "ledger": "github_deployment" if durable_ledger_checked else None,
                "checked": durable_ledger_checked,
                "resolution": durable_resolution,
            },
        }
        receipt_sha256 = hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return {
            "schema_version": 1,
            "kind": "nbadb_verified_public_baseline_receipt",
            "receipt": body,
            "receipt_sha256": receipt_sha256,
        }

    @classmethod
    def _validate_verified_download_inventory(cls, inventory: object) -> int:
        """Validate exact-file topology and return its bounded payload byte count."""

        if not isinstance(inventory, list) or not inventory:
            raise ValueError("verified public baseline inventory must be a nonempty list")
        paths: set[str] = set()
        total_bytes = 0
        for item in inventory:
            if not isinstance(item, dict):
                raise ValueError("verified public baseline inventory entry must be an object")
            raw_path = item.get("path")
            byte_count = item.get("bytes")
            if not isinstance(raw_path, str) or "\x00" in raw_path:
                raise ValueError("verified public baseline inventory path is invalid")
            normalized_path = cls._normalize_resource_path(raw_path)
            if normalized_path != raw_path:
                raise ValueError(
                    f"verified public baseline inventory path is not canonical: {raw_path!r}"
                )
            if PurePosixPath(normalized_path).parts[0] == ".complete":
                raise ValueError(
                    "verified public baseline inventory uses reserved KaggleHub metadata path: "
                    f"{normalized_path}"
                )
            if normalized_path in paths:
                raise ValueError(
                    f"verified public baseline inventory contains duplicate path: {normalized_path}"
                )
            if (
                not isinstance(byte_count, int)
                or isinstance(byte_count, bool)
                or byte_count < 0
                or byte_count > _MAX_SIGNED_63
            ):
                raise ValueError(
                    f"verified public baseline inventory byte size is invalid: {normalized_path}"
                )
            if total_bytes > _MAX_SIGNED_63 - byte_count:
                raise OverflowError("verified public baseline inventory byte total exceeds int64")
            paths.add(normalized_path)
            total_bytes += byte_count

        for resource_path in paths:
            parts = PurePosixPath(resource_path).parts
            for part_count in range(1, len(parts)):
                parent_path = PurePosixPath(*parts[:part_count]).as_posix()
                if parent_path in paths:
                    raise ValueError(
                        "verified public baseline inventory contains a file/prefix collision: "
                        f"{parent_path}, {resource_path}"
                    )
        return total_bytes

    @staticmethod
    def _copy_verified_download_file(source: Path, destination: Path) -> None:
        """Copy one resolver payload into the clean candidate with no replacement."""

        source_before = os.stat(source, follow_symlinks=False)
        if not stat.S_ISREG(source_before.st_mode):
            raise ValueError("verified public baseline resolver source must be a regular file")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        source_descriptor = -1
        destination_descriptor = -1
        destination_created = False
        try:
            source_descriptor = os.open(source, _FILE_READ_FLAGS)
            source_opened = os.fstat(source_descriptor)
            if not stat.S_ISREG(source_opened.st_mode) or _directory_identity(
                source_opened
            ) != _directory_identity(source_before):
                raise RuntimeError("verified public baseline resolver source changed while opening")
            destination_descriptor = os.open(destination, _FILE_CREATE_FLAGS, 0o600)
            destination_created = True
            while True:
                chunk = os.read(source_descriptor, 1024 * 1024)
                if not chunk:
                    break
                remaining = memoryview(chunk)
                while remaining:
                    written = os.write(destination_descriptor, remaining)
                    if written <= 0:
                        raise OSError("verified public baseline candidate copy made no progress")
                    remaining = remaining[written:]
            os.fsync(destination_descriptor)
            source_after = os.fstat(source_descriptor)
            destination_after = os.fstat(destination_descriptor)
            if (
                _directory_identity(source_after) != _directory_identity(source_opened)
                or source_after.st_size != source_opened.st_size
                or source_after.st_mtime_ns != source_opened.st_mtime_ns
            ):
                raise RuntimeError("verified public baseline resolver source changed during copy")
            if not stat.S_ISREG(destination_after.st_mode):
                raise RuntimeError("verified public baseline candidate is not a regular file")
            if destination_after.st_size != source_after.st_size:
                raise RuntimeError("verified public baseline candidate copy is incomplete")
        except BaseException:
            if destination_descriptor >= 0:
                os.close(destination_descriptor)
                destination_descriptor = -1
            if source_descriptor >= 0:
                os.close(source_descriptor)
                source_descriptor = -1
            if destination_created:
                destination.unlink(missing_ok=True)
            raise
        finally:
            if destination_descriptor >= 0:
                os.close(destination_descriptor)
            if source_descriptor >= 0:
                os.close(source_descriptor)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _normalize_resource_path(raw_path: str) -> str:
        if "\\" in raw_path:
            msg = f"Kaggle resource path must use POSIX separators: {raw_path}"
            raise ValueError(msg)
        path = PurePosixPath(raw_path.strip())
        if path.is_absolute():
            msg = f"Kaggle resource path must be relative: {raw_path}"
            raise ValueError(msg)
        if not path.parts or any(part in ("", ".", "..") for part in path.parts):
            msg = f"Kaggle resource path must be a normalized relative path: {raw_path}"
            raise ValueError(msg)
        return path.as_posix()

    @staticmethod
    def _resource_paths_overlap(first_path: str, second_path: str) -> bool:
        return first_path.startswith(f"{second_path}/") or second_path.startswith(f"{first_path}/")

    @staticmethod
    def _validate_directory_resource_inventory(
        resource_path: str,
        directory_inventory: dict[str, Any],
        directory_path: Path,
    ) -> None:
        if int(directory_inventory.get("file_count", 0)) == 0:
            msg = f"Kaggle directory resource is empty: {resource_path}"
            raise ValueError(msg)
        for file_inventory in directory_inventory["files"]:
            relative_path = file_inventory["path"]
            parts = PurePosixPath(relative_path).parts
            if any(part.startswith(".") for part in parts):
                msg = (
                    "Kaggle resource directory contains hidden or ignored path: "
                    f"{resource_path}/{relative_path}"
                )
                raise ValueError(msg)
            if PurePosixPath(relative_path).suffix != ".parquet":
                msg = (
                    "Kaggle directory resources may only contain parquet files: "
                    f"{resource_path}/{relative_path}"
                )
                raise ValueError(msg)
            file_inventory["parquet_validation"] = KaggleClient._validate_parquet_file(
                directory_path / relative_path,
                f"{resource_path}/{relative_path}",
            )

    def _directory_inventory(self, path: Path) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        total_bytes = 0
        for child in sorted(path.rglob("*")):
            if child.is_symlink():
                msg = f"Kaggle resource directory contains symlink: {child}"
                raise ValueError(msg)
            if not child.is_file():
                continue
            relative_path = child.relative_to(path).as_posix()
            size = child.stat().st_size
            total_bytes += size
            files.append(
                {
                    "path": relative_path,
                    "bytes": size,
                    "sha256": self._file_sha256(child),
                }
            )
        fingerprint_source = json.dumps(files, sort_keys=True, separators=(",", ":"))
        return {
            "bytes": total_bytes,
            "file_count": len(files),
            "files": files,
            "fingerprint": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        }

    def _stage_file_from_inventory(
        self,
        *,
        source_path: Path,
        destination: Path,
        inventory: dict[str, Any],
    ) -> None:
        relative_path = inventory["path"]
        self._assert_file_matches_inventory(
            source_path,
            inventory,
            relative_path=relative_path,
            mismatch_message="Kaggle resource file changed before staging",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source_path, destination)
        except OSError as exc:
            if exc.errno not in {errno.EXDEV, errno.EPERM, errno.EACCES, errno.ENOTSUP}:
                raise
            self._require_disk_capacity(
                destination.parent,
                required_bytes=int(inventory["bytes"]) + _DISK_SAFETY_RESERVE_BYTES,
                operation=f"fallback staging copy of {relative_path}",
            )
            shutil.copy2(source_path, destination)
        self._assert_file_matches_inventory(
            destination,
            inventory,
            relative_path=relative_path,
            mismatch_message="Kaggle staged file does not match preflight inventory",
        )

    def _assert_file_matches_inventory(
        self,
        path: Path,
        inventory: dict[str, Any],
        *,
        relative_path: str,
        mismatch_message: str,
    ) -> None:
        if path.is_symlink():
            msg = f"Kaggle file inventory path must not be a symlink: {relative_path}"
            raise ValueError(msg)
        if not path.is_file():
            msg = f"Kaggle file inventory path does not exist: {relative_path}"
            raise FileNotFoundError(msg)
        size = path.stat().st_size
        digest = self._file_sha256(path)
        if size != inventory["bytes"] or digest != inventory["sha256"]:
            msg = f"{mismatch_message}: {relative_path}"
            raise ValueError(msg)

    @staticmethod
    def _require_disk_capacity(path: Path, *, required_bytes: int, operation: str) -> None:
        available_bytes = shutil.disk_usage(path).free
        if available_bytes < required_bytes:
            msg = (
                f"Insufficient disk capacity for Kaggle {operation}: "
                f"required={required_bytes}, available={available_bytes}"
            )
            raise OSError(errno.ENOSPC, msg)

    @staticmethod
    def _expected_staged_tree_snapshot(
        preflight: dict[str, Any],
        root: Path,
        *,
        publication_marker: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        files: list[dict[str, Any]] = [
            {
                "path": "dataset-metadata.json",
                "bytes": preflight["metadata_bytes"],
                "sha256": preflight["metadata_sha256"],
            }
        ]
        for resource in preflight["resources"]:
            if resource["kind"] == "file":
                files.append(
                    {
                        "path": resource["path"],
                        "bytes": resource["bytes"],
                        "sha256": resource["sha256"],
                    }
                )
                continue
            if resource["kind"] == "directory":
                for file_inventory in resource["files"]:
                    files.append(
                        {
                            "path": f"{resource['path']}/{file_inventory['path']}",
                            "bytes": file_inventory["bytes"],
                            "sha256": file_inventory["sha256"],
                        }
                    )
        if publication_marker is not None:
            marker_bytes = KaggleClient._publication_marker_bytes(publication_marker)
            files.append(
                {
                    "path": PUBLICATION_MARKER_NAME,
                    "bytes": len(marker_bytes),
                    "sha256": hashlib.sha256(marker_bytes).hexdigest(),
                }
            )
        files = sorted(files, key=lambda file_inventory: file_inventory["path"])
        fingerprint_source = json.dumps(files, sort_keys=True, separators=(",", ":"))
        return {
            "root": str(root),
            "file_count": len(files),
            "bytes": sum(file_inventory["bytes"] for file_inventory in files),
            "files": files,
            "fingerprint": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        }

    def _build_publication_intent(
        self,
        *,
        preflight: dict[str, Any],
        expected_staged: dict[str, Any],
        publication_marker: dict[str, Any],
        publication_ledger: PublicationLedger,
        verify_remote: bool,
        full_publication: bool,
    ) -> PublicationIntent:
        resources = {
            str(resource["path"]): resource
            for resource in cast("list[dict[str, Any]]", preflight["resources"])
        }
        provenance = cast("dict[str, Any] | None", preflight.get("provenance"))
        source_sha = publication_ledger.source_sha
        if provenance is not None and provenance.get("source_sha") != source_sha:
            msg = "Durable Kaggle publication source does not match assured artifact provenance"
            raise ValueError(msg)

        assured_resource = resources.get(ASSURED_ARTIFACT_MANIFEST_NAME)
        terminal_resource = resources.get(TERMINAL_ASSURANCE_REPORT_NAME)
        marker_sha256 = hashlib.sha256(
            self._publication_marker_bytes(publication_marker)
        ).hexdigest()
        return PublicationIntent(
            dataset=self._dataset,
            source_sha=source_sha,
            publish_key=str(publication_marker["publish_key"]),
            bundle_fingerprint=str(publication_marker["bundle_fingerprint"]),
            data_tree_fingerprint=str(publication_marker["data_tree_fingerprint"]),
            staged_tree_fingerprint=str(expected_staged["fingerprint"]),
            publication_marker_sha256=marker_sha256,
            metadata_sha256=str(publication_marker["metadata_sha256"]),
            resource_count=int(publication_marker["resource_count"]),
            resource_bytes=int(publication_marker["resource_bytes"]),
            verify_remote=verify_remote,
            full_publication=full_publication,
            chain_id=(str(provenance["chain_id"]) if provenance is not None else None),
            coverage_fingerprint=(
                str(provenance["coverage_fingerprint"]) if provenance is not None else None
            ),
            assured_data_tree_fingerprint=(
                str(provenance["data_tree_fingerprint"]) if provenance is not None else None
            ),
            assured_manifest_sha256=(
                str(assured_resource["sha256"]) if assured_resource is not None else None
            ),
            terminal_assurance_report_sha256=(
                str(terminal_resource["sha256"]) if terminal_resource is not None else None
            ),
        )

    def _reconcile_durable_publication(
        self,
        *,
        publication_ledger: PublicationLedger | None,
        marker: dict[str, Any],
        resolved_version: int,
        resource_verification: dict[str, Any],
    ) -> dict[str, Any] | None:
        if publication_ledger is None:
            return None
        marker_sha256 = hashlib.sha256(self._publication_marker_bytes(marker)).hexdigest()
        receipt = publication_ledger.find_remote_match(
            marker,
            marker_sha256=marker_sha256,
        )
        if receipt is None:
            return None
        resolution = publication_ledger.mark_reconciled(
            receipt,
            resolved_version=resolved_version,
            publication_marker_sha256=marker_sha256,
            readback_fingerprint=str(resource_verification["fingerprint"]),
        )
        return resolution.to_dict()

    def _publication_marker_payload(
        self,
        *,
        preflight: dict[str, Any],
        publish_key: str,
        data_tree_fingerprint: str,
    ) -> dict[str, Any]:
        resources = [
            {
                "path": resource["path"],
                "kind": resource["kind"],
                "bytes": resource["bytes"],
                "sha256": resource["sha256"],
                **(
                    {"file_count": resource["file_count"]}
                    if resource["kind"] == "directory"
                    else {}
                ),
            }
            for resource in preflight["resources"]
        ]
        marker = {
            "schema_version": 2 if preflight.get("provenance") is not None else 1,
            "dataset": self._dataset,
            "publish_key": publish_key,
            "bundle_fingerprint": preflight["fingerprint"],
            "data_tree_fingerprint": data_tree_fingerprint,
            "metadata_sha256": preflight["metadata_sha256"],
            "resource_count": preflight["resource_count"],
            "resource_bytes": preflight["resource_bytes"],
            "resources": resources,
        }
        if preflight.get("provenance") is not None:
            marker["provenance"] = preflight["provenance"]
        return marker

    @staticmethod
    def _publication_marker_bytes(marker: dict[str, Any]) -> bytes:
        return (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8")

    @classmethod
    def _write_publication_marker(cls, staged_dir: Path, marker: dict[str, Any]) -> Path:
        marker_path = staged_dir / PUBLICATION_MARKER_NAME
        marker_path.write_bytes(cls._publication_marker_bytes(marker))
        return marker_path

    @staticmethod
    def _publication_marker_matches(
        observed: dict[str, Any],
        *,
        expected: dict[str, Any],
    ) -> bool:
        identity_fields = (
            "schema_version",
            "dataset",
            "publish_key",
            "bundle_fingerprint",
            "data_tree_fingerprint",
            "metadata_sha256",
            "resource_count",
            "resource_bytes",
            "resources",
            "provenance",
        )
        return all(observed.get(field) == expected.get(field) for field in identity_fields)

    @staticmethod
    def _publication_marker_matches_record(
        marker: dict[str, Any],
        *,
        record: dict[str, Any],
    ) -> bool:
        return all(
            marker.get(field) == record.get(field)
            for field in ("dataset", "publish_key", "bundle_fingerprint")
        )

    def _validate_publication_marker(self, marker: dict[str, Any]) -> None:
        schema_version = marker.get("schema_version")
        if type(schema_version) is not int or schema_version not in {1, 2}:
            msg = "Kaggle remote publication marker has an unsupported schema"
            raise ValueError(msg)
        if marker.get("dataset") != self._dataset:
            msg = "Kaggle remote publication marker dataset does not match configuration"
            raise ValueError(msg)
        digest_fields = {
            "bundle_fingerprint": 64,
            "data_tree_fingerprint": 64,
            "metadata_sha256": 64,
            "publish_key": 20,
        }
        for field, length in digest_fields.items():
            value = marker.get(field)
            if (
                not isinstance(value, str)
                or len(value) != length
                or any(character not in "0123456789abcdef" for character in value)
            ):
                msg = f"Kaggle remote publication marker has invalid {field}"
                raise ValueError(msg)
        resources = marker.get("resources")
        if not isinstance(resources, list):
            msg = "Kaggle remote publication marker resources must be a list"
            raise ValueError(msg)
        resource_count = marker.get("resource_count")
        resource_bytes = marker.get("resource_bytes")
        if (
            not isinstance(resource_count, int)
            or isinstance(resource_count, bool)
            or resource_count <= 0
            or resource_count != len(resources)
        ):
            msg = "Kaggle remote publication marker resource count is inconsistent"
            raise ValueError(msg)
        if (
            not isinstance(resource_bytes, int)
            or isinstance(resource_bytes, bool)
            or resource_bytes < 0
        ):
            msg = "Kaggle remote publication marker resource bytes are invalid"
            raise ValueError(msg)
        provenance = marker.get("provenance")
        if schema_version == 2:
            if not isinstance(provenance, dict):
                msg = "Kaggle remote publication marker provenance must be an object"
                raise ValueError(msg)
            if (
                not isinstance(provenance.get("chain_id"), str)
                or not provenance["chain_id"].strip()
            ):
                msg = "Kaggle remote publication marker provenance chain_id is invalid"
                raise ValueError(msg)
            for field, length in {
                "source_sha": 40,
                "coverage_fingerprint": 64,
                "data_tree_fingerprint": 64,
            }.items():
                value = provenance.get(field)
                if (
                    not isinstance(value, str)
                    or len(value) != length
                    or any(character not in "0123456789abcdef" for character in value)
                ):
                    msg = f"Kaggle remote publication marker provenance {field} is invalid"
                    raise ValueError(msg)
        elif provenance is not None:
            msg = "Kaggle schema-v1 publication marker must not declare provenance"
            raise ValueError(msg)
        observed_bytes = 0
        seen_paths: set[str] = set()
        for resource in resources:
            if not isinstance(resource, dict):
                msg = "Kaggle remote publication marker resource must be an object"
                raise ValueError(msg)
            path = resource.get("path")
            kind = resource.get("kind")
            byte_count = resource.get("bytes")
            digest = resource.get("sha256")
            if not isinstance(path, str) or self._normalize_resource_path(path) != path:
                msg = "Kaggle remote publication marker resource path is invalid"
                raise ValueError(msg)
            if path in seen_paths:
                msg = "Kaggle remote publication marker has duplicate resource paths"
                raise ValueError(msg)
            seen_paths.add(path)
            if kind not in {"file", "directory"}:
                msg = "Kaggle remote publication marker resource kind is invalid"
                raise ValueError(msg)
            if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
                msg = "Kaggle remote publication marker resource bytes are invalid"
                raise ValueError(msg)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                msg = "Kaggle remote publication marker resource digest is invalid"
                raise ValueError(msg)
            if kind == "directory":
                file_count = resource.get("file_count")
                if (
                    not isinstance(file_count, int)
                    or isinstance(file_count, bool)
                    or file_count <= 0
                ):
                    msg = "Kaggle remote publication marker directory file count is invalid"
                    raise ValueError(msg)
            observed_bytes += byte_count
        if observed_bytes != resource_bytes:
            msg = "Kaggle remote publication marker resource bytes are inconsistent"
            raise ValueError(msg)

    def _snapshot_tree(self, root: Path) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        total_bytes = 0
        for child in sorted(root.rglob("*")):
            if child.is_symlink():
                msg = f"Kaggle staged bundle contains symlink: {child}"
                raise ValueError(msg)
            if not child.is_file():
                continue
            relative_path = child.relative_to(root).as_posix()
            size = child.stat().st_size
            total_bytes += size
            files.append(
                {
                    "path": relative_path,
                    "bytes": size,
                    "sha256": self._file_sha256(child),
                }
            )
        fingerprint_source = json.dumps(files, sort_keys=True, separators=(",", ":"))
        return {
            "root": str(root),
            "file_count": len(files),
            "bytes": total_bytes,
            "files": files,
            "fingerprint": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _database_validation_for_resource(path: Path, resource_path: str) -> dict[str, Any] | None:
        suffix = PurePosixPath(resource_path).suffix.lower()
        if suffix in {".sqlite", ".sqlite3", ".db"}:
            return KaggleClient._validate_sqlite_database(path, resource_path)
        if suffix == ".duckdb":
            return KaggleClient._validate_duckdb_database(path, resource_path)
        return None

    @staticmethod
    def _parquet_validation_for_resource(path: Path, resource_path: str) -> dict[str, Any] | None:
        suffix = PurePosixPath(resource_path).suffix.lower()
        if suffix == ".parquet":
            return KaggleClient._validate_parquet_file(path, resource_path)
        return None

    @staticmethod
    def _validate_csv_file(path: Path, resource_path: str) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle, strict=True)
                try:
                    columns = next(reader)
                except StopIteration as exc:
                    msg = f"Kaggle CSV resource is empty: {resource_path}"
                    raise ValueError(msg) from exc
                if not columns or any(not column for column in columns):
                    msg = f"Kaggle CSV resource header is invalid: {resource_path}"
                    raise ValueError(msg)
                if len(set(columns)) != len(columns):
                    msg = f"Kaggle CSV resource has duplicate columns: {resource_path}"
                    raise ValueError(msg)
                row_count = 0
                for row_number, row in enumerate(reader, start=2):
                    if len(row) != len(columns):
                        msg = (
                            f"Kaggle CSV resource row {row_number} has {len(row)} fields; "
                            f"expected {len(columns)}: {resource_path}"
                        )
                        raise ValueError(msg)
                    row_count += 1
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            msg = f"Kaggle CSV resource validation failed: {resource_path}"
            raise ValueError(msg) from exc
        return {
            "engine": "csv",
            "row_count": row_count,
            "column_count": len(columns),
            "columns": columns,
        }

    @staticmethod
    def _validate_parquet_file(path: Path, resource_path: str) -> dict[str, Any]:
        import pyarrow.parquet as pq

        try:
            metadata = pq.read_metadata(path)
            arrow_schema = metadata.schema.to_arrow_schema()
        except Exception as exc:
            msg = f"Kaggle Parquet resource metadata validation failed: {resource_path}"
            raise ValueError(msg) from exc
        return {
            "engine": "parquet",
            "row_count": int(metadata.num_rows),
            "column_count": int(metadata.num_columns),
            "row_group_count": int(metadata.num_row_groups),
            "columns": list(arrow_schema.names),
        }

    @staticmethod
    def _validate_sqlite_database(path: Path, resource_path: str) -> dict[str, Any]:
        import sqlite3

        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.DatabaseError as exc:
            msg = f"Kaggle SQLite resource is not readable: {resource_path}"
            raise ValueError(msg) from exc
        try:
            quick_check = conn.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                msg = f"Kaggle SQLite resource failed quick_check: {resource_path}"
                raise ValueError(msg)
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_rows:
                msg = f"Kaggle SQLite resource failed foreign_key_check: {resource_path}"
                raise ValueError(msg)
            table_names = [
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                ).fetchall()
            ]
            public_table_names = sorted(
                table_name for table_name in table_names if not table_name.startswith("_")
            )
            excluded_internal_tables = sorted(
                table_name for table_name in table_names if table_name.startswith("_")
            )
            if not public_table_names:
                msg = f"Kaggle SQLite resource contains no public user tables: {resource_path}"
                raise ValueError(msg)
            row_counts: dict[str, int] = {}
            table_columns: dict[str, list[str]] = {}
            for table_name in public_table_names:
                validate_sql_identifier(table_name)
                quoted = f'"{table_name}"'
                row = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
                row_counts[table_name] = int(row[0]) if row is not None else 0
                table_columns[table_name] = [
                    str(column[1])
                    for column in conn.execute(f"PRAGMA table_info({quoted})").fetchall()
                ]
        except sqlite3.DatabaseError as exc:
            msg = f"Kaggle SQLite resource integrity validation failed: {resource_path}"
            raise ValueError(msg) from exc
        finally:
            conn.close()
        return {
            "engine": "sqlite",
            "quick_check": "ok",
            "foreign_key_check_error_count": 0,
            "table_count": len(public_table_names),
            "row_count": sum(row_counts.values()),
            "tables": row_counts,
            "columns": table_columns,
            "excluded_internal_table_count": len(excluded_internal_tables),
            "excluded_internal_tables": excluded_internal_tables,
        }

    @staticmethod
    def _validate_duckdb_database(path: Path, resource_path: str) -> dict[str, Any]:
        import duckdb

        from nbadb.core.db import get_user_tables

        try:
            conn = duckdb.connect(str(path), read_only=True)
        except duckdb.Error as exc:
            msg = f"Kaggle DuckDB resource is not readable: {resource_path}"
            raise ValueError(msg) from exc
        try:
            all_table_names = sorted(
                str(row[0])
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            )
            table_names = get_user_tables(conn)
            excluded_internal_tables = sorted(
                table_name for table_name in all_table_names if table_name.startswith("_")
            )
            if not table_names:
                msg = f"Kaggle DuckDB resource contains no public user tables: {resource_path}"
                raise ValueError(msg)
            row_counts: dict[str, int] = {}
            table_columns: dict[str, list[str]] = {}
            for table_name in table_names:
                validate_sql_identifier(table_name)
                quoted = f'"{table_name}"'
                row = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
                row_counts[table_name] = int(row[0]) if row is not None else 0
                table_columns[table_name] = [
                    str(column[0])
                    for column in conn.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'main' AND table_name = ?
                        ORDER BY ordinal_position
                        """,
                        [table_name],
                    ).fetchall()
                ]
        except duckdb.Error as exc:
            msg = f"Kaggle DuckDB resource integrity validation failed: {resource_path}"
            raise ValueError(msg) from exc
        finally:
            conn.close()
        return {
            "engine": "duckdb",
            "table_count": len(table_names),
            "row_count": sum(row_counts.values()),
            "tables": row_counts,
            "columns": table_columns,
            "excluded_internal_table_count": len(excluded_internal_tables),
            "excluded_internal_tables": excluded_internal_tables,
        }

    @staticmethod
    def _validate_database_resource_parity(resources: list[dict[str, Any]]) -> None:
        database_resources = [
            resource
            for resource in resources
            if isinstance(resource.get("database_validation"), dict)
        ]
        sqlite_resource = next(
            (
                resource
                for resource in database_resources
                if resource["database_validation"].get("engine") == "sqlite"
            ),
            None,
        )
        duckdb_resource = next(
            (
                resource
                for resource in database_resources
                if resource["database_validation"].get("engine") == "duckdb"
            ),
            None,
        )
        if sqlite_resource is None or duckdb_resource is None:
            return
        sqlite_tables = sqlite_resource["database_validation"]["tables"]
        duckdb_tables = duckdb_resource["database_validation"]["tables"]
        sqlite_table_names = set(sqlite_tables)
        duckdb_table_names = set(duckdb_tables)
        missing_from_sqlite = sorted(duckdb_table_names - sqlite_table_names)
        missing_from_duckdb = sorted(sqlite_table_names - duckdb_table_names)
        if missing_from_sqlite or missing_from_duckdb:
            msg = (
                "Kaggle SQLite and DuckDB resources are missing public tables: "
                f"{sqlite_resource['path']} vs {duckdb_resource['path']}; "
                f"missing_from_sqlite={missing_from_sqlite}; "
                f"missing_from_duckdb={missing_from_duckdb}"
            )
            raise ValueError(msg)
        row_count_diffs = {
            table_name: {
                "sqlite": sqlite_tables[table_name],
                "duckdb": duckdb_tables[table_name],
            }
            for table_name in sorted(sqlite_table_names)
            if sqlite_tables[table_name] != duckdb_tables[table_name]
        }
        if row_count_diffs:
            msg = (
                "Kaggle SQLite and DuckDB resources have mismatched public table row counts: "
                f"{sqlite_resource['path']} vs {duckdb_resource['path']}; "
                f"differences={row_count_diffs}"
            )
            raise ValueError(msg)

    @staticmethod
    def _validate_full_publication_format_parity(
        resources: list[dict[str, Any]],
        *,
        require_authoritative_values: bool = False,
    ) -> None:
        """Validate the four projections and exact authoritative values.

        DuckDB and Parquet are the logical-type authorities. SQLite and CSV are
        convenience projections, so they retain inventory, row-count, and
        ordered-column checks without an inaccurate type-lossless claim.
        """

        database_tables: dict[str, dict[str, int]] = {}
        database_columns: dict[str, dict[str, list[str]]] = {}
        csv_tables: dict[str, dict[str, Any]] = {}
        parquet_tables: dict[str, dict[str, Any]] = {}

        for resource in resources:
            database_validation = resource.get("database_validation")
            if isinstance(database_validation, dict):
                engine = str(database_validation["engine"])
                database_tables[engine] = {
                    str(table): int(row_count)
                    for table, row_count in dict(database_validation["tables"]).items()
                }
                database_columns[engine] = {
                    str(table): [str(column) for column in columns]
                    for table, columns in dict(database_validation["columns"]).items()
                }

            resource_path = str(resource["path"])
            parts = PurePosixPath(resource_path).parts
            if len(parts) == 2 and parts[0] == "csv" and parts[1].endswith(".csv"):
                validation = resource.get("csv_validation")
                if not isinstance(validation, dict):
                    msg = f"Full Kaggle publication CSV validation is missing: {resource_path}"
                    raise ValueError(msg)
                csv_tables[PurePosixPath(parts[1]).stem] = validation
                continue
            if len(parts) < 2 or parts[0] != "parquet":
                continue
            table = parts[1]
            if resource["kind"] == "file":
                validation = resource.get("parquet_validation")
                if not isinstance(validation, dict):
                    msg = f"Full Kaggle publication Parquet validation is missing: {resource_path}"
                    raise ValueError(msg)
                parquet_tables[table] = validation
                continue
            file_validations = [
                file_inventory.get("parquet_validation")
                for file_inventory in resource.get("files", [])
            ]
            if not file_validations or any(
                not isinstance(validation, dict) for validation in file_validations
            ):
                msg = (
                    "Full Kaggle publication partitioned Parquet validation is incomplete: "
                    f"{resource_path}"
                )
                raise ValueError(msg)
            typed_validations = cast("list[dict[str, Any]]", file_validations)
            physical_column_orders: list[list[str]] = []
            partition_column_orders: list[list[str]] = []
            for file_inventory, validation in zip(
                resource["files"], typed_validations, strict=True
            ):
                partition_columns = [
                    part.partition("=")[0]
                    for part in PurePosixPath(str(file_inventory["path"])).parts[:-1]
                    if "=" in part and part.partition("=")[0]
                ]
                if len(set(partition_columns)) != len(partition_columns):
                    msg = (
                        "Full Kaggle publication partitioned Parquet path repeats a partition "
                        f"column: {file_inventory['path']}"
                    )
                    raise ValueError(msg)
                physical_columns = [str(column) for column in validation["columns"]]
                if set(physical_columns) & set(partition_columns):
                    msg = (
                        "Full Kaggle publication partition columns are also stored physically: "
                        f"{file_inventory['path']}"
                    )
                    raise ValueError(msg)
                physical_column_orders.append(physical_columns)
                partition_column_orders.append(partition_columns)
            first_physical_columns = physical_column_orders[0]
            first_partition_columns = partition_column_orders[0]
            inconsistent_files = [
                str(file_inventory["path"])
                for file_inventory, physical_columns, partition_columns in zip(
                    resource["files"],
                    physical_column_orders,
                    partition_column_orders,
                    strict=True,
                )
                if physical_columns != first_physical_columns
                or partition_columns != first_partition_columns
            ]
            if inconsistent_files:
                msg = (
                    "Full Kaggle publication partitioned Parquet schemas differ for "
                    f"{resource_path}: {inconsistent_files}"
                )
                raise ValueError(msg)
            parquet_tables[table] = {
                "engine": "parquet",
                "row_count": sum(int(validation["row_count"]) for validation in typed_validations),
                "column_count": len(first_physical_columns) + len(first_partition_columns),
                "columns": [*first_physical_columns, *first_partition_columns],
                "physical_columns": first_physical_columns,
                "partition_columns": first_partition_columns,
                "file_count": len(typed_validations),
            }

        format_tables: dict[str, set[str]] = {
            engine: set(tables) for engine, tables in database_tables.items()
        }
        format_tables["csv"] = set(csv_tables)
        format_tables["parquet"] = set(parquet_tables)
        required_formats = {"duckdb", "sqlite", "csv", "parquet"}
        if set(format_tables) != required_formats:
            missing_formats = sorted(required_formats - set(format_tables))
            msg = f"Full Kaggle publication format validation is missing: {missing_formats}"
            raise ValueError(msg)

        expected_tables = format_tables["duckdb"]
        table_inventory_diffs = {
            engine: {
                "missing": sorted(expected_tables - tables),
                "unexpected": sorted(tables - expected_tables),
            }
            for engine, tables in sorted(format_tables.items())
            if tables != expected_tables
        }
        if table_inventory_diffs:
            msg = (
                "Full Kaggle publication table inventory differs across formats: "
                f"{table_inventory_diffs}"
            )
            raise ValueError(msg)

        row_count_diffs: dict[str, dict[str, int]] = {}
        schema_diffs: dict[str, dict[str, list[str]]] = {}
        for table in sorted(expected_tables):
            counts = {
                "duckdb": database_tables["duckdb"][table],
                "sqlite": database_tables["sqlite"][table],
                "csv": int(csv_tables[table]["row_count"]),
                "parquet": int(parquet_tables[table]["row_count"]),
            }
            if len(set(counts.values())) != 1:
                row_count_diffs[table] = counts
            duckdb_columns = database_columns["duckdb"][table]
            sqlite_columns = database_columns["sqlite"][table]
            csv_columns = [str(column) for column in csv_tables[table]["columns"]]
            parquet_columns = [str(column) for column in parquet_tables[table]["columns"]]
            partition_columns = [
                str(column) for column in parquet_tables[table].get("partition_columns", [])
            ]
            ordered_schema_mismatch = (
                sqlite_columns != duckdb_columns or csv_columns != duckdb_columns
            )
            if partition_columns:
                physical_columns = [
                    str(column) for column in parquet_tables[table].get("physical_columns", [])
                ]
                expected_physical_columns = [
                    column for column in duckdb_columns if column not in partition_columns
                ]
                parquet_schema_mismatch = (
                    physical_columns != expected_physical_columns
                    or any(column not in duckdb_columns for column in partition_columns)
                    or len(physical_columns) + len(partition_columns) != len(duckdb_columns)
                )
            else:
                parquet_schema_mismatch = parquet_columns != duckdb_columns
            if ordered_schema_mismatch or parquet_schema_mismatch:
                schema_diffs[table] = {
                    "duckdb": duckdb_columns,
                    "sqlite": sqlite_columns,
                    "csv": csv_columns,
                    "parquet": parquet_columns,
                }
        if row_count_diffs:
            sample = dict(list(row_count_diffs.items())[:20])
            msg = (
                "Full Kaggle publication row-count parity failed across DuckDB, SQLite, CSV, "
                f"and Parquet: mismatch_count={len(row_count_diffs)}; differences={sample}"
            )
            raise ValueError(msg)
        if schema_diffs:
            sample = dict(list(schema_diffs.items())[:20])
            msg = (
                "Full Kaggle publication schema parity failed across DuckDB, SQLite, CSV, "
                "and Parquet: "
                f"mismatch_count={len(schema_diffs)}; differences={sample}"
            )
            raise ValueError(msg)

        duckdb_resource = next(
            (
                resource
                for resource in resources
                if isinstance(resource.get("database_validation"), dict)
                and resource["database_validation"].get("engine") == "duckdb"
            ),
            None,
        )
        duckdb_source = duckdb_resource.get("source_path") if duckdb_resource is not None else None
        parquet_sources = {
            PurePosixPath(str(resource["path"])).parts[1]: resource.get("source_path")
            for resource in resources
            if len(PurePosixPath(str(resource["path"])).parts) >= 2
            and PurePosixPath(str(resource["path"])).parts[0] == "parquet"
        }
        source_backed = duckdb_source is not None or any(
            source is not None for source in parquet_sources.values()
        )
        if require_authoritative_values or source_backed:
            if not isinstance(duckdb_source, str) or not duckdb_source:
                msg = "Full Kaggle publication authoritative DuckDB source is missing"
                raise ValueError(msg)
            missing_parquet_sources = sorted(
                table
                for table, source in parquet_sources.items()
                if not isinstance(source, str) or not source
            )
            if set(parquet_sources) != expected_tables or missing_parquet_sources:
                msg = (
                    "Full Kaggle publication authoritative Parquet sources are incomplete: "
                    f"missing_paths={missing_parquet_sources}; "
                    f"missing_tables={sorted(expected_tables - set(parquet_sources))}; "
                    f"unexpected_tables={sorted(set(parquet_sources) - expected_tables)}"
                )
                raise ValueError(msg)
            from nbadb.orchestrate.successor_publication_inventory import (
                validate_authoritative_duckdb_parquet_values,
            )

            parquet_file_receipts: dict[str, dict[str, tuple[int, str]]] = {}
            for resource in resources:
                parts = PurePosixPath(str(resource["path"])).parts
                if len(parts) < 2 or parts[0] != "parquet":
                    continue
                table = parts[1]
                if resource["kind"] == "file":
                    source = Path(cast("str", resource["source_path"]))
                    parquet_file_receipts[table] = {
                        source.name: (
                            int(resource["bytes"]),
                            str(resource["sha256"]),
                        )
                    }
                else:
                    parquet_file_receipts[table] = {
                        str(file_inventory["path"]): (
                            int(file_inventory["bytes"]),
                            str(file_inventory["sha256"]),
                        )
                        for file_inventory in resource["files"]
                    }
            validate_authoritative_duckdb_parquet_values(
                Path(duckdb_source),
                {table: Path(cast("str", source)) for table, source in parquet_sources.items()},
                expected_duckdb_bytes=int(cast("dict[str, Any]", duckdb_resource)["bytes"]),
                expected_duckdb_sha256=str(cast("dict[str, Any]", duckdb_resource)["sha256"]),
                expected_parquet_files=parquet_file_receipts,
            )

    @staticmethod
    def _monotonic() -> float:
        return time.monotonic()

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(seconds)

    @staticmethod
    def _is_publication_marker_not_found(exc: Exception) -> bool:
        from kagglehub.exceptions import KaggleApiHTTPError

        response = getattr(exc, "response", None)
        if (
            not isinstance(exc, KaggleApiHTTPError)
            or response is None
            or response.status_code != HTTPStatus.NOT_FOUND
        ):
            return False
        request = getattr(response, "request", None)
        request_locations = (
            getattr(response, "url", ""),
            getattr(request, "url", ""),
            getattr(request, "body", ""),
        )
        return any(PUBLICATION_MARKER_NAME in str(location) for location in request_locations)

    @staticmethod
    def _require_exact_dataset_version(version: Any, *, source: str) -> int:
        if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
            msg = f"Kaggle {source} did not resolve an exact dataset version"
            raise RuntimeError(msg)
        return version

    def _resolve_remote_dataset_version(self) -> int:
        from kagglehub.clients import build_kaggle_client
        from kagglehub.exceptions import handle_call
        from kagglehub.handle import parse_dataset_handle
        from kagglesdk.datasets.types.dataset_api_service import ApiGetDatasetRequest

        handle = parse_dataset_handle(self._dataset)
        request = ApiGetDatasetRequest()
        request.owner_slug = handle.owner
        request.dataset_slug = handle.dataset
        with build_kaggle_client() as api_client:
            dataset = handle_call(
                lambda: api_client.datasets.dataset_api_client.get_dataset(request),
                handle,
            )
        return self._require_exact_dataset_version(
            dataset.current_version_number,
            source="dataset metadata API",
        )

    def _list_remote_dataset_files(self, version: int) -> list[dict[str, Any]]:
        from kagglehub.clients import build_kaggle_client
        from kagglehub.exceptions import handle_call
        from kagglehub.handle import parse_dataset_handle
        from kagglesdk.datasets.types.dataset_api_service import ApiListDatasetFilesRequest

        version = self._require_exact_dataset_version(version, source="file inventory API")
        handle = parse_dataset_handle(self._dataset).with_version(version)
        files: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        page_token = ""
        seen_page_tokens = {page_token}

        with build_kaggle_client() as api_client:
            while True:
                request = ApiListDatasetFilesRequest()
                request.owner_slug = handle.owner
                request.dataset_slug = handle.dataset
                request.dataset_version_number = version
                request.page_size = _REMOTE_FILE_LIST_PAGE_SIZE
                request.page_token = page_token
                response = handle_call(
                    lambda request=request: (
                        api_client.datasets.dataset_api_client.list_dataset_files(request)
                    ),
                    handle,
                )
                if response.error_message:
                    msg = f"Kaggle remote file inventory failed: {response.error_message}"
                    raise RuntimeError(msg)
                if not isinstance(response.dataset_files, list):
                    msg = "Kaggle remote file inventory response has invalid files"
                    raise ValueError(msg)
                for remote_file in response.dataset_files:
                    raw_path = getattr(remote_file, "name", None)
                    byte_count = getattr(remote_file, "total_bytes", None)
                    if not isinstance(raw_path, str) or not raw_path:
                        msg = "Kaggle remote file inventory contains an invalid path"
                        raise ValueError(msg)
                    path = self._normalize_resource_path(raw_path)
                    if path != raw_path:
                        msg = (
                            "Kaggle remote file inventory contains a noncanonical path: "
                            f"{raw_path!r}"
                        )
                        raise ValueError(msg)
                    if path in seen_paths:
                        msg = f"Kaggle remote file inventory contains duplicate path: {path}"
                        raise ValueError(msg)
                    if (
                        not isinstance(byte_count, int)
                        or isinstance(byte_count, bool)
                        or byte_count < 0
                    ):
                        msg = f"Kaggle remote file inventory has invalid byte size: {path}"
                        raise ValueError(msg)
                    seen_paths.add(path)
                    files.append({"path": path, "bytes": byte_count})

                next_page_token = response.next_page_token
                if not next_page_token:
                    break
                if not isinstance(next_page_token, str) or next_page_token in seen_page_tokens:
                    msg = "Kaggle remote file inventory pagination is invalid"
                    raise ValueError(msg)
                seen_page_tokens.add(next_page_token)
                page_token = next_page_token

        return sorted(files, key=lambda item: item["path"])

    def _download_remote_dataset_file(
        self,
        download_root: Path,
        version: int,
        relative_path: str,
    ) -> tuple[Path, int]:
        from kagglehub import registry
        from kagglehub.handle import parse_dataset_handle

        version = self._require_exact_dataset_version(version, source="file readback")
        normalized_path = self._normalize_resource_path(relative_path)
        handle = parse_dataset_handle(self._dataset).with_version(version)
        downloaded, resolved_version = registry.dataset_resolver(
            handle,
            normalized_path,
            output_dir=str(download_root),
            force_download=True,
        )
        resolved_version = self._require_exact_dataset_version(
            resolved_version,
            source="file readback",
        )
        if resolved_version != version:
            msg = (
                "Kaggle remote file readback resolved the wrong dataset version: "
                f"expected={version}, resolved={resolved_version}, path={normalized_path}"
            )
            raise RuntimeError(msg)
        root = download_root.resolve()
        raw_downloaded_path = Path(downloaded)
        if raw_downloaded_path.is_symlink():
            msg = f"Kaggle remote file readback resolved a symlink: {normalized_path}"
            raise ValueError(msg)
        downloaded_path = raw_downloaded_path.resolve()
        try:
            downloaded_path.relative_to(root)
        except ValueError as exc:
            msg = f"Kaggle remote file readback escaped its download root: {normalized_path}"
            raise ValueError(msg) from exc
        if not downloaded_path.is_file():
            msg = f"Kaggle remote file readback did not resolve a regular file: {normalized_path}"
            raise FileNotFoundError(msg)
        return downloaded_path, resolved_version

    @classmethod
    def _index_file_inventory(
        cls,
        files: Any,
        *,
        source: str,
        require_sha256: bool,
    ) -> dict[str, dict[str, Any]]:
        if not isinstance(files, list):
            msg = f"Kaggle {source} file inventory must be a list"
            raise ValueError(msg)
        indexed: dict[str, dict[str, Any]] = {}
        for item in files:
            if not isinstance(item, dict):
                msg = f"Kaggle {source} file inventory entry must be an object"
                raise ValueError(msg)
            path = item.get("path")
            byte_count = item.get("bytes")
            if not isinstance(path, str) or cls._normalize_resource_path(path) != path:
                msg = f"Kaggle {source} file inventory path is invalid"
                raise ValueError(msg)
            if path in indexed:
                msg = f"Kaggle {source} file inventory contains duplicate path: {path}"
                raise ValueError(msg)
            if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
                msg = f"Kaggle {source} file inventory has invalid byte size: {path}"
                raise ValueError(msg)
            if require_sha256 and not cls._is_lowercase_hex(item.get("sha256"), length=64):
                msg = f"Kaggle {source} file inventory has invalid sha256: {path}"
                raise ValueError(msg)
            indexed[path] = item
        return indexed

    @classmethod
    def _assert_remote_file_inventory_matches(
        cls,
        expected_files: Any,
        observed_files: Any,
        *,
        compare_sha256: bool,
    ) -> None:
        expected = cls._index_file_inventory(
            expected_files,
            source="expected staged",
            require_sha256=True,
        )
        observed = cls._index_file_inventory(
            observed_files,
            source="remote",
            require_sha256=compare_sha256,
        )
        missing = sorted(set(expected).difference(observed))
        extra = sorted(set(observed).difference(expected))
        size_mismatches = sorted(
            path
            for path in set(expected).intersection(observed)
            if expected[path]["bytes"] != observed[path]["bytes"]
        )
        sha256_mismatches = (
            sorted(
                path
                for path in set(expected).intersection(observed)
                if expected[path]["sha256"] != observed[path]["sha256"]
            )
            if compare_sha256
            else []
        )
        mismatches: list[str] = []
        if missing:
            mismatches.append(f"missing={missing}")
        if extra:
            mismatches.append(f"extra={extra}")
        if size_mismatches:
            mismatches.append(f"bytes={size_mismatches}")
        if sha256_mismatches:
            mismatches.append(f"sha256={sha256_mismatches}")
        if mismatches:
            msg = "Kaggle remote resource inventory mismatch: " + "; ".join(mismatches)
            raise ValueError(msg)

    def _assert_remote_marker_inventory_matches(
        self,
        marker: dict[str, Any],
        observed_files: Any,
        *,
        compare_sha256: bool,
    ) -> None:
        self._validate_publication_marker(marker)
        observed = self._index_file_inventory(
            observed_files,
            source="remote marker-attested",
            require_sha256=compare_sha256,
        )
        mismatches: list[str] = []
        consumed_paths = {"dataset-metadata.json", PUBLICATION_MARKER_NAME}

        for required_path in sorted(consumed_paths):
            if required_path not in observed:
                mismatches.append(f"missing={required_path}")

        marker_bytes = self._publication_marker_bytes(marker)
        marker_file = observed.get(PUBLICATION_MARKER_NAME)
        if marker_file is not None:
            if marker_file["bytes"] != len(marker_bytes):
                mismatches.append(f"bytes={PUBLICATION_MARKER_NAME}")
            if compare_sha256 and marker_file["sha256"] != hashlib.sha256(marker_bytes).hexdigest():
                mismatches.append(f"sha256={PUBLICATION_MARKER_NAME}")

        metadata_file = observed.get("dataset-metadata.json")
        if (
            compare_sha256
            and metadata_file is not None
            and metadata_file["sha256"] != marker["metadata_sha256"]
        ):
            mismatches.append("sha256=dataset-metadata.json")

        identity_resources: list[dict[str, Any]] = []
        resources = cast("list[dict[str, Any]]", marker["resources"])
        resource_paths = [str(resource["path"]) for resource in resources]
        for index, resource_path in enumerate(resource_paths):
            overlap = next(
                (
                    other
                    for other in resource_paths[index + 1 :]
                    if self._resource_paths_overlap(resource_path, other)
                ),
                None,
            )
            if overlap is not None:
                mismatches.append(f"overlap={resource_path},{overlap}")

        for resource in resources:
            resource_path = str(resource["path"])
            if resource["kind"] == "file":
                consumed_paths.add(resource_path)
                observed_resource = observed.get(resource_path)
                if observed_resource is None:
                    mismatches.append(f"missing={resource_path}")
                else:
                    if observed_resource["bytes"] != resource["bytes"]:
                        mismatches.append(f"bytes={resource_path}")
                    if compare_sha256 and observed_resource["sha256"] != resource["sha256"]:
                        mismatches.append(f"sha256={resource_path}")
                identity_resources.append(
                    {
                        "path": resource_path,
                        "kind": "file",
                        "bytes": resource["bytes"],
                        "sha256": resource["sha256"],
                    }
                )
                continue

            prefix = f"{resource_path}/"
            children = [item for path, item in observed.items() if path.startswith(prefix)]
            consumed_paths.update(str(item["path"]) for item in children)
            if len(children) != resource["file_count"]:
                mismatches.append(f"file_count={resource_path}")
            if sum(int(item["bytes"]) for item in children) != resource["bytes"]:
                mismatches.append(f"bytes={resource_path}")
            child_files = [
                {
                    "path": str(item["path"])[len(prefix) :],
                    "bytes": item["bytes"],
                    **({"sha256": item["sha256"]} if compare_sha256 else {}),
                }
                for item in children
            ]
            child_files.sort(key=lambda item: item["path"])
            if compare_sha256:
                directory_source = json.dumps(
                    child_files,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if hashlib.sha256(directory_source.encode()).hexdigest() != resource["sha256"]:
                    mismatches.append(f"sha256={resource_path}")
            identity_resources.append(
                {
                    "path": resource_path,
                    "kind": "directory",
                    "bytes": resource["bytes"],
                    "sha256": resource["sha256"],
                    "file_count": resource["file_count"],
                    **({"files": child_files} if compare_sha256 else {}),
                }
            )

        extra = sorted(set(observed).difference(consumed_paths))
        if extra:
            mismatches.append(f"extra={extra}")

        if compare_sha256 and not mismatches:
            data_files = sorted(
                (item for path, item in observed.items() if path != PUBLICATION_MARKER_NAME),
                key=lambda item: item["path"],
            )
            data_tree_source = json.dumps(data_files, sort_keys=True, separators=(",", ":"))
            if (
                hashlib.sha256(data_tree_source.encode()).hexdigest()
                != marker["data_tree_fingerprint"]
            ):
                mismatches.append("fingerprint=data_tree")

            fingerprint_payload = {
                "metadata_sha256": marker["metadata_sha256"],
                "resources": sorted(identity_resources, key=lambda item: item["path"]),
            }
            bundle_source = json.dumps(
                fingerprint_payload,
                sort_keys=True,
                separators=(",", ":"),
            )
            if hashlib.sha256(bundle_source.encode()).hexdigest() != marker["bundle_fingerprint"]:
                mismatches.append("fingerprint=bundle")

        if mismatches:
            msg = "Kaggle remote marker-attested inventory mismatch: " + "; ".join(mismatches)
            raise ValueError(msg)

    def _snapshot_remote_files_streaming(
        self,
        download_root: Path,
        api_inventory: list[dict[str, Any]],
        *,
        version: int,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        download_root.mkdir(parents=True, exist_ok=True)
        files: list[dict[str, Any]] = []
        for api_file in api_inventory:
            self._require_verification_deadline(deadline, operation="remote file download")
            self._require_disk_capacity(
                download_root,
                required_bytes=int(api_file["bytes"]) + _DISK_SAFETY_RESERVE_BYTES,
                operation=f"readback of {api_file['path']}",
            )
            downloaded_path, _resolved_version = self._download_remote_dataset_file(
                download_root,
                version,
                str(api_file["path"]),
            )
            self._require_verification_deadline(deadline, operation="remote file download")
            byte_count = downloaded_path.stat().st_size
            if byte_count != api_file["bytes"]:
                msg = (
                    "Kaggle downloaded remote file size differs from API inventory: "
                    f"{api_file['path']}"
                )
                raise ValueError(msg)
            digest = self._file_sha256(downloaded_path)
            self._require_verification_deadline(deadline, operation="remote file hashing")
            files.append({"path": api_file["path"], "bytes": byte_count, "sha256": digest})
            downloaded_path.unlink()

        files.sort(key=lambda item: item["path"])
        fingerprint_source = json.dumps(files, sort_keys=True, separators=(",", ":"))
        return {
            "file_count": len(files),
            "bytes": sum(item["bytes"] for item in files),
            "files": files,
            "fingerprint": hashlib.sha256(fingerprint_source.encode()).hexdigest(),
        }

    def _verify_remote_bundle(
        self,
        expected_tree: dict[str, Any] | None,
        *,
        expected_marker: dict[str, Any] | None = None,
        version: int,
        deadline: float | None = None,
    ) -> dict[str, Any]:
        if expected_tree is None and expected_marker is None:
            msg = "Kaggle remote bundle verification requires expected inventory evidence"
            raise ValueError(msg)
        expected_files = None
        if expected_tree is not None:
            expected_files = expected_tree.get("files")
            self._index_file_inventory(
                expected_files,
                source="expected staged",
                require_sha256=True,
            )
            if not self._is_lowercase_hex(expected_tree.get("fingerprint"), length=64):
                msg = "Kaggle expected staged tree fingerprint is invalid"
                raise ValueError(msg)
        self._require_verification_deadline(deadline, operation="remote inventory listing")
        api_inventory = self._list_remote_dataset_files(version)
        self._require_verification_deadline(deadline, operation="remote inventory listing")
        if expected_tree is not None:
            self._assert_remote_file_inventory_matches(
                expected_files,
                api_inventory,
                compare_sha256=False,
            )
        if expected_marker is not None:
            self._assert_remote_marker_inventory_matches(
                expected_marker,
                api_inventory,
                compare_sha256=False,
            )

        with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-bundle-readback-") as temp_dir:
            snapshot = self._snapshot_remote_files_streaming(
                Path(temp_dir) / "files",
                api_inventory,
                version=version,
                deadline=deadline,
            )

        if expected_tree is not None:
            self._assert_remote_file_inventory_matches(
                expected_files,
                snapshot["files"],
                compare_sha256=True,
            )
            expected_fingerprint = expected_tree.get("fingerprint")
            if snapshot["fingerprint"] != expected_fingerprint:
                msg = "Kaggle remote resource inventory fingerprint does not match staged bundle"
                raise ValueError(msg)
        if expected_marker is not None:
            self._assert_remote_marker_inventory_matches(
                expected_marker,
                snapshot["files"],
                compare_sha256=True,
            )
        return {
            "version": version,
            "file_count": snapshot["file_count"],
            "bytes": snapshot["bytes"],
            "fingerprint": snapshot["fingerprint"],
            "api_file_count": len(api_inventory),
            "content_identity": "sha256_full_readback",
        }

    def _reconcile_bootstrap_before_upload(
        self,
        *,
        expected_marker: dict[str, Any],
        baseline_version: int,
    ) -> dict[str, Any]:
        """Recheck the marker and exact metadata version just before an upload call."""
        try:
            with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-bootstrap-recheck-") as temp_dir:
                marker, marker_version = self._download_remote_publication_marker(Path(temp_dir))
        except Exception as exc:
            if not self._is_publication_marker_not_found(exc):
                raise
            metadata_version = self._resolve_remote_dataset_version()
            return {
                "state": "marker_missing",
                "marker_status_code": int(HTTPStatus.NOT_FOUND),
                "baseline_version": baseline_version,
                "metadata_version": metadata_version,
                "version_unchanged": metadata_version == baseline_version,
                "upload_allowed": metadata_version == baseline_version,
            }

        metadata_version = self._resolve_remote_dataset_version()
        marker_matches = self._publication_marker_matches(marker, expected=expected_marker)
        return {
            "state": "marker_present",
            "marker": marker,
            "publish_key": marker.get("publish_key"),
            "bundle_fingerprint": marker.get("bundle_fingerprint"),
            "baseline_version": baseline_version,
            "marker_version": marker_version,
            "metadata_version": metadata_version,
            "versions_agree": marker_version == metadata_version,
            "matches_expected": marker_matches,
            "upload_allowed": marker_version == metadata_version and marker_matches,
        }

    def _reconcile_marker_baseline_before_upload(
        self,
        *,
        expected_marker: dict[str, Any],
        baseline_marker: dict[str, Any],
        baseline_version: int,
    ) -> dict[str, Any]:
        """Recheck a marker-present baseline immediately before upload."""
        with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-marker-recheck-") as temp_dir:
            marker, marker_version = self._download_remote_publication_marker(Path(temp_dir))
        metadata_version = self._resolve_remote_dataset_version()
        marker_matches_expected = self._publication_marker_matches(
            marker,
            expected=expected_marker,
        )
        marker_matches_baseline = self._publication_marker_matches(
            marker,
            expected=baseline_marker,
        )
        versions_agree = marker_version == metadata_version
        baseline_unchanged = marker_version == baseline_version and marker_matches_baseline
        return {
            "state": "marker_present",
            "marker": marker,
            "publish_key": marker.get("publish_key"),
            "bundle_fingerprint": marker.get("bundle_fingerprint"),
            "baseline_version": baseline_version,
            "marker_version": marker_version,
            "metadata_version": metadata_version,
            "versions_agree": versions_agree,
            "baseline_unchanged": baseline_unchanged,
            "matches_expected": marker_matches_expected,
            "upload_allowed": versions_agree and (baseline_unchanged or marker_matches_expected),
        }

    def _download_remote_publication_marker(
        self,
        download_root: Path,
    ) -> tuple[dict[str, Any], int]:
        from kagglehub import registry
        from kagglehub.handle import parse_dataset_handle

        downloaded, version = registry.dataset_resolver(
            parse_dataset_handle(self._dataset),
            PUBLICATION_MARKER_NAME,
            output_dir=str(download_root),
            force_download=True,
        )
        version = self._require_exact_dataset_version(
            version,
            source="remote publication marker",
        )
        remote_path = Path(downloaded)
        marker_path = (
            remote_path if remote_path.is_file() else remote_path / PUBLICATION_MARKER_NAME
        )
        if not marker_path.is_file():
            candidates = list(remote_path.rglob(PUBLICATION_MARKER_NAME))
            if len(candidates) != 1:
                msg = "Kaggle remote publication marker is missing or ambiguous"
                raise FileNotFoundError(msg)
            marker_path = candidates[0]
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            msg = "Kaggle remote publication marker is not valid JSON"
            raise ValueError(msg) from exc
        if not isinstance(marker, dict):
            msg = "Kaggle remote publication marker must be a JSON object"
            raise ValueError(msg)
        self._validate_publication_marker(marker)
        return marker, version

    def _verify_remote_upload(
        self,
        expected_marker: dict[str, Any],
        *,
        expected_tree: dict[str, Any] | None = None,
        timeout_seconds: float = 3600.0,
        poll_interval_seconds: float = 15.0,
        publication: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if publication is None:
            publication = {}
        observations = list(publication.get("observations") or [])
        started = self._monotonic()
        deadline = started + timeout_seconds
        attempt = 0
        while True:
            attempt += 1
            observation: dict[str, Any] = {"attempt": attempt}
            try:
                with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-readback-") as temp_dir:
                    remote_marker, version = self._download_remote_publication_marker(
                        Path(temp_dir)
                    )
            except Exception as exc:
                if self._is_local_resource_error(exc):
                    raise
                observation["error"] = self._redacted_error(exc)
            else:
                marker_matches = self._publication_marker_matches(
                    remote_marker,
                    expected=expected_marker,
                )
                observation.update(
                    {
                        "publish_key": remote_marker.get("publish_key"),
                        "bundle_fingerprint": remote_marker.get("bundle_fingerprint"),
                        "matches_expected": marker_matches,
                        "version": version,
                    }
                )
                if observation["matches_expected"]:
                    try:
                        metadata_version = self._resolve_remote_dataset_version()
                    except Exception as exc:
                        if self._is_local_resource_error(exc):
                            raise
                        observation["metadata_error"] = self._redacted_error(exc)
                    else:
                        observation["metadata_version"] = metadata_version
                        observation["versions_agree"] = version == metadata_version
                        if version == metadata_version:
                            try:
                                resource_verification = self._verify_remote_bundle(
                                    expected_tree,
                                    expected_marker=remote_marker,
                                    version=version,
                                    deadline=deadline,
                                )
                                post_readback_version = self._resolve_remote_dataset_version()
                                self._require_verification_deadline(
                                    deadline,
                                    operation="remote version stabilization",
                                )
                                if post_readback_version != version:
                                    msg = (
                                        "Kaggle current dataset version changed during remote "
                                        "resource verification: "
                                        f"marker={version}, current={post_readback_version}"
                                    )
                                    raise RuntimeError(msg)
                            except Exception as exc:
                                if self._is_local_resource_error(exc):
                                    raise
                                observation["resource_verification_error"] = self._redacted_error(
                                    exc
                                )
                            else:
                                observation["post_readback_version"] = post_readback_version
                                observation["resource_verification"] = resource_verification
                                elapsed = max(0.0, self._monotonic() - started)
                                observations.append(observation)
                                publication.update(
                                    {
                                        "verification_attempts": attempt,
                                        "verification_elapsed_seconds": round(elapsed, 3),
                                        "resolved_version": version,
                                        "resource_verification": resource_verification,
                                        "observations": observations,
                                    }
                                )
                                return {
                                    **remote_marker,
                                    "verification_mode": "publication_marker",
                                    "resource_verification": resource_verification,
                                    "verification_attempts": attempt,
                                    "verification_elapsed_seconds": round(elapsed, 3),
                                    "resolved_version": version,
                                }
            observations.append(observation)
            elapsed = max(0.0, self._monotonic() - started)
            publication.update(
                {
                    "verification_attempts": attempt,
                    "verification_elapsed_seconds": round(elapsed, 3),
                    "observations": observations,
                }
            )
            if elapsed >= timeout_seconds:
                msg = "Kaggle publication did not expose the expected bundle before the deadline"
                raise KagglePublicationPendingError(msg, publication)
            self._sleep(min(poll_interval_seconds, timeout_seconds - elapsed))

    @staticmethod
    def _is_local_resource_error(exc: Exception) -> bool:
        return isinstance(exc, OSError) and exc.errno in {
            errno.EACCES,
            errno.EDQUOT,
            errno.EIO,
            errno.ENFILE,
            errno.ENOSPC,
            errno.EMFILE,
        }

    def _require_verification_deadline(
        self,
        deadline: float | None,
        *,
        operation: str,
    ) -> None:
        if deadline is not None and self._monotonic() >= deadline:
            raise TimeoutError(f"Kaggle {operation} exceeded the verification deadline")

    @staticmethod
    def _redact_sensitive_text(message: str) -> str:
        home = str(Path.home())
        if home and home in message:
            message = message.replace(home, "~")
        message = re.sub(
            r"(?i)(?<!\w)file://(?:\[[^\]\s'\"<>|,;)}]+\]|"
            r"(?:localhost|[^/\s'\"<>|,;)\]}]+))?"
            r"(?:/[A-Za-z]:)?/[^\s'\"<>|,;)\]}]+",
            "<local-path>",
            message,
        )
        message = re.sub(
            r"(?<![\w/])/(?!/)[^\s'\"<>|,;)\]}]+",
            "<local-path>",
            message,
        )
        message = re.sub(
            r"(?<!\w)(?:[A-Za-z]:[\\/]|\\\\)[^\s'\"<>|,;)\]}]+",
            "<local-path>",
            message,
        )
        message = _AUTHORIZATION_BEARER_RE.sub(r"\1<redacted>", message)
        message = _SECRET_ASSIGNMENT_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(4)}",
            message,
        )
        return _SECRET_FLAG_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(4)}",
            message,
        )

    @classmethod
    def _redact_persisted_error_fields(
        cls,
        value: Any,
        *,
        field_name: str = "",
        error_context: bool = False,
    ) -> Any:
        error_context = error_context or "error" in field_name.lower()
        if isinstance(value, dict):
            return {
                key: cls._redact_persisted_error_fields(
                    item,
                    field_name=str(key),
                    error_context=error_context,
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                cls._redact_persisted_error_fields(item, error_context=error_context)
                for item in value
            ]
        if isinstance(value, str) and error_context:
            return cls._redact_sensitive_text(value)
        return value

    @classmethod
    def _redacted_error(cls, exc: Exception) -> str:
        return f"{type(exc).__name__}: {cls._redact_sensitive_text(str(exc))}"
