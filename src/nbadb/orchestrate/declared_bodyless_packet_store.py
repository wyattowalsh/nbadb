"""Descriptor-anchored durable storage for declared-bodyless static packets."""

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
from pathlib import Path
from typing import TYPE_CHECKING, Final

from nbadb.contracts.declared_bodyless_packet_types import (
    MAX_DECLARED_BODYLESS_PACKET_BYTES,
    DeclaredBodylessPacketError,
    DeclaredBodylessPacketReadbackReceiptV1,
    DeclaredBodylessPacketV1,
    validate_declared_bodyless_packet_bytes,
    validate_declared_bodyless_packet_readback_receipt,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


_LOCK_NAME: Final = ".declared-bodyless-packet.lock"
_LOCK_BOOTSTRAP_ATTEMPTS: Final = 4
_SAFE_ID_RE: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}\Z")
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)


class DeclaredBodylessPacketStoreError(RuntimeError):
    """Raised when packet persistence or exact readback cannot be proven."""


def _fail(message: str) -> DeclaredBodylessPacketStoreError:
    return DeclaredBodylessPacketStoreError(message)


def _close_descriptor(descriptor: int, *, failure_message: str) -> None:
    """Close one descriptor without exposing OS details or masking an active failure."""

    active_exception = sys.exception()
    try:
        os.close(descriptor)
    except OSError:
        if active_exception is None:
            raise _fail(failure_message) from None


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8", errors="strict")
    return hashlib.sha256(encoded).hexdigest()


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


def _require_platform() -> None:
    required = (
        os.name == "posix",
        hasattr(os, "O_DIRECTORY"),
        hasattr(os, "O_NOFOLLOW"),
        hasattr(os, "O_NONBLOCK"),
        os.open in os.supports_dir_fd,
        os.stat in os.supports_dir_fd,
        os.link in os.supports_dir_fd,
        os.unlink in os.supports_dir_fd,
    )
    if not all(required):
        raise _fail("declared bodyless storage requires descriptor-relative POSIX authority")


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC


def _read_flags() -> int:
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC


def _exact_positive_integer(value: object, *, label: str) -> int:
    if type(value) is not int or not 1 <= value <= (1 << 63) - 1:
        raise _fail(f"{label} must be one bounded exact positive integer")
    return value


def _exact_safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        raise _fail(f"{label} must be one exact public-safe identifier")
    return value


def _exact_source_sha(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise _fail("store source identity must be one exact Git SHA")
    return value


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _fail(f"{label} must be one exact SHA-256")
    return value


class DeclaredBodylessPacketStore:
    """A run-owned immutable packet store with exact post-commit readback."""

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
            raise _fail("declared bodyless store root must be one exact absolute Path")
        if any(part in {"", ".", ".."} for part in root.parts[1:]) or root == Path("/"):
            raise _fail("declared bodyless store root is invalid")
        self._root = root
        self._source_sha = _exact_source_sha(source_sha)
        self._run_id = _exact_positive_integer(run_id, label="store run ID")
        self._run_attempt = _exact_positive_integer(run_attempt, label="store run attempt")
        self._chain_id = _exact_safe_id(chain_id, label="store chain identity")
        self._lane_id = _exact_safe_id(lane_id, label="store lane identity")
        self._namespace_sha256 = _canonical_sha256(
            {
                "chain_id": self._chain_id,
                "kind": "nbadb_declared_bodyless_packet_store_namespace_v1",
                "lane_id": self._lane_id,
                "run_attempt": self._run_attempt,
                "run_id": self._run_id,
                "source_sha": self._source_sha,
            }
        )
        self._thread_lock = threading.RLock()
        descriptor, admitted_root = self._open_root()
        try:
            lock_descriptor = self._open_lock(descriptor, create=True)
            try:
                os.fsync(lock_descriptor)
                os.fsync(descriptor)
            finally:
                _close_descriptor(
                    lock_descriptor,
                    failure_message="declared bodyless store lock cannot be released safely",
                )
            self._require_named_root(descriptor, admitted_root)
        except OSError:
            raise _fail("declared bodyless store lock cannot be initialized safely") from None
        finally:
            _close_descriptor(
                descriptor,
                failure_message="declared bodyless store root cannot be released safely",
            )

    @property
    def namespace_sha256(self) -> str:
        """Return the path-free identity of this exact run-owned namespace."""

        return self._namespace_sha256

    def _open_root(self) -> tuple[int, tuple[int, int, int, int, int]]:
        descriptor = -1
        try:
            descriptor = os.open("/", _directory_flags())
            for part in self._root.parts[1:]:
                child = -1
                try:
                    child = os.open(part, _directory_flags(), dir_fd=descriptor)
                    opened = os.fstat(child)
                    if not stat.S_ISDIR(opened.st_mode):
                        raise _fail("declared bodyless store root is not a directory")
                except BaseException:
                    if child >= 0:
                        with suppress(OSError):
                            os.close(child)
                    raise
                previous = descriptor
                descriptor = child
                child = -1
                _close_descriptor(
                    previous,
                    failure_message="declared bodyless store root cannot be released safely",
                )
            opened_root = os.fstat(descriptor)
            named_root = os.stat(self._root, follow_symlinks=False)
        except DeclaredBodylessPacketStoreError:
            if descriptor >= 0:
                _close_descriptor(
                    descriptor,
                    failure_message="declared bodyless store root cannot be released safely",
                )
            raise
        except OSError:
            if descriptor >= 0:
                _close_descriptor(
                    descriptor,
                    failure_message="declared bodyless store root cannot be released safely",
                )
            raise _fail("declared bodyless store root cannot be opened safely") from None
        identity = _directory_identity(opened_root)
        if (
            identity != _directory_identity(named_root)
            or not stat.S_ISDIR(opened_root.st_mode)
            or opened_root.st_uid != os.geteuid()
            or stat.S_IMODE(opened_root.st_mode) & 0o077
        ):
            _close_descriptor(
                descriptor,
                failure_message="declared bodyless store root cannot be released safely",
            )
            raise _fail("declared bodyless store root lacks exact owner-only authority")
        return descriptor, identity

    def _require_named_root(
        self,
        root_descriptor: int,
        admitted_root: tuple[int, int, int, int, int],
    ) -> None:
        try:
            opened = os.fstat(root_descriptor)
            named = os.stat(self._root, follow_symlinks=False)
        except OSError:
            raise _fail("declared bodyless configured root binding is unavailable") from None
        if (
            _directory_identity(opened) != admitted_root
            or _directory_identity(named) != admitted_root
            or not stat.S_ISDIR(named.st_mode)
        ):
            raise _fail("declared bodyless configured root was rebound")

    @staticmethod
    def _validate_lock_binding(root_descriptor: int, lock_descriptor: int) -> None:
        try:
            opened = os.fstat(lock_descriptor)
            named = os.stat(_LOCK_NAME, dir_fd=root_descriptor, follow_symlinks=False)
        except OSError:
            raise _fail("declared bodyless store lock binding is unavailable") from None
        if (
            _stat_identity(opened) != _stat_identity(named)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o600
        ):
            raise _fail("declared bodyless store lock lacks exact regular-file authority")

    @classmethod
    def _open_lock(cls, root_descriptor: int, *, create: bool) -> int:
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | _CLOEXEC
        if create:
            flags |= os.O_CREAT
        for _attempt in range(_LOCK_BOOTSTRAP_ATTEMPTS if create else 1):
            descriptor = -1
            try:
                descriptor = os.open(
                    _LOCK_NAME,
                    flags,
                    0o600,
                    dir_fd=root_descriptor,
                )
                cls._validate_lock_binding(root_descriptor, descriptor)
                return descriptor
            except FileNotFoundError:
                if descriptor >= 0:
                    _close_descriptor(
                        descriptor,
                        failure_message="declared bodyless store lock cannot be released safely",
                    )
                continue
            except BaseException:
                if descriptor >= 0:
                    _close_descriptor(
                        descriptor,
                        failure_message="declared bodyless store lock cannot be released safely",
                    )
                raise
        raise _fail("declared bodyless store lock bootstrap did not converge") from None

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
            except DeclaredBodylessPacketStoreError:
                raise
            except OSError:
                raise _fail("declared bodyless store lock cannot be acquired safely") from None
            finally:
                active_exception = sys.exception()
                release_failed = False
                if lock_descriptor >= 0:
                    with suppress(OSError):
                        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                    try:
                        os.close(lock_descriptor)
                    except OSError:
                        release_failed = True
                try:
                    os.close(root_descriptor)
                except OSError:
                    release_failed = True
                if release_failed and active_exception is None:
                    raise _fail(
                        "declared bodyless store descriptors cannot be released safely"
                    ) from None

    @staticmethod
    def _packet_name(packet: DeclaredBodylessPacketV1) -> str:
        name = packet.public_resource_name
        if (
            type(name) is not str
            or not name.endswith(".json")
            or "/" in name
            or "\\" in name
            or name in {".", ".."}
        ):
            raise _fail("declared bodyless public resource identity is invalid")
        return name

    @staticmethod
    def _read_bound_file(
        root_descriptor: int,
        name: str,
        *,
        expected_length: int,
        expected_nlink: int = 1,
        synchronize: bool = False,
    ) -> bytes | None:
        if type(expected_nlink) is not int or expected_nlink not in {1, 2}:
            raise _fail("declared bodyless packet link authority is invalid")
        try:
            named_before = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return None
        except OSError:
            raise _fail("declared bodyless packet cannot be inspected safely") from None
        if (
            not stat.S_ISREG(named_before.st_mode)
            or named_before.st_nlink != expected_nlink
            or named_before.st_uid != os.geteuid()
            or stat.S_IMODE(named_before.st_mode) != 0o600
            or named_before.st_size != expected_length
            or not 1 <= named_before.st_size <= MAX_DECLARED_BODYLESS_PACKET_BYTES
        ):
            raise _fail("declared bodyless packet storage is corrupt or colliding")
        descriptor = -1
        try:
            descriptor = os.open(name, _read_flags(), dir_fd=root_descriptor)
            opened_before = os.fstat(descriptor)
            admitted = _stat_identity(opened_before)
            if admitted != _stat_identity(named_before) or not stat.S_ISREG(opened_before.st_mode):
                raise _fail("declared bodyless packet changed while it was opened")
            remaining = expected_length
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise _fail("declared bodyless packet ended before its admitted length")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise _fail("declared bodyless packet contains trailing bytes")
            if synchronize:
                os.fsync(descriptor)
            opened_after = os.fstat(descriptor)
            named_after = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
            if synchronize:
                os.fsync(root_descriptor)
        except DeclaredBodylessPacketStoreError:
            raise
        except OSError:
            raise _fail("declared bodyless packet cannot be read safely") from None
        finally:
            if descriptor >= 0:
                _close_descriptor(
                    descriptor,
                    failure_message="declared bodyless packet descriptor cannot be released safely",
                )
        if admitted != _stat_identity(opened_after) or admitted != _stat_identity(named_after):
            raise _fail("declared bodyless packet changed during exact readback")
        return b"".join(chunks)

    def _temporary_name(self, packet_name: str) -> str:
        temporary_name = f".{packet_name}.{self._namespace_sha256}.tmp"
        if len(os.fsencode(temporary_name)) > 255:
            raise _fail("declared bodyless temporary resource identity is too long")
        return temporary_name

    @classmethod
    def _reconcile_temporary_install(
        cls,
        root_descriptor: int,
        *,
        temporary_name: str,
        packet_name: str,
        packet_bytes: bytes,
        expected_length: int,
    ) -> None:
        """Recover only an exact descriptor-bound interrupted install."""

        try:
            temporary_stat = os.stat(
                temporary_name,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        except OSError:
            raise _fail("declared bodyless temporary packet cannot be inspected safely") from None
        if (
            not stat.S_ISREG(temporary_stat.st_mode)
            or temporary_stat.st_uid != os.geteuid()
            or stat.S_IMODE(temporary_stat.st_mode) != 0o600
            or temporary_stat.st_nlink not in {1, 2}
        ):
            raise _fail("declared bodyless temporary packet lacks exact authority")

        try:
            packet_stat = os.stat(
                packet_name,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            packet_stat = None
        except OSError:
            raise _fail("declared bodyless packet cannot be inspected safely") from None

        try:
            if packet_stat is None:
                if temporary_stat.st_nlink != 1:
                    raise _fail("declared bodyless interrupted install has foreign links")
                if temporary_stat.st_size != expected_length:
                    current = os.stat(
                        temporary_name,
                        dir_fd=root_descriptor,
                        follow_symlinks=False,
                    )
                    if _stat_identity(current) != _stat_identity(temporary_stat):
                        raise _fail("declared bodyless temporary packet changed during recovery")
                    os.unlink(temporary_name, dir_fd=root_descriptor)
                    os.fsync(root_descriptor)
                    return
                temporary_bytes = cls._read_bound_file(
                    root_descriptor,
                    temporary_name,
                    expected_length=expected_length,
                    synchronize=True,
                )
                if temporary_bytes != packet_bytes:
                    raise _fail(
                        "declared bodyless temporary packet collides with different content"
                    )
                os.link(
                    temporary_name,
                    packet_name,
                    src_dir_fd=root_descriptor,
                    dst_dir_fd=root_descriptor,
                    follow_symlinks=False,
                )
                os.unlink(temporary_name, dir_fd=root_descriptor)
                os.fsync(root_descriptor)
                return

            same_member = (
                temporary_stat.st_dev == packet_stat.st_dev
                and temporary_stat.st_ino == packet_stat.st_ino
            )
            if (
                not same_member
                or temporary_stat.st_nlink != 2
                or packet_stat.st_nlink != 2
                or not stat.S_ISREG(packet_stat.st_mode)
                or packet_stat.st_uid != os.geteuid()
                or stat.S_IMODE(packet_stat.st_mode) != 0o600
                or temporary_stat.st_size != expected_length
                or packet_stat.st_size != expected_length
            ):
                raise _fail("declared bodyless interrupted install is corrupt or colliding")
            temporary_bytes = cls._read_bound_file(
                root_descriptor,
                temporary_name,
                expected_length=expected_length,
                expected_nlink=2,
                synchronize=True,
            )
            installed_bytes = cls._read_bound_file(
                root_descriptor,
                packet_name,
                expected_length=expected_length,
                expected_nlink=2,
            )
            if temporary_bytes != packet_bytes or installed_bytes != packet_bytes:
                raise _fail("declared bodyless interrupted install differs from exact content")
            os.unlink(temporary_name, dir_fd=root_descriptor)
            os.fsync(root_descriptor)
        except DeclaredBodylessPacketStoreError:
            raise
        except OSError:
            raise _fail(
                "declared bodyless interrupted install cannot be recovered safely"
            ) from None

    def _require_store_identity(self, packet: DeclaredBodylessPacketV1) -> None:
        if (
            packet.source_sha != self._source_sha
            or packet.run_id != self._run_id
            or packet.run_attempt != self._run_attempt
            or packet.chain_id != self._chain_id
            or packet.lane_id != self._lane_id
        ):
            raise _fail("declared bodyless packet references a foreign run namespace")

    def persist(
        self,
        *,
        packet: DeclaredBodylessPacketV1,
        packet_bytes: bytes,
        expected_observation_sha256: str,
        expected_observation_record_sha256: str,
        expected_packet_authority_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> DeclaredBodylessPacketReadbackReceiptV1:
        """Validate, atomically install, durably sync, and read back one packet."""

        try:
            validated = validate_declared_bodyless_packet_bytes(
                packet,
                packet_bytes=packet_bytes,
                expected_observation_sha256=expected_observation_sha256,
                expected_observation_record_sha256=expected_observation_record_sha256,
                expected_packet_authority_sha256=expected_packet_authority_sha256,
                known_secrets=known_secrets,
            )
        except DeclaredBodylessPacketError:
            raise _fail("declared bodyless packet failed exact authority validation") from None
        self._require_store_identity(validated)
        name = self._packet_name(validated)
        temporary_name = self._temporary_name(name)
        with self._locked_root() as root_descriptor:
            self._reconcile_temporary_install(
                root_descriptor,
                temporary_name=temporary_name,
                packet_name=name,
                packet_bytes=packet_bytes,
                expected_length=validated.stored_payload_length,
            )
            existing = self._read_bound_file(
                root_descriptor,
                name,
                expected_length=validated.stored_payload_length,
                synchronize=True,
            )
            if existing is not None:
                if existing != packet_bytes:
                    raise _fail("declared bodyless packet key collides with different content")
                return DeclaredBodylessPacketReadbackReceiptV1.build(
                    packet=validated,
                    readback_bytes=existing,
                    store_namespace_sha256=self._namespace_sha256,
                    expected_packet_authority_sha256=expected_packet_authority_sha256,
                    known_secrets=known_secrets,
                )

            descriptor = -1
            try:
                descriptor = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | _CLOEXEC,
                    0o600,
                    dir_fd=root_descriptor,
                )
                view = memoryview(packet_bytes)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("declared bodyless packet write did not progress")
                    view = view[written:]
                os.fchmod(descriptor, 0o600)
                os.fsync(descriptor)
                _close_descriptor(
                    descriptor,
                    failure_message="declared bodyless packet descriptor cannot be released safely",
                )
                descriptor = -1
                os.link(
                    temporary_name,
                    name,
                    src_dir_fd=root_descriptor,
                    dst_dir_fd=root_descriptor,
                    follow_symlinks=False,
                )
                os.unlink(temporary_name, dir_fd=root_descriptor)
                os.fsync(root_descriptor)
            except DeclaredBodylessPacketStoreError:
                raise
            except OSError:
                raise _fail("declared bodyless packet cannot be installed durably") from None
            finally:
                if descriptor >= 0:
                    with suppress(OSError):
                        os.close(descriptor)
                with suppress(OSError):
                    os.unlink(temporary_name, dir_fd=root_descriptor)

            readback = self._read_bound_file(
                root_descriptor,
                name,
                expected_length=validated.stored_payload_length,
            )
            if readback is None or readback != packet_bytes:
                raise _fail("declared bodyless packet post-commit readback failed")
            return DeclaredBodylessPacketReadbackReceiptV1.build(
                packet=validated,
                readback_bytes=readback,
                store_namespace_sha256=self._namespace_sha256,
                expected_packet_authority_sha256=expected_packet_authority_sha256,
                known_secrets=known_secrets,
            )

    def readback(
        self,
        *,
        receipt: DeclaredBodylessPacketReadbackReceiptV1,
        packet: DeclaredBodylessPacketV1,
        packet_bytes: bytes,
        expected_observation_sha256: str,
        expected_observation_record_sha256: str,
        expected_packet_authority_sha256: str,
        expected_receipt_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> bytes:
        """Read exact stored bytes only after packet and receipt reconstruction."""

        expected_receipt = _exact_sha256(
            expected_receipt_sha256,
            label="expected readback receipt",
        )
        if type(receipt) is not DeclaredBodylessPacketReadbackReceiptV1:
            raise _fail("declared bodyless readback receipt has a foreign type")
        candidate_receipt = _exact_sha256(
            receipt.receipt_sha256,
            label="candidate readback receipt",
        )
        if candidate_receipt != expected_receipt:
            raise _fail("declared bodyless readback receipt differs from its external authority")
        try:
            validated = validate_declared_bodyless_packet_bytes(
                packet,
                packet_bytes=packet_bytes,
                expected_observation_sha256=expected_observation_sha256,
                expected_observation_record_sha256=expected_observation_record_sha256,
                expected_packet_authority_sha256=expected_packet_authority_sha256,
                known_secrets=known_secrets,
            )
        except DeclaredBodylessPacketError:
            raise _fail("declared bodyless packet failed exact readback validation") from None
        try:
            validate_declared_bodyless_packet_readback_receipt(
                receipt,
                packet=validated,
                readback_bytes=packet_bytes,
                store_namespace_sha256=self._namespace_sha256,
                expected_packet_authority_sha256=expected_packet_authority_sha256,
                expected_receipt_sha256=expected_receipt_sha256,
                known_secrets=known_secrets,
            )
        except DeclaredBodylessPacketError:
            raise _fail("declared bodyless readback receipt is invalid") from None
        self._require_store_identity(validated)
        name = self._packet_name(validated)
        with self._locked_root() as root_descriptor:
            readback = self._read_bound_file(
                root_descriptor,
                name,
                expected_length=validated.stored_payload_length,
                synchronize=True,
            )
            if readback is None or readback != packet_bytes:
                raise _fail("declared bodyless packet exact readback is unavailable")
        try:
            validate_declared_bodyless_packet_readback_receipt(
                receipt,
                packet=validated,
                readback_bytes=readback,
                store_namespace_sha256=self._namespace_sha256,
                expected_packet_authority_sha256=expected_packet_authority_sha256,
                expected_receipt_sha256=expected_receipt_sha256,
                known_secrets=known_secrets,
            )
        except DeclaredBodylessPacketError:
            raise _fail("declared bodyless readback receipt is invalid") from None
        return readback


__all__ = [
    "DeclaredBodylessPacketStore",
    "DeclaredBodylessPacketStoreError",
]
