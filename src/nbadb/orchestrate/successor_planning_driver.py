"""Strict schema-v2 driver for partition-local successor planning.

The driver admits only the current request-builder inventory and never treats
member envelopes as a value program.  Envelopes bind one exact semantic
descriptor; values are reloaded from the descriptor-safe planning DuckDB and
recompiled by :mod:`successor_planning_program_compiler` before they can
authorize another provider call or a sealed manifest.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import platform
import re
import stat
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from ctypes import Structure, c_int, c_longlong, c_short, sizeof
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol, Self, cast

import duckdb

from nbadb.contracts.staging_route_contract import (
    StagingRouteContract,
    staging_route_contract_bundle,
)
from nbadb.orchestrate.successor_planner import (
    PlanningCallExecution,
    PlanningDriverContext,
    PlanningWaveSeal,
)
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDataMember,
    PlanningDispatchPhase,
    PlanningGenerationManifest,
    SealedProviderDispatch,
    SuccessorPlanningArtifactIdentity,
    canonical_planning_json_bytes,
    canonical_planning_sha256,
)
from nbadb.orchestrate.successor_planning_program_compiler import (
    CompiledSuccessorPlanningProgram,
    PlanningSemanticMemberAuthority,
    PlanningSemanticPartitionValues,
    SuccessorPlanningProgramCompilerError,
    compile_successor_planning_program,
    read_successor_planning_semantic_registry,
    successor_planning_database_schema_sha256,
)
from nbadb.orchestrate.successor_planning_request_builder import (
    SuccessorPlanningRequestBuilderError,
    validate_successor_planning_request,
)
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    PlanningSemanticKind,
    SuccessorPlanningSemanticContractError,
)
from nbadb.orchestrate.successor_planning_store import (
    CommittedPlanningCall,
    PlanningArtifactSource,
    PlanningDatabaseSource,
    PlanningGenerationPhase,
    PlanningWaveAdmission,
)
from nbadb.orchestrate.successor_update_contract import RequestedRouteScope

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "PlanningExactCallRuntime",
    "PlanningExactCallRuntimeRequest",
    "PlanningMemberEnvelope",
    "PlanningProgramDriverError",
    "PlanningWaveSealRuntimeRequest",
    "RequestDrivenSuccessorPlanningDriver",
]

_SCHEMA_VERSION = 2
_MAX_ENVELOPE_BYTES = 1024 * 1024
_COPY_CHUNK_BYTES = 1024 * 1024
_MAX_PROCESS_DESCRIPTORS = 4096
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_REGULAR_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)

_ENVELOPE_SCHEMA_SHA256 = canonical_planning_sha256(
    {
        "domain": "nbadb.successor-planning-member-envelope.schema.v2",
        "fields": [
            ["planning_request_sha256", "sha256"],
            ["planning_generation_id", "safe_token"],
            ["wave_index", "uint"],
            ["producing_scope", "requested_route_scope.v1"],
            ["input_planning_database_sha256", "nullable_sha256"],
            ["output_planning_database_sha256", "sha256"],
            ["logical_call_receipt_sha256", "sha256"],
            ["provider_authority_sha256", "sha256"],
            ["member_id", "safe_token"],
            ["semantic", "planning_semantic_descriptor.v1"],
        ],
    }
)


class PlanningProgramDriverError(RuntimeError):
    """Raised when runtime, database, or current planning authority differs."""


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PlanningProgramDriverError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise PlanningProgramDriverError(f"{field_name} must be a path-free safe token")
    return value


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise PlanningProgramDriverError(f"{field_name} must be a string-keyed object")
    return cast("Mapping[str, object]", value)


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if frozenset(payload) != expected:
        raise PlanningProgramDriverError(f"{label} fields are invalid")


def _decode_canonical_object(encoded: bytes, *, label: str) -> Mapping[str, object]:
    if type(encoded) is not bytes or not encoded or len(encoded) > _MAX_ENVELOPE_BYTES:
        raise PlanningProgramDriverError(f"{label} canonical byte length is invalid")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PlanningProgramDriverError(f"{label} contains a duplicate key")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise PlanningProgramDriverError(f"{label} contains non-finite JSON value {value}")

    try:
        decoded = json.loads(
            encoded.decode("ascii", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except PlanningProgramDriverError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PlanningProgramDriverError(f"{label} is not strict ASCII JSON") from exc
    payload = _require_mapping(decoded, field_name=label)
    try:
        canonical = canonical_planning_json_bytes(payload)
    except (TypeError, ValueError, RecursionError) as exc:
        raise PlanningProgramDriverError(f"{label} contains invalid JSON values") from exc
    if canonical != encoded:
        raise PlanningProgramDriverError(f"{label} bytes are not canonical")
    return payload


def _current_route(scope: RequestedRouteScope) -> StagingRouteContract:
    route = staging_route_contract_bundle().by_route_id.get(scope.route_id)
    if (
        route is None
        or route.endpoint_name != scope.endpoint_name
        or route.contract_sha256 != scope.route_contract_sha256
    ):
        raise PlanningProgramDriverError(
            "planning requested scope differs from current route authority"
        )
    return route


@dataclass(frozen=True, slots=True)
class PlanningMemberEnvelope:
    """Path-free binding of one member to its exact semantic descriptor."""

    planning_request_sha256: str
    planning_generation_id: str
    wave_index: int
    producing_scope: RequestedRouteScope
    input_planning_database_sha256: str | None
    output_planning_database_sha256: str
    logical_call_receipt_sha256: str
    provider_authority_sha256: str
    member_id: str
    semantic: PlanningSemanticDescriptor

    schema_version: ClassVar[int] = _SCHEMA_VERSION
    kind: ClassVar[str] = "successor_planning_member_envelope"
    schema_sha256: ClassVar[str] = _ENVELOPE_SCHEMA_SHA256

    def __post_init__(self) -> None:
        _require_sha256(self.planning_request_sha256, field_name="planning_request_sha256")
        _require_token(self.planning_generation_id, field_name="planning_generation_id")
        if type(self.wave_index) is not int or self.wave_index not in {0, 1}:
            raise PlanningProgramDriverError("planning member wave index must be 0 or 1")
        if not isinstance(self.producing_scope, RequestedRouteScope):
            raise PlanningProgramDriverError("planning member producing scope is invalid")
        _current_route(self.producing_scope)
        if self.input_planning_database_sha256 is not None:
            _require_sha256(
                self.input_planning_database_sha256,
                field_name="input_planning_database_sha256",
            )
        _require_sha256(
            self.output_planning_database_sha256,
            field_name="output_planning_database_sha256",
        )
        _require_sha256(
            self.logical_call_receipt_sha256,
            field_name="logical_call_receipt_sha256",
        )
        _require_sha256(
            self.provider_authority_sha256,
            field_name="provider_authority_sha256",
        )
        _require_token(self.member_id, field_name="member_id")
        if not isinstance(self.semantic, PlanningSemanticDescriptor):
            raise PlanningProgramDriverError("planning member semantic descriptor is invalid")

    @property
    def producing_scope_identity_sha256(self) -> str:
        return self.producing_scope.identity_sha256

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "planning_request_sha256": self.planning_request_sha256,
            "planning_generation_id": self.planning_generation_id,
            "wave_index": self.wave_index,
            "producing_scope": self.producing_scope.to_dict(),
            "input_planning_database_sha256": self.input_planning_database_sha256,
            "output_planning_database_sha256": self.output_planning_database_sha256,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "member_id": self.member_id,
            "semantic": self.semantic.to_dict(),
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_planning_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "planning_request_sha256",
                    "planning_generation_id",
                    "wave_index",
                    "producing_scope",
                    "input_planning_database_sha256",
                    "output_planning_database_sha256",
                    "logical_call_receipt_sha256",
                    "provider_authority_sha256",
                    "member_id",
                    "semantic",
                }
            ),
            label="planning member envelope",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise PlanningProgramDriverError("planning member envelope schema is invalid")
        raw_input = payload["input_planning_database_sha256"]
        input_sha256 = (
            None
            if raw_input is None
            else _require_sha256(raw_input, field_name="input_planning_database_sha256")
        )
        if type(payload["wave_index"]) is not int:
            raise PlanningProgramDriverError("planning member wave index is invalid")
        try:
            scope = RequestedRouteScope.from_dict(
                _require_mapping(payload["producing_scope"], field_name="producing_scope")
            )
            semantic = PlanningSemanticDescriptor.from_dict(
                _require_mapping(payload["semantic"], field_name="semantic")
            )
        except (
            TypeError,
            ValueError,
            SuccessorPlanningSemanticContractError,
        ) as exc:
            raise PlanningProgramDriverError("planning member envelope body is invalid") from exc
        return cls(
            planning_request_sha256=_require_sha256(
                payload["planning_request_sha256"], field_name="planning_request_sha256"
            ),
            planning_generation_id=_require_token(
                payload["planning_generation_id"], field_name="planning_generation_id"
            ),
            wave_index=payload["wave_index"],
            producing_scope=scope,
            input_planning_database_sha256=input_sha256,
            output_planning_database_sha256=_require_sha256(
                payload["output_planning_database_sha256"],
                field_name="output_planning_database_sha256",
            ),
            logical_call_receipt_sha256=_require_sha256(
                payload["logical_call_receipt_sha256"],
                field_name="logical_call_receipt_sha256",
            ),
            provider_authority_sha256=_require_sha256(
                payload["provider_authority_sha256"],
                field_name="provider_authority_sha256",
            ),
            member_id=_require_token(payload["member_id"], field_name="member_id"),
            semantic=semantic,
        )

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_object(encoded, label="planning member envelope"))
        if result.canonical_bytes != encoded:
            raise PlanningProgramDriverError("planning member envelope canonical bytes differ")
        return result


@dataclass(frozen=True, slots=True)
class PlanningExactCallRuntimeRequest:
    """Ephemeral exact authority passed to one provider-owning runtime call."""

    request: SuccessorPlanningRequest
    planning_generation_id: str
    wave_index: int
    admission: PlanningWaveAdmission
    dispatch: SealedProviderDispatch
    requested_route_scopes: tuple[RequestedRouteScope, ...]
    provider_authority_sha256: str
    cutoff_utc: str
    as_of_utc: str
    workflow_run_id: int
    workflow_run_attempt: int
    input_planning_database: PlanningDatabaseSource | None
    private_work_root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.request, SuccessorPlanningRequest):
            raise PlanningProgramDriverError("exact runtime request is invalid")
        _require_token(self.planning_generation_id, field_name="planning_generation_id")
        if self.wave_index != self.admission.wave_index:
            raise PlanningProgramDriverError("exact runtime request wave differs")
        if self.dispatch not in self.admission.sealed_dispatches:
            raise PlanningProgramDriverError("exact runtime dispatch is not admitted")
        if (
            self.cutoff_utc != self.request.cutoff_utc
            or self.as_of_utc != self.request.as_of_utc
            or self.workflow_run_id != self.request.workflow_run_id
            or self.workflow_run_attempt != self.request.workflow_run_attempt
        ):
            raise PlanningProgramDriverError("exact runtime coordinates differ")
        _require_sha256(self.provider_authority_sha256, field_name="provider_authority_sha256")
        if not Path(self.private_work_root).is_absolute():
            raise PlanningProgramDriverError("exact runtime work root must be absolute")


@dataclass(frozen=True, slots=True)
class PlanningWaveSealRuntimeRequest:
    """Ephemeral complete-wave authority passed to the sealing runtime."""

    request: SuccessorPlanningRequest
    planning_generation_id: str
    admission: PlanningWaveAdmission
    committed_calls: tuple[CommittedPlanningCall, ...]
    member_envelopes: tuple[PlanningMemberEnvelope, ...]
    planning_database: PlanningDatabaseSource
    private_work_root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.request, SuccessorPlanningRequest):
            raise PlanningProgramDriverError("wave seal runtime request is invalid")
        _require_token(self.planning_generation_id, field_name="planning_generation_id")
        if not self.committed_calls or any(
            call.wave_index != self.admission.wave_index for call in self.committed_calls
        ):
            raise PlanningProgramDriverError("wave seal requires its complete committed calls")
        if not self.member_envelopes or any(
            envelope.wave_index != self.admission.wave_index for envelope in self.member_envelopes
        ):
            raise PlanningProgramDriverError("wave seal requires its member envelopes")
        if not isinstance(self.planning_database, PlanningDatabaseSource):
            raise PlanningProgramDriverError("wave seal planning database is invalid")
        if not Path(self.private_work_root).is_absolute():
            raise PlanningProgramDriverError("wave seal work root must be absolute")


class PlanningExactCallRuntime(Protocol):
    """Provider/capture/database implementation injected beneath the program."""

    async def execute_planning_call(
        self,
        request: PlanningExactCallRuntimeRequest,
    ) -> PlanningCallExecution: ...

    async def seal_planning_wave(
        self,
        request: PlanningWaveSealRuntimeRequest,
    ) -> PlanningWaveSeal: ...


@dataclass(frozen=True, slots=True)
class _DecodedCommittedEnvelope:
    call: CommittedPlanningCall
    member: PlanningDataMember
    member_identity_sha256: str
    envelope: PlanningMemberEnvelope
    authority: PlanningSemanticMemberAuthority


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


@dataclass(slots=True)
class _HeldRegularFile:
    root_path: Path
    root_descriptor: int
    root_stat: os.stat_result
    directory_chain: tuple[tuple[int, str, int, os.stat_result], ...]
    parent_descriptor: int
    name: str
    descriptor: int
    file_stat: os.stat_result
    path: Path

    def verify(self) -> None:
        try:
            root_named = os.stat(self.root_path, follow_symlinks=False)
            root_open = os.fstat(self.root_descriptor)
        except OSError as exc:
            raise PlanningProgramDriverError("planning private root changed while held") from exc
        if (
            not stat.S_ISDIR(root_named.st_mode)
            or not stat.S_ISDIR(root_open.st_mode)
            or (root_named.st_dev, root_named.st_ino)
            != (self.root_stat.st_dev, self.root_stat.st_ino)
            or (root_open.st_dev, root_open.st_ino)
            != (self.root_stat.st_dev, self.root_stat.st_ino)
        ):
            raise PlanningProgramDriverError("planning private root changed while held")
        for parent, name, descriptor, expected in self.directory_chain:
            try:
                opened = os.fstat(descriptor)
                named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except OSError as exc:
                raise PlanningProgramDriverError(
                    "planning private directory changed while held"
                ) from exc
            if (
                not stat.S_ISDIR(opened.st_mode)
                or not stat.S_ISDIR(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)
                or (named.st_dev, named.st_ino) != (expected.st_dev, expected.st_ino)
            ):
                raise PlanningProgramDriverError("planning private directory changed while held")
        try:
            opened = os.fstat(self.descriptor)
            named = os.stat(self.name, dir_fd=self.parent_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise PlanningProgramDriverError("planning private file changed while held") from exc
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or _stat_identity(opened) != _stat_identity(self.file_stat)
            or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise PlanningProgramDriverError("planning private file changed while held")

    def close(self) -> None:
        descriptors = [self.descriptor]
        descriptors.extend(item[2] for item in reversed(self.directory_chain))
        descriptors.append(self.root_descriptor)
        for descriptor in descriptors:
            with suppress(OSError):
                os.close(descriptor)


@contextmanager
def _hold_private_regular_file(
    *,
    private_work_root: Path,
    path: Path,
) -> Iterator[_HeldRegularFile]:
    root_path = Path(os.path.abspath(private_work_root))
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(root_path)
    except ValueError as exc:
        raise PlanningProgramDriverError(
            "planning private file falls outside its work root"
        ) from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise PlanningProgramDriverError("planning private file path is invalid")
    root_descriptor = -1
    opened_directories: list[tuple[int, str, int, os.stat_result]] = []
    file_descriptor = -1
    try:
        root_descriptor = os.open(root_path, _DIRECTORY_FLAGS)
        root_stat = os.fstat(root_descriptor)
        root_named = os.stat(root_path, follow_symlinks=False)
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or not stat.S_ISDIR(root_named.st_mode)
            or (root_stat.st_dev, root_stat.st_ino) != (root_named.st_dev, root_named.st_ino)
            or (
                os.name == "posix"
                and (root_stat.st_uid != os.geteuid() or stat.S_IMODE(root_stat.st_mode) != 0o700)
            )
        ):
            raise PlanningProgramDriverError(
                "planning private work root is not stable owner-only authority"
            )
        parent = root_descriptor
        for component in relative.parts[:-1]:
            descriptor = os.open(component, _DIRECTORY_FLAGS, dir_fd=parent)
            opened = os.fstat(descriptor)
            named = os.stat(component, dir_fd=parent, follow_symlinks=False)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or not stat.S_ISDIR(named.st_mode)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            ):
                raise PlanningProgramDriverError("planning private directory is unstable")
            opened_directories.append((parent, component, descriptor, opened))
            parent = descriptor
        name = relative.parts[-1]
        file_descriptor = os.open(name, _REGULAR_FLAGS, dir_fd=parent)
        file_stat = os.fstat(file_descriptor)
        file_named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or not stat.S_ISREG(file_named.st_mode)
            or (file_stat.st_dev, file_stat.st_ino) != (file_named.st_dev, file_named.st_ino)
        ):
            raise PlanningProgramDriverError("planning private source must be a stable file")
        held = _HeldRegularFile(
            root_path=root_path,
            root_descriptor=root_descriptor,
            root_stat=root_stat,
            directory_chain=tuple(opened_directories),
            parent_descriptor=parent,
            name=name,
            descriptor=file_descriptor,
            file_stat=file_stat,
            path=absolute,
        )
        try:
            yield held
        finally:
            held.close()
            file_descriptor = -1
            opened_directories.clear()
            root_descriptor = -1
    except PlanningProgramDriverError:
        if file_descriptor >= 0:
            with suppress(OSError):
                os.close(file_descriptor)
        for _parent, _name, descriptor, _opened in reversed(opened_directories):
            with suppress(OSError):
                os.close(descriptor)
        if root_descriptor >= 0:
            with suppress(OSError):
                os.close(root_descriptor)
        raise
    except OSError as exc:
        if file_descriptor >= 0:
            with suppress(OSError):
                os.close(file_descriptor)
        for _parent, _name, descriptor, _opened in reversed(opened_directories):
            with suppress(OSError):
                os.close(descriptor)
        if root_descriptor >= 0:
            with suppress(OSError):
                os.close(root_descriptor)
        raise PlanningProgramDriverError("planning private source cannot be opened safely") from exc


def _hash_descriptor(descriptor: int) -> tuple[int, str, os.stat_result]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise PlanningProgramDriverError("planning source descriptor is not regular")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    observed = 0
    while chunk := os.read(descriptor, _COPY_CHUNK_BYTES):
        digest.update(chunk)
        observed += len(chunk)
    after = os.fstat(descriptor)
    if _stat_identity(before) != _stat_identity(after) or observed != before.st_size:
        raise PlanningProgramDriverError("planning source changed while hashing")
    return observed, digest.hexdigest(), after


def _read_descriptor(descriptor: int, *, max_bytes: int) -> bytes:
    observed = os.fstat(descriptor)
    if observed.st_size < 1 or observed.st_size > max_bytes:
        raise PlanningProgramDriverError("planning member envelope size is invalid")
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = observed.st_size
    while remaining:
        chunk = os.read(descriptor, min(remaining, _COPY_CHUNK_BYTES))
        if not chunk:
            raise PlanningProgramDriverError("planning member envelope ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    if _stat_identity(observed) != _stat_identity(os.fstat(descriptor)):
        raise PlanningProgramDriverError("planning member envelope changed while reading")
    return b"".join(chunks)


def _prove_flock_available(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError as exc:
        raise PlanningProgramDriverError(
            "planning database is already locked or does not support the required "
            "exclusive preflight"
        ) from exc


def _snapshot_process_descriptors() -> dict[int, tuple[int, int, int]]:
    """Measure the process descriptor table without retaining the scan descriptor."""

    try:
        with os.scandir("/dev/fd") as entries:
            names = tuple(entry.name for entry in entries)
    except OSError as exc:
        raise PlanningProgramDriverError(
            "process descriptor inventory is unavailable for DuckDB binding"
        ) from exc
    if len(names) > _MAX_PROCESS_DESCRIPTORS:
        raise PlanningProgramDriverError("process descriptor inventory exceeds the binding limit")
    snapshot: dict[int, tuple[int, int, int]] = {}
    for name in names:
        if not name.isascii() or not name.isdecimal():
            continue
        descriptor = int(name)
        try:
            observed = os.fstat(descriptor)
        except OSError as exc:
            if exc.errno == errno.EBADF:
                continue
            raise PlanningProgramDriverError(
                "process descriptor inventory changed unexpectedly"
            ) from exc
        snapshot[descriptor] = (
            observed.st_dev,
            observed.st_ino,
            stat.S_IFMT(observed.st_mode),
        )
    return snapshot


@dataclass(frozen=True, slots=True)
class _DuckDBEngineFileBinding:
    descriptor: int
    device: int
    inode: int

    def verify(self, *, stage: str) -> None:
        try:
            observed = os.fstat(self.descriptor)
        except OSError as exc:
            raise PlanningProgramDriverError(
                f"DuckDB released its exact planning database descriptor at {stage}"
            ) from exc
        if not stat.S_ISREG(observed.st_mode) or (observed.st_dev, observed.st_ino) != (
            self.device,
            self.inode,
        ):
            raise PlanningProgramDriverError(
                f"DuckDB planning database descriptor changed at {stage}"
            )
        _require_duckdb_record_lock(self.descriptor, stage=stage)

    def require_released(self) -> None:
        try:
            observed = os.fstat(self.descriptor)
        except OSError as exc:
            if exc.errno == errno.EBADF:
                return
            raise PlanningProgramDriverError(
                "DuckDB planning database descriptor release could not be verified"
            ) from exc
        if (observed.st_dev, observed.st_ino) == (self.device, self.inode):
            raise PlanningProgramDriverError(
                "DuckDB retained its exact planning database descriptor after close"
            )


def _bind_duckdb_engine_file(
    *,
    before: Mapping[int, tuple[int, int, int]],
    after: Mapping[int, tuple[int, int, int]],
    expected: os.stat_result,
) -> _DuckDBEngineFileBinding:
    retained_regular = tuple(
        sorted(
            (descriptor, identity)
            for descriptor, identity in after.items()
            if before.get(descriptor) != identity and identity[2] == stat.S_IFREG
        )
    )
    expected_identity = (expected.st_dev, expected.st_ino)
    if len(retained_regular) != 1 or retained_regular[0][1][:2] != expected_identity:
        raise PlanningProgramDriverError(
            "DuckDB engine did not open exactly the held planning database inode"
        )
    descriptor, identity = retained_regular[0]
    return _DuckDBEngineFileBinding(
        descriptor=descriptor,
        device=identity[0],
        inode=identity[1],
    )


class _DarwinFlock(Structure):
    _fields_ = [
        ("l_start", c_longlong),
        ("l_len", c_longlong),
        ("l_pid", c_int),
        ("l_type", c_short),
        ("l_whence", c_short),
    ]


class _LinuxFlock(Structure):
    _fields_ = [
        ("l_type", c_short),
        ("l_whence", c_short),
        ("l_start", c_longlong),
        ("l_len", c_longlong),
        ("l_pid", c_int),
    ]


def _record_lock_query(descriptor: int) -> tuple[int, int]:
    system = platform.system()
    if system == "Darwin":
        command = 92  # F_OFD_GETLK in the Darwin SDK; absent from Python's fcntl.
        structure_type = _DarwinFlock
        query = structure_type(0, 0, 0, fcntl.F_WRLCK, os.SEEK_SET)
    elif system == "Linux" and hasattr(fcntl, "F_OFD_GETLK"):
        command = fcntl.F_OFD_GETLK
        structure_type = _LinuxFlock
        query = structure_type(fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0)
    else:
        raise PlanningProgramDriverError(
            "platform cannot attest DuckDB's exact planning database record lock"
        )
    try:
        encoded = fcntl.fcntl(descriptor, command, bytes(query))
    except OSError as exc:
        raise PlanningProgramDriverError("planning database record-lock query failed") from exc
    if len(encoded) != sizeof(structure_type):
        raise PlanningProgramDriverError(
            "planning database record-lock query returned an invalid result"
        )
    result = structure_type.from_buffer_copy(encoded)
    return result.l_type, result.l_pid


def _require_record_lock_unlocked(descriptor: int, *, stage: str) -> None:
    lock_type, lock_pid = _record_lock_query(descriptor)
    if lock_type != fcntl.F_UNLCK or lock_pid != 0:
        raise PlanningProgramDriverError(f"planning database already has a record lock at {stage}")


def _require_duckdb_record_lock(descriptor: int, *, stage: str) -> None:
    lock_type, lock_pid = _record_lock_query(descriptor)
    if lock_type != fcntl.F_RDLCK or lock_pid != os.getpid():
        raise PlanningProgramDriverError(
            f"DuckDB does not hold the exact planning database record lock at {stage}"
        )


def _require_duckdb_lock_released(descriptor: int) -> None:
    _require_record_lock_unlocked(descriptor, stage="after engine close")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except OSError as exc:
        raise PlanningProgramDriverError(
            "DuckDB did not release the exact planning database inode"
        ) from exc


def _connect_planning_database_read_only(path: Path) -> duckdb.DuckDBPyConnection:
    """Single monkeypatchable engine-open boundary for descriptor-race probes."""

    return duckdb.connect(str(path), read_only=True)


@contextmanager
def _bound_semantic_registry(
    *,
    source: PlanningDatabaseSource,
    private_work_root: Path,
    authorities: tuple[PlanningSemanticMemberAuthority, ...],
) -> Iterator[tuple[PlanningSemanticPartitionValues, ...]]:
    if not isinstance(source, PlanningDatabaseSource):
        raise PlanningProgramDriverError("planning database source is invalid")
    ordered = tuple(sorted(authorities, key=lambda item: item.descriptor_identity_sha256))
    connection: duckdb.DuckDBPyConnection | None = None
    engine_binding: _DuckDBEngineFileBinding | None = None
    with _hold_private_regular_file(
        private_work_root=private_work_root,
        path=source.artifact.path,
    ) as held:
        byte_count, digest, measured = _hash_descriptor(held.descriptor)
        held.file_stat = measured
        if byte_count != source.artifact.byte_count or digest != source.artifact.sha256:
            raise PlanningProgramDriverError("planning database bytes differ from source authority")
        held.verify()
        _prove_flock_available(held.descriptor)
        _require_record_lock_unlocked(held.descriptor, stage="before engine open")
        descriptors_before_engine = _snapshot_process_descriptors()
        try:
            connection = _connect_planning_database_read_only(held.path)
            engine_binding = _bind_duckdb_engine_file(
                before=descriptors_before_engine,
                after=_snapshot_process_descriptors(),
                expected=held.file_stat,
            )
            engine_binding.verify(stage="after engine open")
            held.verify()
            if successor_planning_database_schema_sha256(connection) != source.schema_sha256:
                raise PlanningProgramDriverError(
                    "planning database schema differs from source authority"
                )
            registry = read_successor_planning_semantic_registry(
                connection,
                authorities=ordered,
            )
            engine_binding.verify(stage="after semantic read")
            held.verify()
            yield registry
            engine_binding.verify(stage="after compiler use")
            if successor_planning_database_schema_sha256(connection) != source.schema_sha256:
                raise PlanningProgramDriverError(
                    "planning database schema changed during compiler use"
                )
        except SuccessorPlanningProgramCompilerError as exc:
            raise PlanningProgramDriverError(
                "planning database semantic authority is invalid"
            ) from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception as exc:
                    raise PlanningProgramDriverError(
                        "planning database engine close failed"
                    ) from exc
                if engine_binding is not None:
                    engine_binding.require_released()
                _require_duckdb_lock_released(held.descriptor)
        held.verify()
        final_bytes, final_digest, final_stat = _hash_descriptor(held.descriptor)
        held.file_stat = final_stat
        if final_bytes != byte_count or final_digest != digest:
            raise PlanningProgramDriverError(
                "planning database changed during semantic compilation"
            )
        held.verify()


def _read_bound_member_artifact(
    *,
    source: PlanningArtifactSource,
    private_work_root: Path,
) -> bytes:
    with _hold_private_regular_file(
        private_work_root=private_work_root,
        path=source.path,
    ) as held:
        encoded = _read_descriptor(held.descriptor, max_bytes=_MAX_ENVELOPE_BYTES)
        observed = os.fstat(held.descriptor)
        held.file_stat = observed
        if (
            len(encoded) != source.byte_count
            or hashlib.sha256(encoded).hexdigest() != source.sha256
        ):
            raise PlanningProgramDriverError("planning member bytes differ from source authority")
        held.verify()
        return encoded


class RequestDrivenSuccessorPlanningDriver:
    """Deterministic two-wave program over reverified semantic partitions."""

    def __init__(self, runtime: PlanningExactCallRuntime) -> None:
        for method_name in ("execute_planning_call", "seal_planning_wave"):
            if not callable(getattr(runtime, method_name, None)):
                raise PlanningProgramDriverError(
                    f"planning exact-call runtime is missing {method_name}"
                )
        self._runtime = runtime

    async def derive_wave(
        self,
        context: PlanningDriverContext,
        wave_index: int,
    ) -> PlanningWaveAdmission:
        self._require_context(context)
        if type(wave_index) is not int or wave_index not in {0, 1}:
            raise PlanningProgramDriverError("planning wave index must be exactly 0 or 1")
        if wave_index == 0:
            if (
                context.snapshot.phase is not PlanningGenerationPhase.BUILDING
                or context.snapshot.committed_waves
                or (
                    context.snapshot.active_wave is not None
                    and context.snapshot.active_wave.wave_index != 0
                )
            ):
                raise PlanningProgramDriverError(
                    "wave 0 derivation requires its building generation"
                )
            result = self._wave_0_admission(context)
        else:
            if (
                context.snapshot.phase is not PlanningGenerationPhase.WAVE_0_COMMITTED
                or len(context.snapshot.committed_waves) != 1
                or context.planning_database is None
                or (
                    context.snapshot.active_wave is not None
                    and context.snapshot.active_wave.wave_index != 1
                )
            ):
                raise PlanningProgramDriverError("wave 1 derivation requires exact sealed wave 0")
            decoded = self._decode_committed_envelopes(context)
            with _bound_semantic_registry(
                source=context.planning_database,
                private_work_root=context.private_work_root,
                authorities=tuple(item.authority for item in decoded),
            ) as registry:
                program = self._compile(
                    request=context.request,
                    registry=tuple(
                        item for item in registry if item.authority.member.wave_index == 0
                    ),
                    phase=PlanningDispatchPhase.PLANNING_WAVE_1,
                )
                result = PlanningWaveAdmission(
                    wave_index=1,
                    parent_wave_identity_sha256=(
                        context.snapshot.committed_waves[0].identity_sha256
                    ),
                    requested_route_scopes=program.requested_route_scopes,
                    sealed_dispatches=program.sealed_dispatches,
                )
        if context.snapshot.active_wave is not None and context.snapshot.active_wave != result:
            raise PlanningProgramDriverError(
                f"rederived wave {wave_index} differs from durable admission"
            )
        return result

    async def execute_call(
        self,
        context: PlanningDriverContext,
        admission: PlanningWaveAdmission,
        dispatch: SealedProviderDispatch,
    ) -> PlanningCallExecution:
        self._require_context(context)
        if context.snapshot.active_wave != admission:
            raise PlanningProgramDriverError("planning call admission is not the active wave")
        if dispatch not in admission.sealed_dispatches:
            raise PlanningProgramDriverError("planning call dispatch is not admitted")
        decoded = self._decode_committed_envelopes(context)
        self._validate_active_admission(context, admission, decoded)
        scope_by_id = {scope.identity_sha256: scope for scope in admission.requested_route_scopes}
        scopes = tuple(
            scope_by_id[scope_id] for scope_id in dispatch.requested_scope_identity_sha256s
        )
        provider_authority = self._provider_authority(scopes)
        runtime_request = PlanningExactCallRuntimeRequest(
            request=context.request,
            planning_generation_id=context.planning_generation_id,
            wave_index=admission.wave_index,
            admission=admission,
            dispatch=dispatch,
            requested_route_scopes=scopes,
            provider_authority_sha256=provider_authority,
            cutoff_utc=context.request.cutoff_utc,
            as_of_utc=context.request.as_of_utc,
            workflow_run_id=context.request.workflow_run_id,
            workflow_run_attempt=context.request.workflow_run_attempt,
            input_planning_database=context.planning_database,
            private_work_root=context.private_work_root,
        )
        result = await self._runtime.execute_planning_call(runtime_request)
        if not isinstance(result, PlanningCallExecution):
            raise PlanningProgramDriverError("planning runtime returned an invalid call result")
        self._require_private_result_sources(context, result)
        expected_input = (
            None if context.planning_database is None else context.planning_database.artifact.sha256
        )
        returned_authorities: list[PlanningSemanticMemberAuthority] = []
        returned_envelopes: list[PlanningMemberEnvelope] = []
        receipts: set[str] = set()
        for source in result.members:
            member = source.member
            if (
                member.wave_index != admission.wave_index
                or member.producing_scope_sha256 not in dispatch.requested_scope_identity_sha256s
            ):
                raise PlanningProgramDriverError(
                    "planning runtime member differs from its admitted dispatch"
                )
            envelope = PlanningMemberEnvelope.from_canonical_bytes(
                _read_bound_member_artifact(
                    source=source.artifact,
                    private_work_root=context.private_work_root,
                )
            )
            expected_scope = scope_by_id[member.producing_scope_sha256]
            self._validate_envelope(
                context=context,
                envelope=envelope,
                member=member,
                expected_scope=expected_scope,
                expected_receipt_sha256=source.receipt_sha256,
                expected_provider_authority_sha256=provider_authority,
                expected_input_database_sha256=expected_input,
                expected_output_database_sha256=result.planning_database.artifact.sha256,
            )
            receipts.add(source.receipt_sha256)
            returned_envelopes.append(envelope)
            returned_authorities.append(
                PlanningSemanticMemberAuthority(
                    member=member,
                    producing_scope=envelope.producing_scope,
                    logical_call_receipt_sha256=envelope.logical_call_receipt_sha256,
                    provider_authority_sha256=envelope.provider_authority_sha256,
                )
            )
        if len(receipts) != 1:
            raise PlanningProgramDriverError(
                "one planning logical call returned multiple receipt authorities"
            )
        self._validate_returned_semantic_inventory(
            request=context.request,
            wave_index=admission.wave_index,
            scopes=scopes,
            envelopes=tuple(returned_envelopes),
        )
        combined = tuple(item.authority for item in decoded) + tuple(returned_authorities)
        with _bound_semantic_registry(
            source=result.planning_database,
            private_work_root=context.private_work_root,
            authorities=combined,
        ) as registry:
            position = admission.sealed_dispatches.index(dispatch)
            committed = tuple(
                call
                for call in context.snapshot.committed_calls
                if call.wave_index == admission.wave_index
            )
            if position != len(committed):
                raise PlanningProgramDriverError(
                    "planning call is not the next admitted logical call"
                )
            if position == len(admission.sealed_dispatches) - 1:
                phase = (
                    PlanningDispatchPhase.PLANNING_WAVE_1
                    if admission.wave_index == 0
                    else PlanningDispatchPhase.UPDATE
                )
                compile_registry = (
                    tuple(item for item in registry if item.authority.member.wave_index == 0)
                    if phase is PlanningDispatchPhase.PLANNING_WAVE_1
                    else registry
                )
                self._compile(
                    request=context.request,
                    registry=compile_registry,
                    phase=phase,
                )
        return result

    async def seal_wave(
        self,
        context: PlanningDriverContext,
        admission: PlanningWaveAdmission,
    ) -> PlanningWaveSeal:
        self._require_context(context)
        if context.snapshot.active_wave != admission or context.planning_database is None:
            raise PlanningProgramDriverError("wave seal requires its active complete database")
        committed_calls = tuple(
            call
            for call in context.snapshot.committed_calls
            if call.wave_index == admission.wave_index
        )
        if tuple(call.sealed_dispatch for call in committed_calls) != admission.sealed_dispatches:
            raise PlanningProgramDriverError("wave seal calls differ from admitted program")
        decoded = self._decode_committed_envelopes(context)
        self._validate_active_admission(context, admission, decoded)
        with _bound_semantic_registry(
            source=context.planning_database,
            private_work_root=context.private_work_root,
            authorities=tuple(item.authority for item in decoded),
        ) as registry:
            phase = (
                PlanningDispatchPhase.PLANNING_WAVE_1
                if admission.wave_index == 0
                else PlanningDispatchPhase.UPDATE
            )
            compile_registry = (
                tuple(item for item in registry if item.authority.member.wave_index == 0)
                if phase is PlanningDispatchPhase.PLANNING_WAVE_1
                else registry
            )
            self._compile(
                request=context.request,
                registry=compile_registry,
                phase=phase,
            )
        current = tuple(item for item in decoded if item.member.wave_index == admission.wave_index)
        runtime_request = PlanningWaveSealRuntimeRequest(
            request=context.request,
            planning_generation_id=context.planning_generation_id,
            admission=admission,
            committed_calls=committed_calls,
            member_envelopes=tuple(item.envelope for item in current),
            planning_database=context.planning_database,
            private_work_root=context.private_work_root,
        )
        seal = await self._runtime.seal_planning_wave(runtime_request)
        if not isinstance(seal, PlanningWaveSeal):
            raise PlanningProgramDriverError("planning runtime returned an invalid wave seal")
        with _bound_semantic_registry(
            source=context.planning_database,
            private_work_root=context.private_work_root,
            authorities=tuple(item.authority for item in decoded),
        ):
            pass
        expected_members = tuple(sorted(item.member_identity_sha256 for item in current))
        receipt = seal.completion_receipt
        if (
            seal.wave.wave_index != admission.wave_index
            or seal.wave.parent_wave_identity_sha256 != admission.parent_wave_identity_sha256
            or seal.wave.requested_scope_identity_sha256s
            != admission.requested_scope_identity_sha256s
            or seal.wave.completed_scope_identity_sha256s
            != admission.requested_scope_identity_sha256s
            or seal.wave.member_identity_sha256s != expected_members
            or receipt.planning_request_sha256 != context.request.identity_sha256
            or receipt.planning_generation_id != context.planning_generation_id
            or receipt.wave_admission_identity_sha256 != admission.identity_sha256
            or receipt.capture_scope.semantic_source_sha != context.request.source_sha
            or receipt.capture_scope.workflow_run_id != context.request.workflow_run_id
            or receipt.capture_scope.workflow_run_attempt != context.request.workflow_run_attempt
            or receipt.private_generation_identity.workflow_run_id
            != context.request.workflow_run_id
            or receipt.private_generation_identity.workflow_run_attempt
            != context.request.workflow_run_attempt
            or receipt.planning_database_sha256 != context.planning_database.artifact.sha256
            or receipt.planning_database_bytes != context.planning_database.artifact.byte_count
            or receipt.planning_database_schema_sha256 != context.planning_database.schema_sha256
        ):
            raise PlanningProgramDriverError(
                "planning wave seal differs from request, admission, members, or database"
            )
        return seal

    async def derive_manifest(
        self,
        context: PlanningDriverContext,
    ) -> PlanningGenerationManifest:
        self._require_context(context)
        snapshot = context.snapshot
        if (
            snapshot.phase is not PlanningGenerationPhase.WAVE_1_COMMITTED
            or len(snapshot.committed_waves) != 2
            or len(snapshot.committed_wave_admissions) != 2
            or context.planning_database is None
            or snapshot.active_wave is not None
        ):
            raise PlanningProgramDriverError(
                "manifest derivation requires two committed planning waves"
            )
        decoded = self._decode_committed_envelopes(context)
        with _bound_semantic_registry(
            source=context.planning_database,
            private_work_root=context.private_work_root,
            authorities=tuple(item.authority for item in decoded),
        ) as registry:
            wave_1_program = self._compile(
                request=context.request,
                registry=tuple(item for item in registry if item.authority.member.wave_index == 0),
                phase=PlanningDispatchPhase.PLANNING_WAVE_1,
            )
            wave_1_admission = snapshot.committed_wave_admissions[1]
            self._require_program_matches_admission(wave_1_program, wave_1_admission)
            update_program = self._compile(
                request=context.request,
                registry=registry,
                phase=PlanningDispatchPhase.UPDATE,
            )
            members = tuple(
                sorted(
                    (item.member for item in decoded),
                    key=lambda member: member.identity_sha256,
                )
            )
            scope_by_id: dict[str, RequestedRouteScope] = {}
            for admission in snapshot.committed_wave_admissions:
                for scope in admission.requested_route_scopes:
                    existing = scope_by_id.get(scope.identity_sha256)
                    if existing is not None and existing.to_dict() != scope.to_dict():
                        raise PlanningProgramDriverError(
                            "planning requested route scope identity collides"
                        )
                    scope_by_id[scope.identity_sha256] = scope
            for scope in update_program.requested_route_scopes:
                existing = scope_by_id.get(scope.identity_sha256)
                if existing is not None and existing.to_dict() != scope.to_dict():
                    raise PlanningProgramDriverError(
                        "compiled update requested route scope identity collides"
                    )
                scope_by_id[scope.identity_sha256] = scope
            planning_dispatches = tuple(
                dispatch
                for admission in snapshot.committed_wave_admissions
                for dispatch in admission.sealed_dispatches
            )
            dispatches = (*planning_dispatches, *update_program.sealed_dispatches)
            waves = tuple(snapshot.committed_waves)
            database = context.planning_database
            artifact_identity = SuccessorPlanningArtifactIdentity(
                planning_request_sha256=context.request.identity_sha256,
                planning_generation_id=context.planning_generation_id,
                planning_database_sha256=database.artifact.sha256,
                planning_database_bytes=database.artifact.byte_count,
                planning_database_schema_sha256=database.schema_sha256,
                member_inventory_sha256=canonical_planning_sha256(
                    [member.to_dict() for member in members]
                ),
                private_generation_identity_sha256=canonical_planning_sha256(
                    [wave.private_generation_identity_sha256 for wave in waves]
                ),
                wave_inventory_sha256=canonical_planning_sha256([wave.to_dict() for wave in waves]),
                planning_manifest_sha256="0" * 64,
                sealed_dispatch_inventory_sha256=canonical_planning_sha256(
                    [dispatch.to_dict() for dispatch in dispatches]
                ),
            )
            return PlanningGenerationManifest.seal(
                request=context.request,
                artifact_identity=artifact_identity,
                waves=cast("tuple", waves),
                members=members,
                requested_route_scopes=tuple(
                    sorted(scope_by_id.values(), key=lambda scope: scope.identity_sha256)
                ),
                sealed_dispatches=dispatches,
            )

    @staticmethod
    def _compile(
        *,
        request: SuccessorPlanningRequest,
        registry: tuple[PlanningSemanticPartitionValues, ...],
        phase: PlanningDispatchPhase,
    ) -> CompiledSuccessorPlanningProgram:
        try:
            return compile_successor_planning_program(
                request=request,
                semantic_registry=registry,
                phase=phase,
            )
        except SuccessorPlanningProgramCompilerError as exc:
            raise PlanningProgramDriverError(
                f"{phase.value} semantic program compilation failed"
            ) from exc

    def _wave_0_admission(self, context: PlanningDriverContext) -> PlanningWaveAdmission:
        scopes = context.request.requested_planning_scopes
        return PlanningWaveAdmission(
            wave_index=0,
            parent_wave_identity_sha256=None,
            requested_route_scopes=scopes,
            sealed_dispatches=self._build_wave_0_dispatches(scopes),
        )

    @staticmethod
    def _build_wave_0_dispatches(
        scopes: tuple[RequestedRouteScope, ...],
    ) -> tuple[SealedProviderDispatch, ...]:
        groups: dict[tuple[str, str], list[RequestedRouteScope]] = {}
        for scope in scopes:
            groups.setdefault((scope.endpoint_name, scope.scope_sha256), []).append(scope)
        dispatches: list[SealedProviderDispatch] = []
        for _key, grouped in sorted(
            groups.items(),
            key=lambda item: min(scope.identity_sha256 for scope in item[1]),
        ):
            routes = {scope.route_id: _current_route(scope) for scope in grouped}
            ordered = tuple(sorted(grouped, key=lambda scope: routes[scope.route_id].ordinal))
            first = ordered[0]
            patterns = {routes[scope.route_id].param_pattern for scope in ordered}
            providers = {routes[scope.route_id].provider_authority_sha256 for scope in ordered}
            provider_endpoints = {routes[scope.route_id].provider_endpoint_id for scope in ordered}
            if len(patterns) != 1 or len(providers) != 1 or len(provider_endpoints) != 1:
                raise PlanningProgramDriverError(
                    "wave 0 logical call routes differ in provider authority"
                )
            dispatches.append(
                SealedProviderDispatch.from_parameters(
                    phase=PlanningDispatchPhase.PLANNING_WAVE_0,
                    endpoint_name=first.endpoint_name,
                    requested_scope_identity_sha256s=tuple(
                        scope.identity_sha256 for scope in ordered
                    ),
                    parameters=first.parameters,
                    pattern=next(iter(patterns)),
                    staging_route_ids=tuple(scope.route_id for scope in ordered),
                    dependency_identity_sha256s=(),
                )
            )
        return tuple(dispatches)

    def _validate_active_admission(
        self,
        context: PlanningDriverContext,
        admission: PlanningWaveAdmission,
        decoded: tuple[_DecodedCommittedEnvelope, ...],
    ) -> None:
        if admission.wave_index == 0:
            if self._wave_0_admission(context) != admission:
                raise PlanningProgramDriverError(
                    "active wave 0 differs from current request authority"
                )
            if context.planning_database is not None:
                with _bound_semantic_registry(
                    source=context.planning_database,
                    private_work_root=context.private_work_root,
                    authorities=tuple(item.authority for item in decoded),
                ):
                    pass
            return
        if context.planning_database is None:
            raise PlanningProgramDriverError("wave 1 admission lacks planning database")
        with _bound_semantic_registry(
            source=context.planning_database,
            private_work_root=context.private_work_root,
            authorities=tuple(item.authority for item in decoded),
        ) as registry:
            program = self._compile(
                request=context.request,
                registry=tuple(item for item in registry if item.authority.member.wave_index == 0),
                phase=PlanningDispatchPhase.PLANNING_WAVE_1,
            )
            self._require_program_matches_admission(program, admission)

    @staticmethod
    def _require_program_matches_admission(
        program: CompiledSuccessorPlanningProgram,
        admission: PlanningWaveAdmission,
    ) -> None:
        if tuple(scope.to_dict() for scope in program.requested_route_scopes) != tuple(
            scope.to_dict() for scope in admission.requested_route_scopes
        ) or tuple(dispatch.to_dict() for dispatch in program.sealed_dispatches) != tuple(
            dispatch.to_dict() for dispatch in admission.sealed_dispatches
        ):
            raise PlanningProgramDriverError(
                "compiled semantic program differs from durable wave admission"
            )

    @staticmethod
    def _require_context(context: PlanningDriverContext) -> None:
        if not isinstance(context, PlanningDriverContext):
            raise PlanningProgramDriverError("driver context is invalid")
        try:
            validated = validate_successor_planning_request(context.request)
        except SuccessorPlanningRequestBuilderError as exc:
            raise PlanningProgramDriverError(
                "planning request differs from current exact builder authority"
            ) from exc
        if validated.to_dict() != context.request.to_dict():
            raise PlanningProgramDriverError(
                "planning request validation returned different authority"
            )

    @staticmethod
    def _require_private_result_sources(
        context: PlanningDriverContext,
        result: PlanningCallExecution,
    ) -> None:
        root = Path(os.path.abspath(context.private_work_root))
        for source in (
            *(member.artifact for member in result.members),
            result.planning_database.artifact,
        ):
            absolute = Path(os.path.abspath(source.path))
            try:
                absolute.relative_to(root)
            except ValueError as exc:
                raise PlanningProgramDriverError(
                    "planning runtime source falls outside private work root"
                ) from exc

    def _decode_committed_envelopes(
        self,
        context: PlanningDriverContext,
    ) -> tuple[_DecodedCommittedEnvelope, ...]:
        calls = {call.identity_sha256: call for call in context.snapshot.committed_calls}
        call_positions = {
            call.identity_sha256: position
            for position, call in enumerate(context.snapshot.committed_calls)
        }
        result: list[_DecodedCommittedEnvelope] = []
        for payload in context.committed_member_payloads:
            call = calls.get(payload.call_identity_sha256)
            if call is None or payload.committed not in call.members:
                raise PlanningProgramDriverError("committed member is outside its call")
            position = call_positions[call.identity_sha256]
            expected_input = (
                None
                if position == 0
                else context.snapshot.committed_calls[position - 1].planning_database_sha256
            )
            envelope = PlanningMemberEnvelope.from_canonical_bytes(payload.encoded)
            scope_by_id = {scope.identity_sha256: scope for scope in call.requested_route_scopes}
            expected_scope = scope_by_id.get(payload.committed.member.producing_scope_sha256)
            if expected_scope is None:
                raise PlanningProgramDriverError("committed member producing scope is not admitted")
            provider = self._provider_authority(call.requested_route_scopes)
            self._validate_envelope(
                context=context,
                envelope=envelope,
                member=payload.committed.member,
                expected_scope=expected_scope,
                expected_receipt_sha256=payload.committed.receipt_sha256,
                expected_provider_authority_sha256=provider,
                expected_input_database_sha256=expected_input,
                expected_output_database_sha256=call.planning_database_sha256,
            )
            authority = PlanningSemanticMemberAuthority(
                member=payload.committed.member,
                producing_scope=envelope.producing_scope,
                logical_call_receipt_sha256=envelope.logical_call_receipt_sha256,
                provider_authority_sha256=envelope.provider_authority_sha256,
            )
            result.append(
                _DecodedCommittedEnvelope(
                    call=call,
                    member=payload.committed.member,
                    member_identity_sha256=payload.committed.member.identity_sha256,
                    envelope=envelope,
                    authority=authority,
                )
            )
        return tuple(result)

    @staticmethod
    def _validate_envelope(
        *,
        context: PlanningDriverContext,
        envelope: PlanningMemberEnvelope,
        member: PlanningDataMember,
        expected_scope: RequestedRouteScope,
        expected_receipt_sha256: str,
        expected_provider_authority_sha256: str,
        expected_input_database_sha256: str | None,
        expected_output_database_sha256: str,
    ) -> None:
        if (
            envelope.planning_request_sha256 != context.request.identity_sha256
            or envelope.planning_generation_id != context.planning_generation_id
            or envelope.wave_index != member.wave_index
            or envelope.producing_scope.to_dict() != expected_scope.to_dict()
            or envelope.producing_scope_identity_sha256 != member.producing_scope_sha256
            or envelope.input_planning_database_sha256 != expected_input_database_sha256
            or envelope.output_planning_database_sha256 != expected_output_database_sha256
            or envelope.logical_call_receipt_sha256 != expected_receipt_sha256
            or envelope.provider_authority_sha256 != expected_provider_authority_sha256
            or envelope.member_id != member.member_id
            or envelope.semantic.to_dict() != member.semantic.to_dict()
            or member.schema_sha256 != PlanningMemberEnvelope.schema_sha256
        ):
            raise PlanningProgramDriverError(
                "planning member envelope differs from request, scope, receipt, or member"
            )

    @staticmethod
    def _expected_semantic_inventory(
        *,
        request: SuccessorPlanningRequest,
        wave_index: int,
        scopes: tuple[RequestedRouteScope, ...],
    ) -> set[tuple[str, PlanningSemanticKind, str]]:
        seasons = sorted(
            {
                cast("str", scope.parameters["season"])
                for scope in request.requested_planning_scopes
                if scope.endpoint_name == "league_game_log"
            }
        )
        result: set[tuple[str, PlanningSemanticKind, str]] = set()

        def add(
            scope: RequestedRouteScope,
            kind: PlanningSemanticKind,
            partition: Mapping[str, object],
        ) -> None:
            result.add(
                (
                    scope.identity_sha256,
                    kind,
                    canonical_planning_sha256(dict(partition)),
                )
            )

        for scope in scopes:
            parameters = scope.parameters
            if wave_index == 1:
                if scope.endpoint_name == "cume_stats_player_games":
                    add(
                        scope,
                        PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS,
                        parameters,
                    )
                elif scope.endpoint_name == "cume_stats_team_games":
                    add(
                        scope,
                        PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS,
                        parameters,
                    )
                else:
                    raise PlanningProgramDriverError(
                        "wave 1 runtime returned a non-foundation semantic route"
                    )
            elif scope.endpoint_name == "league_game_log":
                add(
                    scope,
                    PlanningSemanticKind.GAME_DATE_INDEX,
                    {
                        "season": parameters["season"],
                        "season_type": parameters["season_type"],
                    },
                )
            elif scope.endpoint_name == "player_game_logs":
                add(
                    scope,
                    PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION,
                    {
                        "season": parameters["season"],
                        "season_type": parameters["season_type"],
                    },
                )
            elif scope.endpoint_name == "common_all_players":
                raw_current = parameters["is_only_current_season"]
                if type(raw_current) is not int or raw_current not in {0, 1}:
                    raise PlanningProgramDriverError(
                        "planning player scope current-only flag is invalid"
                    )
                add(
                    scope,
                    PlanningSemanticKind.SEASON_PLAYER_UNIVERSE,
                    {
                        "season": parameters["season"],
                        "current_only": bool(raw_current),
                    },
                )
            elif scope.endpoint_name == "common_team_years":
                for season in seasons:
                    add(
                        scope,
                        PlanningSemanticKind.SEASON_TEAM_UNIVERSE,
                        {"season": season},
                    )
                add(
                    scope,
                    PlanningSemanticKind.CURRENT_TEAM_UNIVERSE,
                    {"as_of_utc": request.as_of_utc},
                )
                add(scope, PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA, {})
            elif scope.endpoint_name == "live_score_board":
                add(
                    scope,
                    PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS,
                    {"as_of_utc": request.as_of_utc},
                )
            else:
                raise PlanningProgramDriverError(
                    "wave 0 runtime returned an unrecognized planning root"
                )
        return result

    @classmethod
    def _validate_returned_semantic_inventory(
        cls,
        *,
        request: SuccessorPlanningRequest,
        wave_index: int,
        scopes: tuple[RequestedRouteScope, ...],
        envelopes: tuple[PlanningMemberEnvelope, ...],
    ) -> None:
        expected = cls._expected_semantic_inventory(
            request=request,
            wave_index=wave_index,
            scopes=scopes,
        )
        observed = {
            (
                envelope.producing_scope.identity_sha256,
                envelope.semantic.semantic_kind,
                canonical_planning_sha256(envelope.semantic.partition),
            )
            for envelope in envelopes
        }
        if len(observed) != len(envelopes) or observed != expected:
            raise PlanningProgramDriverError(
                "planning call semantic members differ from exact route topology"
            )

    @staticmethod
    def _provider_authority(scopes: tuple[RequestedRouteScope, ...]) -> str:
        values = {_current_route(scope).provider_authority_sha256 for scope in scopes}
        if len(values) != 1:
            raise PlanningProgramDriverError("logical call has mixed provider authority")
        return next(iter(values))
