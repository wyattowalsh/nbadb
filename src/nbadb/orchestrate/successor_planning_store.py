"""Private, durable artifact storage for one successor planning generation.

This module owns persistence and verification only.  It stores immutable
planning-DuckDB snapshots and member blobs as opaque regular files, advances a
small canonical checkpoint at complete call and wave boundaries, and finally
anchors the canonical :class:`PlanningGenerationManifest` bytes.  It does not
open DuckDB, implement the generation-relative journal, own capture sessions,
or execute provider calls.
"""

from __future__ import annotations

import errno
import hashlib
import importlib
import json
import math
import os
import secrets
import shutil
import stat
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from functools import wraps
from pathlib import Path, PurePath
from typing import Any, ClassVar, Final, Self, cast

from nbadb.orchestrate import successor_crash_injection as crash_injection
from nbadb.orchestrate.capture_session import PrivateGenerationIdentity
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDataMember,
    PlanningDispatchPhase,
    PlanningGenerationManifest,
    SealedProviderDispatch,
    SuccessorPlanningGenerationContractError,
    SuccessorPlanningWave,
    canonical_planning_json_bytes,
    canonical_planning_sha256,
)
from nbadb.orchestrate.successor_planning_wave_receipt import (
    PlanningWaveCompletionReceipt,
    PlanningWaveCompletionReceiptError,
)
from nbadb.orchestrate.successor_update_contract import RequestedRouteScope

__all__ = [
    "SUCCESSOR_PLANNING_STORE_SCHEMA_VERSION",
    "CommittedPlanningCall",
    "CommittedPlanningMember",
    "CommittedPlanningWaveAuthority",
    "PlanningArtifactSource",
    "PlanningDatabaseSource",
    "PlanningGenerationPhase",
    "PlanningGenerationSnapshot",
    "PlanningGenerationContextExport",
    "PlanningMemberSource",
    "PlanningStoreBudget",
    "PlanningStoreCollectionResult",
    "PlanningWaveAdmission",
    "SuccessorPlanningStore",
    "SuccessorPlanningStoreError",
]

SUCCESSOR_PLANNING_STORE_SCHEMA_VERSION: Final = 2

_LOCK_NAME: Final = ".successor-planning-store.lock"
_REQUEST_NAME: Final = "request.json"
_CHECKPOINT_NAME: Final = "checkpoint.json"
_MANIFEST_NAME: Final = "planning-generation-manifest.json"
_SHA256_LENGTH: Final = 64
_MAX_SIGNED_63: Final = (1 << 63) - 1
_OBJECT_KINDS: Final = frozenset(
    {
        "member",
        "database",
        "wave",
        "member_inventory",
        "wave_inventory",
        "dispatch_inventory",
        "manifest",
        "private_generation_identity",
        "wave_completion_receipt",
    }
)
_PHASE_RANK: Final = {
    "building": 0,
    "wave_0_committed": 1,
    "wave_1_committed": 2,
    "sealed": 3,
}


class SuccessorPlanningStoreError(RuntimeError):
    """Raised when private planning persistence or verification is unsafe."""


class PlanningGenerationPhase(StrEnum):
    """Durable phases exposed only after their complete checkpoint commits."""

    BUILDING = "building"
    WAVE_0_COMMITTED = "wave_0_committed"
    WAVE_1_COMMITTED = "wave_1_committed"
    SEALED = "sealed"


def _require_sha256(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SuccessorPlanningStoreError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise SuccessorPlanningStoreError(f"{field_name} must be a nonnegative integer")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise SuccessorPlanningStoreError(f"{field_name} must be a positive integer")
    return value


def _require_positive_signed63(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1 or value > _MAX_SIGNED_63:
        raise SuccessorPlanningStoreError(f"{field_name} must be a positive signed-63-bit integer")
    return value


def _require_safe_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise SuccessorPlanningStoreError(f"{field_name} must be a path-free safe token")
    if not value[0].isalnum() or any(
        not (character.isascii() and (character.isalnum() or character in "_.:-"))
        for character in value
    ):
        raise SuccessorPlanningStoreError(f"{field_name} must be a path-free safe token")
    return value


def _canonical_bytes(payload: object) -> bytes:
    return canonical_planning_json_bytes(payload)


def _raw_sha256(encoded: bytes) -> str:
    return hashlib.sha256(encoded).hexdigest()


def _generation_identity(request_sha256: str, planning_generation_id: str) -> str:
    return canonical_planning_sha256(
        {
            "domain": "nbadb.successor-planning-store.generation.v2",
            "planning_request_sha256": request_sha256,
            "planning_generation_id": planning_generation_id,
        }
    )


def _object_domain_sha256(kind: str, sha256: str, byte_count: int) -> str:
    return canonical_planning_sha256(
        {
            "domain": f"nbadb.successor-planning-store.object.{kind}.v2",
            "sha256": sha256,
            "bytes": byte_count,
        }
    )


@dataclass(frozen=True, slots=True)
class PlanningWaveAdmission:
    """Exact scope bodies and ordered call program persisted before a wave."""

    wave_index: int
    parent_wave_identity_sha256: str | None
    requested_route_scopes: tuple[RequestedRouteScope, ...]
    sealed_dispatches: tuple[SealedProviderDispatch, ...]

    schema_version: ClassVar[int] = SUCCESSOR_PLANNING_STORE_SCHEMA_VERSION
    kind: ClassVar[str] = "planning_wave_admission"

    def __post_init__(self) -> None:
        if type(self.wave_index) is not int or self.wave_index not in {0, 1}:
            raise SuccessorPlanningStoreError("wave admission index must be exactly 0 or 1")
        if self.wave_index == 0:
            if self.parent_wave_identity_sha256 is not None:
                raise SuccessorPlanningStoreError("wave 0 admission cannot have a parent")
        elif self.parent_wave_identity_sha256 is None:
            raise SuccessorPlanningStoreError("wave 1 admission requires its wave 0 parent")
        else:
            _require_sha256(
                self.parent_wave_identity_sha256,
                field_name="wave admission parent identity",
            )
        scopes = self.requested_route_scopes
        if type(scopes) is not tuple or not scopes:
            raise SuccessorPlanningStoreError(
                "wave admission scopes must be a nonempty immutable tuple"
            )
        if any(not isinstance(scope, RequestedRouteScope) for scope in scopes):
            raise SuccessorPlanningStoreError("wave admission scope is invalid")
        if scopes != tuple(sorted(scopes, key=lambda scope: scope.identity_sha256)):
            raise SuccessorPlanningStoreError("wave admission scopes must be canonical")
        scope_ids = tuple(scope.identity_sha256 for scope in scopes)
        if len(scope_ids) != len(set(scope_ids)):
            raise SuccessorPlanningStoreError("wave admission scopes contain duplicates")
        dispatches = self.sealed_dispatches
        if type(dispatches) is not tuple or not dispatches:
            raise SuccessorPlanningStoreError(
                "wave admission dispatches must be a nonempty immutable tuple"
            )
        if any(not isinstance(dispatch, SealedProviderDispatch) for dispatch in dispatches):
            raise SuccessorPlanningStoreError("wave admission dispatch is invalid")
        expected_phase = (
            PlanningDispatchPhase.PLANNING_WAVE_0
            if self.wave_index == 0
            else PlanningDispatchPhase.PLANNING_WAVE_1
        )
        scope_by_id = {scope.identity_sha256: scope for scope in scopes}
        dispatched_scope_ids: list[str] = []
        for dispatch in dispatches:
            if dispatch.phase is not expected_phase:
                raise SuccessorPlanningStoreError("wave admission dispatch phase differs")
            for position, scope_id in enumerate(dispatch.requested_scope_identity_sha256s):
                scope = scope_by_id.get(scope_id)
                if scope is None:
                    raise SuccessorPlanningStoreError(
                        "wave admission dispatch widens beyond exact scopes"
                    )
                if (
                    scope.endpoint_name != dispatch.endpoint_name
                    or scope.parameters != dispatch.parameters
                    or scope.route_id != dispatch.staging_route_ids[position]
                ):
                    raise SuccessorPlanningStoreError(
                        "wave admission dispatch rewrites an exact scope"
                    )
            dispatched_scope_ids.extend(dispatch.requested_scope_identity_sha256s)
        if len(dispatched_scope_ids) != len(set(dispatched_scope_ids)):
            raise SuccessorPlanningStoreError(
                "wave admission scope appears in more than one dispatch"
            )
        if set(dispatched_scope_ids) != set(scope_ids):
            raise SuccessorPlanningStoreError(
                "wave admission dispatches do not exactly cover its scopes"
            )

    @property
    def requested_scope_identity_sha256s(self) -> tuple[str, ...]:
        return tuple(scope.identity_sha256 for scope in self.requested_route_scopes)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "domain": "nbadb.successor-planning-store.wave-admission.v2",
            "wave_index": self.wave_index,
            "parent_wave_identity_sha256": self.parent_wave_identity_sha256,
            "requested_route_scopes": [scope.to_dict() for scope in self.requested_route_scopes],
            "sealed_dispatches": [dispatch.to_dict() for dispatch in self.sealed_dispatches],
        }

    @property
    def identity_sha256(self) -> str:
        return canonical_planning_sha256(self._identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "wave_index": self.wave_index,
            "parent_wave_identity_sha256": self.parent_wave_identity_sha256,
            "requested_route_scopes": [scope.to_dict() for scope in self.requested_route_scopes],
            "sealed_dispatches": [dispatch.to_dict() for dispatch in self.sealed_dispatches],
            "identity_sha256": self.identity_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        if set(payload) != {
            "schema_version",
            "kind",
            "wave_index",
            "parent_wave_identity_sha256",
            "requested_route_scopes",
            "sealed_dispatches",
            "identity_sha256",
        }:
            raise SuccessorPlanningStoreError("wave admission fields are invalid")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != SUCCESSOR_PLANNING_STORE_SCHEMA_VERSION
            or payload["kind"] != cls.kind
        ):
            raise SuccessorPlanningStoreError("wave admission schema is invalid")
        raw_parent = payload["parent_wave_identity_sha256"]
        parent = (
            None
            if raw_parent is None
            else _require_sha256(raw_parent, field_name="wave admission parent identity")
        )
        raw_scopes = payload["requested_route_scopes"]
        raw_dispatches = payload["sealed_dispatches"]
        if not isinstance(raw_scopes, list) or not isinstance(raw_dispatches, list):
            raise SuccessorPlanningStoreError("wave admission scopes must be a list")
        try:
            result = cls(
                wave_index=_require_nonnegative_int(
                    payload["wave_index"], field_name="wave admission index"
                ),
                parent_wave_identity_sha256=parent,
                requested_route_scopes=tuple(
                    RequestedRouteScope.from_dict(cast("Mapping[str, object]", item))
                    for item in raw_scopes
                ),
                sealed_dispatches=tuple(
                    SealedProviderDispatch.from_dict(cast("Mapping[str, object]", item))
                    for item in raw_dispatches
                ),
            )
        except (TypeError, ValueError) as exc:
            raise SuccessorPlanningStoreError("wave admission nested authority is invalid") from exc
        if result.identity_sha256 != _require_sha256(
            payload["identity_sha256"], field_name="wave admission identity"
        ):
            raise SuccessorPlanningStoreError("wave admission identity differs")
        return result


@dataclass(frozen=True, slots=True)
class PlanningStoreBudget:
    """Caller-measured limits for exactly one store operation.

    Current monotonic time comes from the store's injected clock only after the
    operation owns the store lock.  It is never caller-stored replay authority.
    """

    generation_max_bytes: int
    artifact_max_bytes: int
    control_max_bytes: int
    minimum_free_bytes: int
    monotonic_deadline_seconds: float
    minimum_deadline_headroom_seconds: float

    def __post_init__(self) -> None:
        for field_name in (
            "generation_max_bytes",
            "artifact_max_bytes",
            "control_max_bytes",
        ):
            _require_positive_int(getattr(self, field_name), field_name=field_name)
        _require_nonnegative_int(self.minimum_free_bytes, field_name="minimum_free_bytes")
        for field_name in (
            "monotonic_deadline_seconds",
            "minimum_deadline_headroom_seconds",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or value < 0
            ):
                raise SuccessorPlanningStoreError(f"{field_name} must be finite and nonnegative")


@dataclass(frozen=True, slots=True)
class PlanningArtifactSource:
    """Caller-measured source for one opaque private content object."""

    path: Path
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        path = Path(self.path)
        if not path.is_absolute():
            raise SuccessorPlanningStoreError("artifact source path must be absolute")
        object.__setattr__(self, "path", path)
        _require_sha256(self.sha256, field_name="artifact source sha256")
        _require_nonnegative_int(self.byte_count, field_name="artifact source byte_count")


@dataclass(frozen=True, slots=True)
class PlanningDatabaseSource:
    """One complete opaque planning-DuckDB snapshot and its schema identity."""

    artifact: PlanningArtifactSource
    schema_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, PlanningArtifactSource):
            raise SuccessorPlanningStoreError("planning database artifact is invalid")
        if self.artifact.byte_count < 1:
            raise SuccessorPlanningStoreError("planning database must be nonempty")
        _require_sha256(self.schema_sha256, field_name="planning database schema_sha256")


@dataclass(frozen=True, slots=True)
class PlanningMemberSource:
    """One DP1 member value, its exact receipt, and its private artifact bytes."""

    member: PlanningDataMember
    receipt_sha256: str
    artifact: PlanningArtifactSource

    def __post_init__(self) -> None:
        if not isinstance(self.member, PlanningDataMember):
            raise SuccessorPlanningStoreError("planning member is invalid")
        _require_sha256(self.receipt_sha256, field_name="planning member receipt_sha256")
        if not isinstance(self.artifact, PlanningArtifactSource):
            raise SuccessorPlanningStoreError("planning member artifact is invalid")
        if self.member.content_sha256 != self.artifact.sha256:
            raise SuccessorPlanningStoreError(
                "planning member content digest differs from its artifact source"
            )


@dataclass(frozen=True, slots=True)
class CommittedPlanningMember:
    """Verified, checkpoint-referenced member returned by a store read."""

    member: PlanningDataMember
    receipt_sha256: str
    artifact_sha256: str
    artifact_bytes: int
    object_domain_sha256: str


@dataclass(frozen=True, slots=True)
class CommittedPlanningCall:
    """One exact call boundary adopted by the canonical checkpoint."""

    ordinal: int
    wave_index: int
    sealed_dispatch: SealedProviderDispatch
    requested_route_scopes: tuple[RequestedRouteScope, ...]
    members: tuple[CommittedPlanningMember, ...]
    planning_database_sha256: str
    planning_database_bytes: int
    planning_database_schema_sha256: str
    identity_sha256: str


@dataclass(frozen=True, slots=True)
class CommittedPlanningWaveAuthority:
    """Verified path-free private authority retained for one committed wave."""

    wave_index: int
    private_generation_identity: PrivateGenerationIdentity
    completion_receipt: PlanningWaveCompletionReceipt
    private_generation_identity_sha256: str
    private_generation_identity_bytes: int
    private_generation_identity_object_domain_sha256: str
    completion_receipt_sha256: str
    completion_receipt_bytes: int
    completion_receipt_object_domain_sha256: str


@dataclass(frozen=True, slots=True)
class PlanningGenerationSnapshot:
    """Fully reverified private state at one canonical checkpoint revision."""

    request: SuccessorPlanningRequest
    planning_generation_id: str
    generation_identity_sha256: str
    phase: PlanningGenerationPhase
    revision: int
    committed_calls: tuple[CommittedPlanningCall, ...]
    committed_waves: tuple[SuccessorPlanningWave, ...]
    committed_wave_admissions: tuple[PlanningWaveAdmission, ...]
    committed_wave_authorities: tuple[CommittedPlanningWaveAuthority, ...]
    active_wave: PlanningWaveAdmission | None
    planning_database_sha256: str | None
    planning_database_bytes: int | None
    planning_database_schema_sha256: str | None
    manifest: PlanningGenerationManifest | None


@dataclass(frozen=True, slots=True)
class PlanningStoreCollectionResult:
    """Path-free identities removed or kept by receipt-bound planning-store GC."""

    deleted_generation_identity_sha256s: tuple[str, ...]
    deleted_object_sha256s: tuple[str, ...]
    retained_generation_identity_sha256s: tuple[str, ...]
    retained_planning_generation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _PlanningGenerationHeader:
    path: Path
    request: SuccessorPlanningRequest
    planning_generation_id: str
    generation_identity_sha256: str
    object_sha256s: frozenset[str]
    retain_identity_sha256s: frozenset[str]


@dataclass(frozen=True, slots=True)
class PlanningGenerationContextExport:
    """One twice-verified snapshot plus all bytes needed by a driver context."""

    snapshot: PlanningGenerationSnapshot
    committed_member_bytes: tuple[tuple[str, str, bytes], ...]
    planning_database: PlanningDatabaseSource | None

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, PlanningGenerationSnapshot):
            raise SuccessorPlanningStoreError("planning context export snapshot is invalid")
        expected_members = tuple(
            (
                call.identity_sha256,
                member.member.identity_sha256,
                member.artifact_sha256,
                member.artifact_bytes,
            )
            for call in self.snapshot.committed_calls
            for member in call.members
        )
        observed_members: list[tuple[str, str, str, int]] = []
        for call_identity, member_identity, encoded in self.committed_member_bytes:
            if not isinstance(encoded, bytes):
                raise SuccessorPlanningStoreError(
                    "planning context export member bytes are invalid"
                )
            observed_members.append(
                (
                    call_identity,
                    member_identity,
                    _raw_sha256(encoded),
                    len(encoded),
                )
            )
        if tuple(observed_members) != expected_members:
            raise SuccessorPlanningStoreError(
                "planning context export member inventory differs from its snapshot"
            )
        database_present = self.snapshot.planning_database_sha256 is not None
        if database_present != (self.planning_database is not None):
            raise SuccessorPlanningStoreError(
                "planning context export database differs from its snapshot"
            )
        if self.planning_database is not None and (
            self.planning_database.artifact.sha256 != self.snapshot.planning_database_sha256
            or self.planning_database.artifact.byte_count != self.snapshot.planning_database_bytes
            or self.planning_database.schema_sha256 != self.snapshot.planning_database_schema_sha256
        ):
            raise SuccessorPlanningStoreError(
                "planning context export database authority differs from its snapshot"
            )


@dataclass(frozen=True, slots=True)
class _VerifiedPlanningState:
    snapshot: PlanningGenerationSnapshot
    checkpoint: dict[str, object]
    generation_stat: os.stat_result
    checkpoint_stat: os.stat_result
    logical_bytes: int


@dataclass(frozen=True, slots=True)
class _ObjectReference:
    kind: str
    sha256: str
    byte_count: int
    domain_sha256: str

    def __post_init__(self) -> None:
        if self.kind not in _OBJECT_KINDS:
            raise SuccessorPlanningStoreError("planning object kind is invalid")
        _require_sha256(self.sha256, field_name="planning object sha256")
        _require_nonnegative_int(self.byte_count, field_name="planning object bytes")
        _require_sha256(self.domain_sha256, field_name="planning object domain_sha256")
        if self.domain_sha256 != _object_domain_sha256(self.kind, self.sha256, self.byte_count):
            raise SuccessorPlanningStoreError("planning object domain identity differs")

    @classmethod
    def create(cls, *, kind: str, sha256: str, byte_count: int) -> Self:
        return cls(
            kind=kind,
            sha256=sha256,
            byte_count=byte_count,
            domain_sha256=_object_domain_sha256(kind, sha256, byte_count),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        if set(payload) != {"kind", "sha256", "bytes", "domain_sha256"}:
            raise SuccessorPlanningStoreError("planning object reference fields are invalid")
        kind = payload["kind"]
        if not isinstance(kind, str):
            raise SuccessorPlanningStoreError("planning object kind is invalid")
        return cls(
            kind=kind,
            sha256=_require_sha256(payload["sha256"], field_name="planning object sha256"),
            byte_count=_require_nonnegative_int(
                payload["bytes"], field_name="planning object bytes"
            ),
            domain_sha256=_require_sha256(
                payload["domain_sha256"], field_name="planning object domain_sha256"
            ),
        )

    def to_dict(self) -> dict[str, str | int]:
        return {
            "kind": self.kind,
            "sha256": self.sha256,
            "bytes": self.byte_count,
            "domain_sha256": self.domain_sha256,
        }


_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


def _exclusive_operation(method: Any) -> Any:
    @wraps(method)
    def locked(self: SuccessorPlanningStore, *args: Any, **kwargs: Any) -> Any:
        with self._exclusive_store_lock():
            return method(self, *args, **kwargs)

    return locked


class SuccessorPlanningStore:
    """Content-addressed private planning artifact and phase-pointer store."""

    def __init__(
        self,
        root: Path,
        *,
        public_roots: Sequence[Path],
        monotonic_clock: Callable[[], float],
    ) -> None:
        supplied_root = Path(root)
        if not supplied_root.is_absolute():
            raise SuccessorPlanningStoreError("planning store root must be absolute")
        supplied_public_roots = tuple(Path(item) for item in public_roots)
        if not supplied_public_roots:
            raise SuccessorPlanningStoreError("public_roots must be explicitly nonempty")
        if any(not item.is_absolute() for item in supplied_public_roots):
            raise SuccessorPlanningStoreError("every public root must be absolute")
        if not callable(monotonic_clock):
            raise SuccessorPlanningStoreError("monotonic_clock must be callable")
        self.root = Path(os.path.abspath(supplied_root))
        self.objects_root = self.root / "objects"
        self.generations_root = self.root / "generations"
        self._public_roots = tuple(
            self._existing_regular_directory(item, label="public root")
            for item in supplied_public_roots
        )
        self._lock_state = threading.local()
        self._monotonic_clock = monotonic_clock
        self._expected_root_identity: tuple[int, int] | None = None
        self._expected_lock_identity: tuple[int, int] | None = None
        self._reject_public_overlap(self.root)

    @staticmethod
    def generation_identity(
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
    ) -> str:
        if not isinstance(request, SuccessorPlanningRequest):
            raise SuccessorPlanningStoreError("request must be a SuccessorPlanningRequest")
        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        return _generation_identity(request.identity_sha256, generation_id)

    def generation_path(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
    ) -> Path:
        identity = self.generation_identity(request, planning_generation_id)
        return self.generations_root / f"generation-{identity}"

    @_exclusive_operation
    def begin_generation(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        budget: PlanningStoreBudget,
    ) -> PlanningGenerationSnapshot:
        """Create or reverify one exact request/generation pair."""

        self._require_request_and_budget(request, planning_generation_id, budget)
        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        generation = self.generation_path(request, generation_id)
        if generation.exists() or generation.is_symlink():
            return self._load_and_verify_locked(request, generation_id, budget=budget)

        request_bytes = _canonical_bytes(request.to_dict())
        self._require_control_bytes(request_bytes, budget=budget, label="planning request")
        generation_identity = _generation_identity(request.identity_sha256, generation_id)
        checkpoint = self._new_checkpoint(
            request=request,
            planning_generation_id=generation_id,
            generation_identity_sha256=generation_identity,
            request_bytes=len(request_bytes),
        )
        checkpoint_bytes = _canonical_bytes(checkpoint)
        self._require_control_bytes(checkpoint_bytes, budget=budget, label="planning checkpoint")
        self._require_generation_bound(
            checkpoint,
            request_bytes=len(request_bytes),
            checkpoint_bytes=len(checkpoint_bytes),
            manifest_file_bytes=0,
            budget=budget,
        )
        self._require_disk_capacity(len(request_bytes) + len(checkpoint_bytes), budget=budget)
        temporary = self._new_private_directory(
            self.generations_root,
            prefix=f".{generation.name}.",
        )
        temporary_descriptor = self._open_directory(
            temporary,
            label="temporary planning generation",
        )
        temporary_before = os.fstat(temporary_descriptor)
        try:
            self._write_new_regular(
                temporary / _REQUEST_NAME,
                request_bytes,
                expected_parent=temporary_before,
            )
            self._write_new_regular(
                temporary / _CHECKPOINT_NAME,
                checkpoint_bytes,
                expected_parent=temporary_before,
            )
            observed_request, _request_stat = self._read_control_at(
                temporary_descriptor,
                _REQUEST_NAME,
                budget=budget,
                label="new planning request",
            )
            observed_checkpoint, _checkpoint_stat = self._read_control_at(
                temporary_descriptor,
                _CHECKPOINT_NAME,
                budget=budget,
                label="new planning checkpoint",
            )
            if observed_request != request_bytes or observed_checkpoint != checkpoint_bytes:
                raise SuccessorPlanningStoreError(
                    "new planning generation controls differ before publication"
                )
            self._validate_generation_layout_at(
                temporary_descriptor,
                manifest_present=False,
            )
            os.fsync(temporary_descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                temporary,
                temporary_before,
                os.fstat(temporary_descriptor),
                label="temporary planning generation",
            )
            try:
                os.rename(temporary, generation)
            except FileExistsError as exc:
                raise SuccessorPlanningStoreError(
                    "planning generation destination appeared during publication"
                ) from exc
            self._assert_locked_identity()
            self._require_same_open_directory(
                generation,
                temporary_before,
                os.fstat(temporary_descriptor),
                label="published planning generation",
            )
            self._fsync_directory(self.generations_root)
            self._require_same_open_directory(
                generation,
                temporary_before,
                os.fstat(temporary_descriptor),
                label="published planning generation",
            )
        finally:
            os.close(temporary_descriptor)
            # Once a control name exists, failure cleanup never unlinks it: a
            # concurrent replacement cannot be distinguished atomically here.
            # An unpublished random private generation directory is inert and
            # intentionally abandoned for fail-closed external cleanup.
            pass
        result = self._load_and_verify_locked(
            request,
            generation_id,
            budget=budget,
            expected_generation_stat=temporary_before,
        )
        if (
            result.revision != 0
            or result.phase is not PlanningGenerationPhase.BUILDING
            or result.active_wave is not None
            or result.committed_calls
            or result.committed_waves
        ):
            raise SuccessorPlanningStoreError(
                "new planning generation did not reach its exact postcondition"
            )
        crash_injection.after_durable_step(
            crash_injection.DurablePlanningStep.POINTER_ADVANCE,
            pointer="planning_generation",
            phase=PlanningGenerationPhase.BUILDING.value,
            revision=0,
            committed_call_count=0,
            committed_wave_count=0,
            has_active_wave=False,
            sealed=False,
        )
        return result

    @_exclusive_operation
    def begin_wave(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        admission: PlanningWaveAdmission,
        budget: PlanningStoreBudget,
    ) -> PlanningGenerationSnapshot:
        """Persist one exact wave scope before any of that wave's calls execute."""

        self._require_request_and_budget(request, planning_generation_id, budget)
        if not isinstance(admission, PlanningWaveAdmission):
            raise SuccessorPlanningStoreError("admission must be a PlanningWaveAdmission")
        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        state = self._load_state(request, generation_id, budget=budget)
        snapshot = state.snapshot
        checkpoint = state.checkpoint
        active = snapshot.active_wave
        if active is not None:
            if active != admission:
                raise SuccessorPlanningStoreError(
                    "active planning wave differs from the supplied admission"
                )
            return snapshot

        target_phase = (
            PlanningGenerationPhase.WAVE_0_COMMITTED
            if admission.wave_index == 0
            else PlanningGenerationPhase.WAVE_1_COMMITTED
        )
        if _PHASE_RANK[snapshot.phase.value] >= _PHASE_RANK[target_phase.value]:
            if admission.wave_index >= len(snapshot.committed_wave_admissions):
                raise SuccessorPlanningStoreError(
                    "planning phase is ahead without its admitted wave"
                )
            if snapshot.committed_wave_admissions[admission.wave_index] != admission:
                raise SuccessorPlanningStoreError(
                    "same-generation wave admission differs from committed authority"
                )
            return snapshot

        expected_phase = (
            PlanningGenerationPhase.BUILDING
            if admission.wave_index == 0
            else PlanningGenerationPhase.WAVE_0_COMMITTED
        )
        if snapshot.phase is not expected_phase:
            raise SuccessorPlanningStoreError(
                f"wave {admission.wave_index} cannot begin from {snapshot.phase.value}"
            )
        if any(call.wave_index == admission.wave_index for call in snapshot.committed_calls):
            raise SuccessorPlanningStoreError(
                "planning calls exist before their durable wave admission"
            )
        if admission.wave_index == 0:
            request_scopes = tuple(
                sorted(
                    request.requested_planning_scopes,
                    key=lambda scope: scope.identity_sha256,
                )
            )
            if admission.requested_route_scopes != request_scopes:
                raise SuccessorPlanningStoreError(
                    "wave 0 admission scopes differ from the exact planning request"
                )
        else:
            if len(snapshot.committed_waves) != 1:
                raise SuccessorPlanningStoreError("wave 1 admission requires committed wave 0")
            if admission.parent_wave_identity_sha256 != snapshot.committed_waves[0].identity_sha256:
                raise SuccessorPlanningStoreError("wave 1 admission parent authority differs")
            self._require_wave_1_dispatch_dependencies(
                admission,
                snapshot.committed_calls,
            )

        updated = dict(checkpoint)
        updated["revision"] = cast("int", checkpoint["revision"]) + 1
        updated["active_wave"] = admission.to_dict()
        self._commit_checkpoint(
            self.generation_path(request, generation_id),
            updated,
            state=state,
            budget=budget,
        )
        result = self._load_and_verify_locked(
            request,
            generation_id,
            budget=budget,
            expected_generation_stat=state.generation_stat,
        )
        if (
            result.revision != snapshot.revision + 1
            or result.phase is not snapshot.phase
            or result.active_wave != admission
        ):
            raise SuccessorPlanningStoreError(
                "wave admission checkpoint did not reach its exact postcondition"
            )
        return result

    @_exclusive_operation
    def commit_call(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        sealed_dispatch_identity_sha256: str,
        members: Sequence[PlanningMemberSource],
        planning_database: PlanningDatabaseSource,
        budget: PlanningStoreBudget,
    ) -> PlanningGenerationSnapshot:
        """Atomically expose one complete same-generation planning call."""

        self._require_request_and_budget(request, planning_generation_id, budget)
        dispatch_identity = _require_sha256(
            sealed_dispatch_identity_sha256,
            field_name="sealed dispatch identity",
        )
        if not isinstance(planning_database, PlanningDatabaseSource):
            raise SuccessorPlanningStoreError("planning_database must be a PlanningDatabaseSource")
        member_sources = tuple(members)
        if not member_sources or any(
            not isinstance(item, PlanningMemberSource) for item in member_sources
        ):
            raise SuccessorPlanningStoreError(
                "call members must be nonempty PlanningMemberSource values"
            )
        if member_sources != tuple(
            sorted(member_sources, key=lambda item: item.member.identity_sha256)
        ):
            raise SuccessorPlanningStoreError("call members must use canonical identity order")
        member_identities = [item.member.identity_sha256 for item in member_sources]
        if len(member_identities) != len(set(member_identities)):
            raise SuccessorPlanningStoreError("call member inventory contains duplicates")
        member_ids = [item.member.member_id for item in member_sources]
        if len(member_ids) != len(set(member_ids)):
            raise SuccessorPlanningStoreError("call member ids contain duplicates")
        wave_indexes = {item.member.wave_index for item in member_sources}
        if len(wave_indexes) != 1:
            raise SuccessorPlanningStoreError("one committed call must contain one wave")
        wave_index = next(iter(wave_indexes))

        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        state = self._load_state(request, generation_id, budget=budget)
        snapshot = state.snapshot
        checkpoint = state.checkpoint
        admissions = [*snapshot.committed_wave_admissions]
        if snapshot.active_wave is not None:
            admissions.append(snapshot.active_wave)
        admitted = [
            (admission, dispatch)
            for admission in admissions
            for dispatch in admission.sealed_dispatches
            if dispatch.identity_sha256 == dispatch_identity
        ]
        if len(admitted) != 1:
            raise SuccessorPlanningStoreError(
                "sealed dispatch is not uniquely present in durable wave admission"
            )
        admission, dispatch = admitted[0]
        if admission.wave_index != wave_index:
            raise SuccessorPlanningStoreError(
                "planning call member wave differs from its sealed dispatch"
            )
        scope_by_id = {scope.identity_sha256: scope for scope in admission.requested_route_scopes}
        requested_route_scopes = tuple(
            scope_by_id[scope_id] for scope_id in dispatch.requested_scope_identity_sha256s
        )
        producing_scopes = {item.member.producing_scope_sha256 for item in member_sources}
        if producing_scopes != set(dispatch.requested_scope_identity_sha256s):
            raise SuccessorPlanningStoreError(
                "planning call members do not exactly cover its sealed dispatch scopes"
            )
        required_phase = (
            PlanningGenerationPhase.BUILDING
            if wave_index == 0
            else PlanningGenerationPhase.WAVE_0_COMMITTED
        )
        if _PHASE_RANK[snapshot.phase.value] < _PHASE_RANK[required_phase.value]:
            raise SuccessorPlanningStoreError(
                f"wave {wave_index} call cannot commit before {required_phase.value}"
            )

        stored_calls = cast("list[dict[str, object]]", checkpoint["committed_calls"])
        existing = next(
            (
                item
                for item in stored_calls
                if item["sealed_dispatch_identity_sha256"] == dispatch_identity
            ),
            None,
        )
        if existing is None:
            active = snapshot.active_wave
            if active is None or active != admission:
                raise SuccessorPlanningStoreError(
                    "planning call requires its exact durable active wave admission"
                )
            if snapshot.phase is not required_phase:
                raise SuccessorPlanningStoreError(
                    "new planning calls cannot be appended after their wave is committed"
                )
            committed_program = tuple(
                call.sealed_dispatch.identity_sha256
                for call in snapshot.committed_calls
                if call.wave_index == wave_index
            )
            admitted_program = tuple(item.identity_sha256 for item in admission.sealed_dispatches)
            if (
                committed_program != admitted_program[: len(committed_program)]
                or len(committed_program) >= len(admitted_program)
                or admitted_program[len(committed_program)] != dispatch_identity
            ):
                raise SuccessorPlanningStoreError(
                    "planning call differs from the admitted dispatch program order"
                )
            prior_members = [
                member.member
                for prior_call in snapshot.committed_calls
                for member in prior_call.members
            ]
            if set(member_identities) & {member.identity_sha256 for member in prior_members}:
                raise SuccessorPlanningStoreError(
                    "planning generation member identities must be globally unique"
                )
            if set(member_ids) & {member.member_id for member in prior_members}:
                raise SuccessorPlanningStoreError(
                    "planning generation member ids must be globally unique"
                )

        member_records: list[dict[str, object]] = []
        for source in member_sources:
            reference = self._store_source_object("member", source.artifact, budget=budget)
            member_records.append(
                {
                    "member": source.member.to_dict(),
                    "member_identity_sha256": source.member.identity_sha256,
                    "receipt_sha256": source.receipt_sha256,
                    "artifact": reference.to_dict(),
                }
            )
        database_reference = self._store_source_object(
            "database", planning_database.artifact, budget=budget
        )
        database_record = {
            "artifact": database_reference.to_dict(),
            "schema_sha256": planning_database.schema_sha256,
        }
        ordinal = len(stored_calls)
        call_body: dict[str, object] = {
            "ordinal": ordinal,
            "wave_index": wave_index,
            "sealed_dispatch": dispatch.to_dict(),
            "sealed_dispatch_identity_sha256": dispatch_identity,
            "requested_route_scopes": [scope.to_dict() for scope in requested_route_scopes],
            "members": member_records,
            "database": database_record,
        }
        call_identity = canonical_planning_sha256(
            {
                "domain": "nbadb.successor-planning-store.call.v2",
                **call_body,
            }
        )
        call_record = {**call_body, "call_identity_sha256": call_identity}

        if existing is not None:
            comparison = dict(call_record)
            comparison["ordinal"] = existing["ordinal"]
            body = dict(comparison)
            body.pop("call_identity_sha256")
            comparison["call_identity_sha256"] = canonical_planning_sha256(
                {"domain": "nbadb.successor-planning-store.call.v2", **body}
            )
            if existing != comparison:
                raise SuccessorPlanningStoreError(
                    "same-generation planning call differs from its committed boundary"
                )
            return self._load_and_verify_locked(request, generation_id, budget=budget)

        updated = dict(checkpoint)
        updated["revision"] = cast("int", checkpoint["revision"]) + 1
        updated["committed_calls"] = [
            *stored_calls,
            call_record,
        ]
        updated["current_database"] = database_record
        self._commit_checkpoint(
            self.generation_path(request, generation_id),
            updated,
            state=state,
            budget=budget,
        )
        result = self._load_and_verify_locked(
            request,
            generation_id,
            budget=budget,
            expected_generation_stat=state.generation_stat,
        )
        if (
            result.revision != snapshot.revision + 1
            or not result.committed_calls
            or result.committed_calls[-1].identity_sha256 != call_identity
            or result.planning_database_sha256 != database_reference.sha256
        ):
            raise SuccessorPlanningStoreError(
                "planning call checkpoint did not reach its exact postcondition"
            )
        crash_injection.after_durable_step(
            crash_injection.DurablePlanningStep.CALL_COMPLETION,
            sealed_dispatch_identity_sha256=dispatch_identity,
            wave_index=wave_index,
            call_identity_sha256=call_identity,
            committed_call_count=len(result.committed_calls),
        )
        return result

    @_exclusive_operation
    def commit_wave(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        wave: SuccessorPlanningWave,
        planning_database: PlanningDatabaseSource,
        private_generation_identity: PrivateGenerationIdentity,
        completion_receipt: PlanningWaveCompletionReceipt,
        budget: PlanningStoreBudget,
    ) -> PlanningGenerationSnapshot:
        """Advance a wave pointer only after exact call/member/DB verification."""

        self._require_request_and_budget(request, planning_generation_id, budget)
        if not isinstance(wave, SuccessorPlanningWave):
            raise SuccessorPlanningStoreError("wave must be a SuccessorPlanningWave")
        if not isinstance(planning_database, PlanningDatabaseSource):
            raise SuccessorPlanningStoreError("planning_database must be a PlanningDatabaseSource")
        if not isinstance(private_generation_identity, PrivateGenerationIdentity):
            raise SuccessorPlanningStoreError(
                "private_generation_identity must be a PrivateGenerationIdentity"
            )
        if not isinstance(completion_receipt, PlanningWaveCompletionReceipt):
            raise SuccessorPlanningStoreError(
                "completion_receipt must be a PlanningWaveCompletionReceipt"
            )
        private_identity_bytes = private_generation_identity.canonical_bytes
        completion_receipt_bytes = completion_receipt.canonical_bytes
        if _raw_sha256(private_identity_bytes) != wave.private_generation_identity_sha256:
            raise SuccessorPlanningStoreError(
                "wave private generation identity differs from its raw canonical bytes"
            )
        if _raw_sha256(completion_receipt_bytes) != wave.completion_receipt_sha256:
            raise SuccessorPlanningStoreError(
                "wave completion receipt differs from its raw canonical bytes"
            )
        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        state = self._load_state(request, generation_id, budget=budget)
        snapshot = state.snapshot
        checkpoint = state.checkpoint
        expected_phase = (
            PlanningGenerationPhase.BUILDING
            if wave.wave_index == 0
            else PlanningGenerationPhase.WAVE_0_COMMITTED
        )
        target_phase = (
            PlanningGenerationPhase.WAVE_0_COMMITTED
            if wave.wave_index == 0
            else PlanningGenerationPhase.WAVE_1_COMMITTED
        )
        stored_waves = cast("list[dict[str, object]]", checkpoint["committed_waves"])
        database_reference = self._store_source_object(
            "database", planning_database.artifact, budget=budget
        )
        supplied_database = {
            "artifact": database_reference.to_dict(),
            "schema_sha256": planning_database.schema_sha256,
        }
        private_reference = self._store_bytes_object(
            "private_generation_identity", private_identity_bytes, budget=budget
        )
        receipt_reference = self._store_bytes_object(
            "wave_completion_receipt", completion_receipt_bytes, budget=budget
        )
        supplied_private_authority = {
            "private_generation_identity": private_reference.to_dict(),
            "completion_receipt": receipt_reference.to_dict(),
        }
        if _PHASE_RANK[snapshot.phase.value] >= _PHASE_RANK[target_phase.value]:
            if wave.wave_index >= len(stored_waves):
                raise SuccessorPlanningStoreError(
                    "wave pointer is ahead without its wave authority"
                )
            observed_wave = SuccessorPlanningWave.from_dict(
                cast("Mapping[str, object]", stored_waves[wave.wave_index]["wave"])
            )
            if observed_wave != wave:
                raise SuccessorPlanningStoreError(
                    "same-generation wave differs from its committed authority"
                )
            if stored_waves[wave.wave_index]["database"] != supplied_database:
                raise SuccessorPlanningStoreError(
                    "same-generation wave database differs from committed authority"
                )
            if any(
                stored_waves[wave.wave_index][field_name] != expected
                for field_name, expected in supplied_private_authority.items()
            ):
                raise SuccessorPlanningStoreError(
                    "same-generation wave private authority differs from committed authority"
                )
            wave_calls = tuple(
                call for call in snapshot.committed_calls if call.wave_index == wave.wave_index
            )
            admission = snapshot.committed_wave_admissions[wave.wave_index]
            self._require_wave_completion_authority(
                request=request,
                planning_generation_id=generation_id,
                wave=wave,
                admission=admission,
                calls=wave_calls,
                planning_database=planning_database,
                private_generation_identity=private_generation_identity,
                completion_receipt=completion_receipt,
            )
            return self._load_and_verify_locked(request, generation_id, budget=budget)
        if snapshot.phase is not expected_phase:
            raise SuccessorPlanningStoreError(
                f"wave {wave.wave_index} cannot commit from {snapshot.phase.value}"
            )
        active = snapshot.active_wave
        if active is None or not self._admission_matches_wave(active, wave):
            raise SuccessorPlanningStoreError(
                "completed planning wave differs from its durable admission"
            )

        if checkpoint["current_database"] != supplied_database:
            raise SuccessorPlanningStoreError(
                "wave planning database differs from the last committed call boundary"
            )
        calls = [
            item
            for item in cast("list[dict[str, object]]", checkpoint["committed_calls"])
            if item["wave_index"] == wave.wave_index
        ]
        call_dispatches = tuple(
            cast("str", item["sealed_dispatch_identity_sha256"]) for item in calls
        )
        admitted_dispatches = tuple(
            dispatch.identity_sha256 for dispatch in active.sealed_dispatches
        )
        if call_dispatches != admitted_dispatches:
            raise SuccessorPlanningStoreError(
                "committed calls do not exactly complete the admitted dispatch program"
            )
        call_scopes = tuple(
            sorted(
                cast("str", scope_id)
                for item in calls
                for scope_id in cast(
                    "list[object]",
                    cast("dict[str, object]", item["sealed_dispatch"])[
                        "requested_scope_identity_sha256s"
                    ],
                )
            )
        )
        if call_scopes != wave.requested_scope_identity_sha256s:
            raise SuccessorPlanningStoreError(
                "committed call scopes do not exactly cover the sealed wave"
            )
        if wave.wave_index == 0:
            request_scopes = tuple(
                sorted(scope.identity_sha256 for scope in request.requested_planning_scopes)
            )
            if wave.requested_scope_identity_sha256s != request_scopes:
                raise SuccessorPlanningStoreError(
                    "wave 0 scopes differ from the exact planning request"
                )
        member_records = sorted(
            (
                cast("dict[str, object]", member)
                for call in calls
                for member in cast("list[object]", call["members"])
            ),
            key=lambda item: cast("str", item["member_identity_sha256"]),
        )
        if tuple(cast("str", item["member_identity_sha256"]) for item in member_records) != (
            wave.member_identity_sha256s
        ):
            raise SuccessorPlanningStoreError(
                "committed members do not exactly cover the sealed wave"
            )
        if tuple(cast("str", item["receipt_sha256"]) for item in member_records) != (
            wave.member_receipt_sha256s
        ):
            raise SuccessorPlanningStoreError(
                "committed member receipts differ from the sealed wave"
            )
        if wave.wave_index == 1:
            if not stored_waves:
                raise SuccessorPlanningStoreError("wave 1 requires a committed wave 0")
            parent = SuccessorPlanningWave.from_dict(
                cast("Mapping[str, object]", stored_waves[0]["wave"])
            )
            if wave.parent_wave_identity_sha256 != parent.identity_sha256:
                raise SuccessorPlanningStoreError("wave 1 parent authority differs")

        committed_wave_calls = tuple(
            call for call in snapshot.committed_calls if call.wave_index == wave.wave_index
        )
        self._require_wave_completion_authority(
            request=request,
            planning_generation_id=generation_id,
            wave=wave,
            admission=active,
            calls=committed_wave_calls,
            planning_database=planning_database,
            private_generation_identity=private_generation_identity,
            completion_receipt=completion_receipt,
        )

        wave_bytes = _canonical_bytes(wave.to_dict())
        wave_reference = self._store_bytes_object("wave", wave_bytes, budget=budget)
        wave_record: dict[str, object] = {
            "wave": wave.to_dict(),
            "wave_identity_sha256": wave.identity_sha256,
            "admission": active.to_dict(),
            "artifact": wave_reference.to_dict(),
            "database": supplied_database,
            "call_identity_sha256s": [item["call_identity_sha256"] for item in calls],
            **supplied_private_authority,
        }
        crash_injection.after_durable_step(
            crash_injection.DurablePlanningStep.WAVE_MANIFEST,
            wave_index=wave.wave_index,
            wave_identity_sha256=wave.identity_sha256,
        )
        updated = dict(checkpoint)
        updated["revision"] = cast("int", checkpoint["revision"]) + 1
        updated["phase"] = target_phase.value
        updated["committed_waves"] = [*stored_waves, wave_record]
        updated["active_wave"] = None
        self._commit_checkpoint(
            self.generation_path(request, generation_id),
            updated,
            state=state,
            budget=budget,
        )
        result = self._load_and_verify_locked(
            request,
            generation_id,
            budget=budget,
            expected_generation_stat=state.generation_stat,
        )
        if (
            result.revision != snapshot.revision + 1
            or result.phase is not target_phase
            or result.active_wave is not None
            or len(result.committed_waves) <= wave.wave_index
            or result.committed_waves[wave.wave_index] != wave
            or len(result.committed_wave_authorities) <= wave.wave_index
            or result.committed_wave_authorities[wave.wave_index].completion_receipt
            != completion_receipt
        ):
            raise SuccessorPlanningStoreError(
                "planning wave checkpoint did not reach its exact postcondition"
            )
        return result

    @_exclusive_operation
    def seal_generation(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        manifest: PlanningGenerationManifest,
        budget: PlanningStoreBudget,
    ) -> PlanningGenerationSnapshot:
        """Persist canonical DP1 bytes, then atomically expose the sealed pointer."""

        self._require_request_and_budget(request, planning_generation_id, budget)
        if not isinstance(manifest, PlanningGenerationManifest):
            raise SuccessorPlanningStoreError("manifest must be a PlanningGenerationManifest")
        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        state = self._load_state(request, generation_id, budget=budget)
        snapshot = state.snapshot
        checkpoint = state.checkpoint
        if snapshot.phase is PlanningGenerationPhase.SEALED:
            if snapshot.manifest != manifest:
                raise SuccessorPlanningStoreError(
                    "same-generation manifest differs from its sealed authority"
                )
            return snapshot
        if snapshot.phase is not PlanningGenerationPhase.WAVE_1_COMMITTED:
            raise SuccessorPlanningStoreError("both planning waves must commit before sealing")
        if manifest.request != request:
            raise SuccessorPlanningStoreError(
                "planning manifest request differs from the generation"
            )
        if manifest.artifact_identity.planning_generation_id != generation_id:
            raise SuccessorPlanningStoreError("planning manifest generation id differs")
        stored_waves = tuple(
            SuccessorPlanningWave.from_dict(cast("Mapping[str, object]", item["wave"]))
            for item in cast("list[dict[str, object]]", checkpoint["committed_waves"])
        )
        if stored_waves != manifest.waves:
            raise SuccessorPlanningStoreError(
                "planning manifest waves differ from stored authority"
            )
        self._require_manifest_admission_program(
            manifest,
            snapshot.committed_wave_admissions,
        )
        committed_members = tuple(
            sorted(
                (
                    PlanningDataMember.from_dict(cast("Mapping[str, object]", member["member"]))
                    for call in cast("list[dict[str, object]]", checkpoint["committed_calls"])
                    for member in cast("list[dict[str, object]]", call["members"])
                ),
                key=lambda item: item.identity_sha256,
            )
        )
        if committed_members != manifest.members:
            raise SuccessorPlanningStoreError(
                "planning manifest members differ from committed member boundaries"
            )
        current_database = cast("dict[str, object]", checkpoint["current_database"])
        current_database_ref = _ObjectReference.from_dict(
            cast("Mapping[str, object]", current_database["artifact"])
        )
        artifact_identity = manifest.artifact_identity
        if (
            current_database_ref.sha256 != artifact_identity.planning_database_sha256
            or current_database_ref.byte_count != artifact_identity.planning_database_bytes
            or current_database["schema_sha256"]
            != artifact_identity.planning_database_schema_sha256
        ):
            raise SuccessorPlanningStoreError(
                "planning manifest database authority differs from the stored snapshot"
            )

        member_inventory_bytes = _canonical_bytes([member.to_dict() for member in manifest.members])
        wave_inventory_bytes = _canonical_bytes([wave.to_dict() for wave in manifest.waves])
        dispatch_inventory_bytes = _canonical_bytes(
            [dispatch.to_dict() for dispatch in manifest.sealed_dispatches]
        )
        manifest_bytes = manifest.canonical_bytes
        if _raw_sha256(member_inventory_bytes) != artifact_identity.member_inventory_sha256:
            raise SuccessorPlanningStoreError("member inventory bytes differ from DP1 authority")
        if _raw_sha256(wave_inventory_bytes) != artifact_identity.wave_inventory_sha256:
            raise SuccessorPlanningStoreError("wave inventory bytes differ from DP1 authority")
        if (
            _raw_sha256(dispatch_inventory_bytes)
            != artifact_identity.sealed_dispatch_inventory_sha256
        ):
            raise SuccessorPlanningStoreError("dispatch inventory bytes differ from DP1 authority")

        member_inventory_ref = self._store_bytes_object(
            "member_inventory", member_inventory_bytes, budget=budget
        )
        wave_inventory_ref = self._store_bytes_object(
            "wave_inventory", wave_inventory_bytes, budget=budget
        )
        dispatch_inventory_ref = self._store_bytes_object(
            "dispatch_inventory", dispatch_inventory_bytes, budget=budget
        )
        manifest_ref = self._store_bytes_object("manifest", manifest_bytes, budget=budget)
        generation = self.generation_path(request, generation_id)
        self._require_control_bytes(manifest_bytes, budget=budget, label="planning manifest")
        manifest_path = generation / _MANIFEST_NAME
        if manifest_path.exists() or manifest_path.is_symlink():
            if self._read_control(manifest_path, budget=budget, label="planning manifest") != (
                manifest_bytes
            ):
                raise SuccessorPlanningStoreError("canonical planning manifest bytes changed")
        else:
            self._require_disk_capacity(len(manifest_bytes), budget=budget)
            self._publish_new_regular_no_replace(
                manifest_path,
                manifest_bytes,
                expected_parent=state.generation_stat,
            )

        crash_injection.after_durable_step(
            crash_injection.DurablePlanningStep.DISPATCH_SEAL,
            manifest_identity_sha256=manifest.identity_sha256,
            planning_generation_id=generation_id,
        )
        updated = dict(checkpoint)
        updated["revision"] = cast("int", checkpoint["revision"]) + 1
        updated["phase"] = PlanningGenerationPhase.SEALED.value
        updated["member_inventory"] = member_inventory_ref.to_dict()
        updated["wave_inventory"] = wave_inventory_ref.to_dict()
        updated["sealed_dispatch_inventory"] = dispatch_inventory_ref.to_dict()
        updated["manifest"] = {
            "artifact": manifest_ref.to_dict(),
            "identity_sha256": manifest.identity_sha256,
            "body_sha256": artifact_identity.planning_manifest_sha256,
        }
        self._commit_checkpoint(generation, updated, state=state, budget=budget)
        result = self._load_and_verify_locked(
            request,
            generation_id,
            budget=budget,
            expected_generation_stat=state.generation_stat,
        )
        if (
            result.revision != snapshot.revision + 1
            or result.phase is not PlanningGenerationPhase.SEALED
            or result.manifest != manifest
        ):
            raise SuccessorPlanningStoreError(
                "sealed planning checkpoint did not reach its exact postcondition"
            )
        return result

    @_exclusive_operation
    def load_and_verify(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        budget: PlanningStoreBudget,
    ) -> PlanningGenerationSnapshot:
        """Rehash every referenced byte before returning resumable authority."""

        self._require_request_and_budget(request, planning_generation_id, budget)
        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        return self._load_and_verify_locked(request, generation_id, budget=budget)

    @_exclusive_operation
    def provision(self) -> None:
        """Create the owner-only planning-store layout under the caller-owned root."""

        self._require_private_directory(self.root, label="planning store root")
        self._require_private_directory(self.objects_root, label="planning store directory")
        self._require_private_directory(self.generations_root, label="planning store directory")
        root_descriptor = int(self._lock_state.root_descriptor)
        self._require_complete_measurement_layout_at(
            root_descriptor,
            self._directory_entry_names(root_descriptor, label="planning store root"),
        )

    def require_provisioned_layout(self) -> None:
        """Fail closed unless the caller-owned root already has the complete layout."""

        with self._exclusive_store_lock(initialize_layout=False):
            self._require_private_directory(self.root, label="planning store root")
            root_descriptor = int(self._lock_state.root_descriptor)
            self._require_complete_measurement_layout_at(
                root_descriptor,
                self._directory_entry_names(root_descriptor, label="planning store root"),
            )

    @_exclusive_operation
    def collect_unreferenced(
        self,
        *,
        retain_identity_sha256s: frozenset[str],
        retain_planning_generation_ids: frozenset[str],
        budget: PlanningStoreBudget,
    ) -> PlanningStoreCollectionResult:
        """Delete unreferenced generations and objects; retain named resume authority."""

        if not isinstance(retain_identity_sha256s, frozenset) or any(
            not isinstance(item, str) for item in retain_identity_sha256s
        ):
            raise SuccessorPlanningStoreError(
                "retain_identity_sha256s must be a frozenset of strings"
            )
        if not isinstance(retain_planning_generation_ids, frozenset) or any(
            not isinstance(item, str) for item in retain_planning_generation_ids
        ):
            raise SuccessorPlanningStoreError(
                "retain_planning_generation_ids must be a frozenset of strings"
            )
        if not isinstance(budget, PlanningStoreBudget):
            raise SuccessorPlanningStoreError("budget must be a PlanningStoreBudget")
        self._admit_current_call(budget)
        for identity in retain_identity_sha256s:
            if len(identity) == _SHA256_LENGTH:
                _require_sha256(identity, field_name="retained private identity")

        committed, orphans = self._list_generation_directories_locked()
        headers: list[_PlanningGenerationHeader] = []
        for generation_dir in committed:
            headers.append(self._read_generation_header_locked(generation_dir, budget=budget))

        retained_headers: list[_PlanningGenerationHeader] = []
        deleted_generation_identities: list[str] = []
        for header in headers:
            if self._generation_header_retained(
                header,
                retain_identity_sha256s=retain_identity_sha256s,
                retain_planning_generation_ids=retain_planning_generation_ids,
            ):
                self._load_and_verify_locked(
                    header.request,
                    header.planning_generation_id,
                    budget=budget,
                )
                retained_headers.append(header)
                continue
            self._remove_planning_directory(header.path)
            deleted_generation_identities.append(header.generation_identity_sha256)

        for orphan in orphans:
            self._remove_planning_directory(orphan)

        referenced_objects: set[str] = set()
        for header in retained_headers:
            referenced_objects.update(header.object_sha256s)
        deleted_objects = self._collect_unreferenced_objects_locked(referenced_objects)
        return PlanningStoreCollectionResult(
            deleted_generation_identity_sha256s=tuple(sorted(deleted_generation_identities)),
            deleted_object_sha256s=tuple(sorted(deleted_objects)),
            retained_generation_identity_sha256s=tuple(
                sorted(header.generation_identity_sha256 for header in retained_headers)
            ),
            retained_planning_generation_ids=tuple(
                sorted({header.planning_generation_id for header in retained_headers})
            ),
        )

    def existing_generation_logical_bytes(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        root_descriptor: int,
        budget: PlanningStoreBudget,
    ) -> int:
        """Return exact existing bytes for aggregate-capacity admission.

        A pristine empty root is the only pre-lock state accepted as zero.  An
        initialized root must already contain the complete store layout and is
        measured while its existing exact lock is held.  The supplied root
        descriptor is the descriptor already admitted by ``CapacityRoot``;
        accepting a path-only alias here would sever that authority chain.
        """

        if not isinstance(request, SuccessorPlanningRequest):
            raise SuccessorPlanningStoreError("request must be a SuccessorPlanningRequest")
        generation_id = _require_safe_token(
            planning_generation_id,
            field_name="planning_generation_id",
        )
        if not isinstance(budget, PlanningStoreBudget):
            raise SuccessorPlanningStoreError("budget must be a PlanningStoreBudget")
        root_before = self._require_capacity_root_descriptor(root_descriptor)
        root_entries = self._directory_entry_names(
            root_descriptor,
            label="planning capacity root",
        )
        if not root_entries:
            self._admit_current_call(budget)
            self._require_unchanged_capacity_root_descriptor(
                root_descriptor,
                root_before,
            )
            return 0

        self._require_complete_measurement_layout_at(root_descriptor, root_entries)
        with self._exclusive_store_lock(initialize_layout=False):
            self._require_capacity_root_descriptor(root_descriptor)
            self._require_request_and_budget(request, generation_id, budget)
            objects_descriptor = self._open_directory_at(
                root_descriptor,
                self.objects_root.name,
                label="planning objects directory",
            )
            generations_descriptor = self._open_directory_at(
                root_descriptor,
                self.generations_root.name,
                label="planning generations directory",
            )
            objects_before = os.fstat(objects_descriptor)
            generations_before = os.fstat(generations_descriptor)
            object_directory_descriptors: dict[str, int] = {}
            generation_descriptor = -1
            try:
                for kind in sorted(_OBJECT_KINDS):
                    object_directory_descriptors[kind] = self._open_directory_at(
                        objects_descriptor,
                        kind,
                        label=f"{kind} object directory",
                    )
                generation_name = self.generation_path(request, generation_id).name
                try:
                    os.stat(
                        generation_name,
                        dir_fd=generations_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    partial_prefix = f".{generation_name}."
                    if any(
                        name.startswith(partial_prefix)
                        for name in self._directory_entry_names(
                            generations_descriptor,
                            label="planning generations directory",
                        )
                    ):
                        raise SuccessorPlanningStoreError(
                            "planning generation has unverified partial state"
                        ) from None
                    self._assert_locked_identity()
                    self._require_capacity_root_descriptor(root_descriptor)
                    for kind, descriptor in object_directory_descriptors.items():
                        opened = os.fstat(descriptor)
                        self._require_same_named_directory_at(
                            objects_descriptor,
                            kind,
                            opened,
                            os.fstat(descriptor),
                            label=f"{kind} object directory",
                        )
                    self._require_same_named_directory_at(
                        root_descriptor,
                        self.objects_root.name,
                        objects_before,
                        os.fstat(objects_descriptor),
                        label="planning objects directory",
                    )
                    self._require_same_named_directory_at(
                        root_descriptor,
                        self.generations_root.name,
                        generations_before,
                        os.fstat(generations_descriptor),
                        label="planning generations directory",
                    )
                    return 0
                generation_descriptor = self._open_directory_at(
                    generations_descriptor,
                    generation_name,
                    label="planning generation",
                )
                generation_before = os.fstat(generation_descriptor)
                state = self._load_verified_state_from_open_generation(
                    request,
                    generation_id,
                    generation=self.generation_path(request, generation_id),
                    generation_descriptor=generation_descriptor,
                    generation_before=generation_before,
                    budget=budget,
                    object_directory_descriptors=object_directory_descriptors,
                )
                self._assert_locked_identity()
                self._require_capacity_root_descriptor(root_descriptor)
                self._require_same_named_directory_at(
                    generations_descriptor,
                    generation_name,
                    generation_before,
                    os.fstat(generation_descriptor),
                    label="planning generation",
                )
                for kind, descriptor in object_directory_descriptors.items():
                    opened = os.fstat(descriptor)
                    self._require_same_named_directory_at(
                        objects_descriptor,
                        kind,
                        opened,
                        os.fstat(descriptor),
                        label=f"{kind} object directory",
                    )
                self._require_same_named_directory_at(
                    root_descriptor,
                    self.objects_root.name,
                    objects_before,
                    os.fstat(objects_descriptor),
                    label="planning objects directory",
                )
                self._require_same_named_directory_at(
                    root_descriptor,
                    self.generations_root.name,
                    generations_before,
                    os.fstat(generations_descriptor),
                    label="planning generations directory",
                )
                return state.logical_bytes
            finally:
                if generation_descriptor >= 0:
                    os.close(generation_descriptor)
                for descriptor in object_directory_descriptors.values():
                    os.close(descriptor)
                os.close(generations_descriptor)
                os.close(objects_descriptor)

    @_exclusive_operation
    def read_committed_member_bytes(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        call_identity_sha256: str,
        member_identity_sha256: str,
        max_bytes: int,
        budget: PlanningStoreBudget,
    ) -> bytes:
        """Copy one exact committed member while its generation remains locked."""

        self._require_request_and_budget(request, planning_generation_id, budget)
        call_identity = _require_sha256(
            call_identity_sha256,
            field_name="committed call identity",
        )
        member_identity = _require_sha256(
            member_identity_sha256,
            field_name="committed member identity",
        )
        byte_limit = _require_nonnegative_int(max_bytes, field_name="member max_bytes")
        if byte_limit > budget.artifact_max_bytes:
            raise OSError(errno.ENOSPC, "member max_bytes exceeds artifact_max_bytes")
        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        snapshot = self._load_and_verify_locked(request, generation_id, budget=budget)
        matching_calls = [
            call for call in snapshot.committed_calls if call.identity_sha256 == call_identity
        ]
        if len(matching_calls) != 1:
            raise SuccessorPlanningStoreError(
                "committed member call identity is not exact generation authority"
            )
        matching_members = [
            member
            for member in matching_calls[0].members
            if member.member.identity_sha256 == member_identity
        ]
        if len(matching_members) != 1:
            raise SuccessorPlanningStoreError(
                "committed member identity is not exact call authority"
            )
        member = matching_members[0]
        reference = _ObjectReference(
            kind="member",
            sha256=member.artifact_sha256,
            byte_count=member.artifact_bytes,
            domain_sha256=member.object_domain_sha256,
        )
        if reference.byte_count > byte_limit:
            raise OSError(errno.ENOSPC, "committed member exceeds max_bytes")
        encoded = self._read_regular_exact(
            self._object_path(reference),
            max_bytes=byte_limit,
            expected_bytes=reference.byte_count,
            label="committed planning member",
        )
        if _raw_sha256(encoded) != reference.sha256:
            raise SuccessorPlanningStoreError("committed planning member digest differs")
        self._assert_locked_identity()
        return encoded

    @_exclusive_operation
    def export_driver_context(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        destination: Path,
        planning_database_max_bytes: int,
        budget: PlanningStoreBudget,
    ) -> PlanningGenerationContextExport:
        """Twice verify and export every opaque input for one driver operation."""

        self._require_request_and_budget(request, planning_generation_id, budget)
        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        database_max_bytes = _require_positive_signed63(
            planning_database_max_bytes,
            field_name="planning_database_max_bytes",
        )
        snapshot = self._load_and_verify_locked(request, generation_id, budget=budget)
        if (
            snapshot.planning_database_bytes is not None
            and snapshot.planning_database_bytes > database_max_bytes
        ):
            raise OSError(
                errno.ENOSPC,
                "planning driver input database exceeds planning_database_max_bytes",
            )
        committed_member_bytes: list[tuple[str, str, bytes]] = []
        exported_bytes = 0
        for call in snapshot.committed_calls:
            for member in call.members:
                if member.artifact_bytes > budget.artifact_max_bytes:
                    raise OSError(errno.ENOSPC, "committed member exceeds artifact_max_bytes")
                exported_bytes += member.artifact_bytes
                if exported_bytes > budget.generation_max_bytes:
                    raise OSError(
                        errno.ENOSPC,
                        "planning driver context export exceeds generation_max_bytes",
                    )
                reference = _ObjectReference(
                    kind="member",
                    sha256=member.artifact_sha256,
                    byte_count=member.artifact_bytes,
                    domain_sha256=member.object_domain_sha256,
                )
                encoded = self._read_regular_exact(
                    self._object_path(reference),
                    max_bytes=budget.artifact_max_bytes,
                    expected_bytes=reference.byte_count,
                    label="committed planning member",
                )
                if _raw_sha256(encoded) != reference.sha256:
                    raise SuccessorPlanningStoreError("committed planning member digest differs")
                committed_member_bytes.append(
                    (call.identity_sha256, member.member.identity_sha256, encoded)
                )
        planning_database: PlanningDatabaseSource | None = None
        planning_database_identity: tuple[int, int] | None = None
        if snapshot.planning_database_sha256 is not None:
            assert snapshot.planning_database_bytes is not None
            assert snapshot.planning_database_schema_sha256 is not None
            exported_bytes += snapshot.planning_database_bytes
            if exported_bytes > budget.generation_max_bytes:
                raise OSError(
                    errno.ENOSPC,
                    "planning driver context export exceeds generation_max_bytes",
                )
            planning_database, planning_database_identity = self._copy_current_database_locked(
                expected_sha256=snapshot.planning_database_sha256,
                expected_bytes=snapshot.planning_database_bytes,
                expected_schema=snapshot.planning_database_schema_sha256,
                destination=destination,
                budget=budget,
            )
        try:
            self._assert_locked_identity()
            if self._load_and_verify_locked(request, generation_id, budget=budget) != snapshot:
                raise SuccessorPlanningStoreError(
                    "planning generation changed during driver context export"
                )
        except Exception:
            if planning_database is not None and planning_database_identity is not None:
                try:
                    self._remove_exact_driver_context_database_locked(
                        planning_database,
                        expected_identity=planning_database_identity,
                    )
                except Exception as cleanup_error:
                    raise SuccessorPlanningStoreError(
                        "planning driver context export failed and exact database cleanup "
                        "was refused"
                    ) from cleanup_error
            raise
        return PlanningGenerationContextExport(
            snapshot=snapshot,
            committed_member_bytes=tuple(committed_member_bytes),
            planning_database=planning_database,
        )

    @_exclusive_operation
    def copy_current_database(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        *,
        planning_database_sha256: str,
        planning_database_bytes: int,
        planning_database_schema_sha256: str,
        destination: Path,
        budget: PlanningStoreBudget,
    ) -> PlanningDatabaseSource:
        """Publish one verified current database copy without exposing a store path."""

        self._require_request_and_budget(request, planning_generation_id, budget)
        expected_sha256 = _require_sha256(
            planning_database_sha256,
            field_name="planning database sha256",
        )
        expected_bytes = _require_positive_int(
            planning_database_bytes,
            field_name="planning database bytes",
        )
        expected_schema = _require_sha256(
            planning_database_schema_sha256,
            field_name="planning database schema sha256",
        )
        generation_id = _require_safe_token(
            planning_generation_id, field_name="planning_generation_id"
        )
        snapshot = self._load_and_verify_locked(request, generation_id, budget=budget)
        if (
            snapshot.planning_database_sha256 != expected_sha256
            or snapshot.planning_database_bytes != expected_bytes
            or snapshot.planning_database_schema_sha256 != expected_schema
        ):
            raise SuccessorPlanningStoreError(
                "current planning database differs from supplied snapshot authority"
            )
        planning_database, _published_identity = self._copy_current_database_locked(
            expected_sha256=expected_sha256,
            expected_bytes=expected_bytes,
            expected_schema=expected_schema,
            destination=destination,
            budget=budget,
        )
        return planning_database

    def _copy_current_database_locked(
        self,
        *,
        expected_sha256: str,
        expected_bytes: int,
        expected_schema: str,
        destination: Path,
        budget: PlanningStoreBudget,
    ) -> tuple[PlanningDatabaseSource, tuple[int, int]]:
        destination_path = Path(destination)
        if not destination_path.is_absolute() or destination_path.name in {"", ".", ".."}:
            raise SuccessorPlanningStoreError(
                "planning database destination must be an absolute file path"
            )
        destination_path = Path(os.path.abspath(destination_path))
        self._reject_public_overlap(destination_path)
        self._reject_store_overlap(destination_path)
        if expected_bytes > budget.artifact_max_bytes:
            raise OSError(errno.ENOSPC, "planning database exceeds artifact_max_bytes")
        database_reference = _ObjectReference.create(
            kind="database",
            sha256=expected_sha256,
            byte_count=expected_bytes,
        )
        database_path = self._object_path(database_reference)
        source_descriptor, source_before = self._open_absolute_regular(
            database_path,
            label="current planning database",
        )
        destination_parent_descriptor = self._open_directory(
            destination_path.parent,
            label="planning database destination parent",
        )
        destination_parent_before = os.fstat(destination_parent_descriptor)
        temporary_name = f".{destination_path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        temporary_descriptor = -1
        published_identity: tuple[int, int] | None = None
        try:
            filesystem = os.fstatvfs(destination_parent_descriptor)
            available = filesystem.f_bavail * filesystem.f_frsize
            if available < expected_bytes + budget.minimum_free_bytes:
                raise OSError(
                    errno.ENOSPC,
                    "insufficient destination capacity for planning database copy",
                )
            try:
                os.stat(
                    destination_path.name,
                    dir_fd=destination_parent_descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                pass
            else:
                raise SuccessorPlanningStoreError("planning database destination already exists")
            self._assert_locked_identity()
            self._require_same_open_directory(
                destination_path.parent,
                destination_parent_before,
                os.fstat(destination_parent_descriptor),
                label="planning database destination parent",
            )
            temporary_descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._nofollow_flags(),
                0o600,
                dir_fd=destination_parent_descriptor,
            )
            hasher = hashlib.sha256()
            observed_bytes = 0
            while True:
                chunk = os.read(source_descriptor, 1024 * 1024)
                if not chunk:
                    break
                observed_bytes += len(chunk)
                if observed_bytes > expected_bytes:
                    raise SuccessorPlanningStoreError(
                        "current planning database grew while copying"
                    )
                hasher.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(temporary_descriptor, view)
                    if written <= 0:
                        raise SuccessorPlanningStoreError(
                            "planning database copy made no write progress"
                        )
                    view = view[written:]
            if observed_bytes != expected_bytes or hasher.hexdigest() != expected_sha256:
                raise SuccessorPlanningStoreError(
                    "current planning database digest or byte count differs"
                )
            os.fsync(temporary_descriptor)
            source_after = os.fstat(source_descriptor)
            self._require_same_open_file(
                database_path,
                source_before,
                source_after,
                label="current planning database",
            )
            self._assert_locked_identity()
            self._require_same_open_directory(
                destination_path.parent,
                destination_parent_before,
                os.fstat(destination_parent_descriptor),
                label="planning database destination parent",
            )
            os.link(
                temporary_name,
                destination_path.name,
                src_dir_fd=destination_parent_descriptor,
                dst_dir_fd=destination_parent_descriptor,
                follow_symlinks=False,
            )
            published_identity = self._verify_published_regular_at(
                destination_parent_descriptor,
                destination_path.name,
                temporary_descriptor,
                expected_bytes=expected_bytes,
                expected_sha256=expected_sha256,
                expected_mode=0o600,
                label="planning database destination",
            )
            os.fsync(destination_parent_descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                destination_path.parent,
                destination_parent_before,
                os.fstat(destination_parent_descriptor),
                label="planning database destination parent",
            )
            final_identity = self._verify_published_regular_at(
                destination_parent_descriptor,
                destination_path.name,
                temporary_descriptor,
                expected_bytes=expected_bytes,
                expected_sha256=expected_sha256,
                expected_mode=0o600,
                label="planning database destination",
            )
            if final_identity != published_identity:
                raise SuccessorPlanningStoreError(
                    "planning database destination identity changed after publication"
                )
        except OSError as exc:
            raise SuccessorPlanningStoreError(
                "planning database copy cannot be published safely"
            ) from exc
        finally:
            if temporary_descriptor >= 0:
                os.close(temporary_descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=destination_parent_descriptor)
            os.close(destination_parent_descriptor)
            os.close(source_descriptor)
        if published_identity is None:
            raise SuccessorPlanningStoreError("planning database destination was not published")
        return (
            PlanningDatabaseSource(
                artifact=PlanningArtifactSource(
                    path=destination_path,
                    sha256=expected_sha256,
                    byte_count=expected_bytes,
                ),
                schema_sha256=expected_schema,
            ),
            published_identity,
        )

    def _remove_exact_driver_context_database_locked(
        self,
        planning_database: PlanningDatabaseSource,
        *,
        expected_identity: tuple[int, int],
    ) -> None:
        """Remove only the exact private database inode published by this export."""

        destination_path = planning_database.artifact.path
        parent_descriptor = self._open_directory(
            destination_path.parent,
            label="planning driver context cleanup parent",
        )
        parent_before = os.fstat(parent_descriptor)
        database_descriptor = -1
        try:
            database_descriptor = os.open(
                destination_path.name,
                os.O_RDONLY | self._nofollow_flags(),
                dir_fd=parent_descriptor,
            )
            observed_identity = self._verify_published_regular_at(
                parent_descriptor,
                destination_path.name,
                database_descriptor,
                expected_bytes=planning_database.artifact.byte_count,
                expected_sha256=planning_database.artifact.sha256,
                expected_mode=0o600,
                label="planning driver context cleanup database",
            )
            if observed_identity != expected_identity:
                raise SuccessorPlanningStoreError(
                    "planning driver context cleanup database is not the exported inode"
                )
            self._assert_locked_identity()
            self._require_same_open_directory(
                destination_path.parent,
                parent_before,
                os.fstat(parent_descriptor),
                label="planning driver context cleanup parent",
            )
            os.unlink(destination_path.name, dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                destination_path.parent,
                parent_before,
                os.fstat(parent_descriptor),
                label="planning driver context cleanup parent",
            )
        except OSError as exc:
            raise SuccessorPlanningStoreError(
                "planning driver context cleanup cannot remove the exact exported database"
            ) from exc
        finally:
            if database_descriptor >= 0:
                os.close(database_descriptor)
            os.close(parent_descriptor)

    def _load_state(
        self,
        request: SuccessorPlanningRequest,
        generation_id: str,
        *,
        budget: PlanningStoreBudget,
    ) -> _VerifiedPlanningState:
        return self._load_verified_state_locked(request, generation_id, budget=budget)

    def _load_and_verify_locked(
        self,
        request: SuccessorPlanningRequest,
        generation_id: str,
        *,
        budget: PlanningStoreBudget,
        expected_generation_stat: os.stat_result | None = None,
    ) -> PlanningGenerationSnapshot:
        state = self._load_verified_state_locked(
            request,
            generation_id,
            budget=budget,
            expected_generation_stat=expected_generation_stat,
        )
        return state.snapshot

    def _load_verified_state_locked(
        self,
        request: SuccessorPlanningRequest,
        generation_id: str,
        *,
        budget: PlanningStoreBudget,
        expected_generation_stat: os.stat_result | None = None,
    ) -> _VerifiedPlanningState:
        self._admit_current_call(budget)
        generation = self.generation_path(request, generation_id)
        self._require_private_directory(generation, label="planning generation")
        generation_descriptor = self._open_directory(
            generation,
            label="planning generation",
        )
        generation_before = os.fstat(generation_descriptor)
        try:
            if expected_generation_stat is not None and self._directory_identity(
                generation_before
            ) != self._directory_identity(expected_generation_stat):
                raise SuccessorPlanningStoreError(
                    "planning generation differs from its mutation authority"
                )
            return self._load_verified_state_from_open_generation(
                request,
                generation_id,
                generation=generation,
                generation_descriptor=generation_descriptor,
                generation_before=generation_before,
                budget=budget,
            )
        finally:
            os.close(generation_descriptor)

    def _load_verified_state_from_open_generation(
        self,
        request: SuccessorPlanningRequest,
        generation_id: str,
        *,
        generation: Path,
        generation_descriptor: int,
        generation_before: os.stat_result,
        budget: PlanningStoreBudget,
        object_directory_descriptors: Mapping[str, int] | None = None,
    ) -> _VerifiedPlanningState:
        request_bytes, _request_stat = self._read_control_at(
            generation_descriptor,
            _REQUEST_NAME,
            budget=budget,
            label="planning request",
        )
        if request_bytes != _canonical_bytes(request.to_dict()):
            raise SuccessorPlanningStoreError(
                "planning generation request differs from the exact resume request"
            )
        checkpoint_bytes, checkpoint_stat = self._read_control_at(
            generation_descriptor,
            _CHECKPOINT_NAME,
            budget=budget,
            label="planning checkpoint",
        )
        checkpoint = self._decode_checkpoint(checkpoint_bytes)
        generation_identity = _generation_identity(request.identity_sha256, generation_id)
        expected_header = {
            "planning_request_sha256": request.identity_sha256,
            "planning_generation_id": generation_id,
            "generation_identity_sha256": generation_identity,
            "request_bytes": len(request_bytes),
        }
        for field_name, expected in expected_header.items():
            if checkpoint[field_name] != expected:
                raise SuccessorPlanningStoreError(
                    f"planning checkpoint {field_name} differs from exact generation authority"
                )
        try:
            phase = PlanningGenerationPhase(cast("str", checkpoint["phase"]))
        except ValueError as exc:
            raise SuccessorPlanningStoreError("planning checkpoint phase is invalid") from exc
        raw_active_wave = checkpoint["active_wave"]
        if raw_active_wave is None:
            active_wave = None
        elif isinstance(raw_active_wave, Mapping):
            active_wave = PlanningWaveAdmission.from_dict(
                cast("Mapping[str, object]", raw_active_wave)
            )
        else:
            raise SuccessorPlanningStoreError("active wave admission is invalid")

        committed_calls: list[CommittedPlanningCall] = []
        seen_call_keys: set[str] = set()
        seen_member_ids: set[str] = set()
        seen_member_identities: set[str] = set()
        current_database_record: dict[str, object] | None = None
        for expected_ordinal, raw_call in enumerate(
            cast("list[dict[str, object]]", checkpoint["committed_calls"])
        ):
            call = self._verify_call(
                raw_call,
                expected_ordinal=expected_ordinal,
                budget=budget,
                object_directory_descriptors=object_directory_descriptors,
            )
            key = call.sealed_dispatch.identity_sha256
            if key in seen_call_keys:
                raise SuccessorPlanningStoreError("planning checkpoint contains duplicate calls")
            seen_call_keys.add(key)
            call_member_ids = {member.member.member_id for member in call.members}
            call_member_identities = {member.member.identity_sha256 for member in call.members}
            if (
                len(call_member_ids) != len(call.members)
                or len(call_member_identities) != len(call.members)
                or seen_member_ids & call_member_ids
                or seen_member_identities & call_member_identities
            ):
                raise SuccessorPlanningStoreError(
                    "planning generation members must be globally unique"
                )
            seen_member_ids.update(call_member_ids)
            seen_member_identities.update(call_member_identities)
            committed_calls.append(call)
            current_database_record = cast("dict[str, object]", raw_call["database"])
        if checkpoint["current_database"] != current_database_record:
            raise SuccessorPlanningStoreError(
                "planning checkpoint current database is not the last committed call boundary"
            )

        committed_waves: list[SuccessorPlanningWave] = []
        committed_wave_admissions: list[PlanningWaveAdmission] = []
        committed_wave_authorities: list[CommittedPlanningWaveAuthority] = []
        raw_waves = cast("list[dict[str, object]]", checkpoint["committed_waves"])
        for expected_index, raw_wave in enumerate(raw_waves):
            wave, admission, authority = self._verify_wave(
                raw_wave,
                request=request,
                planning_generation_id=generation_id,
                expected_index=expected_index,
                calls=tuple(committed_calls),
                budget=budget,
                object_directory_descriptors=object_directory_descriptors,
            )
            if expected_index == 1 and (
                not committed_waves
                or wave.parent_wave_identity_sha256 != committed_waves[0].identity_sha256
            ):
                raise SuccessorPlanningStoreError("stored wave 1 parent differs")
            committed_waves.append(wave)
            committed_wave_admissions.append(admission)
            committed_wave_authorities.append(authority)
        expected_wave_count = {
            PlanningGenerationPhase.BUILDING: 0,
            PlanningGenerationPhase.WAVE_0_COMMITTED: 1,
            PlanningGenerationPhase.WAVE_1_COMMITTED: 2,
            PlanningGenerationPhase.SEALED: 2,
        }[phase]
        if len(committed_waves) != expected_wave_count:
            raise SuccessorPlanningStoreError("planning phase and wave inventory differ")
        if active_wave is not None:
            expected_active_index = {
                PlanningGenerationPhase.BUILDING: 0,
                PlanningGenerationPhase.WAVE_0_COMMITTED: 1,
                PlanningGenerationPhase.WAVE_1_COMMITTED: None,
                PlanningGenerationPhase.SEALED: None,
            }[phase]
            if active_wave.wave_index != expected_active_index:
                raise SuccessorPlanningStoreError(
                    "active wave admission is incompatible with the planning phase"
                )
            if active_wave.wave_index == 0:
                request_scopes = tuple(
                    sorted(
                        request.requested_planning_scopes,
                        key=lambda scope: scope.identity_sha256,
                    )
                )
                if active_wave.requested_route_scopes != request_scopes:
                    raise SuccessorPlanningStoreError(
                        "active wave 0 admission differs from the exact request"
                    )
            elif (
                not committed_waves
                or active_wave.parent_wave_identity_sha256 != committed_waves[0].identity_sha256
            ):
                raise SuccessorPlanningStoreError(
                    "active wave 1 admission parent authority differs"
                )
            else:
                self._require_wave_1_dispatch_dependencies(
                    active_wave,
                    committed_calls,
                )

        request_scopes = tuple(
            sorted(
                request.requested_planning_scopes,
                key=lambda scope: scope.identity_sha256,
            )
        )
        if (
            committed_wave_admissions
            and committed_wave_admissions[0].requested_route_scopes != request_scopes
        ):
            raise SuccessorPlanningStoreError(
                "committed wave 0 admission differs from the exact request"
            )

        for wave_index in (0, 1):
            wave_calls = tuple(call for call in committed_calls if call.wave_index == wave_index)
            if wave_index < len(committed_wave_admissions):
                admission = committed_wave_admissions[wave_index]
                require_complete_program = True
            elif active_wave is not None and wave_index == active_wave.wave_index:
                admission = active_wave
                require_complete_program = False
            else:
                if not wave_calls:
                    continue
                raise SuccessorPlanningStoreError(
                    "planning call exists without a durable wave admission"
                )
            admitted_dispatches = admission.sealed_dispatches
            observed_dispatches = tuple(call.sealed_dispatch for call in wave_calls)
            expected_dispatches = (
                admitted_dispatches
                if require_complete_program
                else admitted_dispatches[: len(observed_dispatches)]
            )
            if observed_dispatches != expected_dispatches:
                raise SuccessorPlanningStoreError(
                    "planning calls differ from their durable dispatch program"
                )
            scope_by_id = {
                scope.identity_sha256: scope for scope in admission.requested_route_scopes
            }
            for call in wave_calls:
                expected_scopes = tuple(
                    scope_by_id[scope_id]
                    for scope_id in call.sealed_dispatch.requested_scope_identity_sha256s
                )
                if call.requested_route_scopes != expected_scopes:
                    raise SuccessorPlanningStoreError(
                        "planning call scope bodies differ from durable admission"
                    )

        manifest: PlanningGenerationManifest | None = None
        manifest_file_bytes = 0
        sealed_fields = (
            "member_inventory",
            "wave_inventory",
            "sealed_dispatch_inventory",
            "manifest",
        )
        if phase is PlanningGenerationPhase.SEALED:
            if any(checkpoint[field_name] is None for field_name in sealed_fields):
                raise SuccessorPlanningStoreError("sealed planning checkpoint is incomplete")
            manifest_bytes, _manifest_stat = self._read_control_at(
                generation_descriptor,
                _MANIFEST_NAME,
                budget=budget,
                label="planning manifest",
            )
            manifest_file_bytes = len(manifest_bytes)
            manifest_record = cast("dict[str, object]", checkpoint["manifest"])
            manifest_ref = _ObjectReference.from_dict(
                cast("Mapping[str, object]", manifest_record["artifact"])
            )
            if manifest_ref.kind != "manifest":
                raise SuccessorPlanningStoreError("manifest object has the wrong content domain")
            object_bytes = self._read_verified_object_bytes(
                manifest_ref,
                budget=budget,
                label="planning manifest object",
                object_directory_descriptors=object_directory_descriptors,
            )
            if object_bytes != manifest_bytes:
                raise SuccessorPlanningStoreError("manifest file and object bytes differ")
            try:
                manifest = PlanningGenerationManifest.from_canonical_bytes(manifest_bytes)
            except SuccessorPlanningGenerationContractError as exc:
                raise SuccessorPlanningStoreError("stored planning manifest is invalid") from exc
            if (
                manifest.request != request
                or manifest.artifact_identity.planning_generation_id != generation_id
                or manifest.identity_sha256 != manifest_record["identity_sha256"]
                or manifest.artifact_identity.planning_manifest_sha256
                != manifest_record["body_sha256"]
                or manifest.waves != tuple(committed_waves)
            ):
                raise SuccessorPlanningStoreError("stored planning manifest authority differs")
            self._require_manifest_admission_program(
                manifest,
                tuple(committed_wave_admissions),
            )
            committed_members = tuple(
                sorted(
                    (member.member for call in committed_calls for member in call.members),
                    key=lambda item: item.identity_sha256,
                )
            )
            if committed_members != manifest.members:
                raise SuccessorPlanningStoreError(
                    "stored planning manifest member inventory differs"
                )
            inventories = {
                "member_inventory": _canonical_bytes(
                    [member.to_dict() for member in manifest.members]
                ),
                "wave_inventory": _canonical_bytes([wave.to_dict() for wave in manifest.waves]),
                "sealed_dispatch_inventory": _canonical_bytes(
                    [dispatch.to_dict() for dispatch in manifest.sealed_dispatches]
                ),
            }
            expected_kinds = {
                "member_inventory": "member_inventory",
                "wave_inventory": "wave_inventory",
                "sealed_dispatch_inventory": "dispatch_inventory",
            }
            for field_name, expected_bytes in inventories.items():
                reference = _ObjectReference.from_dict(
                    cast("Mapping[str, object]", checkpoint[field_name])
                )
                if reference.kind != expected_kinds[field_name]:
                    raise SuccessorPlanningStoreError(f"{field_name} has the wrong content domain")
                observed = self._read_verified_object_bytes(
                    reference,
                    budget=budget,
                    label=field_name,
                    object_directory_descriptors=object_directory_descriptors,
                )
                if observed != expected_bytes:
                    raise SuccessorPlanningStoreError(f"{field_name} bytes differ")
        else:
            if any(checkpoint[field_name] is not None for field_name in sealed_fields):
                raise SuccessorPlanningStoreError(
                    "unsealed planning checkpoint contains final manifest authority"
                )
            if self._entry_exists_at(generation_descriptor, _MANIFEST_NAME):
                staged_manifest_bytes, _staged_manifest_stat = self._read_control_at(
                    generation_descriptor,
                    _MANIFEST_NAME,
                    budget=budget,
                    label="staged planning manifest",
                )
                manifest_file_bytes = len(staged_manifest_bytes)
                try:
                    staged_manifest = PlanningGenerationManifest.from_canonical_bytes(
                        staged_manifest_bytes
                    )
                except SuccessorPlanningGenerationContractError as exc:
                    raise SuccessorPlanningStoreError(
                        "staged planning manifest is invalid"
                    ) from exc
                committed_members = tuple(
                    sorted(
                        (member.member for call in committed_calls for member in call.members),
                        key=lambda item: item.identity_sha256,
                    )
                )
                if (
                    phase is not PlanningGenerationPhase.WAVE_1_COMMITTED
                    or staged_manifest.request != request
                    or staged_manifest.artifact_identity.planning_generation_id != generation_id
                    or staged_manifest.waves != tuple(committed_waves)
                    or staged_manifest.members != committed_members
                    or current_database_record is None
                ):
                    raise SuccessorPlanningStoreError(
                        "staged planning manifest differs from committed boundaries"
                    )
                self._require_manifest_admission_program(
                    staged_manifest,
                    tuple(committed_wave_admissions),
                )
                staged_database = _ObjectReference.from_dict(
                    cast("Mapping[str, object]", current_database_record["artifact"])
                )
                staged_identity = staged_manifest.artifact_identity
                if (
                    staged_database.sha256 != staged_identity.planning_database_sha256
                    or staged_database.byte_count != staged_identity.planning_database_bytes
                    or current_database_record["schema_sha256"]
                    != staged_identity.planning_database_schema_sha256
                ):
                    raise SuccessorPlanningStoreError(
                        "staged planning manifest database authority differs"
                    )

        manifest_present = self._entry_exists_at(generation_descriptor, _MANIFEST_NAME)
        self._validate_generation_layout_at(
            generation_descriptor,
            manifest_present=manifest_present,
        )
        logical_bytes = self._require_generation_bound(
            checkpoint,
            request_bytes=len(request_bytes),
            checkpoint_bytes=len(checkpoint_bytes),
            manifest_file_bytes=manifest_file_bytes,
            budget=budget,
        )
        self._require_disk_capacity(0, budget=budget)
        database_sha256: str | None = None
        database_bytes: int | None = None
        database_schema: str | None = None
        if current_database_record is not None:
            reference = _ObjectReference.from_dict(
                cast("Mapping[str, object]", current_database_record["artifact"])
            )
            database_sha256 = reference.sha256
            database_bytes = reference.byte_count
            database_schema = cast("str", current_database_record["schema_sha256"])
        self._require_same_named_file_at(
            generation_descriptor,
            _REQUEST_NAME,
            _request_stat,
            _request_stat,
            label="planning request",
        )
        self._require_same_named_file_at(
            generation_descriptor,
            _CHECKPOINT_NAME,
            checkpoint_stat,
            checkpoint_stat,
            label="planning checkpoint",
        )
        self._require_same_open_directory(
            generation,
            generation_before,
            os.fstat(generation_descriptor),
            label="planning generation",
        )
        snapshot = PlanningGenerationSnapshot(
            request=request,
            planning_generation_id=generation_id,
            generation_identity_sha256=generation_identity,
            phase=phase,
            revision=cast("int", checkpoint["revision"]),
            committed_calls=tuple(committed_calls),
            committed_waves=tuple(committed_waves),
            committed_wave_admissions=tuple(committed_wave_admissions),
            committed_wave_authorities=tuple(committed_wave_authorities),
            active_wave=active_wave,
            planning_database_sha256=database_sha256,
            planning_database_bytes=database_bytes,
            planning_database_schema_sha256=database_schema,
            manifest=manifest,
        )
        return _VerifiedPlanningState(
            snapshot=snapshot,
            checkpoint=checkpoint,
            generation_stat=generation_before,
            checkpoint_stat=checkpoint_stat,
            logical_bytes=logical_bytes,
        )

    def _verify_call(
        self,
        payload: Mapping[str, object],
        *,
        expected_ordinal: int,
        budget: PlanningStoreBudget,
        object_directory_descriptors: Mapping[str, int] | None = None,
    ) -> CommittedPlanningCall:
        expected = {
            "ordinal",
            "wave_index",
            "sealed_dispatch",
            "sealed_dispatch_identity_sha256",
            "requested_route_scopes",
            "members",
            "database",
            "call_identity_sha256",
        }
        if set(payload) != expected:
            raise SuccessorPlanningStoreError("committed planning call fields are invalid")
        ordinal = _require_nonnegative_int(payload["ordinal"], field_name="call ordinal")
        if ordinal != expected_ordinal:
            raise SuccessorPlanningStoreError("committed planning call ordinals are not contiguous")
        wave_index = _require_nonnegative_int(payload["wave_index"], field_name="call wave_index")
        if wave_index not in {0, 1}:
            raise SuccessorPlanningStoreError("call wave_index must be 0 or 1")
        try:
            dispatch = SealedProviderDispatch.from_dict(
                cast("Mapping[str, object]", payload["sealed_dispatch"])
            )
        except (TypeError, ValueError) as exc:
            raise SuccessorPlanningStoreError("committed sealed dispatch is invalid") from exc
        dispatch_identity = _require_sha256(
            payload["sealed_dispatch_identity_sha256"],
            field_name="sealed dispatch identity",
        )
        if dispatch.identity_sha256 != dispatch_identity:
            raise SuccessorPlanningStoreError("committed sealed dispatch identity differs")
        expected_phase = (
            PlanningDispatchPhase.PLANNING_WAVE_0
            if wave_index == 0
            else PlanningDispatchPhase.PLANNING_WAVE_1
        )
        if dispatch.phase is not expected_phase:
            raise SuccessorPlanningStoreError("committed sealed dispatch wave differs")
        raw_scopes = payload["requested_route_scopes"]
        if not isinstance(raw_scopes, list) or not raw_scopes:
            raise SuccessorPlanningStoreError("committed call scopes must be nonempty")
        try:
            requested_route_scopes = tuple(
                RequestedRouteScope.from_dict(cast("Mapping[str, object]", raw_scope))
                for raw_scope in raw_scopes
            )
        except (TypeError, ValueError) as exc:
            raise SuccessorPlanningStoreError("committed call scope is invalid") from exc
        if tuple(scope.identity_sha256 for scope in requested_route_scopes) != (
            dispatch.requested_scope_identity_sha256s
        ):
            raise SuccessorPlanningStoreError(
                "committed call scopes differ from its sealed dispatch"
            )
        if any(
            scope.endpoint_name != dispatch.endpoint_name
            or scope.parameters != dispatch.parameters
            or scope.route_id != dispatch.staging_route_ids[position]
            for position, scope in enumerate(requested_route_scopes)
        ):
            raise SuccessorPlanningStoreError(
                "committed call scope bodies differ from its sealed dispatch"
            )
        raw_members = payload["members"]
        if not isinstance(raw_members, list) or not raw_members:
            raise SuccessorPlanningStoreError("committed call members must be nonempty")
        members: list[CommittedPlanningMember] = []
        for raw_member in raw_members:
            if not isinstance(raw_member, Mapping) or set(raw_member) != {
                "member",
                "member_identity_sha256",
                "receipt_sha256",
                "artifact",
            }:
                raise SuccessorPlanningStoreError("committed planning member fields are invalid")
            member_payload = cast("Mapping[str, object]", raw_member)
            try:
                member = PlanningDataMember.from_dict(
                    cast("Mapping[str, object]", member_payload["member"])
                )
            except SuccessorPlanningGenerationContractError as exc:
                raise SuccessorPlanningStoreError("committed planning member is invalid") from exc
            if (
                member.identity_sha256 != member_payload["member_identity_sha256"]
                or member.wave_index != wave_index
                or member.producing_scope_sha256 not in dispatch.requested_scope_identity_sha256s
            ):
                raise SuccessorPlanningStoreError("committed planning member authority differs")
            receipt = _require_sha256(
                member_payload["receipt_sha256"], field_name="planning member receipt"
            )
            reference = _ObjectReference.from_dict(
                cast("Mapping[str, object]", member_payload["artifact"])
            )
            if reference.kind != "member" or reference.sha256 != member.content_sha256:
                raise SuccessorPlanningStoreError("planning member object authority differs")
            self._verify_object(
                reference,
                budget=budget,
                label="planning member artifact",
                object_directory_descriptors=object_directory_descriptors,
            )
            members.append(
                CommittedPlanningMember(
                    member=member,
                    receipt_sha256=receipt,
                    artifact_sha256=reference.sha256,
                    artifact_bytes=reference.byte_count,
                    object_domain_sha256=reference.domain_sha256,
                )
            )
        if tuple(item.member.identity_sha256 for item in members) != tuple(
            sorted(item.member.identity_sha256 for item in members)
        ):
            raise SuccessorPlanningStoreError("committed call members are not canonical")
        if {item.member.producing_scope_sha256 for item in members} != set(
            dispatch.requested_scope_identity_sha256s
        ):
            raise SuccessorPlanningStoreError(
                "committed call members do not cover every sealed dispatch scope"
            )
        database = payload["database"]
        if not isinstance(database, Mapping) or set(database) != {"artifact", "schema_sha256"}:
            raise SuccessorPlanningStoreError("committed call database fields are invalid")
        database_payload = cast("Mapping[str, object]", database)
        database_reference = _ObjectReference.from_dict(
            cast("Mapping[str, object]", database_payload["artifact"])
        )
        if database_reference.kind != "database" or database_reference.byte_count < 1:
            raise SuccessorPlanningStoreError("planning database object authority is invalid")
        self._verify_object(
            database_reference,
            budget=budget,
            label="planning database snapshot",
            object_directory_descriptors=object_directory_descriptors,
        )
        database_schema = _require_sha256(
            database_payload["schema_sha256"], field_name="planning database schema"
        )
        body = dict(payload)
        identity = _require_sha256(
            body.pop("call_identity_sha256"), field_name="planning call identity"
        )
        if identity != canonical_planning_sha256(
            {"domain": "nbadb.successor-planning-store.call.v2", **body}
        ):
            raise SuccessorPlanningStoreError("planning call identity differs")
        return CommittedPlanningCall(
            ordinal=ordinal,
            wave_index=wave_index,
            sealed_dispatch=dispatch,
            requested_route_scopes=requested_route_scopes,
            members=tuple(members),
            planning_database_sha256=database_reference.sha256,
            planning_database_bytes=database_reference.byte_count,
            planning_database_schema_sha256=database_schema,
            identity_sha256=identity,
        )

    def _verify_wave(
        self,
        payload: Mapping[str, object],
        *,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        expected_index: int,
        calls: tuple[CommittedPlanningCall, ...],
        budget: PlanningStoreBudget,
        object_directory_descriptors: Mapping[str, int] | None = None,
    ) -> tuple[
        SuccessorPlanningWave,
        PlanningWaveAdmission,
        CommittedPlanningWaveAuthority,
    ]:
        if set(payload) != {
            "wave",
            "wave_identity_sha256",
            "admission",
            "artifact",
            "database",
            "call_identity_sha256s",
            "private_generation_identity",
            "completion_receipt",
        }:
            raise SuccessorPlanningStoreError("committed planning wave fields are invalid")
        try:
            wave = SuccessorPlanningWave.from_dict(cast("Mapping[str, object]", payload["wave"]))
        except SuccessorPlanningGenerationContractError as exc:
            raise SuccessorPlanningStoreError("committed planning wave is invalid") from exc
        if (
            wave.wave_index != expected_index
            or wave.identity_sha256 != payload["wave_identity_sha256"]
        ):
            raise SuccessorPlanningStoreError("committed wave identity differs")
        try:
            admission = PlanningWaveAdmission.from_dict(
                cast("Mapping[str, object]", payload["admission"])
            )
        except (TypeError, ValueError) as exc:
            raise SuccessorPlanningStoreError("committed wave admission is invalid") from exc
        if not self._admission_matches_wave(admission, wave):
            raise SuccessorPlanningStoreError("committed wave differs from its persisted admission")
        if expected_index == 1:
            self._require_wave_1_dispatch_dependencies(admission, calls)
        reference = _ObjectReference.from_dict(cast("Mapping[str, object]", payload["artifact"]))
        if reference.kind != "wave":
            raise SuccessorPlanningStoreError("wave object has the wrong content domain")
        if self._read_verified_object_bytes(
            reference,
            budget=budget,
            label="planning wave manifest",
            object_directory_descriptors=object_directory_descriptors,
        ) != _canonical_bytes(wave.to_dict()):
            raise SuccessorPlanningStoreError("planning wave artifact bytes differ")
        wave_calls = tuple(call for call in calls if call.wave_index == expected_index)
        if payload["call_identity_sha256s"] != [call.identity_sha256 for call in wave_calls]:
            raise SuccessorPlanningStoreError("wave call inventory differs")
        if tuple(call.sealed_dispatch.identity_sha256 for call in wave_calls) != tuple(
            dispatch.identity_sha256 for dispatch in admission.sealed_dispatches
        ):
            raise SuccessorPlanningStoreError("wave dispatch program differs")
        call_scopes = tuple(
            sorted(
                scope.identity_sha256
                for call in wave_calls
                for scope in call.requested_route_scopes
            )
        )
        if call_scopes != wave.requested_scope_identity_sha256s:
            raise SuccessorPlanningStoreError("wave call scopes differ")
        members = tuple(
            sorted(
                (member for call in wave_calls for member in call.members),
                key=lambda item: item.member.identity_sha256,
            )
        )
        if (
            tuple(member.member.identity_sha256 for member in members)
            != wave.member_identity_sha256s
        ):
            raise SuccessorPlanningStoreError("wave member inventory differs")
        if tuple(member.receipt_sha256 for member in members) != wave.member_receipt_sha256s:
            raise SuccessorPlanningStoreError("wave member receipt inventory differs")
        database = payload["database"]
        if not isinstance(database, Mapping) or set(database) != {"artifact", "schema_sha256"}:
            raise SuccessorPlanningStoreError("wave database authority is invalid")
        database_payload = cast("Mapping[str, object]", database)
        database_ref = _ObjectReference.from_dict(
            cast("Mapping[str, object]", database_payload["artifact"])
        )
        if database_ref.kind != "database":
            raise SuccessorPlanningStoreError("wave database has the wrong content domain")
        self._verify_object(
            database_ref,
            budget=budget,
            label="wave planning database",
            object_directory_descriptors=object_directory_descriptors,
        )
        if not wave_calls or (
            database_ref.sha256 != wave_calls[-1].planning_database_sha256
            or database_ref.byte_count != wave_calls[-1].planning_database_bytes
            or database_payload["schema_sha256"] != wave_calls[-1].planning_database_schema_sha256
        ):
            raise SuccessorPlanningStoreError("wave database differs from its final call boundary")
        private_reference = _ObjectReference.from_dict(
            cast("Mapping[str, object]", payload["private_generation_identity"])
        )
        receipt_reference = _ObjectReference.from_dict(
            cast("Mapping[str, object]", payload["completion_receipt"])
        )
        if private_reference.kind != "private_generation_identity":
            raise SuccessorPlanningStoreError(
                "private generation identity has the wrong content domain"
            )
        if receipt_reference.kind != "wave_completion_receipt":
            raise SuccessorPlanningStoreError(
                "wave completion receipt has the wrong content domain"
            )
        if private_reference.sha256 != wave.private_generation_identity_sha256:
            raise SuccessorPlanningStoreError(
                "private generation identity raw digest differs from the sealed wave"
            )
        if receipt_reference.sha256 != wave.completion_receipt_sha256:
            raise SuccessorPlanningStoreError(
                "wave completion receipt raw digest differs from the sealed wave"
            )
        private_bytes = self._read_verified_object_bytes(
            private_reference,
            budget=budget,
            label="private generation identity",
            object_directory_descriptors=object_directory_descriptors,
        )
        receipt_bytes = self._read_verified_object_bytes(
            receipt_reference,
            budget=budget,
            label="planning wave completion receipt",
            object_directory_descriptors=object_directory_descriptors,
        )
        try:
            private_generation_identity = PrivateGenerationIdentity.from_canonical_bytes(
                private_bytes
            )
            completion_receipt = PlanningWaveCompletionReceipt.from_canonical_bytes(receipt_bytes)
        except (ValueError, PlanningWaveCompletionReceiptError) as exc:
            raise SuccessorPlanningStoreError(
                "stored planning wave private authority is invalid"
            ) from exc
        self._require_wave_completion_authority(
            request=request,
            planning_generation_id=planning_generation_id,
            wave=wave,
            admission=admission,
            calls=wave_calls,
            planning_database=PlanningDatabaseSource(
                artifact=PlanningArtifactSource(
                    path=self._object_path(database_ref),
                    sha256=database_ref.sha256,
                    byte_count=database_ref.byte_count,
                ),
                schema_sha256=cast("str", database_payload["schema_sha256"]),
            ),
            private_generation_identity=private_generation_identity,
            completion_receipt=completion_receipt,
        )
        return (
            wave,
            admission,
            CommittedPlanningWaveAuthority(
                wave_index=expected_index,
                private_generation_identity=private_generation_identity,
                completion_receipt=completion_receipt,
                private_generation_identity_sha256=private_reference.sha256,
                private_generation_identity_bytes=private_reference.byte_count,
                private_generation_identity_object_domain_sha256=(private_reference.domain_sha256),
                completion_receipt_sha256=receipt_reference.sha256,
                completion_receipt_bytes=receipt_reference.byte_count,
                completion_receipt_object_domain_sha256=receipt_reference.domain_sha256,
            ),
        )

    @staticmethod
    def _require_wave_completion_authority(
        *,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        wave: SuccessorPlanningWave,
        admission: PlanningWaveAdmission,
        calls: tuple[CommittedPlanningCall, ...],
        planning_database: PlanningDatabaseSource,
        private_generation_identity: PrivateGenerationIdentity,
        completion_receipt: PlanningWaveCompletionReceipt,
    ) -> None:
        if completion_receipt.private_generation_identity != private_generation_identity:
            raise SuccessorPlanningStoreError(
                "completion receipt private generation authority differs"
            )
        expected_header = (
            completion_receipt.planning_request_sha256 == request.identity_sha256
            and completion_receipt.planning_generation_id == planning_generation_id
            and completion_receipt.wave_index == wave.wave_index
            and completion_receipt.parent_wave_identity_sha256 == wave.parent_wave_identity_sha256
            and completion_receipt.wave_admission_identity_sha256 == admission.identity_sha256
            and completion_receipt.sealed_dispatch_identity_sha256s
            == tuple(dispatch.identity_sha256 for dispatch in admission.sealed_dispatches)
            and completion_receipt.requested_scope_identity_sha256s
            == wave.requested_scope_identity_sha256s
            and completion_receipt.completed_scope_identity_sha256s
            == wave.completed_scope_identity_sha256s
        )
        if not expected_header:
            raise SuccessorPlanningStoreError(
                "completion receipt differs from request, generation, wave, or admission authority"
            )
        expected_members = tuple(
            sorted(
                (member for call in calls for member in call.members),
                key=lambda item: item.member.identity_sha256,
            )
        )
        receipt_members = completion_receipt.members
        if tuple(item.member for item in receipt_members) != tuple(
            item.member for item in expected_members
        ):
            raise SuccessorPlanningStoreError(
                "completion receipt full member authority differs from committed calls"
            )
        if tuple(item.member_identity_sha256 for item in receipt_members) != (
            wave.member_identity_sha256s
        ):
            raise SuccessorPlanningStoreError(
                "completion receipt member identities differ from the sealed wave"
            )
        if len(completion_receipt.committed_calls) != len(calls):
            raise SuccessorPlanningStoreError(
                "completion receipt call inventory differs from committed calls"
            )
        binding_by_root = {
            binding.logical_call_receipt_sha256: binding
            for binding in completion_receipt.logical_call_bindings
        }
        for ordinal, (receipt_call, stored_call) in enumerate(
            zip(completion_receipt.committed_calls, calls, strict=True)
        ):
            stored_roots = {member.receipt_sha256 for member in stored_call.members}
            if stored_roots != {receipt_call.logical_call_receipt_sha256}:
                raise SuccessorPlanningStoreError(
                    "completion receipt logical root differs from stored member receipts"
                )
            if (
                receipt_call.ordinal != ordinal
                or receipt_call.sealed_dispatch_identity_sha256
                != stored_call.sealed_dispatch.identity_sha256
                or receipt_call.committed_call_identity_sha256 != stored_call.identity_sha256
                or receipt_call.member_identity_sha256s
                != tuple(member.member.identity_sha256 for member in stored_call.members)
            ):
                raise SuccessorPlanningStoreError(
                    "completion receipt call binding differs from committed calls"
                )
            binding = binding_by_root.get(receipt_call.logical_call_receipt_sha256)
            if binding is None or (
                binding.endpoint_name != stored_call.sealed_dispatch.endpoint_name
                or binding.logical_parameters_sha256
                != stored_call.sealed_dispatch.parameters_sha256
                or binding.result_route_ids
                != tuple(sorted(stored_call.sealed_dispatch.staging_route_ids))
            ):
                raise SuccessorPlanningStoreError(
                    "completion receipt logical binding differs from admitted dispatch"
                )
        root_by_member = {
            member.member.identity_sha256: member.receipt_sha256 for member in expected_members
        }
        if any(
            member.logical_call_receipt_sha256 != root_by_member[member.member_identity_sha256]
            for member in receipt_members
        ):
            raise SuccessorPlanningStoreError(
                "completion receipt member logical root differs from stored receipt"
            )
        artifact = planning_database.artifact
        if (
            completion_receipt.planning_database_sha256 != artifact.sha256
            or completion_receipt.planning_database_bytes != artifact.byte_count
            or completion_receipt.planning_database_schema_sha256 != planning_database.schema_sha256
        ):
            raise SuccessorPlanningStoreError(
                "completion receipt planning database differs from final wave boundary"
            )
        if (
            completion_receipt.capture_scope.semantic_source_sha != request.source_sha
            or completion_receipt.capture_scope.workflow_run_id != request.workflow_run_id
            or completion_receipt.capture_scope.workflow_run_attempt != request.workflow_run_attempt
            or private_generation_identity.workflow_run_id != request.workflow_run_id
            or private_generation_identity.workflow_run_attempt != request.workflow_run_attempt
        ):
            raise SuccessorPlanningStoreError(
                "completion receipt capture execution differs from planning request"
            )

    @staticmethod
    def _admission_matches_wave(
        admission: PlanningWaveAdmission,
        wave: SuccessorPlanningWave,
    ) -> bool:
        return (
            admission.wave_index == wave.wave_index
            and admission.parent_wave_identity_sha256 == wave.parent_wave_identity_sha256
            and admission.requested_scope_identity_sha256s == wave.requested_scope_identity_sha256s
            and wave.completed_scope_identity_sha256s == admission.requested_scope_identity_sha256s
        )

    @staticmethod
    def _require_wave_1_dispatch_dependencies(
        admission: PlanningWaveAdmission,
        calls: Sequence[CommittedPlanningCall],
    ) -> None:
        wave_0_members = {
            member.member.identity_sha256
            for call in calls
            if call.wave_index == 0
            for member in call.members
        }
        dependencies = {
            dependency
            for dispatch in admission.sealed_dispatches
            for dependency in dispatch.dependency_identity_sha256s
        }
        if admission.wave_index != 1 or not dependencies <= wave_0_members:
            raise SuccessorPlanningStoreError(
                "wave 1 dispatch dependency is not an exact committed wave 0 member"
            )

    @staticmethod
    def _require_manifest_admission_program(
        manifest: PlanningGenerationManifest,
        admissions: Sequence[PlanningWaveAdmission],
    ) -> None:
        if len(admissions) != 2:
            raise SuccessorPlanningStoreError(
                "sealed planning manifest requires both admitted wave programs"
            )
        admitted_dispatches = tuple(
            dispatch for admission in admissions for dispatch in admission.sealed_dispatches
        )
        manifest_planning_dispatches = tuple(
            dispatch
            for dispatch in manifest.sealed_dispatches
            if dispatch.phase
            in {
                PlanningDispatchPhase.PLANNING_WAVE_0,
                PlanningDispatchPhase.PLANNING_WAVE_1,
            }
        )
        if manifest_planning_dispatches != admitted_dispatches:
            raise SuccessorPlanningStoreError(
                "planning manifest dispatch program differs from durable admissions"
            )
        admitted_scopes = tuple(
            sorted(
                (scope for admission in admissions for scope in admission.requested_route_scopes),
                key=lambda scope: scope.identity_sha256,
            )
        )
        admitted_scope_ids = {scope.identity_sha256 for scope in admitted_scopes}
        manifest_planning_scopes = tuple(
            scope
            for scope in manifest.requested_route_scopes
            if scope.identity_sha256 in admitted_scope_ids
        )
        if manifest_planning_scopes != admitted_scopes:
            raise SuccessorPlanningStoreError(
                "planning manifest scope bodies differ from durable admissions"
            )

    @staticmethod
    def _new_checkpoint(
        *,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        generation_identity_sha256: str,
        request_bytes: int,
    ) -> dict[str, object]:
        return {
            "schema_version": SUCCESSOR_PLANNING_STORE_SCHEMA_VERSION,
            "kind": "successor_planning_store_checkpoint",
            "planning_request_sha256": request.identity_sha256,
            "planning_generation_id": planning_generation_id,
            "generation_identity_sha256": generation_identity_sha256,
            "request_bytes": request_bytes,
            "phase": PlanningGenerationPhase.BUILDING.value,
            "revision": 0,
            "active_wave": None,
            "committed_calls": [],
            "committed_waves": [],
            "current_database": None,
            "member_inventory": None,
            "wave_inventory": None,
            "sealed_dispatch_inventory": None,
            "manifest": None,
        }

    @staticmethod
    def _decode_checkpoint(encoded: bytes) -> dict[str, object]:
        def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise SuccessorPlanningStoreError(
                        f"planning checkpoint contains duplicate key {key!r}"
                    )
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise SuccessorPlanningStoreError(
                f"planning checkpoint contains non-finite JSON value {value}"
            )

        try:
            decoded = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=pairs_hook,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorPlanningStoreError("planning checkpoint is not strict JSON") from exc
        if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
            raise SuccessorPlanningStoreError("planning checkpoint must be an object")
        if _canonical_bytes(decoded) != encoded:
            raise SuccessorPlanningStoreError("planning checkpoint bytes are not canonical")
        expected = {
            "schema_version",
            "kind",
            "planning_request_sha256",
            "planning_generation_id",
            "generation_identity_sha256",
            "request_bytes",
            "phase",
            "revision",
            "active_wave",
            "committed_calls",
            "committed_waves",
            "current_database",
            "member_inventory",
            "wave_inventory",
            "sealed_dispatch_inventory",
            "manifest",
        }
        if set(decoded) != expected:
            raise SuccessorPlanningStoreError("planning checkpoint fields are invalid")
        if (
            type(decoded["schema_version"]) is not int
            or decoded["schema_version"] != SUCCESSOR_PLANNING_STORE_SCHEMA_VERSION
            or decoded["kind"] != "successor_planning_store_checkpoint"
        ):
            raise SuccessorPlanningStoreError("planning checkpoint schema is invalid")
        _require_sha256(decoded["planning_request_sha256"], field_name="checkpoint request sha256")
        _require_safe_token(
            decoded["planning_generation_id"], field_name="checkpoint planning_generation_id"
        )
        _require_sha256(
            decoded["generation_identity_sha256"], field_name="checkpoint generation identity"
        )
        _require_positive_int(decoded["request_bytes"], field_name="checkpoint request_bytes")
        _require_nonnegative_int(decoded["revision"], field_name="checkpoint revision")
        if not isinstance(decoded["phase"], str) or decoded["phase"] not in _PHASE_RANK:
            raise SuccessorPlanningStoreError("planning checkpoint phase is invalid")
        if not isinstance(decoded["committed_calls"], list) or not isinstance(
            decoded["committed_waves"], list
        ):
            raise SuccessorPlanningStoreError("planning checkpoint inventories must be lists")
        expected_revision = (
            len(decoded["committed_calls"])
            + 2 * len(decoded["committed_waves"])
            + int(decoded["active_wave"] is not None)
            + int(decoded["manifest"] is not None)
        )
        if decoded["revision"] != expected_revision:
            raise SuccessorPlanningStoreError(
                "planning checkpoint revision differs from its durable boundaries"
            )
        return cast("dict[str, object]", decoded)

    def _commit_checkpoint(
        self,
        generation: Path,
        checkpoint: dict[str, object],
        *,
        state: _VerifiedPlanningState,
        budget: PlanningStoreBudget,
    ) -> None:
        encoded = _canonical_bytes(checkpoint)
        self._require_control_bytes(encoded, budget=budget, label="planning checkpoint")
        request_bytes = cast("int", checkpoint["request_bytes"])
        manifest_file_bytes = 0
        if checkpoint["manifest"] is not None:
            manifest_file_bytes = cast(
                "int",
                cast(
                    "dict[str, object]",
                    cast("dict[str, object]", checkpoint["manifest"])["artifact"],
                )["bytes"],
            )
        self._require_generation_bound(
            checkpoint,
            request_bytes=request_bytes,
            checkpoint_bytes=len(encoded),
            manifest_file_bytes=manifest_file_bytes,
            budget=budget,
        )
        self._require_disk_capacity(len(encoded), budget=budget)
        self._atomic_replace_regular(
            generation / _CHECKPOINT_NAME,
            encoded,
            expected_parent=state.generation_stat,
            expected_current=state.checkpoint_stat,
        )
        self._fsync_directory(generation)
        self._require_exact_directory_identity(
            generation,
            state.generation_stat,
            label="planning generation mutation authority",
        )
        crash_injection.after_durable_step(
            crash_injection.DurablePlanningStep.POINTER_ADVANCE,
            pointer="planning_checkpoint",
            phase=str(checkpoint["phase"]),
            revision=checkpoint["revision"],
            committed_call_count=len(cast("list[object]", checkpoint["committed_calls"])),
            committed_wave_count=len(cast("list[object]", checkpoint["committed_waves"])),
            has_active_wave=checkpoint["active_wave"] is not None,
            sealed=checkpoint["manifest"] is not None,
        )

    def _list_generation_directories_locked(self) -> tuple[list[Path], list[Path]]:
        generations_descriptor = self._open_directory(
            self.generations_root,
            label="planning generations directory",
        )
        try:
            names = sorted(
                self._directory_entry_names(
                    generations_descriptor,
                    label="planning generations directory",
                )
            )
        finally:
            os.close(generations_descriptor)
        committed: list[Path] = []
        orphans: list[Path] = []
        prefix = "generation-"
        for name in names:
            path = self.generations_root / name
            if name.startswith(".") and name.endswith(".tmp"):
                orphans.append(path)
                continue
            identity = name[len(prefix) :]
            if (
                not name.startswith(prefix)
                or len(identity) != _SHA256_LENGTH
                or any(character not in "0123456789abcdef" for character in identity)
            ):
                raise SuccessorPlanningStoreError(
                    "planning generations root contains a non-generation entry"
                )
            committed.append(path)
        return committed, orphans

    def _read_generation_header_locked(
        self,
        generation: Path,
        *,
        budget: PlanningStoreBudget,
    ) -> _PlanningGenerationHeader:
        self._require_private_directory(generation, label="planning generation")
        generation_descriptor = self._open_directory(
            generation,
            label="planning generation",
        )
        try:
            request_bytes, _request_stat = self._read_control_at(
                generation_descriptor,
                _REQUEST_NAME,
                budget=budget,
                label="planning request",
            )
            checkpoint_bytes, _checkpoint_stat = self._read_control_at(
                generation_descriptor,
                _CHECKPOINT_NAME,
                budget=budget,
                label="planning checkpoint",
            )
        finally:
            os.close(generation_descriptor)
        try:
            payload = json.loads(request_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorPlanningStoreError("planning request is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise SuccessorPlanningStoreError("planning request must be an object")
        try:
            request = SuccessorPlanningRequest.from_dict(cast("Mapping[str, object]", payload))
        except Exception as exc:
            raise SuccessorPlanningStoreError("planning generation request is invalid") from exc
        if request_bytes != _canonical_bytes(request.to_dict()):
            raise SuccessorPlanningStoreError("planning generation request is not canonical")
        checkpoint = self._decode_checkpoint(checkpoint_bytes)
        planning_generation_id = _require_safe_token(
            checkpoint["planning_generation_id"],
            field_name="checkpoint planning_generation_id",
        )
        generation_identity = _require_sha256(
            checkpoint["generation_identity_sha256"],
            field_name="checkpoint generation identity",
        )
        if generation_identity != _generation_identity(
            request.identity_sha256,
            planning_generation_id,
        ):
            raise SuccessorPlanningStoreError(
                "planning generation identity differs from request and generation id"
            )
        if generation.name != f"generation-{generation_identity}":
            raise SuccessorPlanningStoreError(
                "planning generation directory does not match its identity"
            )
        references = self._checkpoint_object_references(checkpoint)
        retain_identities = {generation_identity}
        retain_identities.update(reference.sha256 for reference in references.values())
        if checkpoint["manifest"] is not None:
            manifest_record = cast("Mapping[str, object]", checkpoint["manifest"])
            retain_identities.add(
                _require_sha256(
                    manifest_record["identity_sha256"],
                    field_name="planning manifest identity",
                )
            )
            retain_identities.add(
                _require_sha256(
                    manifest_record["body_sha256"],
                    field_name="planning manifest body",
                )
            )
        return _PlanningGenerationHeader(
            path=generation,
            request=request,
            planning_generation_id=planning_generation_id,
            generation_identity_sha256=generation_identity,
            object_sha256s=frozenset(reference.sha256 for reference in references.values()),
            retain_identity_sha256s=frozenset(retain_identities),
        )

    @staticmethod
    def _generation_header_retained(
        header: _PlanningGenerationHeader,
        *,
        retain_identity_sha256s: frozenset[str],
        retain_planning_generation_ids: frozenset[str],
    ) -> bool:
        if header.planning_generation_id in retain_planning_generation_ids:
            return True
        return bool(header.retain_identity_sha256s & retain_identity_sha256s)

    def _collect_unreferenced_objects_locked(self, referenced_sha256s: set[str]) -> list[str]:
        deleted: list[str] = []
        objects_descriptor = self._open_directory(
            self.objects_root,
            label="planning objects directory",
        )
        try:
            kind_names = self._directory_entry_names(
                objects_descriptor,
                label="planning objects directory",
            )
            if kind_names != frozenset(_OBJECT_KINDS):
                raise SuccessorPlanningStoreError(
                    "planning object layout has foreign or incomplete state"
                )
            for kind in sorted(_OBJECT_KINDS):
                kind_descriptor = self._open_directory_at(
                    objects_descriptor,
                    kind,
                    label=f"{kind} object directory",
                )
                try:
                    for name in sorted(
                        self._directory_entry_names(
                            kind_descriptor,
                            label=f"{kind} object directory",
                        )
                    ):
                        if len(name) != _SHA256_LENGTH or any(
                            character not in "0123456789abcdef" for character in name
                        ):
                            raise SuccessorPlanningStoreError(
                                f"{kind} object directory contains a non-object entry"
                            )
                        if name in referenced_sha256s:
                            continue
                        self._unlink_named_regular_at(
                            kind_descriptor,
                            name,
                            label=f"{kind} object",
                        )
                        deleted.append(name)
                finally:
                    os.close(kind_descriptor)
        finally:
            os.close(objects_descriptor)
        return deleted

    def _unlink_named_regular_at(
        self,
        directory_descriptor: int,
        name: str,
        *,
        label: str,
    ) -> None:
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | self._nofollow_flags(),
                dir_fd=directory_descriptor,
            )
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode):
                raise SuccessorPlanningStoreError(f"{label} must be a regular file")
            if os.name == "posix" and observed.st_uid != os.geteuid():
                raise SuccessorPlanningStoreError(f"{label} must remain owner-only")
            os.fchmod(descriptor, 0o600)
            os.close(descriptor)
            descriptor = -1
            os.unlink(name, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise SuccessorPlanningStoreError(f"{label} cannot be collected safely") from exc

    def _remove_planning_directory(self, path: Path) -> None:
        try:
            path.relative_to(self.generations_root)
        except ValueError as exc:
            raise SuccessorPlanningStoreError(
                "retired planning generation is outside the planning store"
            ) from exc
        if path.is_symlink() or not path.is_dir() or path.parent != self.generations_root:
            raise SuccessorPlanningStoreError(
                "retired planning generation must be a direct regular directory"
            )
        for root, dir_names, file_names in os.walk(path, topdown=True, followlinks=False):
            root_path = Path(root)
            os.chmod(root_path, 0o700)
            for name in (*dir_names, *file_names):
                child = root_path / name
                if child.is_symlink():
                    raise SuccessorPlanningStoreError(
                        "retired planning generation contains a symlink"
                    )
                os.chmod(child, 0o700 if child.is_dir() else 0o600)
        for root, dir_names, file_names in os.walk(path, topdown=False, followlinks=False):
            root_path = Path(root)
            for name in file_names:
                (root_path / name).unlink()
            for name in dir_names:
                (root_path / name).rmdir()
        path.rmdir()
        self._fsync_directory(self.generations_root)

    @staticmethod
    def _checkpoint_object_references(
        checkpoint: Mapping[str, object],
    ) -> dict[tuple[str, str], _ObjectReference]:
        references: dict[tuple[str, str], _ObjectReference] = {}

        def add(raw: object) -> None:
            if raw is None:
                return
            if not isinstance(raw, Mapping):
                raise SuccessorPlanningStoreError("planning object reference is invalid")
            reference = _ObjectReference.from_dict(cast("Mapping[str, object]", raw))
            references[(reference.kind, reference.sha256)] = reference

        for call in cast("list[dict[str, object]]", checkpoint["committed_calls"]):
            for member in cast("list[dict[str, object]]", call["members"]):
                add(member["artifact"])
            database = cast("dict[str, object]", call["database"])
            add(database["artifact"])
        for wave in cast("list[dict[str, object]]", checkpoint["committed_waves"]):
            add(wave["artifact"])
            add(cast("dict[str, object]", wave["database"])["artifact"])
            add(wave["private_generation_identity"])
            add(wave["completion_receipt"])
        add(checkpoint["member_inventory"])
        add(checkpoint["wave_inventory"])
        add(checkpoint["sealed_dispatch_inventory"])
        if checkpoint["manifest"] is not None:
            add(cast("dict[str, object]", checkpoint["manifest"])["artifact"])
        return references

    def _require_generation_bound(
        self,
        checkpoint: Mapping[str, object],
        *,
        request_bytes: int,
        checkpoint_bytes: int,
        manifest_file_bytes: int,
        budget: PlanningStoreBudget,
    ) -> int:
        references = self._checkpoint_object_references(checkpoint)
        logical_bytes = (
            request_bytes
            + checkpoint_bytes
            + manifest_file_bytes
            + sum(reference.byte_count for reference in references.values())
        )
        if logical_bytes > _MAX_SIGNED_63:
            raise SuccessorPlanningStoreError(
                "planning generation logical bytes exceed signed-63-bit range"
            )
        if logical_bytes > budget.generation_max_bytes:
            raise OSError(
                errno.ENOSPC,
                "planning generation exceeds caller-supplied generation_max_bytes",
            )
        return logical_bytes

    def _store_source_object(
        self,
        kind: str,
        source: PlanningArtifactSource,
        *,
        budget: PlanningStoreBudget,
    ) -> _ObjectReference:
        if source.byte_count > budget.artifact_max_bytes:
            raise OSError(errno.ENOSPC, "planning artifact exceeds artifact_max_bytes")
        reference = _ObjectReference.create(
            kind=kind, sha256=source.sha256, byte_count=source.byte_count
        )
        target = self._object_path(reference)
        self._reject_public_overlap(source.path)
        source_descriptor, source_stat = self._open_absolute_regular(
            source.path, label="planning artifact source"
        )
        try:
            if os.name == "posix" and (
                source_stat.st_uid != os.geteuid() or stat.S_IMODE(source_stat.st_mode) & 0o077
            ):
                raise SuccessorPlanningStoreError(
                    "planning artifact source must be owner-only private"
                )
            if source_stat.st_size != source.byte_count:
                raise SuccessorPlanningStoreError(
                    "planning artifact source byte count differs before copy"
                )
            if target.exists() or target.is_symlink():
                self._hash_descriptor_exact(
                    source_descriptor,
                    expected_bytes=source.byte_count,
                    expected_sha256=source.sha256,
                    label="planning artifact source",
                )
                source_after = os.fstat(source_descriptor)
                self._require_same_open_file(
                    source.path, source_stat, source_after, label="planning artifact source"
                )
                self._verify_object(reference, budget=budget, label=f"{kind} object")
                return reference
            self._require_disk_capacity(source.byte_count, budget=budget)
            object_directory = target.parent
            directory_descriptor = self._open_directory(object_directory, label="object directory")
            directory_before = os.fstat(directory_descriptor)
            temporary_name = f".{source.sha256}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
            temp_descriptor = -1
            published = False
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._nofollow_flags()
                self._assert_locked_identity()
                temp_descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory_descriptor)
                hasher = hashlib.sha256()
                observed_bytes = 0
                while True:
                    chunk = os.read(source_descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    observed_bytes += len(chunk)
                    if observed_bytes > source.byte_count:
                        raise SuccessorPlanningStoreError(
                            "planning artifact source grew while copying"
                        )
                    hasher.update(chunk)
                    view = memoryview(chunk)
                    while view:
                        written = os.write(temp_descriptor, view)
                        if written <= 0:
                            raise SuccessorPlanningStoreError(
                                "planning artifact copy made no write progress"
                            )
                        view = view[written:]
                if observed_bytes != source.byte_count or hasher.hexdigest() != source.sha256:
                    raise SuccessorPlanningStoreError(
                        "planning artifact source digest or byte count differs"
                    )
                os.fchmod(temp_descriptor, 0o400)
                os.fsync(temp_descriptor)
                source_after = os.fstat(source_descriptor)
                self._require_same_open_file(
                    source.path, source_stat, source_after, label="planning artifact source"
                )
                self._assert_locked_identity()
                self._require_same_open_directory(
                    object_directory,
                    directory_before,
                    os.fstat(directory_descriptor),
                    label="object directory",
                )
                try:
                    os.link(
                        temporary_name,
                        source.sha256,
                        src_dir_fd=directory_descriptor,
                        dst_dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    self._verify_object_name_at(
                        directory_descriptor,
                        reference,
                        label=f"{kind} object collision",
                    )
                else:
                    published = True
                    self._verify_published_regular_at(
                        directory_descriptor,
                        source.sha256,
                        temp_descriptor,
                        expected_bytes=source.byte_count,
                        expected_sha256=source.sha256,
                        expected_mode=0o400,
                        label=f"{kind} object",
                    )
                os.fsync(directory_descriptor)
                self._assert_locked_identity()
                self._require_same_open_directory(
                    object_directory,
                    directory_before,
                    os.fstat(directory_descriptor),
                    label="object directory",
                )
                if published:
                    self._verify_published_regular_at(
                        directory_descriptor,
                        source.sha256,
                        temp_descriptor,
                        expected_bytes=source.byte_count,
                        expected_sha256=source.sha256,
                        expected_mode=0o400,
                        label=f"{kind} object",
                    )
                else:
                    self._verify_object_name_at(
                        directory_descriptor,
                        reference,
                        label=f"{kind} object collision",
                    )
            finally:
                if temp_descriptor >= 0:
                    os.close(temp_descriptor)
                with suppress(FileNotFoundError):
                    os.unlink(temporary_name, dir_fd=directory_descriptor)
                os.close(directory_descriptor)
        finally:
            os.close(source_descriptor)
        self._verify_object(reference, budget=budget, label=f"{kind} object")
        return reference

    def _store_bytes_object(
        self,
        kind: str,
        encoded: bytes,
        *,
        budget: PlanningStoreBudget,
    ) -> _ObjectReference:
        if len(encoded) > budget.artifact_max_bytes:
            raise OSError(errno.ENOSPC, "planning artifact exceeds artifact_max_bytes")
        if kind != "member" and kind != "database":
            self._require_control_bytes(encoded, budget=budget, label=f"{kind} object")
        reference = _ObjectReference.create(
            kind=kind, sha256=_raw_sha256(encoded), byte_count=len(encoded)
        )
        target = self._object_path(reference)
        if target.exists() or target.is_symlink():
            self._verify_object(reference, budget=budget, label=f"{kind} object")
            return reference
        self._require_disk_capacity(len(encoded), budget=budget)
        directory_descriptor = self._open_directory(target.parent, label="object directory")
        directory_before = os.fstat(directory_descriptor)
        temporary_name = f".{reference.sha256}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        descriptor = -1
        published = False
        try:
            self._assert_locked_identity()
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._nofollow_flags(),
                0o600,
                dir_fd=directory_descriptor,
            )
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise SuccessorPlanningStoreError("planning object write made no progress")
                view = view[written:]
            os.fchmod(descriptor, 0o400)
            os.fsync(descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                target.parent,
                directory_before,
                os.fstat(directory_descriptor),
                label="object directory",
            )
            try:
                os.link(
                    temporary_name,
                    reference.sha256,
                    src_dir_fd=directory_descriptor,
                    dst_dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError:
                self._verify_object_name_at(
                    directory_descriptor,
                    reference,
                    label=f"{kind} object collision",
                )
            else:
                published = True
                self._verify_published_regular_at(
                    directory_descriptor,
                    reference.sha256,
                    descriptor,
                    expected_bytes=reference.byte_count,
                    expected_sha256=reference.sha256,
                    expected_mode=0o400,
                    label=f"{kind} object",
                )
            os.fsync(directory_descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                target.parent,
                directory_before,
                os.fstat(directory_descriptor),
                label="object directory",
            )
            if published:
                self._verify_published_regular_at(
                    directory_descriptor,
                    reference.sha256,
                    descriptor,
                    expected_bytes=reference.byte_count,
                    expected_sha256=reference.sha256,
                    expected_mode=0o400,
                    label=f"{kind} object",
                )
            else:
                self._verify_object_name_at(
                    directory_descriptor,
                    reference,
                    label=f"{kind} object collision",
                )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_descriptor)
            os.close(directory_descriptor)
        self._verify_object(reference, budget=budget, label=f"{kind} object")
        return reference

    def _verify_object(
        self,
        reference: _ObjectReference,
        *,
        budget: PlanningStoreBudget,
        label: str,
        object_directory_descriptors: Mapping[str, int] | None = None,
    ) -> None:
        if reference.byte_count > budget.artifact_max_bytes:
            raise OSError(errno.ENOSPC, f"{label} exceeds artifact_max_bytes")
        if object_directory_descriptors is not None:
            try:
                directory_descriptor = object_directory_descriptors[reference.kind]
            except KeyError as exc:
                raise SuccessorPlanningStoreError(
                    f"{label} lacks its descriptor-bound object directory"
                ) from exc
            self._verify_object_name_at(
                directory_descriptor,
                reference,
                label=label,
            )
            return
        descriptor, opened = self._open_absolute_regular(self._object_path(reference), label=label)
        try:
            if opened.st_size != reference.byte_count:
                raise SuccessorPlanningStoreError(f"{label} byte count differs")
            if os.name == "posix" and (
                opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) != 0o400
            ):
                raise SuccessorPlanningStoreError(
                    f"{label} must remain an owner-read-only immutable object"
                )
            self._hash_descriptor_exact(
                descriptor,
                expected_bytes=reference.byte_count,
                expected_sha256=reference.sha256,
                label=label,
            )
            after = os.fstat(descriptor)
            self._require_same_open_file(self._object_path(reference), opened, after, label=label)
        finally:
            os.close(descriptor)

    def _read_verified_object_bytes(
        self,
        reference: _ObjectReference,
        *,
        budget: PlanningStoreBudget,
        label: str,
        object_directory_descriptors: Mapping[str, int] | None = None,
    ) -> bytes:
        if reference.byte_count > budget.control_max_bytes:
            raise OSError(errno.ENOSPC, f"{label} exceeds control_max_bytes")
        if object_directory_descriptors is None:
            encoded = self._read_regular_exact(
                self._object_path(reference),
                max_bytes=budget.control_max_bytes,
                expected_bytes=reference.byte_count,
                label=label,
            )
        else:
            try:
                directory_descriptor = object_directory_descriptors[reference.kind]
            except KeyError as exc:
                raise SuccessorPlanningStoreError(
                    f"{label} lacks its descriptor-bound object directory"
                ) from exc
            encoded, _observed = self._read_regular_exact_at(
                directory_descriptor,
                reference.sha256,
                max_bytes=budget.control_max_bytes,
                expected_bytes=reference.byte_count,
                label=label,
            )
        if _raw_sha256(encoded) != reference.sha256:
            raise SuccessorPlanningStoreError(f"{label} digest differs")
        return encoded

    def _object_path(self, reference: _ObjectReference) -> Path:
        return self.objects_root / reference.kind / reference.sha256

    def _require_request_and_budget(
        self,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        budget: PlanningStoreBudget,
    ) -> None:
        if not isinstance(request, SuccessorPlanningRequest):
            raise SuccessorPlanningStoreError("request must be a SuccessorPlanningRequest")
        _require_safe_token(planning_generation_id, field_name="planning_generation_id")
        if not isinstance(budget, PlanningStoreBudget):
            raise SuccessorPlanningStoreError("budget must be a PlanningStoreBudget")
        self._admit_current_call(budget)

    def _admit_current_call(self, budget: PlanningStoreBudget) -> None:
        try:
            monotonic_now = self._monotonic_clock()
        except Exception as exc:
            raise SuccessorPlanningStoreError("monotonic clock could not be sampled") from exc
        if (
            isinstance(monotonic_now, bool)
            or not isinstance(monotonic_now, int | float)
            or not math.isfinite(monotonic_now)
            or monotonic_now < 0
        ):
            raise SuccessorPlanningStoreError(
                "monotonic clock must return a finite nonnegative value"
            )
        if (
            budget.monotonic_deadline_seconds - monotonic_now
            < budget.minimum_deadline_headroom_seconds
        ):
            raise SuccessorPlanningStoreError(
                "planning store deadline headroom is insufficient for this call"
            )

    def _require_disk_capacity(
        self,
        additional_bytes: int,
        *,
        budget: PlanningStoreBudget,
    ) -> None:
        _require_nonnegative_int(additional_bytes, field_name="additional_bytes")
        try:
            available = shutil.disk_usage(self.root).free
        except OSError as exc:
            raise SuccessorPlanningStoreError(
                "planning store free space cannot be measured"
            ) from exc
        required = additional_bytes + budget.minimum_free_bytes
        if available < required:
            message = (
                "insufficient private planning capacity: "
                f"required={required}, available={available}"
            )
            raise OSError(errno.ENOSPC, message)

    @staticmethod
    def _require_control_bytes(
        encoded: bytes,
        *,
        budget: PlanningStoreBudget,
        label: str,
    ) -> None:
        if len(encoded) > budget.control_max_bytes:
            raise OSError(errno.ENOSPC, f"{label} exceeds control_max_bytes")

    def _ensure_layout(self) -> None:
        parent = self.root.parent
        self._require_private_parent(parent)
        if not self.root.exists() and not self.root.is_symlink():
            self.root.mkdir(mode=0o700)
        self._require_private_directory(self.root, label="planning store root")
        for path in (self.objects_root, self.generations_root):
            if not path.exists() and not path.is_symlink():
                path.mkdir(mode=0o700)
            self._require_private_directory(path, label="planning store directory")
        for kind in sorted(_OBJECT_KINDS):
            path = self.objects_root / kind
            if not path.exists() and not path.is_symlink():
                path.mkdir(mode=0o700)
            self._require_private_directory(path, label=f"{kind} object directory")

    def _require_capacity_root_descriptor(self, descriptor: int) -> os.stat_result:
        if type(descriptor) is not int or descriptor < 0:
            raise SuccessorPlanningStoreError(
                "planning capacity root descriptor must be a nonnegative integer"
            )
        try:
            opened = os.fstat(descriptor)
        except OSError as exc:
            raise SuccessorPlanningStoreError(
                "planning capacity root descriptor cannot be inspected"
            ) from exc
        if not stat.S_ISDIR(opened.st_mode):
            raise SuccessorPlanningStoreError(
                "planning capacity root descriptor must reference a directory"
            )
        if os.name == "posix" and (
            opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) != 0o700
        ):
            raise SuccessorPlanningStoreError(
                "planning capacity root descriptor must remain owner-only mode 0700"
            )
        self._require_same_open_directory(
            self.root,
            opened,
            os.fstat(descriptor),
            label="planning capacity root",
        )
        return opened

    def _require_unchanged_capacity_root_descriptor(
        self,
        descriptor: int,
        before: os.stat_result,
    ) -> None:
        try:
            after = os.fstat(descriptor)
        except OSError as exc:
            raise SuccessorPlanningStoreError(
                "planning capacity root descriptor changed while measured"
            ) from exc
        before_authority = (
            before.st_dev,
            before.st_ino,
            before.st_mode,
            before.st_nlink,
            before.st_uid,
            before.st_gid,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_authority = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_nlink,
            after.st_uid,
            after.st_gid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if before_authority != after_authority:
            raise SuccessorPlanningStoreError(
                "planning capacity root descriptor changed while measured"
            )
        self._require_capacity_root_descriptor(descriptor)

    @staticmethod
    def _directory_entry_names(descriptor: int, *, label: str) -> frozenset[str]:
        try:
            with os.scandir(descriptor) as entries:
                return frozenset(entry.name for entry in entries)
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} cannot be scanned") from exc

    @classmethod
    def _open_directory_at(
        cls,
        parent_descriptor: int,
        name: str,
        *,
        label: str,
    ) -> int:
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | cls._nofollow_flags()
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=parent_descriptor,
            )
            observed = os.fstat(descriptor)
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise SuccessorPlanningStoreError(f"{label} cannot be opened safely") from exc
        if not stat.S_ISDIR(observed.st_mode) or (
            os.name == "posix"
            and (observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != 0o700)
        ):
            os.close(descriptor)
            raise SuccessorPlanningStoreError(f"{label} must remain owner-only mode 0700")
        return descriptor

    def _require_complete_measurement_layout_at(
        self,
        root_descriptor: int,
        root_entries: frozenset[str],
    ) -> None:
        expected_root_entries = frozenset({_LOCK_NAME, "objects", "generations"})
        if root_entries != expected_root_entries:
            raise SuccessorPlanningStoreError(
                "planning store has foreign or incomplete measurement state"
            )
        try:
            lock_stat = os.stat(
                _LOCK_NAME,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise SuccessorPlanningStoreError(
                "planning store measurement lock cannot be inspected"
            ) from exc
        if not stat.S_ISREG(lock_stat.st_mode) or (
            os.name == "posix"
            and (lock_stat.st_uid != os.geteuid() or stat.S_IMODE(lock_stat.st_mode) != 0o600)
        ):
            raise SuccessorPlanningStoreError(
                "planning store measurement lock must remain owner-only mode 0600"
            )
        objects_descriptor = self._open_directory_at(
            root_descriptor,
            self.objects_root.name,
            label="planning objects directory",
        )
        generations_descriptor = self._open_directory_at(
            root_descriptor,
            self.generations_root.name,
            label="planning generations directory",
        )
        try:
            if self._directory_entry_names(
                objects_descriptor,
                label="planning objects directory",
            ) != frozenset(_OBJECT_KINDS):
                raise SuccessorPlanningStoreError(
                    "planning object layout has foreign or incomplete state"
                )
            for kind in _OBJECT_KINDS:
                kind_descriptor = self._open_directory_at(
                    objects_descriptor,
                    kind,
                    label=f"{kind} object directory",
                )
                os.close(kind_descriptor)
            self._require_same_open_directory(
                self.objects_root,
                os.fstat(objects_descriptor),
                os.fstat(objects_descriptor),
                label="planning objects directory",
            )
            self._require_same_open_directory(
                self.generations_root,
                os.fstat(generations_descriptor),
                os.fstat(generations_descriptor),
                label="planning generations directory",
            )
        finally:
            os.close(generations_descriptor)
            os.close(objects_descriptor)

    @contextmanager
    def _exclusive_store_lock(self, *, initialize_layout: bool = True) -> Iterator[None]:
        if self._expected_root_identity is not None:
            try:
                root_current = os.stat(self.root, follow_symlinks=False)
                lock_current = os.stat(self.root / _LOCK_NAME, follow_symlinks=False)
            except OSError as exc:
                raise SuccessorPlanningStoreError(
                    "planning store root or lock identity changed"
                ) from exc
            if (
                not stat.S_ISDIR(root_current.st_mode)
                or (root_current.st_dev, root_current.st_ino) != self._expected_root_identity
                or not stat.S_ISREG(lock_current.st_mode)
                or (lock_current.st_dev, lock_current.st_ino) != self._expected_lock_identity
            ):
                raise SuccessorPlanningStoreError("planning store root or lock identity changed")
        if initialize_layout:
            self._ensure_layout()
        lock_key = str(self.root / _LOCK_NAME)
        with _PROCESS_LOCKS_GUARD:
            process_lock = _PROCESS_LOCKS.setdefault(lock_key, threading.RLock())
        with process_lock:
            depth = int(getattr(self._lock_state, "depth", 0))
            if depth:
                self._assert_locked_identity()
                self._lock_state.depth = depth + 1
                try:
                    yield
                finally:
                    self._lock_state.depth = depth
                    self._assert_locked_identity()
                return
            if os.name != "posix" or not getattr(os, "O_NOFOLLOW", 0):
                raise SuccessorPlanningStoreError(
                    "planning store requires POSIX flock and O_NOFOLLOW"
                )
            fcntl = importlib.import_module("fcntl")
            root_descriptor = -1
            lock_descriptor = -1
            acquired = False
            try:
                root_descriptor = self._open_directory(
                    self.root,
                    label="planning store root",
                )
                lock_flags = os.O_RDWR | self._nofollow_flags()
                if initialize_layout:
                    lock_flags |= os.O_CREAT
                lock_descriptor = os.open(
                    _LOCK_NAME,
                    lock_flags,
                    0o600,
                    dir_fd=root_descriptor,
                )
                root_opened = os.fstat(root_descriptor)
                lock_opened = os.fstat(lock_descriptor)
                if not stat.S_ISREG(lock_opened.st_mode):
                    raise SuccessorPlanningStoreError("planning store lock must be regular")
                fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
                acquired = True
                root_identity = (root_opened.st_dev, root_opened.st_ino)
                lock_identity = (lock_opened.st_dev, lock_opened.st_ino)
                if self._expected_root_identity not in (None, root_identity):
                    raise SuccessorPlanningStoreError("planning store root identity changed")
                if self._expected_lock_identity not in (None, lock_identity):
                    raise SuccessorPlanningStoreError("planning store lock identity changed")
                self._expected_root_identity = root_identity
                self._expected_lock_identity = lock_identity
                self._lock_state.root_descriptor = root_descriptor
                self._lock_state.lock_descriptor = lock_descriptor
                self._lock_state.depth = 1
                self._assert_locked_identity()
                if not initialize_layout:
                    measurement_entries = self._directory_entry_names(
                        root_descriptor,
                        label="planning capacity root",
                    )
                    self._require_complete_measurement_layout_at(
                        root_descriptor,
                        measurement_entries,
                    )
                yield
                self._assert_locked_identity()
            except OSError as exc:
                if acquired:
                    raise
                raise SuccessorPlanningStoreError("planning store lock cannot be acquired") from exc
            finally:
                self._lock_state.depth = 0
                self._lock_state.root_descriptor = -1
                self._lock_state.lock_descriptor = -1
                if lock_descriptor >= 0:
                    with suppress(OSError):
                        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                    os.close(lock_descriptor)
                if root_descriptor >= 0:
                    os.close(root_descriptor)

    def _assert_locked_identity(self) -> None:
        root_descriptor = int(getattr(self._lock_state, "root_descriptor", -1))
        lock_descriptor = int(getattr(self._lock_state, "lock_descriptor", -1))
        if root_descriptor < 0 or lock_descriptor < 0:
            raise SuccessorPlanningStoreError("planning store mutation requires its exact lock")
        try:
            root_opened = os.fstat(root_descriptor)
            root_current = os.stat(self.root, follow_symlinks=False)
            lock_opened = os.fstat(lock_descriptor)
            lock_current = os.stat(
                _LOCK_NAME,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise SuccessorPlanningStoreError(
                "planning store root or lock changed while held"
            ) from exc
        root_identity = (root_opened.st_dev, root_opened.st_ino)
        lock_identity = (lock_opened.st_dev, lock_opened.st_ino)
        if (
            not stat.S_ISDIR(root_opened.st_mode)
            or not stat.S_ISDIR(root_current.st_mode)
            or root_identity != (root_current.st_dev, root_current.st_ino)
            or root_identity != self._expected_root_identity
        ):
            raise SuccessorPlanningStoreError("planning store root identity changed while held")
        if (
            not stat.S_ISREG(lock_opened.st_mode)
            or not stat.S_ISREG(lock_current.st_mode)
            or lock_identity != (lock_current.st_dev, lock_current.st_ino)
            or lock_identity != self._expected_lock_identity
        ):
            raise SuccessorPlanningStoreError("planning store lock identity changed while held")

    @staticmethod
    def _nofollow_flags() -> int:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not nofollow:
            raise SuccessorPlanningStoreError("planning store requires O_NOFOLLOW")
        return nofollow | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)

    @classmethod
    def _open_absolute_regular(
        cls,
        path: Path,
        *,
        label: str,
    ) -> tuple[int, os.stat_result]:
        path = Path(path)
        if not path.is_absolute():
            raise SuccessorPlanningStoreError(f"{label} path must be absolute")
        parts = PurePath(os.path.abspath(path)).parts
        directory = os.open(
            parts[0],
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | cls._nofollow_flags(),
        )
        try:
            for component in parts[1:-1]:
                child = os.open(
                    component,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | cls._nofollow_flags(),
                    dir_fd=directory,
                )
                if not stat.S_ISDIR(os.fstat(child).st_mode):
                    os.close(child)
                    raise SuccessorPlanningStoreError(f"{label} parent is not a directory")
                os.close(directory)
                directory = child
            descriptor = os.open(parts[-1], os.O_RDONLY | cls._nofollow_flags(), dir_fd=directory)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                os.close(descriptor)
                raise SuccessorPlanningStoreError(f"{label} must be a regular file")
            return descriptor, opened
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} cannot be opened safely") from exc
        finally:
            os.close(directory)

    @classmethod
    def _open_directory(cls, path: Path, *, label: str) -> int:
        absolute = Path(os.path.abspath(path))
        parts = PurePath(absolute).parts
        descriptor = -1
        try:
            descriptor = os.open(
                parts[0],
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | cls._nofollow_flags(),
            )
            for component in parts[1:]:
                child = os.open(
                    component,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | cls._nofollow_flags(),
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = child
                if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    raise SuccessorPlanningStoreError(f"{label} must be a directory")
            return descriptor
        except OSError as exc:
            if descriptor >= 0:
                os.close(descriptor)
            raise SuccessorPlanningStoreError(f"{label} cannot be opened safely") from exc

    @staticmethod
    def _hash_descriptor_exact(
        descriptor: int,
        *,
        expected_bytes: int,
        expected_sha256: str,
        label: str,
    ) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        hasher = hashlib.sha256()
        observed = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            observed += len(chunk)
            if observed > expected_bytes:
                raise SuccessorPlanningStoreError(f"{label} exceeds its exact byte count")
            hasher.update(chunk)
        if observed != expected_bytes or hasher.hexdigest() != expected_sha256:
            raise SuccessorPlanningStoreError(f"{label} digest or byte count differs")

    @staticmethod
    def _require_same_open_file(
        path: Path,
        before: os.stat_result,
        after: os.stat_result,
        *,
        label: str,
    ) -> None:
        try:
            path_after = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} changed while reading") from exc
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if (
            before_identity != after_identity
            or (after.st_dev, after.st_ino) != (path_after.st_dev, path_after.st_ino)
            or not stat.S_ISREG(path_after.st_mode)
        ):
            raise SuccessorPlanningStoreError(f"{label} changed while reading")

    @staticmethod
    def _require_same_open_directory(
        path: Path,
        before: os.stat_result,
        after: os.stat_result,
        *,
        label: str,
    ) -> None:
        try:
            path_after = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} changed while held") from exc
        before_identity = (before.st_dev, before.st_ino)
        after_identity = (after.st_dev, after.st_ino)
        path_identity = (path_after.st_dev, path_after.st_ino)
        if (
            not stat.S_ISDIR(before.st_mode)
            or not stat.S_ISDIR(after.st_mode)
            or not stat.S_ISDIR(path_after.st_mode)
            or before_identity != after_identity
            or after_identity != path_identity
        ):
            raise SuccessorPlanningStoreError(f"{label} changed while held")

    @staticmethod
    def _require_same_named_directory_at(
        parent_descriptor: int,
        name: str,
        before: os.stat_result,
        after: os.stat_result,
        *,
        label: str,
    ) -> None:
        try:
            named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} changed while held") from exc
        before_identity = (before.st_dev, before.st_ino)
        after_identity = (after.st_dev, after.st_ino)
        named_identity = (named.st_dev, named.st_ino)
        if (
            not stat.S_ISDIR(before.st_mode)
            or not stat.S_ISDIR(after.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or before_identity != after_identity
            or after_identity != named_identity
        ):
            raise SuccessorPlanningStoreError(f"{label} changed while held")

    @classmethod
    def _require_exact_directory_identity(
        cls,
        path: Path,
        expected: os.stat_result,
        *,
        label: str,
    ) -> None:
        descriptor = cls._open_directory(path, label=label)
        try:
            cls._require_same_open_directory(
                path,
                expected,
                os.fstat(descriptor),
                label=label,
            )
        finally:
            os.close(descriptor)

    def _verify_object_name_at(
        self,
        directory_descriptor: int,
        reference: _ObjectReference,
        *,
        label: str,
    ) -> None:
        descriptor = -1
        try:
            descriptor = os.open(
                reference.sha256,
                os.O_RDONLY | self._nofollow_flags(),
                dir_fd=directory_descriptor,
            )
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_size != reference.byte_count
                or (
                    os.name == "posix"
                    and (before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o400)
                )
            ):
                raise SuccessorPlanningStoreError(
                    f"{label} must be the exact owner-read-only object"
                )
            self._hash_descriptor_exact(
                descriptor,
                expected_bytes=reference.byte_count,
                expected_sha256=reference.sha256,
                label=label,
            )
            self._require_same_named_file_at(
                directory_descriptor,
                reference.sha256,
                before,
                os.fstat(descriptor),
                label=label,
            )
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} cannot be opened safely") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _read_regular_exact(
        self,
        path: Path,
        *,
        max_bytes: int,
        expected_bytes: int | None,
        label: str,
    ) -> bytes:
        descriptor, before = self._open_absolute_regular(path, label=label)
        try:
            if before.st_size > max_bytes:
                raise OSError(errno.ENOSPC, f"{label} exceeds the caller-supplied byte limit")
            if expected_bytes is not None and before.st_size != expected_bytes:
                raise SuccessorPlanningStoreError(f"{label} byte count differs")
            remaining = max_bytes + 1
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            encoded = b"".join(chunks)
            after = os.fstat(descriptor)
            self._require_same_open_file(path, before, after, label=label)
        finally:
            os.close(descriptor)
        if len(encoded) > max_bytes or len(encoded) != before.st_size:
            raise SuccessorPlanningStoreError(f"{label} changed while reading")
        return encoded

    def _read_regular_exact_at(
        self,
        directory_descriptor: int,
        name: str,
        *,
        max_bytes: int,
        expected_bytes: int | None,
        label: str,
    ) -> tuple[bytes, os.stat_result]:
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | self._nofollow_flags(),
                dir_fd=directory_descriptor,
            )
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise SuccessorPlanningStoreError(f"{label} must be a regular file")
            if before.st_size > max_bytes:
                raise OSError(errno.ENOSPC, f"{label} exceeds the caller-supplied byte limit")
            if expected_bytes is not None and before.st_size != expected_bytes:
                raise SuccessorPlanningStoreError(f"{label} byte count differs")
            remaining = max_bytes + 1
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            encoded = b"".join(chunks)
            after = os.fstat(descriptor)
            self._require_same_named_file_at(
                directory_descriptor,
                name,
                before,
                after,
                label=label,
            )
            if len(encoded) > max_bytes or len(encoded) != before.st_size:
                raise SuccessorPlanningStoreError(f"{label} changed while reading")
            return encoded, after
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} cannot be opened safely") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _read_control_at(
        self,
        directory_descriptor: int,
        name: str,
        *,
        budget: PlanningStoreBudget,
        label: str,
    ) -> tuple[bytes, os.stat_result]:
        return self._read_regular_exact_at(
            directory_descriptor,
            name,
            max_bytes=budget.control_max_bytes,
            expected_bytes=None,
            label=label,
        )

    @staticmethod
    def _entry_exists_at(directory_descriptor: int, name: str) -> bool:
        try:
            os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return False
        return True

    @staticmethod
    def _require_same_named_file_at(
        directory_descriptor: int,
        name: str,
        before: os.stat_result,
        after: os.stat_result,
        *,
        label: str,
    ) -> None:
        try:
            named = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} changed while held") from exc
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if (
            not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(after.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or before_identity != after_identity
            or (after.st_dev, after.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise SuccessorPlanningStoreError(f"{label} changed while held")

    def _verify_published_regular_at(
        self,
        directory_descriptor: int,
        name: str,
        source_descriptor: int,
        *,
        expected_bytes: int,
        expected_sha256: str,
        expected_mode: int,
        label: str,
    ) -> tuple[int, int]:
        source_stat = os.fstat(source_descriptor)
        descriptor = -1
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | self._nofollow_flags(),
                dir_fd=directory_descriptor,
            )
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(source_stat.st_mode)
                or not stat.S_ISREG(before.st_mode)
                or (source_stat.st_dev, source_stat.st_ino) != (before.st_dev, before.st_ino)
                or before.st_size != expected_bytes
                or (
                    os.name == "posix"
                    and (
                        before.st_uid != os.geteuid()
                        or stat.S_IMODE(before.st_mode) != expected_mode
                    )
                )
            ):
                raise SuccessorPlanningStoreError(
                    f"{label} does not name the exact published private inode"
                )
            self._hash_descriptor_exact(
                descriptor,
                expected_bytes=expected_bytes,
                expected_sha256=expected_sha256,
                label=label,
            )
            after = os.fstat(descriptor)
            self._require_same_named_file_at(
                directory_descriptor,
                name,
                before,
                after,
                label=label,
            )
            if (source_stat.st_dev, source_stat.st_ino) != (after.st_dev, after.st_ino):
                raise SuccessorPlanningStoreError(
                    f"{label} changed from the exact published private inode"
                )
            return after.st_dev, after.st_ino
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} cannot be opened safely") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _file_authority(stat_result: os.stat_result) -> tuple[int, int, int, int, int]:
        return (
            stat_result.st_dev,
            stat_result.st_ino,
            stat_result.st_size,
            stat_result.st_mtime_ns,
            stat_result.st_ctime_ns,
        )

    @staticmethod
    def _directory_identity(stat_result: os.stat_result) -> tuple[int, int]:
        return stat_result.st_dev, stat_result.st_ino

    def _read_control(
        self,
        path: Path,
        *,
        budget: PlanningStoreBudget,
        label: str,
    ) -> bytes:
        return self._read_regular_exact(
            path,
            max_bytes=budget.control_max_bytes,
            expected_bytes=None,
            label=label,
        )

    def _write_new_regular(
        self,
        path: Path,
        encoded: bytes,
        *,
        expected_parent: os.stat_result | None = None,
    ) -> None:
        directory_descriptor = self._open_directory(path.parent, label="control directory")
        descriptor = -1
        try:
            directory_before = os.fstat(directory_descriptor)
            if expected_parent is not None and self._directory_identity(
                directory_before
            ) != self._directory_identity(expected_parent):
                raise SuccessorPlanningStoreError("control directory authority changed")
            self._assert_locked_identity()
            descriptor = os.open(
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._nofollow_flags(),
                0o600,
                dir_fd=directory_descriptor,
            )
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise SuccessorPlanningStoreError("control file write made no progress")
                view = view[written:]
            os.fsync(descriptor)
            self._verify_published_regular_at(
                directory_descriptor,
                path.name,
                descriptor,
                expected_bytes=len(encoded),
                expected_sha256=_raw_sha256(encoded),
                expected_mode=0o600,
                label="new control file",
            )
            os.fsync(directory_descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                path.parent,
                directory_before,
                os.fstat(directory_descriptor),
                label="control directory",
            )
            self._verify_published_regular_at(
                directory_descriptor,
                path.name,
                descriptor,
                expected_bytes=len(encoded),
                expected_sha256=_raw_sha256(encoded),
                expected_mode=0o600,
                label="new control file",
            )
        except OSError as exc:
            raise SuccessorPlanningStoreError("control file cannot be created safely") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            os.close(directory_descriptor)

    def _atomic_replace_regular(
        self,
        path: Path,
        encoded: bytes,
        *,
        expected_parent: os.stat_result,
        expected_current: os.stat_result,
    ) -> None:
        directory_descriptor = self._open_directory(path.parent, label="control directory")
        temporary_name = f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        descriptor = -1
        try:
            directory_before = os.fstat(directory_descriptor)
            if self._directory_identity(directory_before) != self._directory_identity(
                expected_parent
            ):
                raise SuccessorPlanningStoreError("control directory authority changed")
            self._assert_locked_identity()
            try:
                current = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                current = None
            if (
                current is None
                or not stat.S_ISREG(current.st_mode)
                or self._file_authority(current) != self._file_authority(expected_current)
            ):
                raise SuccessorPlanningStoreError(
                    "control file differs from its verified mutation authority"
                )
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._nofollow_flags(),
                0o600,
                dir_fd=directory_descriptor,
            )
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise SuccessorPlanningStoreError("control replacement write made no progress")
                view = view[written:]
            os.fsync(descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                path.parent,
                directory_before,
                os.fstat(directory_descriptor),
                label="control directory",
            )
            current = os.stat(path.name, dir_fd=directory_descriptor, follow_symlinks=False)
            if self._file_authority(current) != self._file_authority(expected_current):
                raise SuccessorPlanningStoreError(
                    "control file changed before its atomic replacement"
                )
            os.replace(
                temporary_name,
                path.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            self._verify_published_regular_at(
                directory_descriptor,
                path.name,
                descriptor,
                expected_bytes=len(encoded),
                expected_sha256=_raw_sha256(encoded),
                expected_mode=0o600,
                label="replaced control file",
            )
            os.fsync(directory_descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                path.parent,
                directory_before,
                os.fstat(directory_descriptor),
                label="control directory",
            )
            self._verify_published_regular_at(
                directory_descriptor,
                path.name,
                descriptor,
                expected_bytes=len(encoded),
                expected_sha256=_raw_sha256(encoded),
                expected_mode=0o600,
                label="replaced control file",
            )
        except OSError as exc:
            raise SuccessorPlanningStoreError("control file cannot be replaced atomically") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_descriptor)
            os.close(directory_descriptor)

    def _publish_new_regular_no_replace(
        self,
        path: Path,
        encoded: bytes,
        *,
        expected_parent: os.stat_result | None = None,
    ) -> None:
        """Publish immutable control bytes through a synced no-overwrite link."""

        directory_descriptor = self._open_directory(path.parent, label="control directory")
        temporary_name = f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
        descriptor = -1
        try:
            directory_before = os.fstat(directory_descriptor)
            if expected_parent is not None and self._directory_identity(
                directory_before
            ) != self._directory_identity(expected_parent):
                raise SuccessorPlanningStoreError("control directory authority changed")
            self._assert_locked_identity()
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | self._nofollow_flags(),
                0o600,
                dir_fd=directory_descriptor,
            )
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise SuccessorPlanningStoreError("immutable control write made no progress")
                view = view[written:]
            os.fsync(descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                path.parent,
                directory_before,
                os.fstat(directory_descriptor),
                label="control directory",
            )
            os.link(
                temporary_name,
                path.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            self._verify_published_regular_at(
                directory_descriptor,
                path.name,
                descriptor,
                expected_bytes=len(encoded),
                expected_sha256=_raw_sha256(encoded),
                expected_mode=0o600,
                label="immutable control file",
            )
            os.fsync(directory_descriptor)
            self._assert_locked_identity()
            self._require_same_open_directory(
                path.parent,
                directory_before,
                os.fstat(directory_descriptor),
                label="control directory",
            )
            self._verify_published_regular_at(
                directory_descriptor,
                path.name,
                descriptor,
                expected_bytes=len(encoded),
                expected_sha256=_raw_sha256(encoded),
                expected_mode=0o600,
                label="immutable control file",
            )
        except OSError as exc:
            raise SuccessorPlanningStoreError(
                "immutable control file cannot be published safely"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_descriptor)
            os.close(directory_descriptor)

    def _new_private_directory(self, parent: Path, *, prefix: str) -> Path:
        for _attempt in range(16):
            candidate = parent / f"{prefix}{os.getpid()}.{secrets.token_hex(8)}.tmp"
            try:
                self._assert_locked_identity()
                candidate.mkdir(mode=0o700)
            except FileExistsError:
                continue
            self._require_private_directory(candidate, label="temporary planning directory")
            self._assert_locked_identity()
            return candidate
        raise SuccessorPlanningStoreError("temporary planning directory cannot be reserved")

    @classmethod
    def _fsync_directory(cls, path: Path) -> None:
        descriptor = cls._open_directory(path, label="fsync directory")
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _require_private_parent(cls, path: Path) -> None:
        try:
            descriptor = cls._open_directory(path, label="planning store parent")
        except SuccessorPlanningStoreError as exc:
            raise SuccessorPlanningStoreError("planning store parent must already exist") from exc
        os.close(descriptor)

    @staticmethod
    def _existing_regular_directory(path: Path, *, label: str) -> Path:
        try:
            resolved = path.resolve(strict=True)
            observed = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} must exist") from exc
        if path.is_symlink() or not stat.S_ISDIR(observed.st_mode):
            raise SuccessorPlanningStoreError(f"{label} must be a non-symlink directory")
        return resolved

    @staticmethod
    def _require_private_directory(path: Path, *, label: str) -> None:
        try:
            observed = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorPlanningStoreError(f"{label} cannot be inspected") from exc
        if not stat.S_ISDIR(observed.st_mode) or path.is_symlink():
            raise SuccessorPlanningStoreError(f"{label} must be a regular directory")
        if os.name == "posix" and (
            observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) & 0o077
        ):
            raise SuccessorPlanningStoreError(f"{label} must be owner-only private")

    def _reject_public_overlap(self, path: Path) -> None:
        candidate = Path(os.path.abspath(path)).resolve(strict=False)
        for public_root in self._public_roots:
            try:
                common = Path(os.path.commonpath((candidate, public_root)))
            except ValueError as exc:
                raise SuccessorPlanningStoreError("planning/public root comparison failed") from exc
            if common in (candidate, public_root):
                raise SuccessorPlanningStoreError(
                    "private planning storage must not overlap a public tree"
                )
            candidate_parts = tuple(part.casefold() for part in candidate.parts)
            public_parts = tuple(part.casefold() for part in public_root.parts)
            if (
                candidate_parts[: len(public_parts)] == public_parts
                or public_parts[: len(candidate_parts)] == candidate_parts
            ):
                raise SuccessorPlanningStoreError(
                    "private planning storage must not overlap a public tree"
                )
            try:
                public_identity = self._filesystem_identity(public_root)
                candidate_ancestor_identities = {
                    self._filesystem_identity(ancestor)
                    for ancestor in (candidate, *candidate.parents)
                    if ancestor.exists()
                }
            except OSError as exc:
                raise SuccessorPlanningStoreError(
                    "planning/public root identity comparison failed"
                ) from exc
            if public_identity in candidate_ancestor_identities:
                raise SuccessorPlanningStoreError(
                    "private planning storage must not overlap a public tree"
                )
            if candidate.exists():
                candidate_identity = self._filesystem_identity(candidate)
                public_ancestor_identities = {
                    self._filesystem_identity(ancestor)
                    for ancestor in (public_root, *public_root.parents)
                }
                if candidate_identity in public_ancestor_identities:
                    raise SuccessorPlanningStoreError(
                        "private planning storage must not overlap a public tree"
                    )

    def _reject_store_overlap(self, path: Path) -> None:
        candidate = Path(os.path.abspath(path)).resolve(strict=False)
        store_root = self.root.resolve(strict=False)
        try:
            common = Path(os.path.commonpath((candidate, store_root)))
        except ValueError as exc:
            raise SuccessorPlanningStoreError("planning store path comparison failed") from exc
        candidate_parts = tuple(part.casefold() for part in candidate.parts)
        store_parts = tuple(part.casefold() for part in store_root.parts)
        if (
            common in (candidate, store_root)
            or candidate_parts[: len(store_parts)] == store_parts
            or store_parts[: len(candidate_parts)] == candidate_parts
        ):
            raise SuccessorPlanningStoreError(
                "planning database destination must not overlap the planning store"
            )
        try:
            store_identity = self._filesystem_identity(store_root)
            candidate_ancestor_identities = {
                self._filesystem_identity(ancestor)
                for ancestor in (candidate, *candidate.parents)
                if ancestor.exists()
            }
        except OSError as exc:
            raise SuccessorPlanningStoreError(
                "planning store path identity comparison failed"
            ) from exc
        if store_identity in candidate_ancestor_identities:
            raise SuccessorPlanningStoreError(
                "planning database destination must not overlap the planning store"
            )

    @staticmethod
    def _filesystem_identity(path: Path) -> tuple[int, int]:
        observed = os.stat(path, follow_symlinks=False)
        return observed.st_dev, observed.st_ino

    @staticmethod
    def _validate_generation_layout_at(
        generation_descriptor: int,
        *,
        manifest_present: bool,
    ) -> None:
        expected = {_REQUEST_NAME, _CHECKPOINT_NAME}
        if manifest_present:
            expected.add(_MANIFEST_NAME)
        try:
            entries = list(os.scandir(generation_descriptor))
        except OSError as exc:
            raise SuccessorPlanningStoreError("planning generation cannot be scanned") from exc
        if {entry.name for entry in entries} != expected:
            raise SuccessorPlanningStoreError(
                "planning generation layout contains unexpected paths"
            )
        if any(not entry.is_file(follow_symlinks=False) for entry in entries):
            raise SuccessorPlanningStoreError(
                "planning generation control paths must be regular files"
            )
