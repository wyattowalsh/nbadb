"""Descriptor-safe durable storage for bundle-scoped parser-input body blobs."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import threading
from contextlib import contextmanager, suppress
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from nbadb.contracts.body_blob_inventory import (
    BODY_BLOB_RESOURCE_PREFIX,
    MAX_BODY_BLOB_CANONICAL_BYTES,
    BodyBlobDescriptorV1,
    BodyBlobFileReadbackReceiptV1,
    BodyBlobInventoryReadbackReceiptV1,
    BodyBlobInventoryV1,
    BodyBlobObservationReadbackReceiptV1,
    replay_body_blob_inventory,
    validate_body_blob_inventory,
)
from nbadb.contracts.raw_request_authority import (
    MAX_PARSER_INPUT_BYTES,
    MAX_PARSER_INPUT_STORED_BYTES,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    decode_parser_input_object,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


_LOCK_NAME: Final = ".body-blob-store.lock"
_LOCK_BOOTSTRAP_ATTEMPTS: Final = 4
_MANIFEST_PREFIX: Final = "body-blobs/inventories/sha256"
_SAFE_ID_RE: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}\Z")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_SHA_RE: Final = re.compile(r"[0-9a-f]{40}\Z")
_RESOURCE_COMPONENT_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}\Z")
_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_FILE_MODE: Final = 0o600
_DIRECTORY_MODE: Final = 0o700


class BodyBlobStoreError(RuntimeError):
    """Raised when durable body-blob storage cannot be proven exactly."""


def _fail(message: str) -> BodyBlobStoreError:
    return BodyBlobStoreError(message)


def _close_descriptors(
    descriptors: tuple[int, ...],
    *,
    failure_message: str,
) -> None:
    """Close every descriptor without masking an exception already in flight."""

    active_exception = sys.exception()
    release_failed = False
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except OSError:
            release_failed = True
    if release_failed and active_exception is None:
        raise _fail(failure_message) from None


def _close_descriptor(descriptor: int, *, failure_message: str) -> None:
    """Close one descriptor under the shared active-exception policy."""

    _close_descriptors((descriptor,), failure_message=failure_message)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")
    return hashlib.sha256(encoded).hexdigest()


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _fail(f"{label} must be one exact SHA-256")
    return value


def _exact_positive_integer(value: object, *, label: str) -> int:
    if type(value) is not int or not 1 <= value <= (1 << 63) - 1:
        raise _fail(f"{label} must be one bounded exact positive integer")
    return value


def _exact_safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise _fail(f"{label} must be one exact public-safe identifier")
    return value


def _require_platform() -> None:
    required = (
        os.name == "posix",
        hasattr(os, "O_DIRECTORY"),
        hasattr(os, "O_NOFOLLOW"),
        hasattr(os, "O_NONBLOCK"),
        hasattr(os, "O_CLOEXEC"),
        os.open in os.supports_dir_fd,
        os.stat in os.supports_dir_fd,
        os.mkdir in os.supports_dir_fd,
        os.link in os.supports_dir_fd,
        os.unlink in os.supports_dir_fd,
    )
    if not all(required):
        raise _fail("body-blob storage requires descriptor-relative POSIX authority")


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC


def _read_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid)


def _validate_directory_stat(value: os.stat_result) -> None:
    if (
        not stat.S_ISDIR(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != _DIRECTORY_MODE
    ):
        raise _fail("body-blob directory lacks exact owner-only authority")


def _validate_file_stat(
    value: os.stat_result,
    *,
    expected_length: int,
    expected_nlink: int,
) -> None:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.geteuid()
        or stat.S_IMODE(value.st_mode) != _FILE_MODE
        or value.st_nlink != expected_nlink
        or value.st_size != expected_length
    ):
        raise _fail("body-blob immutable resource is corrupt or colliding")


class BodyBlobStore:
    """One run-owned immutable body-object and inventory store."""

    def __init__(
        self,
        root: Path,
        *,
        source_sha: str,
        run_id: int,
        run_attempt: int,
        chain_id: str,
        lane_id: str,
    ) -> None:
        _require_platform()
        if type(root) is not type(Path()) or not root.is_absolute():
            raise _fail("body-blob store root must be one exact absolute Path")
        if root == Path("/") or any(part in {"", ".", ".."} for part in root.parts[1:]):
            raise _fail("body-blob store root is invalid")
        if type(source_sha) is not str or _SOURCE_SHA_RE.fullmatch(source_sha) is None:
            raise _fail("body-blob store source identity must be one exact Git SHA")
        self._root = root
        self._source_sha = source_sha
        self._run_id = _exact_positive_integer(run_id, label="body-blob store run ID")
        self._run_attempt = _exact_positive_integer(
            run_attempt,
            label="body-blob store run attempt",
        )
        self._chain_id = _exact_safe_id(chain_id, label="body-blob store chain identity")
        self._lane_id = _exact_safe_id(lane_id, label="body-blob store lane identity")
        self._namespace_sha256 = _canonical_sha256(
            {
                "chain_id": self._chain_id,
                "kind": "nbadb_body_blob_store_namespace_v1",
                "lane_id": self._lane_id,
                "run_attempt": self._run_attempt,
                "run_id": self._run_id,
                "source_sha": self._source_sha,
            }
        )
        self._thread_lock = threading.RLock()
        root_descriptor, admitted_root = self._open_root()
        try:
            lock_descriptor = self._open_lock(root_descriptor, create=True)
            try:
                os.fsync(lock_descriptor)
                os.fsync(root_descriptor)
            finally:
                _close_descriptor(
                    lock_descriptor,
                    failure_message="body-blob store lock cannot be released safely",
                )
            self._require_named_root(root_descriptor, admitted_root)
        except BodyBlobStoreError:
            raise
        except OSError:
            raise _fail("body-blob store lock cannot be initialized safely") from None
        finally:
            _close_descriptor(
                root_descriptor,
                failure_message="body-blob store root cannot be released safely",
            )

    @property
    def namespace_sha256(self) -> str:
        """Return the path-free identity of this run-owned store namespace."""

        return self._namespace_sha256

    @staticmethod
    def _manifest_relative_resource_name(inventory_sha256: str) -> str:
        digest = _exact_sha256(inventory_sha256, label="body-blob inventory resource")
        return f"{_MANIFEST_PREFIX}/{digest[:2]}/{digest}.json"

    def _open_root(self) -> tuple[int, tuple[int, int, int, int, int]]:
        descriptor = -1
        try:
            descriptor = os.open("/", _directory_flags())
            for part in self._root.parts[1:]:
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
                previous = descriptor
                descriptor = child
                os.close(previous)
            opened = os.fstat(descriptor)
            named = os.stat(self._root, follow_symlinks=False)
        except OSError:
            if descriptor >= 0:
                _close_descriptor(
                    descriptor,
                    failure_message="body-blob store root cannot be released safely",
                )
            raise _fail("body-blob store root cannot be opened safely") from None
        except BaseException:
            if descriptor >= 0:
                _close_descriptor(
                    descriptor,
                    failure_message="body-blob store root cannot be released safely",
                )
            raise
        try:
            _validate_directory_stat(opened)
        except BodyBlobStoreError:
            _close_descriptor(
                descriptor,
                failure_message="body-blob store root cannot be released safely",
            )
            raise
        if _directory_identity(opened) != _directory_identity(named):
            try:
                raise _fail("body-blob store root binding is unstable")
            finally:
                _close_descriptor(
                    descriptor,
                    failure_message="body-blob store root cannot be released safely",
                )
        return descriptor, _directory_identity(opened)

    def _require_named_root(
        self,
        root_descriptor: int,
        admitted_root: tuple[int, int, int, int, int],
    ) -> None:
        try:
            opened = os.fstat(root_descriptor)
            named = os.stat(self._root, follow_symlinks=False)
        except OSError:
            raise _fail("body-blob configured root binding is unavailable") from None
        if (
            _directory_identity(opened) != admitted_root
            or _directory_identity(named) != admitted_root
        ):
            raise _fail("body-blob configured root was rebound")
        _validate_directory_stat(opened)
        _validate_directory_stat(named)

    @staticmethod
    def _validate_lock_binding(root_descriptor: int, lock_descriptor: int) -> None:
        try:
            opened = os.fstat(lock_descriptor)
            named = os.stat(_LOCK_NAME, dir_fd=root_descriptor, follow_symlinks=False)
        except OSError:
            raise _fail("body-blob store lock binding is unavailable") from None
        _validate_file_stat(named, expected_length=0, expected_nlink=1)
        if _stat_identity(opened) != _stat_identity(named):
            raise _fail("body-blob store lock binding is unstable")

    @classmethod
    def _open_lock(cls, root_descriptor: int, *, create: bool) -> int:
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC
        if create:
            flags |= os.O_CREAT
        last_missing = False
        for _attempt in range(_LOCK_BOOTSTRAP_ATTEMPTS if create else 1):
            descriptor = -1
            try:
                descriptor = os.open(_LOCK_NAME, flags, _FILE_MODE, dir_fd=root_descriptor)
                cls._validate_lock_binding(root_descriptor, descriptor)
                return descriptor
            except FileNotFoundError:
                last_missing = True
                if descriptor >= 0:
                    with suppress(OSError):
                        os.close(descriptor)
                continue
            except BaseException:
                if descriptor >= 0:
                    with suppress(OSError):
                        os.close(descriptor)
                raise
        if last_missing:
            raise _fail("body-blob store lock bootstrap did not converge")
        raise _fail("body-blob store lock cannot be opened safely")

    @contextmanager
    def _locked_root(self) -> Iterator[int]:
        with self._thread_lock:
            root_descriptor, admitted_root = self._open_root()
            lock_descriptor = -1
            try:
                lock_descriptor = self._open_lock(root_descriptor, create=False)
                fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
                self._validate_lock_binding(root_descriptor, lock_descriptor)
                self._require_named_root(root_descriptor, admitted_root)
                yield root_descriptor
                self._validate_lock_binding(root_descriptor, lock_descriptor)
                self._require_named_root(root_descriptor, admitted_root)
            except BodyBlobStoreError:
                raise
            except OSError:
                raise _fail("body-blob store lock cannot be acquired safely") from None
            finally:
                try:
                    if lock_descriptor >= 0:
                        with suppress(OSError):
                            fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                finally:
                    _close_descriptors(
                        tuple(
                            descriptor
                            for descriptor in (lock_descriptor, root_descriptor)
                            if descriptor >= 0
                        ),
                        failure_message=("body-blob store descriptors cannot be released safely"),
                    )

    @staticmethod
    def _validate_component(value: object) -> str:
        if (
            type(value) is not str
            or _RESOURCE_COMPONENT_RE.fullmatch(value) is None
            or value in {".", ".."}
        ):
            raise _fail("body-blob resource contains an invalid path component")
        return value

    @classmethod
    def _resource_parts(cls, value: object) -> tuple[str, ...]:
        if type(value) is not str or "\\" in value or not value:
            raise _fail("body-blob resource identity is invalid")
        parsed = PurePosixPath(value)
        parts = parsed.parts
        if parsed.is_absolute() or parsed.as_posix() != value or len(parts) < 2:
            raise _fail("body-blob resource identity is invalid")
        return tuple(cls._validate_component(part) for part in parts)

    @classmethod
    def _descriptor_resource_parts(
        cls,
        descriptor: BodyBlobDescriptorV1,
    ) -> tuple[str, ...]:
        parts = cls._resource_parts(descriptor.relative_resource_name)
        expected = (
            "body-blobs",
            "sha256",
            descriptor.blob_sha256[:2],
            f"{descriptor.blob_sha256}.payload.gz",
        )
        if parts != expected or "/".join(parts[:-2]) != BODY_BLOB_RESOURCE_PREFIX:
            raise _fail("body-blob descriptor resource identity is invalid")
        return parts

    @classmethod
    def _manifest_resource_parts(cls, inventory_sha256: str) -> tuple[str, ...]:
        return cls._resource_parts(cls._manifest_relative_resource_name(inventory_sha256))

    @classmethod
    def _open_child_directory(
        cls,
        parent_descriptor: int,
        name: str,
        *,
        create: bool,
    ) -> tuple[int, tuple[int, int, int, int, int]]:
        cls._validate_component(name)
        try:
            before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            if not create:
                raise _fail("body-blob resource directory is missing") from None
            try:
                os.mkdir(name, _DIRECTORY_MODE, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
            except FileExistsError:
                pass
            except OSError:
                raise _fail("body-blob resource directory cannot be created safely") from None
            try:
                before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            except OSError:
                raise _fail("body-blob resource directory cannot be inspected safely") from None
        except OSError:
            raise _fail("body-blob resource directory cannot be inspected safely") from None
        _validate_directory_stat(before)
        descriptor = -1
        try:
            descriptor = os.open(name, _directory_flags(), dir_fd=parent_descriptor)
            opened = os.fstat(descriptor)
            after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except OSError:
            if descriptor >= 0:
                _close_descriptor(
                    descriptor,
                    failure_message=("body-blob resource directory cannot be released safely"),
                )
            raise _fail("body-blob resource directory cannot be opened safely") from None
        except BaseException:
            if descriptor >= 0:
                _close_descriptor(
                    descriptor,
                    failure_message=("body-blob resource directory cannot be released safely"),
                )
            raise
        identity = _directory_identity(opened)
        if identity != _directory_identity(before) or identity != _directory_identity(after):
            try:
                raise _fail("body-blob resource directory binding is unstable")
            finally:
                _close_descriptor(
                    descriptor,
                    failure_message=("body-blob resource directory cannot be released safely"),
                )
        try:
            _validate_directory_stat(opened)
        except BodyBlobStoreError:
            _close_descriptor(
                descriptor,
                failure_message="body-blob resource directory cannot be released safely",
            )
            raise
        return descriptor, identity

    @classmethod
    def _require_child_directory(
        cls,
        parent_descriptor: int,
        name: str,
        child_descriptor: int,
        identity: tuple[int, int, int, int, int],
    ) -> None:
        try:
            opened = os.fstat(child_descriptor)
            named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except OSError:
            raise _fail("body-blob resource directory binding is unavailable") from None
        if _directory_identity(opened) != identity or _directory_identity(named) != identity:
            raise _fail("body-blob resource directory was rebound")
        _validate_directory_stat(opened)
        _validate_directory_stat(named)

    @classmethod
    @contextmanager
    def _open_parent_directory(
        cls,
        root_descriptor: int,
        parts: tuple[str, ...],
        *,
        create: bool,
    ) -> Iterator[int]:
        if type(parts) is not tuple or not parts:
            raise _fail("body-blob resource parent identity is invalid")
        descriptors: list[int] = [root_descriptor]
        bindings: list[tuple[int, str, int, tuple[int, int, int, int, int]]] = []
        try:
            for name in parts:
                parent_descriptor = descriptors[-1]
                child_descriptor, identity = cls._open_child_directory(
                    parent_descriptor,
                    name,
                    create=create,
                )
                descriptors.append(child_descriptor)
                bindings.append((parent_descriptor, name, child_descriptor, identity))
            yield descriptors[-1]
            for binding in reversed(bindings):
                cls._require_child_directory(*binding)
        finally:
            _close_descriptors(
                tuple(reversed(descriptors[1:])),
                failure_message="body-blob resource descriptors cannot be released safely",
            )

    @staticmethod
    def _read_bound_file(
        parent_descriptor: int,
        name: str,
        *,
        expected_length: int,
        maximum_length: int,
        expected_nlink: int = 1,
        synchronize: bool = False,
    ) -> bytes | None:
        if (
            type(expected_length) is not int
            or type(maximum_length) is not int
            or not 1 <= expected_length <= maximum_length
            or type(expected_nlink) is not int
            or expected_nlink not in {1, 2}
        ):
            raise _fail("body-blob resource read authority is invalid")
        try:
            named_before = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError:
            raise _fail("body-blob immutable resource cannot be inspected safely") from None
        _validate_file_stat(
            named_before,
            expected_length=expected_length,
            expected_nlink=expected_nlink,
        )
        descriptor = -1
        try:
            descriptor = os.open(name, _read_flags(), dir_fd=parent_descriptor)
            opened_before = os.fstat(descriptor)
            admitted = _stat_identity(opened_before)
            if admitted != _stat_identity(named_before):
                raise _fail("body-blob immutable resource changed while it was opened")
            remaining = expected_length
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise _fail("body-blob immutable resource ended before its admitted length")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise _fail("body-blob immutable resource contains trailing bytes")
            if synchronize:
                os.fsync(descriptor)
            opened_after = os.fstat(descriptor)
            named_after = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            if synchronize:
                os.fsync(parent_descriptor)
        except BodyBlobStoreError:
            raise
        except OSError:
            raise _fail("body-blob immutable resource cannot be read safely") from None
        finally:
            if descriptor >= 0:
                _close_descriptor(
                    descriptor,
                    failure_message=("body-blob immutable resource cannot be released safely"),
                )
        if admitted != _stat_identity(opened_after) or admitted != _stat_identity(named_after):
            raise _fail("body-blob immutable resource changed during exact readback")
        return b"".join(chunks)

    def _temporary_name(self, final_name: str) -> str:
        temporary = f".{final_name}.{self._namespace_sha256}.tmp"
        if len(os.fsencode(temporary)) > 255:
            raise _fail("body-blob temporary resource identity is too long")
        return temporary

    @classmethod
    def _reconcile_temporary_install(
        cls,
        parent_descriptor: int,
        *,
        temporary_name: str,
        final_name: str,
        content: bytes,
        maximum_length: int,
    ) -> None:
        expected_length = len(content)
        try:
            temporary_stat = os.stat(
                temporary_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        except OSError:
            raise _fail("body-blob temporary resource cannot be inspected safely") from None
        if (
            not stat.S_ISREG(temporary_stat.st_mode)
            or temporary_stat.st_uid != os.geteuid()
            or stat.S_IMODE(temporary_stat.st_mode) != _FILE_MODE
            or temporary_stat.st_nlink not in {1, 2}
        ):
            raise _fail("body-blob temporary resource lacks exact authority")
        try:
            final_stat = os.stat(final_name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            final_stat = None
        except OSError:
            raise _fail("body-blob immutable resource cannot be inspected safely") from None
        try:
            if final_stat is None:
                if temporary_stat.st_nlink != 1:
                    raise _fail("body-blob interrupted install has foreign links")
                if temporary_stat.st_size != expected_length:
                    current = os.stat(
                        temporary_name,
                        dir_fd=parent_descriptor,
                        follow_symlinks=False,
                    )
                    if _stat_identity(current) != _stat_identity(temporary_stat):
                        raise _fail("body-blob temporary resource changed during recovery")
                    os.unlink(temporary_name, dir_fd=parent_descriptor)
                    os.fsync(parent_descriptor)
                    return
                temporary_bytes = cls._read_bound_file(
                    parent_descriptor,
                    temporary_name,
                    expected_length=expected_length,
                    maximum_length=maximum_length,
                    synchronize=True,
                )
                if temporary_bytes != content:
                    raise _fail("body-blob temporary resource collides with different content")
                os.link(
                    temporary_name,
                    final_name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
                os.unlink(temporary_name, dir_fd=parent_descriptor)
                os.fsync(parent_descriptor)
                return
            same_member = (
                temporary_stat.st_dev == final_stat.st_dev
                and temporary_stat.st_ino == final_stat.st_ino
            )
            if (
                not same_member
                or temporary_stat.st_nlink != 2
                or final_stat.st_nlink != 2
                or temporary_stat.st_size != expected_length
                or final_stat.st_size != expected_length
            ):
                raise _fail("body-blob interrupted install is corrupt or colliding")
            temporary_bytes = cls._read_bound_file(
                parent_descriptor,
                temporary_name,
                expected_length=expected_length,
                maximum_length=maximum_length,
                expected_nlink=2,
                synchronize=True,
            )
            final_bytes = cls._read_bound_file(
                parent_descriptor,
                final_name,
                expected_length=expected_length,
                maximum_length=maximum_length,
                expected_nlink=2,
            )
            if temporary_bytes != content or final_bytes != content:
                raise _fail("body-blob interrupted install differs from exact content")
            os.unlink(temporary_name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
        except BodyBlobStoreError:
            raise
        except OSError:
            raise _fail("body-blob interrupted install cannot be recovered safely") from None

    def _install_immutable_file(
        self,
        parent_descriptor: int,
        *,
        final_name: str,
        content: bytes,
        maximum_length: int,
    ) -> bytes:
        if type(content) is not bytes or not 1 <= len(content) <= maximum_length:
            raise _fail("body-blob immutable resource bytes violate their bound")
        final_name = self._validate_component(final_name)
        temporary_name = self._temporary_name(final_name)
        self._reconcile_temporary_install(
            parent_descriptor,
            temporary_name=temporary_name,
            final_name=final_name,
            content=content,
            maximum_length=maximum_length,
        )
        existing = self._read_bound_file(
            parent_descriptor,
            final_name,
            expected_length=len(content),
            maximum_length=maximum_length,
            synchronize=True,
        )
        if existing is not None:
            if existing != content:
                raise _fail("body-blob immutable key collides with different content")
            return existing

        descriptor = -1
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC,
                _FILE_MODE,
                dir_fd=parent_descriptor,
            )
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError
                view = view[written:]
            os.fchmod(descriptor, _FILE_MODE)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.link(
                temporary_name,
                final_name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            os.unlink(temporary_name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
        except BodyBlobStoreError:
            raise
        except OSError:
            raise _fail("body-blob immutable resource cannot be installed durably") from None
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)
            with suppress(OSError):
                os.unlink(temporary_name, dir_fd=parent_descriptor)
        readback = self._read_bound_file(
            parent_descriptor,
            final_name,
            expected_length=len(content),
            maximum_length=maximum_length,
        )
        if readback is None or readback != content:
            raise _fail("body-blob immutable resource post-commit readback failed")
        return readback

    def _require_bundle_namespace(self, bundle: RawRequestAuthorityBundleV2) -> None:
        for observation in bundle.observations:
            attempt = observation.attempt
            if (
                attempt.source_sha != self._source_sha
                or attempt.run_id != self._run_id
                or attempt.run_attempt != self._run_attempt
                or attempt.chain_id != self._chain_id
                or attempt.lane_id != self._lane_id
            ):
                raise _fail("body-blob inventory references a foreign run namespace")

    def _validate_inputs(
        self,
        *,
        bundle: RawRequestAuthorityBundleV2,
        inventory: BodyBlobInventoryV1,
        expected_raw_authority_bundle_sha256: str,
        expected_inventory_sha256: str,
        known_secrets: Sequence[str | bytes],
    ) -> tuple[
        RawRequestAuthorityBundleV2,
        BodyBlobInventoryV1,
        dict[str, ParserInputObjectV2],
    ]:
        bundle_pin = _exact_sha256(
            expected_raw_authority_bundle_sha256,
            label="expected body-blob raw bundle",
        )
        inventory_pin = _exact_sha256(
            expected_inventory_sha256,
            label="expected body-blob inventory",
        )
        if type(bundle) is not RawRequestAuthorityBundleV2:
            raise _fail("body-blob store requires one exact Raw-v2 bundle DTO")
        if type(inventory) is not BodyBlobInventoryV1:
            raise _fail("body-blob store requires one exact inventory DTO")
        if type(known_secrets) not in {tuple, list}:
            raise _fail("body-blob store known-secret inventory has a foreign type")
        try:
            candidate_bundle_pin = _exact_sha256(
                bundle.bundle_sha256,
                label="candidate body-blob raw bundle",
            )
            candidate_inventory_pin = _exact_sha256(
                inventory.inventory_sha256,
                label="candidate body-blob inventory",
            )
        except BodyBlobStoreError:
            raise
        except Exception:
            raise _fail("body-blob store input pins cannot be inspected safely") from None
        if candidate_bundle_pin != bundle_pin or candidate_inventory_pin != inventory_pin:
            raise _fail("body-blob store input differs from its external pins")
        try:
            validated = validate_body_blob_inventory(
                inventory,
                bundle=bundle,
                expected_raw_authority_bundle_sha256=bundle_pin,
                expected_inventory_sha256=inventory_pin,
                known_secrets=known_secrets,
            )
            self._require_bundle_namespace(bundle)
            objects: dict[str, ParserInputObjectV2] = {}
            for item in bundle.objects:
                if type(item) is not ParserInputObjectV2 or item.object_sha256 in objects:
                    raise _fail("body-blob Raw-v2 object inventory is invalid")
                objects[item.object_sha256] = item
            if set(objects) != {item.parser_input_object_sha256 for item in validated.descriptors}:
                raise _fail("body-blob object denominator differs from its descriptors")
        except BodyBlobStoreError:
            raise
        except Exception:
            raise _fail("body-blob inventory failed exact authority validation") from None
        return bundle, validated, objects

    @staticmethod
    def _verify_blob_bytes(
        *,
        descriptor: BodyBlobDescriptorV1,
        parser_input_object: ParserInputObjectV2,
        readback: bytes,
    ) -> None:
        if (
            type(readback) is not bytes
            or len(readback) != descriptor.stored_bytes
            or hashlib.sha256(readback).hexdigest() != descriptor.stored_sha256
            or readback != parser_input_object.stored_payload
        ):
            raise _fail("body-blob stored bytes differ from exact descriptor authority")
        try:
            raw = decode_parser_input_object(parser_input_object)
        except Exception:
            raise _fail("body-blob parser-input object cannot be decoded safely") from None
        if (
            len(raw) != descriptor.uncompressed_bytes
            or len(raw) > MAX_PARSER_INPUT_BYTES
            or hashlib.sha256(raw).hexdigest() != descriptor.response_sha256
        ):
            raise _fail("body-blob raw bytes differ from exact descriptor authority")

    def _read_or_persist_descriptor(
        self,
        root_descriptor: int,
        *,
        descriptor: BodyBlobDescriptorV1,
        parser_input_object: ParserInputObjectV2,
        persist: bool,
        known_secrets: Sequence[str | bytes],
    ) -> BodyBlobFileReadbackReceiptV1:
        parts = self._descriptor_resource_parts(descriptor)
        with self._open_parent_directory(
            root_descriptor,
            parts[:-1],
            create=persist,
        ) as parent_descriptor:
            if persist:
                readback = self._install_immutable_file(
                    parent_descriptor,
                    final_name=parts[-1],
                    content=parser_input_object.stored_payload,
                    maximum_length=MAX_PARSER_INPUT_STORED_BYTES,
                )
            else:
                readback = self._read_bound_file(
                    parent_descriptor,
                    parts[-1],
                    expected_length=descriptor.stored_bytes,
                    maximum_length=MAX_PARSER_INPUT_STORED_BYTES,
                    synchronize=True,
                )
                if readback is None:
                    raise _fail("body-blob immutable resource is missing")
        self._verify_blob_bytes(
            descriptor=descriptor,
            parser_input_object=parser_input_object,
            readback=readback,
        )
        try:
            return BodyBlobFileReadbackReceiptV1.build(
                descriptor=descriptor,
                parser_input_object=parser_input_object,
                readback_bytes=readback,
                store_namespace_sha256=self._namespace_sha256,
                expected_raw_authority_bundle_sha256=descriptor.raw_authority_bundle_sha256,
                expected_descriptor_sha256=descriptor.descriptor_sha256,
                known_secrets=known_secrets,
            )
        except Exception:
            raise _fail("body-blob file readback receipt cannot be built safely") from None

    def _file_receipts(
        self,
        root_descriptor: int,
        *,
        inventory: BodyBlobInventoryV1,
        objects: dict[str, ParserInputObjectV2],
        persist: bool,
        known_secrets: Sequence[str | bytes],
    ) -> tuple[BodyBlobFileReadbackReceiptV1, ...]:
        return tuple(
            self._read_or_persist_descriptor(
                root_descriptor,
                descriptor=descriptor,
                parser_input_object=objects[descriptor.parser_input_object_sha256],
                persist=persist,
                known_secrets=known_secrets,
            )
            for descriptor in inventory.descriptors
        )

    @staticmethod
    def _observation_receipts(
        *,
        inventory: BodyBlobInventoryV1,
        file_receipts: tuple[BodyBlobFileReadbackReceiptV1, ...],
    ) -> tuple[BodyBlobObservationReadbackReceiptV1, ...]:
        file_by_descriptor = {item.descriptor_sha256: item for item in file_receipts}
        try:
            return tuple(
                BodyBlobObservationReadbackReceiptV1.build(
                    reference=reference,
                    file_readback=file_by_descriptor[reference.descriptor_sha256],
                    expected_raw_authority_bundle_sha256=inventory.raw_authority_bundle_sha256,
                    expected_reference_sha256=reference.reference_sha256,
                    expected_file_readback_receipt_sha256=file_by_descriptor[
                        reference.descriptor_sha256
                    ].receipt_sha256,
                )
                for reference in inventory.references
            )
        except Exception:
            raise _fail("body-blob observation readback receipts cannot be built safely") from None

    def _build_aggregate_receipt(
        self,
        *,
        inventory: BodyBlobInventoryV1,
        file_receipts: tuple[BodyBlobFileReadbackReceiptV1, ...],
    ) -> BodyBlobInventoryReadbackReceiptV1:
        observations = self._observation_receipts(
            inventory=inventory,
            file_receipts=file_receipts,
        )
        try:
            return BodyBlobInventoryReadbackReceiptV1.build(
                inventory=inventory,
                file_readbacks=file_receipts,
                observation_readbacks=observations,
                store_namespace_sha256=self._namespace_sha256,
                expected_raw_authority_bundle_sha256=inventory.raw_authority_bundle_sha256,
                expected_inventory_sha256=inventory.inventory_sha256,
            )
        except Exception:
            raise _fail("body-blob inventory readback receipt cannot be built safely") from None

    def persist_objects(
        self,
        *,
        bundle: RawRequestAuthorityBundleV2,
        inventory: BodyBlobInventoryV1,
        expected_raw_authority_bundle_sha256: str,
        expected_inventory_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> tuple[BodyBlobFileReadbackReceiptV1, ...]:
        """Persist and re-read every deduplicated object in canonical content order."""

        _bundle, validated, objects = self._validate_inputs(
            bundle=bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_inventory_sha256=expected_inventory_sha256,
            known_secrets=known_secrets,
        )
        with self._locked_root() as root_descriptor:
            return self._file_receipts(
                root_descriptor,
                inventory=validated,
                objects=objects,
                persist=True,
                known_secrets=known_secrets,
            )

    def seal_inventory(
        self,
        *,
        bundle: RawRequestAuthorityBundleV2,
        inventory: BodyBlobInventoryV1,
        expected_raw_authority_bundle_sha256: str,
        expected_inventory_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> BodyBlobInventoryReadbackReceiptV1:
        """Persist objects, commit the manifest last, and return full readback proof."""

        _bundle, validated, objects = self._validate_inputs(
            bundle=bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_inventory_sha256=expected_inventory_sha256,
            known_secrets=known_secrets,
        )
        manifest = validated.to_canonical_bytes()
        manifest_parts = self._manifest_resource_parts(validated.inventory_sha256)
        with self._locked_root() as root_descriptor:
            self._file_receipts(
                root_descriptor,
                inventory=validated,
                objects=objects,
                persist=True,
                known_secrets=known_secrets,
            )
            with self._open_parent_directory(
                root_descriptor,
                manifest_parts[:-1],
                create=True,
            ) as parent_descriptor:
                installed_manifest = self._install_immutable_file(
                    parent_descriptor,
                    final_name=manifest_parts[-1],
                    content=manifest,
                    maximum_length=MAX_BODY_BLOB_CANONICAL_BYTES,
                )
            try:
                replayed = replay_body_blob_inventory(
                    installed_manifest,
                    bundle=bundle,
                    expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
                    expected_inventory_sha256=expected_inventory_sha256,
                    known_secrets=known_secrets,
                )
            except Exception:
                raise _fail("body-blob installed manifest failed exact replay") from None
            file_receipts = self._file_receipts(
                root_descriptor,
                inventory=replayed,
                objects=objects,
                persist=False,
                known_secrets=known_secrets,
            )
            return self._build_aggregate_receipt(
                inventory=replayed,
                file_receipts=file_receipts,
            )

    def readback_inventory(
        self,
        *,
        bundle: RawRequestAuthorityBundleV2,
        inventory: BodyBlobInventoryV1,
        receipt: BodyBlobInventoryReadbackReceiptV1,
        expected_raw_authority_bundle_sha256: str,
        expected_inventory_sha256: str,
        expected_receipt_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> BodyBlobInventoryReadbackReceiptV1:
        """Re-read a sealed manifest and every blob under exact external pins."""

        expected_receipt = _exact_sha256(
            expected_receipt_sha256,
            label="expected body-blob inventory readback receipt",
        )
        bundle_pin = _exact_sha256(
            expected_raw_authority_bundle_sha256,
            label="expected body-blob raw bundle",
        )
        inventory_pin = _exact_sha256(
            expected_inventory_sha256,
            label="expected body-blob inventory",
        )
        if type(receipt) is not BodyBlobInventoryReadbackReceiptV1:
            raise _fail("body-blob inventory readback receipt has a foreign type")
        try:
            receipt_pin = _exact_sha256(
                receipt.receipt_sha256,
                label="candidate body-blob inventory readback receipt",
            )
            receipt_inventory_pin = _exact_sha256(
                receipt.inventory_sha256,
                label="candidate body-blob inventory readback inventory",
            )
            receipt_bundle_pin = _exact_sha256(
                receipt.raw_authority_bundle_sha256,
                label="candidate body-blob inventory readback raw bundle",
            )
            receipt_namespace_pin = _exact_sha256(
                receipt.store_namespace_sha256,
                label="candidate body-blob inventory readback namespace",
            )
        except BodyBlobStoreError:
            raise
        except Exception:
            raise _fail("body-blob inventory readback receipt pins are unavailable") from None
        if (
            receipt_pin != expected_receipt
            or receipt_inventory_pin != inventory_pin
            or receipt_bundle_pin != bundle_pin
            or receipt_namespace_pin != self._namespace_sha256
        ):
            raise _fail("body-blob inventory readback receipt differs from external pins")
        _bundle, validated, objects = self._validate_inputs(
            bundle=bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=bundle_pin,
            expected_inventory_sha256=inventory_pin,
            known_secrets=known_secrets,
        )
        try:
            admitted = BodyBlobInventoryReadbackReceiptV1.build(
                inventory=validated,
                file_readbacks=receipt.file_readbacks,
                observation_readbacks=receipt.observation_readbacks,
                store_namespace_sha256=self._namespace_sha256,
                expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
                expected_inventory_sha256=expected_inventory_sha256,
            )
        except Exception:
            raise _fail("body-blob inventory readback receipt failed pre-IO validation") from None
        try:
            admitted_bytes = admitted.to_canonical_bytes()
            receipt_bytes = receipt.to_canonical_bytes()
        except Exception:
            raise _fail(
                "body-blob inventory readback receipt failed exact reconstruction"
            ) from None
        if admitted_bytes != receipt_bytes:
            raise _fail("body-blob inventory readback receipt failed exact reconstruction")

        manifest_parts = self._manifest_resource_parts(validated.inventory_sha256)
        with self._locked_root() as root_descriptor:
            with self._open_parent_directory(
                root_descriptor,
                manifest_parts[:-1],
                create=False,
            ) as parent_descriptor:
                manifest = self._read_bound_file(
                    parent_descriptor,
                    manifest_parts[-1],
                    expected_length=len(validated.to_canonical_bytes()),
                    maximum_length=MAX_BODY_BLOB_CANONICAL_BYTES,
                    synchronize=True,
                )
                if manifest is None:
                    raise _fail("body-blob inventory manifest is missing")
            try:
                replayed = replay_body_blob_inventory(
                    manifest,
                    bundle=bundle,
                    expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
                    expected_inventory_sha256=expected_inventory_sha256,
                    known_secrets=known_secrets,
                )
            except Exception:
                raise _fail("body-blob inventory manifest failed exact readback replay") from None
            file_receipts = self._file_receipts(
                root_descriptor,
                inventory=replayed,
                objects=objects,
                persist=False,
                known_secrets=known_secrets,
            )
            rebuilt = self._build_aggregate_receipt(
                inventory=replayed,
                file_receipts=file_receipts,
            )
        if (
            rebuilt.receipt_sha256 != expected_receipt
            or rebuilt.to_canonical_bytes() != receipt.to_canonical_bytes()
        ):
            raise _fail("body-blob inventory readback differs from exact receipt authority")
        return rebuilt


__all__ = ["BodyBlobStore", "BodyBlobStoreError"]
