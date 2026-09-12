"""Concrete two-wave successor planning over retained private store bytes.

This module coordinates an injected planning driver with
``SuccessorPlanningStore``.  The driver owns provider, capture, planning-
database, and manifest construction behavior; this executor owns only exact
store admission, ordered crash recovery, and sealed-evidence verification.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from nbadb.orchestrate import successor_crash_injection as crash_injection
from nbadb.orchestrate.capture_session import PrivateGenerationIdentity
from nbadb.orchestrate.successor_planning_contract import (
    SuccessorPlanningEvidence,
    SuccessorPlanningRequest,
    build_successor_planning_evidence,
)
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningGenerationManifest,
    SealedProviderDispatch,
    SuccessorPlanningWave,
    canonical_planning_sha256,
)
from nbadb.orchestrate.successor_planning_request_builder import (
    SuccessorPlanningRequestBuilderError,
    validate_successor_planning_request,
)
from nbadb.orchestrate.successor_planning_store import (
    CommittedPlanningCall,
    CommittedPlanningMember,
    CommittedPlanningWaveAuthority,
    PlanningDatabaseSource,
    PlanningGenerationPhase,
    PlanningGenerationSnapshot,
    PlanningMemberSource,
    PlanningStoreBudget,
    PlanningWaveAdmission,
    SuccessorPlanningStore,
)
from nbadb.orchestrate.successor_planning_wave_receipt import (
    PlanningWaveCompletionReceipt,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = [
    "ConcreteSuccessorPlanningExecutor",
    "ConcreteSuccessorPlanningError",
    "PlanningCallExecution",
    "PlanningCommittedMemberPayload",
    "PlanningDriverContext",
    "PlanningPrivateGenerationResolver",
    "PlanningWaveSeal",
    "SuccessorPlanningDriver",
    "deterministic_planning_generation_id",
]


class ConcreteSuccessorPlanningError(RuntimeError):
    """Raised when an injected planning result differs from durable authority."""


_MAX_SIGNED_63: Final = (1 << 63) - 1
_DIRECTORY_FLAGS: Final = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_REGULAR_FLAGS: Final = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


def _require_positive_signed63(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1 or value > _MAX_SIGNED_63:
        raise ConcreteSuccessorPlanningError(
            f"{field_name} must be a positive signed-63-bit integer"
        )
    return value


def _require_expected_directory_identity(
    value: object,
    *,
    field_name: str,
) -> tuple[int, int]:
    if (
        type(value) is not tuple
        or len(value) != 2
        or type(value[0]) is not int
        or type(value[1]) is not int
        or value[0] < 0
        or value[1] < 1
    ):
        raise ConcreteSuccessorPlanningError(f"{field_name} must be an exact directory identity")
    return (value[0], value[1])


def _require_owner_only_directory(
    value: object,
    *,
    field_name: str,
) -> tuple[Path, os.stat_result]:
    if not isinstance(value, Path) or not value.is_absolute():
        raise ConcreteSuccessorPlanningError(f"{field_name} must be an absolute Path")
    path = Path(os.path.abspath(value))
    current = Path(path.anchor)
    try:
        for component in path.parts[1:]:
            current /= component
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise ConcreteSuccessorPlanningError(f"{field_name} cannot traverse a symlink")
        observed = os.stat(path, follow_symlinks=False)
    except ConcreteSuccessorPlanningError:
        raise
    except OSError as exc:
        raise ConcreteSuccessorPlanningError(f"{field_name} must exist") from exc
    if not stat.S_ISDIR(observed.st_mode):
        raise ConcreteSuccessorPlanningError(f"{field_name} must be a directory")
    if os.name == "posix" and (
        observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != 0o700
    ):
        raise ConcreteSuccessorPlanningError(f"{field_name} must be owner-only mode 0700")
    return path, observed


def _same_directory_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(left.st_mode)
        and stat.S_ISDIR(right.st_mode)
        and (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)
    )


def _require_named_directory_at(
    parent_descriptor: int,
    name: str,
    descriptor: int,
    expected: os.stat_result,
    *,
    label: str,
) -> None:
    try:
        opened = os.fstat(descriptor)
        named = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise ConcreteSuccessorPlanningError(f"{label} changed identity") from exc
    if not _same_directory_identity(expected, opened) or not _same_directory_identity(
        opened, named
    ):
        raise ConcreteSuccessorPlanningError(f"{label} changed identity")


def _remove_bound_directory_contents(descriptor: int, *, label: str) -> None:
    """Remove only entries whose exact inodes remain bound beneath ``descriptor``."""

    try:
        with os.scandir(descriptor) as scanned:
            entries = tuple(sorted(scanned, key=lambda item: item.name))
    except OSError as exc:
        raise ConcreteSuccessorPlanningError(f"{label} cannot be inventoried for cleanup") from exc
    for entry in entries:
        name = entry.name
        try:
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        except OSError as exc:
            raise ConcreteSuccessorPlanningError(f"{label} changed during cleanup") from exc
        if stat.S_ISDIR(before.st_mode):
            child_descriptor = -1
            try:
                child_descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
                _require_named_directory_at(
                    descriptor,
                    name,
                    child_descriptor,
                    before,
                    label=f"{label} child directory",
                )
                _remove_bound_directory_contents(
                    child_descriptor,
                    label=f"{label}/{name}",
                )
                _require_named_directory_at(
                    descriptor,
                    name,
                    child_descriptor,
                    before,
                    label=f"{label} child directory",
                )
                os.rmdir(name, dir_fd=descriptor)
            except OSError as exc:
                raise ConcreteSuccessorPlanningError(
                    f"{label} child directory cannot be removed safely"
                ) from exc
            finally:
                if child_descriptor >= 0:
                    os.close(child_descriptor)
        elif stat.S_ISREG(before.st_mode):
            file_descriptor = -1
            try:
                file_descriptor = os.open(name, _REGULAR_FLAGS, dir_fd=descriptor)
                opened = os.fstat(file_descriptor)
                named = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
                    or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                ):
                    raise ConcreteSuccessorPlanningError(
                        f"{label} regular file changed during cleanup"
                    )
                os.unlink(name, dir_fd=descriptor)
            except OSError as exc:
                raise ConcreteSuccessorPlanningError(
                    f"{label} regular file cannot be removed safely"
                ) from exc
            finally:
                if file_descriptor >= 0:
                    os.close(file_descriptor)
        else:
            raise ConcreteSuccessorPlanningError(f"{label} contains a non-regular cleanup entry")


def deterministic_planning_generation_id(request: SuccessorPlanningRequest) -> str:
    """Return one domain-separated safe generation token for an exact request."""

    if not isinstance(request, SuccessorPlanningRequest):
        raise ConcreteSuccessorPlanningError(
            "planning generation identity requires a SuccessorPlanningRequest"
        )
    identity = canonical_planning_sha256(
        {
            "domain": "nbadb.concrete-successor-planner.generation.v2",
            "planning_request_sha256": request.identity_sha256,
        }
    )
    return f"successor-planning-v2-{identity}"


@dataclass(frozen=True, slots=True)
class PlanningCommittedMemberPayload:
    """One descriptor-safely reloaded committed member for driver derivation."""

    call_identity_sha256: str
    committed: CommittedPlanningMember
    encoded: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.committed, CommittedPlanningMember):
            raise ConcreteSuccessorPlanningError("committed member payload is invalid")
        if not isinstance(self.encoded, bytes):
            raise ConcreteSuccessorPlanningError("committed member payload must be bytes")
        if hashlib.sha256(self.encoded).hexdigest() != self.committed.artifact_sha256:
            raise ConcreteSuccessorPlanningError(
                "committed member payload digest differs from store authority"
            )


@dataclass(frozen=True, slots=True)
class PlanningDriverContext:
    """Ephemeral verified inputs for one driver operation.

    ``planning_database`` points only to a unique executor-owned private copy.
    It remains valid for the duration of the driver call and its immediate
    store commit, then the executor removes the temporary directory.
    """

    request: SuccessorPlanningRequest
    planning_generation_id: str
    snapshot: PlanningGenerationSnapshot
    committed_member_payloads: tuple[PlanningCommittedMemberPayload, ...]
    planning_database: PlanningDatabaseSource | None
    private_work_root: Path

    def __post_init__(self) -> None:
        if self.snapshot.request.to_dict() != self.request.to_dict():
            raise ConcreteSuccessorPlanningError("driver context request differs from the store")
        if self.snapshot.planning_generation_id != self.planning_generation_id:
            raise ConcreteSuccessorPlanningError("driver context generation differs from the store")
        work_root = Path(self.private_work_root)
        if not work_root.is_absolute():
            raise ConcreteSuccessorPlanningError("driver private work root must be absolute")
        try:
            observed_root = os.stat(work_root, follow_symlinks=False)
        except OSError as exc:
            raise ConcreteSuccessorPlanningError("driver private work root must exist") from exc
        if (
            not stat.S_ISDIR(observed_root.st_mode)
            or work_root.is_symlink()
            or (
                os.name == "posix"
                and (
                    observed_root.st_uid != os.geteuid()
                    or stat.S_IMODE(observed_root.st_mode) != 0o700
                )
            )
        ):
            raise ConcreteSuccessorPlanningError(
                "driver private work root must be an owner-only regular directory"
            )
        object.__setattr__(self, "private_work_root", work_root)
        expected_members = tuple(
            (call.identity_sha256, member.member.identity_sha256)
            for call in self.snapshot.committed_calls
            for member in call.members
        )
        observed_members = tuple(
            (payload.call_identity_sha256, payload.committed.member.identity_sha256)
            for payload in self.committed_member_payloads
        )
        if observed_members != expected_members:
            raise ConcreteSuccessorPlanningError(
                "driver context member bytes differ from the committed inventory"
            )
        database_present = self.snapshot.planning_database_sha256 is not None
        if database_present != (self.planning_database is not None):
            raise ConcreteSuccessorPlanningError(
                "driver context database differs from the committed inventory"
            )
        if self.planning_database is not None and (
            self.planning_database.artifact.sha256 != self.snapshot.planning_database_sha256
            or self.planning_database.artifact.byte_count != self.snapshot.planning_database_bytes
            or self.planning_database.schema_sha256 != self.snapshot.planning_database_schema_sha256
        ):
            raise ConcreteSuccessorPlanningError(
                "driver context database copy differs from store authority"
            )


@dataclass(frozen=True, slots=True)
class PlanningCallExecution:
    """Already-persisted opaque outputs of one idempotent logical call."""

    members: tuple[PlanningMemberSource, ...]
    planning_database: PlanningDatabaseSource

    def __post_init__(self) -> None:
        if not self.members or any(
            not isinstance(member, PlanningMemberSource) for member in self.members
        ):
            raise ConcreteSuccessorPlanningError(
                "planning call execution requires nonempty member sources"
            )
        if not isinstance(self.planning_database, PlanningDatabaseSource):
            raise ConcreteSuccessorPlanningError(
                "planning call execution requires an opaque database source"
            )


@dataclass(frozen=True, slots=True)
class PlanningWaveSeal:
    """One completed wave plus its retained private Bronze authority."""

    wave: SuccessorPlanningWave
    private_generation_identity: PrivateGenerationIdentity
    completion_receipt: PlanningWaveCompletionReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.wave, SuccessorPlanningWave):
            raise ConcreteSuccessorPlanningError("planning wave seal has an invalid wave")
        if not isinstance(self.private_generation_identity, PrivateGenerationIdentity):
            raise ConcreteSuccessorPlanningError(
                "planning wave seal has an invalid private generation identity"
            )
        if not isinstance(self.completion_receipt, PlanningWaveCompletionReceipt):
            raise ConcreteSuccessorPlanningError(
                "planning wave seal has an invalid completion receipt"
            )
        if (
            self.completion_receipt.private_generation_identity.canonical_bytes
            != self.private_generation_identity.canonical_bytes
            or self.completion_receipt.wave_index != self.wave.wave_index
            or self.completion_receipt.parent_wave_identity_sha256
            != self.wave.parent_wave_identity_sha256
        ):
            raise ConcreteSuccessorPlanningError(
                "planning wave seal authorities do not describe the same wave"
            )
        if (
            hashlib.sha256(self.private_generation_identity.canonical_bytes).hexdigest()
            != self.wave.private_generation_identity_sha256
        ):
            raise ConcreteSuccessorPlanningError(
                "planning wave seal private identity differs from the wave"
            )
        if (
            hashlib.sha256(self.completion_receipt.canonical_bytes).hexdigest()
            != self.wave.completion_receipt_sha256
        ):
            raise ConcreteSuccessorPlanningError(
                "planning wave seal completion receipt differs from the wave"
            )


class PlanningPrivateGenerationResolver(Protocol):
    """Re-inventory one retained Bronze generation without trusting store bytes."""

    def verify(
        self,
        *,
        request: SuccessorPlanningRequest,
        planning_generation_id: str,
        authority: CommittedPlanningWaveAuthority,
    ) -> PrivateGenerationIdentity: ...


class SuccessorPlanningDriver(Protocol):
    """Injected owner of exact provider/capture/database planning behavior."""

    async def derive_wave(
        self,
        context: PlanningDriverContext,
        wave_index: int,
    ) -> PlanningWaveAdmission: ...

    async def execute_call(
        self,
        context: PlanningDriverContext,
        admission: PlanningWaveAdmission,
        dispatch: SealedProviderDispatch,
    ) -> PlanningCallExecution: ...

    async def seal_wave(
        self,
        context: PlanningDriverContext,
        admission: PlanningWaveAdmission,
    ) -> PlanningWaveSeal: ...

    async def derive_manifest(
        self,
        context: PlanningDriverContext,
    ) -> PlanningGenerationManifest: ...


class ConcreteSuccessorPlanningExecutor:
    """Execute or resume exactly one deterministic two-wave planning generation."""

    def __init__(
        self,
        store: SuccessorPlanningStore,
        driver: SuccessorPlanningDriver,
        private_generation_resolver: PlanningPrivateGenerationResolver,
        fresh_budget: Callable[[], PlanningStoreBudget],
        planning_driver_database_max_bytes: int,
        planning_work_root: Path,
        expected_planning_work_root_identity: tuple[int, int],
    ) -> None:
        if not isinstance(store, SuccessorPlanningStore):
            raise ConcreteSuccessorPlanningError("store must be a SuccessorPlanningStore")
        if not callable(fresh_budget):
            raise ConcreteSuccessorPlanningError("fresh_budget must be callable")
        for method_name in ("derive_wave", "execute_call", "seal_wave", "derive_manifest"):
            if not callable(getattr(driver, method_name, None)):
                raise ConcreteSuccessorPlanningError(f"planning driver is missing {method_name}")
        if not callable(getattr(private_generation_resolver, "verify", None)):
            raise ConcreteSuccessorPlanningError("private generation resolver is missing verify")
        self._store = store
        self._driver = driver
        self._private_generation_resolver = private_generation_resolver
        self._fresh_budget_factory = fresh_budget
        self._planning_driver_database_max_bytes = _require_positive_signed63(
            planning_driver_database_max_bytes,
            field_name="planning_driver_database_max_bytes",
        )
        work_root, work_stat = _require_owner_only_directory(
            planning_work_root,
            field_name="planning_work_root",
        )
        work_identity = _require_expected_directory_identity(
            expected_planning_work_root_identity,
            field_name="expected_planning_work_root_identity",
        )
        if (work_stat.st_dev, work_stat.st_ino) != work_identity:
            raise ConcreteSuccessorPlanningError(
                "planning_work_root differs from its expected identity"
            )
        work_parts = tuple(part.casefold() for part in work_root.parts)
        store_parts = tuple(part.casefold() for part in self._store.root.parts)
        if (
            work_parts[: len(store_parts)] == store_parts
            or store_parts[: len(work_parts)] == work_parts
        ):
            raise ConcreteSuccessorPlanningError(
                "planning_work_root must not overlap the planning store"
            )
        self._planning_work_root = work_root
        self._expected_planning_work_root_identity = work_identity

    async def __call__(
        self,
        request: SuccessorPlanningRequest,
    ) -> SuccessorPlanningEvidence:
        """Build or resume the exact request-bound planning generation."""

        if not isinstance(request, SuccessorPlanningRequest):
            raise ConcreteSuccessorPlanningError("request must be a SuccessorPlanningRequest")
        self._require_current_request(request)
        generation_id = deterministic_planning_generation_id(request)
        snapshot = self._verify_snapshot_authorities(
            request,
            generation_id,
            self._store.begin_generation(
                request,
                generation_id,
                budget=self._budget(),
            ),
        )
        if snapshot.phase is PlanningGenerationPhase.SEALED:
            return self._sealed_evidence(request, generation_id)

        if snapshot.phase is PlanningGenerationPhase.BUILDING:
            await self._execute_wave(request, generation_id, wave_index=0)
            snapshot = self._load(request, generation_id)
        if snapshot.phase is PlanningGenerationPhase.WAVE_0_COMMITTED:
            await self._execute_wave(request, generation_id, wave_index=1)
            snapshot = self._load(request, generation_id)
        if snapshot.phase is PlanningGenerationPhase.WAVE_1_COMMITTED:
            with self._driver_context(request, generation_id) as context:
                manifest = await self._driver.derive_manifest(context)
                if not isinstance(manifest, PlanningGenerationManifest):
                    raise ConcreteSuccessorPlanningError(
                        "planning driver did not return a PlanningGenerationManifest"
                    )
                provisional = build_successor_planning_evidence(
                    planning_generation_manifest=manifest
                )
                provisional.execution_plan.validate_against_manifest(manifest)
                self._verify_snapshot_authorities(
                    request,
                    generation_id,
                    self._store.seal_generation(
                        request,
                        generation_id,
                        manifest=manifest,
                        budget=self._budget(),
                    ),
                )

        return self._sealed_evidence(request, generation_id)

    def verify(
        self,
        request: SuccessorPlanningRequest,
        evidence: SuccessorPlanningEvidence,
    ) -> SuccessorPlanningEvidence:
        """Reload sealed store authority without invoking any driver method."""

        if not isinstance(request, SuccessorPlanningRequest):
            raise ConcreteSuccessorPlanningError("request must be a SuccessorPlanningRequest")
        self._require_current_request(request)
        if not isinstance(evidence, SuccessorPlanningEvidence):
            raise ConcreteSuccessorPlanningError(
                "supplied evidence must be SuccessorPlanningEvidence"
            )
        generation_id = deterministic_planning_generation_id(request)
        if (
            evidence.planning_generation_manifest.artifact_identity.planning_generation_id
            != generation_id
        ):
            raise ConcreteSuccessorPlanningError(
                "supplied evidence generation differs from the deterministic request generation"
            )
        verified = self._sealed_evidence(request, generation_id)
        if verified.to_dict() != evidence.to_dict():
            raise ConcreteSuccessorPlanningError(
                "supplied planning evidence differs from the sealed store generation"
            )
        return verified

    @staticmethod
    def _require_current_request(request: SuccessorPlanningRequest) -> None:
        try:
            validated = validate_successor_planning_request(request)
        except SuccessorPlanningRequestBuilderError as exc:
            raise ConcreteSuccessorPlanningError(
                "planning request differs from current exact builder authority"
            ) from exc
        if validated.to_dict() != request.to_dict():
            raise ConcreteSuccessorPlanningError(
                "planning request validation returned different authority"
            )

    async def _execute_wave(
        self,
        request: SuccessorPlanningRequest,
        generation_id: str,
        *,
        wave_index: int,
    ) -> None:
        with self._driver_context(request, generation_id) as context:
            admission = await self._driver.derive_wave(context, wave_index)
        if not isinstance(admission, PlanningWaveAdmission):
            raise ConcreteSuccessorPlanningError(
                "planning driver did not return a PlanningWaveAdmission"
            )
        if admission.wave_index != wave_index:
            raise ConcreteSuccessorPlanningError("planning driver returned the wrong wave index")
        snapshot = self._verify_snapshot_authorities(
            request,
            generation_id,
            self._store.begin_wave(
                request,
                generation_id,
                admission=admission,
                budget=self._budget(),
            ),
        )
        committed = tuple(
            call for call in snapshot.committed_calls if call.wave_index == wave_index
        )
        self._require_committed_prefix(committed, admission)
        for dispatch in admission.sealed_dispatches[len(committed) :]:
            with self._driver_context(request, generation_id) as context:
                result = await self._driver.execute_call(context, admission, dispatch)
                if not isinstance(result, PlanningCallExecution):
                    raise ConcreteSuccessorPlanningError(
                        "planning driver did not return PlanningCallExecution"
                    )
                self._require_driver_database_bound(
                    result.planning_database,
                    label="planning driver output database",
                )
                self._require_private_call_sources(context, result)
                snapshot = self._verify_snapshot_authorities(
                    request,
                    generation_id,
                    self._store.commit_call(
                        request,
                        generation_id,
                        sealed_dispatch_identity_sha256=dispatch.identity_sha256,
                        members=result.members,
                        planning_database=result.planning_database,
                        budget=self._budget(),
                    ),
                )
            committed = tuple(
                call for call in snapshot.committed_calls if call.wave_index == wave_index
            )
            self._require_committed_prefix(committed, admission)

        with self._driver_context(request, generation_id) as context:
            if context.planning_database is None:
                raise ConcreteSuccessorPlanningError(
                    "completed planning wave has no committed database"
                )
            seal = await self._driver.seal_wave(context, admission)
            if not isinstance(seal, PlanningWaveSeal):
                raise ConcreteSuccessorPlanningError(
                    "planning driver did not return a PlanningWaveSeal"
                )
            crash_injection.after_durable_step(
                crash_injection.DurablePlanningStep.PRIVATE_SEAL,
                planning_generation_id=generation_id,
                wave_index=admission.wave_index,
                private_generation_identity_sha256=(
                    seal.private_generation_identity.identity_sha256
                ),
            )
            self._verify_snapshot_authorities(
                request,
                generation_id,
                self._store.commit_wave(
                    request,
                    generation_id,
                    wave=seal.wave,
                    planning_database=context.planning_database,
                    private_generation_identity=seal.private_generation_identity,
                    completion_receipt=seal.completion_receipt,
                    budget=self._budget(),
                ),
            )

    @staticmethod
    def _require_committed_prefix(
        committed: tuple[CommittedPlanningCall, ...],
        admission: PlanningWaveAdmission,
    ) -> None:
        observed = tuple(call.sealed_dispatch.identity_sha256 for call in committed)
        expected = tuple(
            dispatch.identity_sha256 for dispatch in admission.sealed_dispatches[: len(observed)]
        )
        if observed != expected or len(observed) > len(admission.sealed_dispatches):
            raise ConcreteSuccessorPlanningError(
                "committed planning calls differ from the admitted dispatch prefix"
            )

    @staticmethod
    def _require_private_call_sources(
        context: PlanningDriverContext,
        result: PlanningCallExecution,
    ) -> None:
        root = context.private_work_root.resolve(strict=True)
        sources = (
            *(member.artifact for member in result.members),
            result.planning_database.artifact,
        )
        for source in sources:
            try:
                resolved = source.path.resolve(strict=True)
            except OSError as exc:
                raise ConcreteSuccessorPlanningError(
                    "planning driver returned an unreadable private source"
                ) from exc
            if not resolved.is_relative_to(root):
                raise ConcreteSuccessorPlanningError(
                    "planning driver source falls outside its private work root"
                )

    def _require_driver_database_bound(
        self,
        database: PlanningDatabaseSource,
        *,
        label: str,
    ) -> None:
        if not isinstance(database, PlanningDatabaseSource):
            raise ConcreteSuccessorPlanningError(f"{label} is invalid")
        if database.artifact.byte_count > self._planning_driver_database_max_bytes:
            raise ConcreteSuccessorPlanningError(
                f"{label} exceeds planning_driver_database_max_bytes"
            )

    def _sealed_evidence(
        self,
        request: SuccessorPlanningRequest,
        generation_id: str,
    ) -> SuccessorPlanningEvidence:
        snapshot = self._load(request, generation_id)
        if snapshot.phase is not PlanningGenerationPhase.SEALED or snapshot.manifest is None:
            raise ConcreteSuccessorPlanningError("planning generation is not durably sealed")
        manifest = PlanningGenerationManifest.from_canonical_bytes(
            snapshot.manifest.canonical_bytes
        )
        if manifest.request.to_dict() != request.to_dict():
            raise ConcreteSuccessorPlanningError("sealed planning request differs")
        if manifest.artifact_identity.planning_generation_id != generation_id:
            raise ConcreteSuccessorPlanningError("sealed planning generation id differs")
        evidence = build_successor_planning_evidence(planning_generation_manifest=manifest)
        evidence.execution_plan.validate_against_manifest(manifest)
        return evidence

    def _load(
        self,
        request: SuccessorPlanningRequest,
        generation_id: str,
    ) -> PlanningGenerationSnapshot:
        return self._verify_snapshot_authorities(
            request,
            generation_id,
            self._store.load_and_verify(
                request,
                generation_id,
                budget=self._budget(),
            ),
        )

    def _verify_snapshot_authorities(
        self,
        request: SuccessorPlanningRequest,
        generation_id: str,
        snapshot: PlanningGenerationSnapshot,
    ) -> PlanningGenerationSnapshot:
        """Re-inventory every committed private wave before trusting a snapshot."""

        if not isinstance(snapshot, PlanningGenerationSnapshot):
            raise ConcreteSuccessorPlanningError("planning store returned an invalid snapshot")
        if (
            snapshot.request.to_dict() != request.to_dict()
            or snapshot.planning_generation_id != generation_id
        ):
            raise ConcreteSuccessorPlanningError(
                "planning snapshot differs from its request or generation"
            )
        for call in snapshot.committed_calls:
            if call.planning_database_bytes > self._planning_driver_database_max_bytes:
                raise ConcreteSuccessorPlanningError(
                    "committed planning database exceeds planning_driver_database_max_bytes"
                )
        if (
            snapshot.planning_database_bytes is not None
            and snapshot.planning_database_bytes > self._planning_driver_database_max_bytes
        ):
            raise ConcreteSuccessorPlanningError(
                "current planning database exceeds planning_driver_database_max_bytes"
            )
        count = len(snapshot.committed_waves)
        if (
            len(snapshot.committed_wave_admissions) != count
            or len(snapshot.committed_wave_authorities) != count
        ):
            raise ConcreteSuccessorPlanningError(
                "planning snapshot wave authority inventories differ"
            )
        for index, (wave, admission, authority) in enumerate(
            zip(
                snapshot.committed_waves,
                snapshot.committed_wave_admissions,
                snapshot.committed_wave_authorities,
                strict=True,
            )
        ):
            if (
                wave.wave_index != index
                or admission.wave_index != index
                or authority.wave_index != index
            ):
                raise ConcreteSuccessorPlanningError(
                    "planning snapshot wave authority indexes differ"
                )
            resolved = self._private_generation_resolver.verify(
                request=request,
                planning_generation_id=generation_id,
                authority=authority,
            )
            if not isinstance(resolved, PrivateGenerationIdentity):
                raise ConcreteSuccessorPlanningError(
                    "private generation resolver returned an invalid identity"
                )
            if resolved.canonical_bytes != authority.private_generation_identity.canonical_bytes:
                raise ConcreteSuccessorPlanningError(
                    "retained private generation differs from store authority"
                )
        if snapshot.active_wave is not None and snapshot.active_wave.wave_index != count:
            raise ConcreteSuccessorPlanningError(
                "active planning wave has committed private authority"
            )
        return snapshot

    @contextmanager
    def _driver_context(
        self,
        request: SuccessorPlanningRequest,
        generation_id: str,
    ) -> Iterator[PlanningDriverContext]:
        self._require_current_planning_work_root()
        with self._authorized_driver_work_directory() as temporary_root:
            self._require_current_planning_work_root()
            exported = self._store.export_driver_context(
                request,
                generation_id,
                destination=temporary_root / "planning.duckdb",
                planning_database_max_bytes=self._planning_driver_database_max_bytes,
                budget=self._budget(),
            )
            if exported.planning_database is not None:
                self._require_driver_database_bound(
                    exported.planning_database,
                    label="planning driver input database",
                )
            committed_by_identity = {
                (call.identity_sha256, member.member.identity_sha256): member
                for call in exported.snapshot.committed_calls
                for member in call.members
            }
            member_payloads = tuple(
                PlanningCommittedMemberPayload(
                    call_identity_sha256=call_identity,
                    committed=committed_by_identity[(call_identity, member_identity)],
                    encoded=encoded,
                )
                for call_identity, member_identity, encoded in exported.committed_member_bytes
            )
            try:
                yield PlanningDriverContext(
                    request=request,
                    planning_generation_id=generation_id,
                    snapshot=exported.snapshot,
                    committed_member_payloads=member_payloads,
                    planning_database=exported.planning_database,
                    private_work_root=temporary_root,
                )
            finally:
                self._require_current_planning_work_root()
        self._require_current_planning_work_root()

    @contextmanager
    def _authorized_driver_work_directory(self) -> Iterator[Path]:
        """Create and clean one temp tree through its admitted parent descriptor."""

        self._require_current_planning_work_root()
        root_descriptor = -1
        temporary_descriptor = -1
        temporary_name: str | None = None
        temporary_stat: os.stat_result | None = None
        cleanup_error: Exception | None = None
        try:
            root_descriptor = os.open(self._planning_work_root, _DIRECTORY_FLAGS)
            root_stat = os.fstat(root_descriptor)
            if (root_stat.st_dev, root_stat.st_ino) != self._expected_planning_work_root_identity:
                raise ConcreteSuccessorPlanningError("planning_work_root changed identity")
            if os.name == "posix" and (
                root_stat.st_uid != os.geteuid() or stat.S_IMODE(root_stat.st_mode) != 0o700
            ):
                raise ConcreteSuccessorPlanningError(
                    "planning_work_root must remain owner-only mode 0700"
                )
            for _attempt in range(32):
                candidate = f".successor-planner-context-{secrets.token_hex(16)}"
                try:
                    os.mkdir(candidate, mode=0o700, dir_fd=root_descriptor)
                except FileExistsError:
                    continue
                temporary_name = candidate
                break
            if temporary_name is None:
                raise ConcreteSuccessorPlanningError(
                    "planning driver work directory cannot obtain a unique name"
                )
            temporary_descriptor = os.open(
                temporary_name,
                _DIRECTORY_FLAGS,
                dir_fd=root_descriptor,
            )
            os.fchmod(temporary_descriptor, 0o700)
            temporary_stat = os.fstat(temporary_descriptor)
            _require_named_directory_at(
                root_descriptor,
                temporary_name,
                temporary_descriptor,
                temporary_stat,
                label="planning driver work directory",
            )
            yield self._planning_work_root / temporary_name
        finally:
            if (
                temporary_descriptor >= 0
                and temporary_name is not None
                and temporary_stat is not None
            ):
                try:
                    _remove_bound_directory_contents(
                        temporary_descriptor,
                        label="planning driver work directory",
                    )
                    _require_named_directory_at(
                        root_descriptor,
                        temporary_name,
                        temporary_descriptor,
                        temporary_stat,
                        label="planning driver work directory",
                    )
                    os.rmdir(temporary_name, dir_fd=root_descriptor)
                    os.fsync(root_descriptor)
                except Exception as exc:
                    cleanup_error = exc
            if temporary_descriptor >= 0:
                os.close(temporary_descriptor)
            if root_descriptor >= 0:
                os.close(root_descriptor)
            if cleanup_error is not None:
                raise ConcreteSuccessorPlanningError(
                    "planning driver work directory cleanup was refused"
                ) from cleanup_error

    def _require_current_planning_work_root(self) -> None:
        _path, observed = _require_owner_only_directory(
            self._planning_work_root,
            field_name="planning_work_root",
        )
        if (observed.st_dev, observed.st_ino) != self._expected_planning_work_root_identity:
            raise ConcreteSuccessorPlanningError("planning_work_root changed identity")

    def _budget(self) -> PlanningStoreBudget:
        budget = self._fresh_budget_factory()
        if not isinstance(budget, PlanningStoreBudget):
            raise ConcreteSuccessorPlanningError(
                "fresh_budget did not return a PlanningStoreBudget"
            )
        return budget
