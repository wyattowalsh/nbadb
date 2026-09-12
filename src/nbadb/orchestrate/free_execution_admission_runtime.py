from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, NoReturn, Self, cast

from nbadb.orchestrate.free_execution_admission import (
    ExactHttpResponseV1,
    ExecutionIntentV1,
    FreeExecutionAdmissionError,
    FreeExecutionAdmissionStatus,
    FreeExecutionAdmissionV1,
    FreeExecutionAuthorityBundleV1,
    FreeExecutionMode,
    FreeExecutionPointOfUseV1,
    PointOfUseAuthorityBundleV1,
    ProviderOperationV1,
    canonical_json_bytes,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "FREE_EXECUTION_BOUNDARY_SCHEMA_VERSION",
    "AtomicFileReplayLedgerV1",
    "FreeExecutionBoundaryError",
    "FreeExecutionBoundaryV1",
    "LedgerRootAuthorityV1",
    "ProviderRequestAuthorizationV1",
    "apply_free_execution_admission",
    "authorize_provider_request",
    "load_free_execution_admission",
]

FREE_EXECUTION_BOUNDARY_SCHEMA_VERSION = 1

_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_MAX_TEXT_BYTES = 16_384
_MAX_INT = (1 << 63) - 1

_LEDGER_INTEGRATION_BLOCKERS = (
    "ledger_root_restore_checkpoint_collector_not_integrated",
    "ledger_tip_chain_collector_not_integrated",
)
_RUNTIME_INTEGRATION_BLOCKERS = (
    "free_execution_manifest_artifact_collector_not_integrated",
    "free_execution_run_job_context_collector_not_integrated",
    "free_execution_workflow_content_collector_not_integrated",
    *_LEDGER_INTEGRATION_BLOCKERS,
)
_AUTHORIZATION_INTEGRATION_BLOCKERS = (
    "free_execution_nonce_issuer_not_integrated",
    "free_execution_operation_registry_not_integrated",
    "free_execution_point_predecessor_chain_collector_not_integrated",
    "free_execution_point_refresh_collector_not_integrated",
    *_LEDGER_INTEGRATION_BLOCKERS,
)


class FreeExecutionBoundaryError(ValueError):
    """Raised when the runtime cannot reconstruct a strictly-free boundary."""


def _raise_runtime_integration_blocked(
    *,
    stage: str,
    codes: tuple[str, ...],
) -> NoReturn:
    normalized = tuple(sorted(set(codes)))
    if not normalized:
        raise FreeExecutionBoundaryError(f"{stage} has no trusted collector capability")
    raise FreeExecutionBoundaryError(f"{stage} is integration-blocked: {','.join(normalized)}")


def _exact_text(value: object, *, field_name: str, maximum_bytes: int = 1024) -> str:
    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value.encode("utf-8")) > maximum_bytes
    ):
        raise FreeExecutionBoundaryError(f"{field_name} must be a bounded exact string")
    return value


def _uint(value: object, *, field_name: str, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or not minimum <= value <= _MAX_INT:
        raise FreeExecutionBoundaryError(f"{field_name} must be a bounded integer")
    return value


def _sha256(value: object, *, field_name: str) -> str:
    raw = _exact_text(value, field_name=field_name)
    if len(raw) != 64 or any(character not in "0123456789abcdef" for character in raw):
        raise FreeExecutionBoundaryError(f"{field_name} must be a lowercase SHA-256")
    return raw


def _timestamp(value: object, *, field_name: str) -> datetime:
    raw = _exact_text(value, field_name=field_name)
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise FreeExecutionBoundaryError(f"{field_name} must be canonical UTC") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != raw:
        raise FreeExecutionBoundaryError(f"{field_name} must be canonical UTC")
    return parsed


def _sealed_digest(supplied: str, identity: Mapping[str, object], *, field_name: str) -> str:
    expected = hashlib.sha256(canonical_json_bytes(dict(identity))).hexdigest()
    if supplied and supplied != expected:
        raise FreeExecutionBoundaryError(f"{field_name} is invalid")
    return expected


def _exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if type(payload) is not dict or frozenset(payload) != expected:
        raise FreeExecutionBoundaryError(f"{label} fields are invalid")


def _normalize_admission(
    raw: FreeExecutionAdmissionV1 | Mapping[str, object] | bytes,
) -> FreeExecutionAdmissionV1:
    try:
        if type(raw) is FreeExecutionAdmissionV1:
            return FreeExecutionAdmissionV1.from_bytes(raw.to_bytes())
        if type(raw) is bytes:
            return FreeExecutionAdmissionV1.from_bytes(raw)
        if type(raw) is dict:
            return FreeExecutionAdmissionV1.from_dict(cast("Mapping[str, object]", raw))
    except FreeExecutionAdmissionError as exc:
        raise FreeExecutionBoundaryError(f"free execution admission is invalid: {exc}") from exc
    raise FreeExecutionBoundaryError("free execution admission representation is unsupported")


def _normalize_point(
    raw: FreeExecutionPointOfUseV1 | Mapping[str, object] | bytes,
) -> FreeExecutionPointOfUseV1:
    try:
        if type(raw) is FreeExecutionPointOfUseV1:
            return FreeExecutionPointOfUseV1.from_bytes(raw.to_bytes())
        if type(raw) is bytes:
            return FreeExecutionPointOfUseV1.from_bytes(raw)
        if type(raw) is dict:
            return FreeExecutionPointOfUseV1.from_dict(cast("Mapping[str, object]", raw))
    except FreeExecutionAdmissionError as exc:
        raise FreeExecutionBoundaryError(f"point-of-use receipt is invalid: {exc}") from exc
    raise FreeExecutionBoundaryError("point-of-use representation is unsupported")


def _read_regular_file(path: Path) -> bytes:
    if not isinstance(path, Path):
        raise FreeExecutionBoundaryError("receipt path must be a concrete Path")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nofollow is None or nonblock is None:
        raise FreeExecutionBoundaryError("platform lacks required safe-open flags")
    flags = os.O_RDONLY | nofollow | nonblock
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FreeExecutionBoundaryError("receipt could not be opened safely") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= _MAX_RECEIPT_BYTES:
            raise FreeExecutionBoundaryError("receipt is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1 << 20))
            if not chunk:
                raise FreeExecutionBoundaryError("receipt changed during descriptor readback")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise FreeExecutionBoundaryError("receipt grew during descriptor readback")
        return b"".join(chunks)
    except OSError as exc:
        raise FreeExecutionBoundaryError("receipt descriptor readback failed") from exc
    finally:
        os.close(descriptor)


def load_free_execution_admission(path: Path) -> FreeExecutionAdmissionV1:
    """Load one canonical admission through a no-follow regular-file descriptor."""
    return _normalize_admission(_read_regular_file(path))


@dataclass(frozen=True, slots=True)
class LedgerRootAuthorityV1:
    """Exact restored ledger-root authority; a fresh caller path alone is insufficient."""

    root_path: Path
    repository: str
    source_sha: str
    run_id: int
    run_attempt: int
    root_device: int
    root_inode: int
    restoration_checkpoint_sha256: str
    authority_response_sha256: str
    authority_response_receipt_sha256: str
    checkpoint_response: ExactHttpResponseV1 = field(repr=False, compare=False)
    authority_sha256: str = ""

    schema_version: ClassVar[int] = 1
    integration_blocker_codes: ClassVar[tuple[str, ...]] = _LEDGER_INTEGRATION_BLOCKERS

    def __post_init__(self) -> None:
        _raise_runtime_integration_blocked(
            stage="ledger root authority",
            codes=_LEDGER_INTEGRATION_BLOCKERS,
        )
        if not isinstance(self.root_path, Path) or not self.root_path.is_absolute():
            raise FreeExecutionBoundaryError("ledger root must be an absolute concrete Path")
        _exact_text(self.repository, field_name="repository")
        _exact_text(self.source_sha, field_name="source_sha")
        _uint(self.run_id, field_name="run_id", positive=True)
        _uint(self.run_attempt, field_name="run_attempt", positive=True)
        _uint(self.root_device, field_name="root_device")
        _uint(self.root_inode, field_name="root_inode", positive=True)
        _sha256(
            self.restoration_checkpoint_sha256,
            field_name="restoration_checkpoint_sha256",
        )
        _sha256(self.authority_response_sha256, field_name="authority_response_sha256")
        _sha256(
            self.authority_response_receipt_sha256,
            field_name="authority_response_receipt_sha256",
        )
        self._validate_checkpoint_authority()
        object.__setattr__(
            self,
            "authority_sha256",
            _sealed_digest(
                self.authority_sha256,
                self._identity_dict(),
                field_name="ledger_root.authority_sha256",
            ),
        )

    def validate_seal(self) -> None:
        self._validate_checkpoint_authority()
        expected = hashlib.sha256(canonical_json_bytes(self._identity_dict())).hexdigest()
        if self.authority_sha256 != expected:
            raise FreeExecutionBoundaryError("ledger root authority changed after sealing")

    def _validate_checkpoint_authority(self) -> None:
        if type(self.checkpoint_response) is not ExactHttpResponseV1:
            raise FreeExecutionBoundaryError("ledger checkpoint response authority is foreign")
        self.checkpoint_response.validate_seal()
        expected_url = (
            f"https://api.github.com/repos/{self.repository}/actions/runs/{self.run_id}/"
            f"attempts/{self.run_attempt}/free-execution-ledger-root"
        )
        if (
            self.checkpoint_response.url != expected_url
            or self.checkpoint_response.api_version != "2026-03-10"
            or self.checkpoint_response.etag is None
            or self.checkpoint_response.body_sha256 != self.authority_response_sha256
            or self.checkpoint_response.receipt_sha256 != self.authority_response_receipt_sha256
        ):
            raise FreeExecutionBoundaryError("ledger checkpoint response identity is foreign")
        payload = self.checkpoint_response.json_object()
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "repository",
                    "source_sha",
                    "run_id",
                    "run_attempt",
                    "root_path",
                    "root_device",
                    "root_inode",
                    "restoration_checkpoint_sha256",
                    "restored",
                }
            ),
            label="ledger root checkpoint authority",
        )
        try:
            metadata = self.root_path.lstat()
        except OSError as exc:
            raise FreeExecutionBoundaryError("ledger root is unavailable") from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or self.root_path.is_symlink()
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or payload["schema_version"] != 1
            or payload["repository"] != self.repository
            or payload["source_sha"] != self.source_sha
            or payload["run_id"] != self.run_id
            or payload["run_attempt"] != self.run_attempt
            or payload["root_path"] != str(self.root_path)
            or payload["root_device"] != self.root_device
            or payload["root_inode"] != self.root_inode
            or payload["root_device"] != metadata.st_dev
            or payload["root_inode"] != metadata.st_ino
            or payload["restoration_checkpoint_sha256"] != self.restoration_checkpoint_sha256
            or payload["restored"] is not True
        ):
            raise FreeExecutionBoundaryError("ledger root checkpoint authority is foreign")

    @classmethod
    def from_checkpoint_authority(
        cls,
        *,
        root_path: Path,
        repository: str,
        source_sha: str,
        run_id: int,
        run_attempt: int,
        response: ExactHttpResponseV1,
    ) -> Self:
        _raise_runtime_integration_blocked(
            stage="ledger root authority",
            codes=_LEDGER_INTEGRATION_BLOCKERS,
        )
        if not isinstance(root_path, Path) or not root_path.is_absolute():
            raise FreeExecutionBoundaryError("ledger root must be an absolute concrete Path")
        expected_url = (
            f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/"
            f"attempts/{run_attempt}/free-execution-ledger-root"
        )
        if (
            response.url != expected_url
            or response.api_version != "2026-03-10"
            or response.etag is None
        ):
            raise FreeExecutionBoundaryError("ledger root checkpoint authority URL is foreign")
        payload = response.json_object()
        _exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "repository",
                    "source_sha",
                    "run_id",
                    "run_attempt",
                    "root_path",
                    "root_device",
                    "root_inode",
                    "restoration_checkpoint_sha256",
                    "restored",
                }
            ),
            label="ledger root checkpoint authority",
        )
        try:
            metadata = root_path.lstat()
        except OSError as exc:
            raise FreeExecutionBoundaryError("ledger root is unavailable") from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or root_path.is_symlink()
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise FreeExecutionBoundaryError("ledger root ownership/type/mode is unsafe")
        if (
            payload["schema_version"] != 1
            or payload["repository"] != repository
            or payload["source_sha"] != source_sha
            or payload["run_id"] != run_id
            or payload["run_attempt"] != run_attempt
            or payload["root_path"] != str(root_path)
            or payload["root_device"] != metadata.st_dev
            or payload["root_inode"] != metadata.st_ino
            or payload["restored"] is not True
        ):
            raise FreeExecutionBoundaryError("ledger root checkpoint authority is foreign")
        return cls(
            root_path=root_path,
            repository=repository,
            source_sha=source_sha,
            run_id=run_id,
            run_attempt=run_attempt,
            root_device=metadata.st_dev,
            root_inode=metadata.st_ino,
            restoration_checkpoint_sha256=_sha256(
                payload["restoration_checkpoint_sha256"],
                field_name="restoration_checkpoint_sha256",
            ),
            authority_response_sha256=response.body_sha256,
            authority_response_receipt_sha256=response.receipt_sha256,
            checkpoint_response=response,
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "root_path": str(self.root_path),
            "repository": self.repository,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "root_device": self.root_device,
            "root_inode": self.root_inode,
            "restoration_checkpoint_sha256": self.restoration_checkpoint_sha256,
            "authority_response_sha256": self.authority_response_sha256,
            "authority_response_receipt_sha256": self.authority_response_receipt_sha256,
        }


@dataclass(frozen=True, slots=True)
class _LedgerClaimV1:
    marker_name: str
    marker_sha256: str


class AtomicFileReplayLedgerV1:
    """Descriptor-anchored, atomic, durable single-use replay ledger."""

    def __init__(self, authority: LedgerRootAuthorityV1) -> None:
        if type(authority) is not LedgerRootAuthorityV1:
            raise FreeExecutionBoundaryError("ledger requires exact restored root authority")
        self._authority = authority

    @property
    def authority(self) -> LedgerRootAuthorityV1:
        self._authority.validate_seal()
        return self._authority

    def _open_root(self) -> int:
        self._authority.validate_seal()
        directory = getattr(os, "O_DIRECTORY", None)
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if directory is None or nofollow is None:
            raise FreeExecutionBoundaryError("platform lacks descriptor-anchored directory flags")
        flags = os.O_RDONLY | directory | nofollow
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            descriptor = os.open(self._authority.root_path, flags)
        except OSError as exc:
            raise FreeExecutionBoundaryError("ledger root could not be opened safely") from exc
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_dev != self._authority.root_device
            or metadata.st_ino != self._authority.root_inode
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            os.close(descriptor)
            raise FreeExecutionBoundaryError("ledger root drifted from checkpoint authority")
        return descriptor

    def claim(self, *, claim_kind: str, identity: Mapping[str, object]) -> _LedgerClaimV1:
        kind = _exact_text(claim_kind, field_name="claim_kind")
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", kind) is None:
            raise FreeExecutionBoundaryError("ledger claim kind is invalid")
        identity_copy = json.loads(canonical_json_bytes(dict(identity)).decode("utf-8"))
        marker_identity = {
            "schema_version": 1,
            "claim_kind": kind,
            "ledger_root_authority_sha256": self._authority.authority_sha256,
            "identity": identity_copy,
        }
        marker_sha = hashlib.sha256(canonical_json_bytes(marker_identity)).hexdigest()
        marker_name = f"{kind}-{marker_sha}.json"
        if len(marker_name.encode("utf-8")) > 255 or "/" in marker_name:
            raise FreeExecutionBoundaryError("ledger marker name is invalid")
        marker_payload = canonical_json_bytes({**marker_identity, "marker_sha256": marker_sha})
        root_descriptor = self._open_root()
        marker_descriptor: int | None = None
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            try:
                marker_descriptor = os.open(
                    marker_name,
                    flags,
                    0o600,
                    dir_fd=root_descriptor,
                )
            except FileExistsError as exc:
                raise FreeExecutionBoundaryError(
                    "single-use authority was already consumed"
                ) from exc
            except OSError as exc:
                raise FreeExecutionBoundaryError("ledger marker claim failed") from exc
            offset = 0
            while offset < len(marker_payload):
                written = os.write(marker_descriptor, marker_payload[offset:])
                if written <= 0:
                    raise FreeExecutionBoundaryError("ledger marker write made no progress")
                offset += written
            os.fsync(marker_descriptor)
            metadata = os.fstat(marker_descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size != len(marker_payload)
            ):
                raise FreeExecutionBoundaryError("ledger marker metadata is unsafe")
            os.close(marker_descriptor)
            marker_descriptor = None
            os.fsync(root_descriptor)
            read_flags = os.O_RDONLY
            if hasattr(os, "O_CLOEXEC"):
                read_flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                read_flags |= os.O_NOFOLLOW
            read_descriptor = os.open(marker_name, read_flags, dir_fd=root_descriptor)
            try:
                readback = bytearray()
                while len(readback) < len(marker_payload):
                    chunk = os.read(read_descriptor, len(marker_payload) - len(readback))
                    if not chunk:
                        break
                    readback.extend(chunk)
                if bytes(readback) != marker_payload or os.read(read_descriptor, 1):
                    raise FreeExecutionBoundaryError("ledger marker readback differs after fsync")
            finally:
                os.close(read_descriptor)
        finally:
            if marker_descriptor is not None:
                os.close(marker_descriptor)
            os.close(root_descriptor)
        return _LedgerClaimV1(marker_name=marker_name, marker_sha256=marker_sha)

    def open_marker(
        self,
        *,
        claim_kind: str,
        marker_sha256: str,
        identity: Mapping[str, object],
    ) -> _LedgerClaimV1:
        """Reopen one exact descriptor-anchored marker as validation authority."""
        kind = _exact_text(claim_kind, field_name="claim_kind")
        if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", kind) is None:
            raise FreeExecutionBoundaryError("ledger claim kind is invalid")
        marker_sha = _sha256(marker_sha256, field_name="marker_sha256")
        identity_copy = json.loads(canonical_json_bytes(dict(identity)).decode("utf-8"))
        marker_identity = {
            "schema_version": 1,
            "claim_kind": kind,
            "ledger_root_authority_sha256": self._authority.authority_sha256,
            "identity": identity_copy,
        }
        expected_sha = hashlib.sha256(canonical_json_bytes(marker_identity)).hexdigest()
        if marker_sha != expected_sha:
            raise FreeExecutionBoundaryError("ledger marker identity digest is foreign")
        marker_name = f"{kind}-{marker_sha}.json"
        root_descriptor = self._open_root()
        descriptor: int | None = None
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        nofollow = getattr(os, "O_NOFOLLOW", None)
        nonblock = getattr(os, "O_NONBLOCK", None)
        if nofollow is None or nonblock is None:
            os.close(root_descriptor)
            raise FreeExecutionBoundaryError("platform lacks safe ledger readback flags")
        flags |= nofollow | nonblock
        try:
            try:
                descriptor = os.open(marker_name, flags, dir_fd=root_descriptor)
            except OSError as exc:
                raise FreeExecutionBoundaryError("ledger marker is unavailable") from exc
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or not 0 < metadata.st_size <= _MAX_RECEIPT_BYTES
            ):
                raise FreeExecutionBoundaryError("ledger marker metadata is unsafe")
            readback = bytearray()
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1 << 20))
                if not chunk:
                    raise FreeExecutionBoundaryError("ledger marker changed during readback")
                readback.extend(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise FreeExecutionBoundaryError("ledger marker grew during readback")
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(root_descriptor)
        try:
            payload = json.loads(bytes(readback))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FreeExecutionBoundaryError("ledger marker is not exact JSON") from exc
        expected_payload = {**marker_identity, "marker_sha256": marker_sha}
        if (
            type(payload) is not dict
            or payload != expected_payload
            or canonical_json_bytes(payload) != bytes(readback)
        ):
            raise FreeExecutionBoundaryError("ledger marker content is foreign")
        return _LedgerClaimV1(marker_name=marker_name, marker_sha256=marker_sha)


@dataclass(frozen=True, slots=True)
class FreeExecutionBoundaryV1:
    admission_sha256: str
    intent_sha256: str
    ledger_root_authority_sha256: str
    ledger_marker_sha256: str
    status: FreeExecutionAdmissionStatus
    provider_calls_allowed: bool
    execution_slot_count: int
    matrix_lane_count: int
    deferred_lane_count: int
    boundary_sha256: str = ""

    schema_version: ClassVar[int] = FREE_EXECUTION_BOUNDARY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "admission_sha256",
            "intent_sha256",
            "ledger_root_authority_sha256",
            "ledger_marker_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        if type(self.status) is not FreeExecutionAdmissionStatus:
            raise FreeExecutionBoundaryError("boundary status is invalid")
        if type(self.provider_calls_allowed) is not bool:
            raise FreeExecutionBoundaryError("provider_calls_allowed must be boolean")
        slots = _uint(self.execution_slot_count, field_name="execution_slot_count")
        matrix = _uint(self.matrix_lane_count, field_name="matrix_lane_count")
        _uint(self.deferred_lane_count, field_name="deferred_lane_count")
        if self.status is FreeExecutionAdmissionStatus.ADMITTED:
            _raise_runtime_integration_blocked(
                stage="positive free-execution boundary",
                codes=_RUNTIME_INTEGRATION_BLOCKERS,
            )
            if not self.provider_calls_allowed or slots < 1:
                raise FreeExecutionBoundaryError("positive boundary capacity is invalid")
        elif self.provider_calls_allowed or slots != 0 or matrix != 0:
            raise FreeExecutionBoundaryError("blocked boundary materializes provider work")
        object.__setattr__(
            self,
            "boundary_sha256",
            _sealed_digest(
                self.boundary_sha256,
                self._identity_dict(),
                field_name="boundary_sha256",
            ),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "admission_sha256": self.admission_sha256,
            "intent_sha256": self.intent_sha256,
            "ledger_root_authority_sha256": self.ledger_root_authority_sha256,
            "ledger_marker_sha256": self.ledger_marker_sha256,
            "status": self.status.value,
            "provider_calls_allowed": self.provider_calls_allowed,
            "execution_slot_count": self.execution_slot_count,
            "matrix_lane_count": self.matrix_lane_count,
            "deferred_lane_count": self.deferred_lane_count,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "boundary_sha256": self.boundary_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(cls.__dataclass_fields__) | {"schema_version"}
        _exact_keys(payload, expected=expected, label="free execution boundary")
        if (
            payload["schema_version"] != cls.schema_version
            or type(payload["schema_version"]) is not int
        ):
            raise FreeExecutionBoundaryError("free execution boundary schema is unsupported")
        try:
            status = FreeExecutionAdmissionStatus(
                _exact_text(payload["status"], field_name="status")
            )
        except ValueError as exc:
            raise FreeExecutionBoundaryError("boundary status is unsupported") from exc
        return cls(
            admission_sha256=cast("str", payload["admission_sha256"]),
            intent_sha256=cast("str", payload["intent_sha256"]),
            ledger_root_authority_sha256=cast("str", payload["ledger_root_authority_sha256"]),
            ledger_marker_sha256=cast("str", payload["ledger_marker_sha256"]),
            status=status,
            provider_calls_allowed=cast("bool", payload["provider_calls_allowed"]),
            execution_slot_count=cast("int", payload["execution_slot_count"]),
            matrix_lane_count=cast("int", payload["matrix_lane_count"]),
            deferred_lane_count=cast("int", payload["deferred_lane_count"]),
            boundary_sha256=cast("str", payload["boundary_sha256"]),
        )

    def validate_for(
        self,
        *,
        admission: FreeExecutionAdmissionV1,
        ledger: AtomicFileReplayLedgerV1,
    ) -> None:
        """Reopen the exact ledger marker; a sealed summary is never authority."""
        normalized = _normalize_admission(admission)
        if type(ledger) is not AtomicFileReplayLedgerV1:
            raise FreeExecutionBoundaryError("boundary requires the concrete replay ledger")
        if normalized.status is FreeExecutionAdmissionStatus.ADMITTED:
            _raise_runtime_integration_blocked(
                stage="positive free-execution boundary",
                codes=_RUNTIME_INTEGRATION_BLOCKERS,
            )
        identity = {
            "repository": normalized.repository,
            "source_sha": normalized.source_sha,
            "run_id": normalized.run_id,
            "run_attempt": normalized.run_attempt,
            "admission_job_id": normalized.admission_job_id,
            "admission_sha256": normalized.admission_sha256,
            "intent_sha256": normalized.intent.intent_sha256,
            "operation": "apply_free_execution_admission",
        }
        ledger.open_marker(
            claim_kind="admission",
            marker_sha256=self.ledger_marker_sha256,
            identity=identity,
        )
        if (
            self.admission_sha256 != normalized.admission_sha256
            or self.intent_sha256 != normalized.intent.intent_sha256
            or self.ledger_root_authority_sha256 != ledger.authority.authority_sha256
            or self.status is not normalized.status
            or self.provider_calls_allowed
            is not (normalized.status is FreeExecutionAdmissionStatus.ADMITTED)
            or self.execution_slot_count
            != (
                normalized.admitted_capacity
                if normalized.status is FreeExecutionAdmissionStatus.ADMITTED
                else 0
            )
            or self.matrix_lane_count
            != (
                normalized.intent.matrix_lane_count
                if normalized.status is FreeExecutionAdmissionStatus.ADMITTED
                else 0
            )
            or self.deferred_lane_count
            != (
                normalized.intent.deferred_lane_count
                if normalized.status is FreeExecutionAdmissionStatus.ADMITTED
                else normalized.intent.active_lane_count
            )
        ):
            raise FreeExecutionBoundaryError("boundary differs from raw/ledger authority")


def _manifest_output(
    manifest_bytes: bytes,
    *,
    admission: FreeExecutionAdmissionV1,
) -> dict[str, object]:
    admission.validate_manifest(manifest_bytes)
    decoded = json.loads(manifest_bytes.decode("utf-8"))
    if type(decoded) is not dict:
        raise FreeExecutionBoundaryError("validated execution manifest is not an object")
    source = cast("dict[str, object]", decoded)
    lanes = source["lanes"]
    matrix_value = source["github_matrix"]
    resource_plan_value = source["resource_plan"]
    if (
        type(lanes) is not list
        or type(matrix_value) is not dict
        or type(resource_plan_value) is not dict
    ):
        raise FreeExecutionBoundaryError("validated manifest public projection is invalid")
    matrix = cast("Mapping[str, object]", matrix_value)
    resource_plan = cast("Mapping[str, object]", resource_plan_value)
    lane_rows: list[dict[str, object]] = []
    for raw_lane in cast("list[object]", lanes):
        if type(raw_lane) is not dict:
            raise FreeExecutionBoundaryError("validated lane row is invalid")
        lane = cast("Mapping[str, object]", raw_lane)
        lane_rows.append(
            {
                key: lane[key]
                for key in ("lane_id", "lane_index", "endpoint", "parameters")
                if key in lane
            }
        )
    include = matrix["include"]
    if type(include) is not list:
        raise FreeExecutionBoundaryError("validated matrix projection is invalid")
    if admission.status is FreeExecutionAdmissionStatus.ADMITTED:
        output_rows: list[dict[str, Any]] = []
        for index, raw_row in enumerate(include):
            if type(raw_row) is not dict:
                raise FreeExecutionBoundaryError("validated matrix row is invalid")
            raw_row_mapping = cast("Mapping[str, object]", raw_row)
            row = {
                key: raw_row_mapping[key]
                for key in ("lane_id", "lane_index", "endpoint", "parameters")
                if key in raw_row_mapping
            }
            row["execution_slot"] = index % admission.admitted_capacity
            row["execution_transport"] = "direct"
            row["use_vpn"] = False
            output_rows.append(row)
        deferred = admission.intent.deferred_lane_count
        matrix_count = len(output_rows)
    else:
        output_rows = []
        deferred = admission.intent.active_lane_count
        matrix_count = 0
    return {
        "schema_version": source["schema_version"],
        "repository": source["repository"],
        "source_sha": source["source_sha"],
        "workflow_path": source["workflow_path"],
        "workflow_sha256": source["workflow_sha256"],
        "publish": source["publish"],
        "active_lane_count": admission.intent.active_lane_count,
        "matrix_lane_count": matrix_count,
        "deferred_lane_count": deferred,
        "lanes": lane_rows,
        "github_matrix": {"include": output_rows},
        "resource_plan": {
            "planned_artifact_max_bytes": resource_plan["planned_artifact_max_bytes"],
            "planned_artifact_retention_hours": resource_plan["planned_artifact_retention_hours"],
            "planned_cache_max_bytes": resource_plan["planned_cache_max_bytes"],
        },
        "execution_policy": {
            "transport": "direct",
            "paid_fallback_allowed": False,
            "proxy_fallback_allowed": False,
            "vpn_fallback_allowed": False,
        },
    }


def apply_free_execution_admission(
    manifest_bytes: bytes,
    raw_admission: FreeExecutionAdmissionV1 | Mapping[str, object] | bytes,
    *,
    authority: FreeExecutionAuthorityBundleV1 | None,
    ledger: AtomicFileReplayLedgerV1,
    repository: str,
    source_sha: str,
    workflow_path: str,
    workflow_sha256: str,
    run_id: int,
    run_attempt: int,
    admission_job_id: str,
    mode: FreeExecutionMode,
    checked_at: str,
) -> tuple[dict[str, object], FreeExecutionBoundaryV1]:
    """Reconstruct, validate, then atomically consume one admission."""
    _raise_runtime_integration_blocked(
        stage="free-execution runtime admission",
        codes=_RUNTIME_INTEGRATION_BLOCKERS,
    )
    admission = _normalize_admission(raw_admission)
    if type(ledger) is not AtomicFileReplayLedgerV1:
        raise FreeExecutionBoundaryError("admission requires the concrete replay ledger")
    if (
        ledger.authority.repository,
        ledger.authority.source_sha,
        ledger.authority.run_id,
        ledger.authority.run_attempt,
    ) != (repository, source_sha, run_id, run_attempt):
        raise FreeExecutionBoundaryError("ledger root authority is foreign to admission context")
    try:
        admission.validate_context(
            repository=repository,
            source_sha=source_sha,
            workflow_path=workflow_path,
            workflow_sha256=workflow_sha256,
            run_id=run_id,
            run_attempt=run_attempt,
            admission_job_id=admission_job_id,
            mode=mode,
            checked_at=checked_at,
        )
        if admission.status is FreeExecutionAdmissionStatus.ADMITTED:
            if type(authority) is not FreeExecutionAuthorityBundleV1:
                raise FreeExecutionAdmissionError("positive admission raw authority is absent")
            admission.validate_authority(authority)
        elif authority is not None:
            raise FreeExecutionAdmissionError("blocked admission cannot carry positive authority")
        output = _manifest_output(manifest_bytes, admission=admission)
    except (FreeExecutionAdmissionError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise FreeExecutionBoundaryError(f"admission reconstruction failed: {exc}") from exc
    claim = ledger.claim(
        claim_kind="admission",
        identity={
            "repository": repository,
            "source_sha": source_sha,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "admission_job_id": admission_job_id,
            "admission_sha256": admission.admission_sha256,
            "intent_sha256": admission.intent.intent_sha256,
            "operation": "apply_free_execution_admission",
        },
    )
    boundary = FreeExecutionBoundaryV1(
        admission_sha256=admission.admission_sha256,
        intent_sha256=admission.intent.intent_sha256,
        ledger_root_authority_sha256=ledger.authority.authority_sha256,
        ledger_marker_sha256=claim.marker_sha256,
        status=admission.status,
        provider_calls_allowed=admission.status is FreeExecutionAdmissionStatus.ADMITTED,
        execution_slot_count=(
            admission.admitted_capacity
            if admission.status is FreeExecutionAdmissionStatus.ADMITTED
            else 0
        ),
        matrix_lane_count=cast("int", output["matrix_lane_count"]),
        deferred_lane_count=cast("int", output["deferred_lane_count"]),
    )
    return output, boundary


@dataclass(frozen=True, slots=True)
class ProviderRequestAuthorizationV1:
    admission_sha256: str
    point_of_use_sha256: str
    operation_sha256: str
    ledger_root_authority_sha256: str
    ledger_marker_sha256: str
    actual_job_id: int
    logical_job_id: str
    lane_id: str
    authorized_at: str
    expires_at: str
    authorization_sha256: str = ""

    schema_version: ClassVar[int] = 1

    def __post_init__(self) -> None:
        _raise_runtime_integration_blocked(
            stage="provider request authorization",
            codes=_AUTHORIZATION_INTEGRATION_BLOCKERS,
        )
        for name in (
            "admission_sha256",
            "point_of_use_sha256",
            "operation_sha256",
            "ledger_root_authority_sha256",
            "ledger_marker_sha256",
        ):
            _sha256(getattr(self, name), field_name=name)
        _uint(self.actual_job_id, field_name="actual_job_id", positive=True)
        _exact_text(self.logical_job_id, field_name="logical_job_id")
        _exact_text(self.lane_id, field_name="lane_id")
        authorized = _timestamp(self.authorized_at, field_name="authorized_at")
        expires = _timestamp(self.expires_at, field_name="expires_at")
        if not authorized < expires:
            raise FreeExecutionBoundaryError("provider authorization expiry is invalid")
        object.__setattr__(
            self,
            "authorization_sha256",
            _sealed_digest(
                self.authorization_sha256,
                self._identity_dict(),
                field_name="authorization_sha256",
            ),
        )

    def _identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "admission_sha256": self.admission_sha256,
            "point_of_use_sha256": self.point_of_use_sha256,
            "operation_sha256": self.operation_sha256,
            "ledger_root_authority_sha256": self.ledger_root_authority_sha256,
            "ledger_marker_sha256": self.ledger_marker_sha256,
            "actual_job_id": self.actual_job_id,
            "logical_job_id": self.logical_job_id,
            "lane_id": self.lane_id,
            "authorized_at": self.authorized_at,
            "expires_at": self.expires_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._identity_dict(), "authorization_sha256": self.authorization_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(cls.__dataclass_fields__) | {"schema_version"}
        _exact_keys(payload, expected=expected, label="provider authorization")
        if payload["schema_version"] != 1 or type(payload["schema_version"]) is not int:
            raise FreeExecutionBoundaryError("provider authorization schema is unsupported")
        return cls(
            admission_sha256=cast("str", payload["admission_sha256"]),
            point_of_use_sha256=cast("str", payload["point_of_use_sha256"]),
            operation_sha256=cast("str", payload["operation_sha256"]),
            ledger_root_authority_sha256=cast("str", payload["ledger_root_authority_sha256"]),
            ledger_marker_sha256=cast("str", payload["ledger_marker_sha256"]),
            actual_job_id=cast("int", payload["actual_job_id"]),
            logical_job_id=cast("str", payload["logical_job_id"]),
            lane_id=cast("str", payload["lane_id"]),
            authorized_at=cast("str", payload["authorized_at"]),
            expires_at=cast("str", payload["expires_at"]),
            authorization_sha256=cast("str", payload["authorization_sha256"]),
        )

    def validate_for(
        self,
        *,
        admission: FreeExecutionAdmissionV1,
        point: FreeExecutionPointOfUseV1,
        operation: ProviderOperationV1,
        ledger: AtomicFileReplayLedgerV1,
    ) -> None:
        """Reopen the exact operation marker; the sealed DTO alone grants nothing."""
        _raise_runtime_integration_blocked(
            stage="provider request authorization",
            codes=_AUTHORIZATION_INTEGRATION_BLOCKERS,
        )
        normalized_operation = _normalize_authorized_operation(
            intent=admission.intent,
            lane_id=point.lane_id,
            logical_job_id=point.logical_job_id,
            operation=operation,
        )
        identity = _operation_claim_identity(
            admission=admission,
            point=point,
            operation=normalized_operation,
        )
        ledger.open_marker(
            claim_kind="operation",
            marker_sha256=self.ledger_marker_sha256,
            identity=identity,
        )
        if (
            self.admission_sha256 != admission.admission_sha256
            or self.point_of_use_sha256 != point.point_of_use_sha256
            or self.operation_sha256 != normalized_operation.operation_sha256
            or self.ledger_root_authority_sha256 != ledger.authority.authority_sha256
            or self.actual_job_id != point.actual_job_id
            or self.logical_job_id != point.logical_job_id
            or self.lane_id != point.lane_id
            or self.expires_at != point.expires_at
            or not _timestamp(point.checked_at, field_name="point.checked_at")
            <= _timestamp(self.authorized_at, field_name="authorized_at")
            < _timestamp(point.expires_at, field_name="point.expires_at")
        ):
            raise FreeExecutionBoundaryError(
                "provider authorization differs from raw/ledger authority"
            )


def _normalize_authorized_operation(
    *,
    intent: ExecutionIntentV1,
    lane_id: str,
    logical_job_id: str,
    operation: ProviderOperationV1,
) -> ProviderOperationV1:
    if type(intent) is not ExecutionIntentV1:
        raise FreeExecutionBoundaryError("operation lacks exact manifest intent")
    if type(operation) is not ProviderOperationV1:
        raise FreeExecutionBoundaryError("provider request operation authority is invalid")
    try:
        normalized = ProviderOperationV1.from_dict(operation.to_dict())
    except FreeExecutionAdmissionError as exc:
        raise FreeExecutionBoundaryError(f"provider operation is invalid: {exc}") from exc
    if normalized.lane_id != lane_id or lane_id not in intent.matrix_lane_ids:
        raise FreeExecutionBoundaryError("operation lane is foreign to exact job/manifest lane")
    if normalized.operation_kind != logical_job_id:
        raise FreeExecutionBoundaryError("operation kind is foreign to the exact logical job")
    if normalized.operation_sha256 not in intent.operation_sha256s_for_lane(lane_id):
        raise FreeExecutionBoundaryError(
            "operation endpoint/path/parameters/body/nonce is not exactly issued"
        )
    return normalized


def _operation_claim_identity(
    *,
    admission: FreeExecutionAdmissionV1,
    point: FreeExecutionPointOfUseV1,
    operation: ProviderOperationV1,
) -> dict[str, object]:
    return {
        "repository": admission.repository,
        "source_sha": admission.source_sha,
        "run_id": admission.run_id,
        "run_attempt": admission.run_attempt,
        "admission_sha256": admission.admission_sha256,
        "point_of_use_sha256": point.point_of_use_sha256,
        "actual_job_id": point.actual_job_id,
        "logical_job_id": point.logical_job_id,
        "lane_id": point.lane_id,
        "operation_sha256": operation.operation_sha256,
        "operation_kind": operation.operation_kind,
        "endpoint_id": operation.endpoint_id,
        "request_url": operation.request_url,
        "safe_parameters_json": operation.safe_parameters_json,
        "request_body_sha256": operation.request_body_sha256,
        "operation_nonce": operation.operation_nonce,
    }


def authorize_provider_request(
    raw_admission: FreeExecutionAdmissionV1 | Mapping[str, object] | bytes,
    raw_point: FreeExecutionPointOfUseV1 | Mapping[str, object] | bytes,
    *,
    point_authority: PointOfUseAuthorityBundleV1,
    predecessor: FreeExecutionAdmissionV1 | FreeExecutionPointOfUseV1,
    operation: ProviderOperationV1,
    ledger: AtomicFileReplayLedgerV1,
    checked_at: str,
) -> ProviderRequestAuthorizationV1:
    """Authorize and atomically consume one exact provider operation."""
    _raise_runtime_integration_blocked(
        stage="provider request authorization",
        codes=_AUTHORIZATION_INTEGRATION_BLOCKERS,
    )
    admission = _normalize_admission(raw_admission)
    point = _normalize_point(raw_point)
    if type(point_authority) is not PointOfUseAuthorityBundleV1:
        raise FreeExecutionBoundaryError("provider request lacks exact point raw authority")
    operation = _normalize_authorized_operation(
        intent=admission.intent,
        lane_id=point.lane_id,
        logical_job_id=point.logical_job_id,
        operation=operation,
    )
    if type(ledger) is not AtomicFileReplayLedgerV1:
        raise FreeExecutionBoundaryError("provider request requires the concrete replay ledger")
    if admission.status is not FreeExecutionAdmissionStatus.ADMITTED:
        raise FreeExecutionBoundaryError("blocked admission cannot authorize provider work")
    if operation.service_kind not in admission.intent.required_external_services:
        raise FreeExecutionBoundaryError("operation service is foreign to manifest intent")
    if (
        ledger.authority.repository,
        ledger.authority.source_sha,
        ledger.authority.run_id,
        ledger.authority.run_attempt,
    ) != (
        admission.repository,
        admission.source_sha,
        admission.run_id,
        admission.run_attempt,
    ):
        raise FreeExecutionBoundaryError("ledger root authority is foreign to provider request")
    try:
        point.validate_for(
            admission=admission,
            authority=point_authority,
            predecessor=predecessor,
        )
        point.validate_checked_at(checked_at)
    except FreeExecutionAdmissionError as exc:
        raise FreeExecutionBoundaryError(f"provider point authority is invalid: {exc}") from exc
    claim = ledger.claim(
        claim_kind="operation",
        identity=_operation_claim_identity(
            admission=admission,
            point=point,
            operation=operation,
        ),
    )
    return ProviderRequestAuthorizationV1(
        admission_sha256=admission.admission_sha256,
        point_of_use_sha256=point.point_of_use_sha256,
        operation_sha256=operation.operation_sha256,
        ledger_root_authority_sha256=ledger.authority.authority_sha256,
        ledger_marker_sha256=claim.marker_sha256,
        actual_job_id=point.actual_job_id,
        logical_job_id=point.logical_job_id,
        lane_id=operation.lane_id,
        authorized_at=checked_at,
        expires_at=point.expires_at,
    )
