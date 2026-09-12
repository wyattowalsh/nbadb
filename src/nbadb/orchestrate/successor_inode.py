"""Exact-inode no-replace retirement for successor scratch directories.

Same-UID pathname ``rmdir`` after a name proof is racy: a substitute can take
the original name between the last identity check and removal.  These helpers
move the current name with a native no-replace rename, inspect the inode that
syscall moved, restore a mismatch, and remove only a confirmed owned empty
directory.
"""

from __future__ import annotations

import ctypes
import errno
import os
import secrets
import stat
import sys
from typing import Any, Final

__all__ = [
    "SuccessorInodeRetirementError",
    "directory_inode",
    "remove_empty_owned_directory",
    "rename_directory_no_replace",
]

_LINUX_RENAME_NOREPLACE: Final = 1
_DARWIN_RENAME_EXCL: Final = 0x00000004
_LINUX_AT_REMOVEDIR: Final = 0x200
_LINUX_AT_EMPTY_PATH: Final = 0x1000
_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW | _CLOEXEC | _NONBLOCK
)


class SuccessorInodeRetirementError(RuntimeError):
    """Raised when an owned empty directory cannot be retired exactly."""


def directory_inode(value: os.stat_result) -> tuple[int, int]:
    return (value.st_dev, value.st_ino)


def rename_directory_no_replace(
    source_descriptor: int,
    source_name: str,
    target_descriptor: int,
    target_name: str,
) -> None:
    """Move one directory name without replacing a destination."""

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
            raise SuccessorInodeRetirementError(
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
        raise SuccessorInodeRetirementError(
            "exact-inode retirement requires macOS or Linux no-replace rename"
        )
    ctypes.set_errno(0)
    if rename(*arguments) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), source_name, target_name)


def _try_unlink_empty_directory_inode(descriptor: int) -> bool:
    if not sys.platform.startswith("linux"):
        return False
    library = ctypes.CDLL(None, use_errno=True)
    try:
        unlinkat = library.unlinkat
    except AttributeError:
        return False
    unlinkat.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int)
    unlinkat.restype = ctypes.c_int
    ctypes.set_errno(0)
    return unlinkat(descriptor, b"", _LINUX_AT_REMOVEDIR | _LINUX_AT_EMPTY_PATH) == 0


def _restore_substituted_name(
    parent_descriptor: int,
    retired_name: str,
    original_name: str,
    error: type[BaseException],
    label: str,
) -> None:
    try:
        rename_directory_no_replace(
            parent_descriptor,
            retired_name,
            parent_descriptor,
            original_name,
        )
        os.fsync(parent_descriptor)
    except OSError as exc:
        raise error(f"{label} substitution could not be restored after quarantine race") from exc


def remove_empty_owned_directory(
    parent_descriptor: int,
    name: str,
    held_descriptor: int,
    *,
    expected_inode: tuple[int, int],
    error: type[BaseException],
    label: str,
) -> None:
    """Retire only the empty directory inode currently named ``name``.

    The held descriptor must remain open across this call.  A name that no
    longer refers to ``expected_inode`` is restored and rejected instead of
    being removed.
    """

    if (
        type(parent_descriptor) is not int
        or parent_descriptor < 0
        or type(held_descriptor) is not int
        or held_descriptor < 0
        or type(name) is not str
        or not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or type(expected_inode) is not tuple
        or len(expected_inode) != 2
        or any(type(part) is not int or part < 0 for part in expected_inode)
    ):
        raise error(f"{label} lacks exact inode retirement authority")

    try:
        held = os.fstat(held_descriptor)
    except OSError as exc:
        raise error(f"{label} held directory changed before quarantine") from exc
    if not stat.S_ISDIR(held.st_mode) or directory_inode(held) != expected_inode:
        raise error(f"{label} held directory changed before quarantine")
    with os.scandir(held_descriptor) as iterator:
        if any(True for _ in iterator):
            raise error(f"{label} is not empty")

    retired_name: str | None = None
    last_error: OSError | None = None
    for _attempt in range(16):
        candidate = f".nbadb-successor-retired-{secrets.token_hex(16)}"
        try:
            rename_directory_no_replace(
                parent_descriptor,
                name,
                parent_descriptor,
                candidate,
            )
        except OSError as exc:
            last_error = exc
            if exc.errno == errno.EEXIST:
                continue
            raise error(f"{label} cannot be quarantined without replacement") from exc
        retired_name = candidate
        break
    if retired_name is None:
        raise error(f"{label} quarantine name allocation failed") from last_error
    os.fsync(parent_descriptor)

    moved_descriptor = -1
    try:
        try:
            moved_descriptor = os.open(
                retired_name,
                _DIRECTORY_FLAGS,
                dir_fd=parent_descriptor,
            )
            moved = os.fstat(moved_descriptor)
            named = os.stat(
                retired_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            held_after_move = os.fstat(held_descriptor)
        except OSError as exc:
            raise error(f"{label} disappeared after quarantine") from exc
        if (
            not stat.S_ISDIR(moved.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or directory_inode(moved) != expected_inode
            or directory_inode(named) != expected_inode
            or directory_inode(held_after_move) != expected_inode
        ):
            _restore_substituted_name(
                parent_descriptor,
                retired_name,
                name,
                error,
                label,
            )
            raise error(f"{label} changed or was replaced at quarantine")

        with os.scandir(moved_descriptor) as iterator:
            if any(True for _ in iterator):
                raise error(f"{label} is not empty")

        if not _try_unlink_empty_directory_inode(held_descriptor):
            os.rmdir(retired_name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)

        try:
            leftover = os.stat(
                retired_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            leftover = None
        if leftover is not None and directory_inode(leftover) == expected_inode:
            raise error(f"{label} remains named after exact retirement")
        try:
            original = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            original = None
        if original is not None and directory_inode(original) == expected_inode:
            raise error(f"{label} replacement appeared after exact retirement")
        retired = os.fstat(held_descriptor)
        if not stat.S_ISDIR(retired.st_mode) or directory_inode(retired) != expected_inode:
            raise error(f"{label} admitted inode changed during retirement")
    finally:
        if moved_descriptor >= 0:
            os.close(moved_descriptor)
