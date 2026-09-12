"""Exact aggregate filesystem admission for one recurring successor.

The persisted successor admission is deliberately path-free.  This module
binds each closed storage role to the directory descriptor that will serve it
at runtime, projects the persisted worst-case byte contract onto the observed
devices, and applies the free-space floor once per device.  The returned
observation is volatile diagnostics only; it is never durable authority.
"""

from __future__ import annotations

import math
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from nbadb.orchestrate.successor_coordinator import (
    SuccessorCandidateAdmission,
    SuccessorCoordinatorError,
)

__all__ = [
    "AggregateCapacityDeviceObservation",
    "AggregateCapacityObservation",
    "AggregateCapacityRootObservation",
    "CapacityRoot",
    "ExactSuccessorAggregateCapacityAuthority",
    "SuccessorAggregateCapacityError",
    "SuccessorCapacityRole",
]

_MAX_SIGNED_63: Final = (1 << 63) - 1
_PRIVATE_DIRECTORY_MODE: Final = 0o700
_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY: Final = getattr(os, "O_DIRECTORY", 0)
_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)
_DIRECTORY_FLAGS: Final = os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC | _NONBLOCK


class SuccessorAggregateCapacityError(RuntimeError):
    """Raised when aggregate capacity authority cannot be proved exactly."""


class SuccessorCapacityRole(StrEnum):
    """Closed runtime storage roles covered by aggregate admission."""

    GENERATION_STORE = "generation_store"
    COORDINATOR_CHECKPOINT = "coordinator_checkpoint"
    PLANNING_STORE = "planning_store"
    PLANNING_WORK = "planning_work"
    PLANNING_CAPTURE = "planning_capture"
    BODY_BLOB = "body_blob"
    DECLARED_BODYLESS_PACKET = "declared_bodyless_packet"
    UPDATE_CAPTURE = "update_capture"
    TERMINAL_RECEIPT = "terminal_receipt"
    RUNTIME_LOG = "runtime_log"
    ASSURANCE_SCRATCH = "assurance_scratch"


_REQUIRED_ROLES: Final = tuple(SuccessorCapacityRole)

type ExistingBytesCallback = Callable[[int], int]
type DescriptorCapacityProbe = Callable[[int, "CapacityRoot"], tuple[int, int]]


@dataclass(frozen=True, slots=True)
class CapacityRoot:
    """One exact runtime directory bound to a closed capacity role.

    ``existing_bytes_callback`` is caller-trusted measurement logic.  It is
    given the already-open root descriptor and must return a nonnegative
    signed-63-bit byte count.  The authority brackets the callback with open
    and named directory snapshots, so a changing measurement root fails the
    admission even though the callback implementation itself is injected.
    """

    role: SuccessorCapacityRole
    path: Path
    expected_identity: tuple[int, int]
    existing_bytes_callback: ExistingBytesCallback | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, SuccessorCapacityRole):
            raise SuccessorAggregateCapacityError("capacity root role is invalid")
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise SuccessorAggregateCapacityError(
                f"{self.role.value} capacity root must be an absolute Path"
            )
        identity = self.expected_identity
        if (
            type(identity) is not tuple
            or len(identity) != 2
            or type(identity[0]) is not int
            or type(identity[1]) is not int
            or identity[0] < 0
            or identity[1] < 1
        ):
            raise SuccessorAggregateCapacityError(f"{self.role.value} expected identity is invalid")
        if self.existing_bytes_callback is not None and not callable(self.existing_bytes_callback):
            raise SuccessorAggregateCapacityError(
                f"{self.role.value} existing-byte callback must be callable"
            )


@dataclass(frozen=True, slots=True)
class AggregateCapacityRootObservation:
    """Volatile path-free observation for one admitted role."""

    role: SuccessorCapacityRole
    device_id: int
    existing_bytes: int
    peak_additional_bytes: int


@dataclass(frozen=True, slots=True)
class AggregateCapacityDeviceObservation:
    """Volatile aggregate requirement and free-space sample for one device."""

    device_id: int
    roles: tuple[SuccessorCapacityRole, ...]
    peak_additional_bytes: int
    minimum_free_bytes: int
    required_free_bytes: int
    observed_free_bytes: int


@dataclass(frozen=True, slots=True)
class AggregateCapacityObservation:
    """Successful volatile capacity diagnostics, never resume authority."""

    stage: str
    monotonic_sample_before_seconds: float
    monotonic_sample_after_seconds: float
    monotonic_deadline_seconds: float
    minimum_required_headroom_seconds: float
    remaining_headroom_seconds: float
    roots: tuple[AggregateCapacityRootObservation, ...]
    devices: tuple[AggregateCapacityDeviceObservation, ...]


@dataclass(frozen=True, slots=True)
class _DirectorySnapshot:
    device: int
    inode: int
    mode: int
    link_count: int
    owner: int
    group: int
    size: int
    modified_ns: int
    changed_ns: int

    @classmethod
    def from_stat(cls, observed: os.stat_result) -> _DirectorySnapshot:
        return cls(
            device=observed.st_dev,
            inode=observed.st_ino,
            mode=observed.st_mode,
            link_count=observed.st_nlink,
            owner=observed.st_uid,
            group=observed.st_gid,
            size=observed.st_size,
            modified_ns=observed.st_mtime_ns,
            changed_ns=observed.st_ctime_ns,
        )


@dataclass(slots=True)
class _OpenedCapacityRoot:
    root: CapacityRoot
    descriptor: int
    snapshot: _DirectorySnapshot
    existing_bytes: int = 0
    first_probe: tuple[int, int] | None = None


def _require_nonnegative_signed63(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0 or value > _MAX_SIGNED_63:
        raise SuccessorAggregateCapacityError(
            f"{label} must be a nonnegative signed-63-bit integer"
        )
    return value


def _checked_sum(*values: int, label: str) -> int:
    total = 0
    for value in values:
        checked = _require_nonnegative_signed63(value, label=label)
        if checked > _MAX_SIGNED_63 - total:
            raise SuccessorAggregateCapacityError(f"{label} exceeds signed-63-bit range")
        total += checked
    return total


def _checked_product(left: int, right: int, *, label: str) -> int:
    first = _require_nonnegative_signed63(left, label=label)
    second = _require_nonnegative_signed63(right, label=label)
    if first and second > _MAX_SIGNED_63 // first:
        raise SuccessorAggregateCapacityError(f"{label} exceeds signed-63-bit range")
    return first * second


def _remaining(maximum: int, existing: int) -> int:
    return max(0, maximum - existing)


def _default_descriptor_probe(
    descriptor: int,
    _root: CapacityRoot,
) -> tuple[int, int]:
    try:
        opened = os.fstat(descriptor)
        filesystem = os.fstatvfs(descriptor)
    except OSError as exc:
        raise SuccessorAggregateCapacityError(
            "capacity filesystem probe could not inspect a root descriptor"
        ) from exc
    fragment_size = filesystem.f_frsize or filesystem.f_bsize
    fragment_size = _require_nonnegative_signed63(
        fragment_size,
        label="filesystem fragment size",
    )
    if fragment_size == 0:
        raise SuccessorAggregateCapacityError("filesystem fragment size must be positive")
    available_blocks = _require_nonnegative_signed63(
        filesystem.f_bavail,
        label="filesystem available blocks",
    )
    free_bytes = _checked_product(
        fragment_size,
        available_blocks,
        label="filesystem free bytes",
    )
    return opened.st_dev, free_bytes


def _require_stage(stage: object) -> str:
    if (
        not isinstance(stage, str)
        or not 1 <= len(stage) <= 128
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-"
            for character in stage
        )
    ):
        raise SuccessorAggregateCapacityError("capacity admission stage is invalid")
    return stage


def _require_clock_sample(value: object, *, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
    ):
        raise SuccessorAggregateCapacityError(f"{label} must be finite and nonnegative")
    return float(value)


def _require_epoch(value: object, *, expected: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SuccessorAggregateCapacityError(
            "monotonic epoch authority must return a lowercase SHA-256"
        )
    if value != expected:
        raise SuccessorAggregateCapacityError("monotonic epoch authority changed")
    return value


def _snapshot_named(path: Path, *, role: SuccessorCapacityRole) -> _DirectorySnapshot:
    try:
        observed = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorAggregateCapacityError(
            f"{role.value} capacity root cannot be inspected by name"
        ) from exc
    return _DirectorySnapshot.from_stat(observed)


def _snapshot_descriptor(
    descriptor: int,
    *,
    role: SuccessorCapacityRole,
) -> _DirectorySnapshot:
    try:
        observed = os.fstat(descriptor)
    except OSError as exc:
        raise SuccessorAggregateCapacityError(
            f"{role.value} capacity root descriptor cannot be inspected"
        ) from exc
    return _DirectorySnapshot.from_stat(observed)


@dataclass(frozen=True, slots=True)
class ExactSuccessorAggregateCapacityAuthority:
    """Immutable aggregate capacity and monotonic-epoch authority.

    Every call reopens all roots, revalidates their captured identities,
    samples each descriptor-backed filesystem twice, and rejects free-space or
    root drift.  ``descriptor_probe`` is a trusted platform seam used by
    deterministic tests; production callers use the ``fstatvfs`` default.
    """

    admission: SuccessorCandidateAdmission
    roots: tuple[CapacityRoot, ...]
    monotonic_clock: Callable[[], float]
    monotonic_epoch_authority: Callable[[], str]
    descriptor_probe: DescriptorCapacityProbe = field(
        default=_default_descriptor_probe,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.admission, SuccessorCandidateAdmission):
            raise SuccessorAggregateCapacityError(
                "capacity authority admission must be SuccessorCandidateAdmission"
            )
        try:
            admission = SuccessorCandidateAdmission.from_dict(self.admission.to_dict())
        except (AttributeError, SuccessorCoordinatorError, TypeError, ValueError) as exc:
            raise SuccessorAggregateCapacityError(
                "capacity authority admission contract is invalid"
            ) from exc
        object.__setattr__(self, "admission", admission)
        roots = tuple(self.roots)
        object.__setattr__(self, "roots", roots)
        if any(not isinstance(root, CapacityRoot) for root in roots):
            raise SuccessorAggregateCapacityError("capacity roots are invalid")
        observed_roles = tuple(root.role for root in roots)
        if (
            len(observed_roles) != len(_REQUIRED_ROLES)
            or len(set(observed_roles)) != len(observed_roles)
            or set(observed_roles) != set(_REQUIRED_ROLES)
        ):
            raise SuccessorAggregateCapacityError(
                "capacity authority requires exactly one root for every closed role"
            )
        by_role = {root.role: root for root in roots}
        object.__setattr__(
            self,
            "roots",
            tuple(by_role[role] for role in _REQUIRED_ROLES),
        )
        if not callable(self.monotonic_clock):
            raise SuccessorAggregateCapacityError("monotonic clock must be callable")
        if not callable(self.monotonic_epoch_authority):
            raise SuccessorAggregateCapacityError("monotonic epoch authority must be callable")
        if not callable(self.descriptor_probe):
            raise SuccessorAggregateCapacityError("descriptor probe must be callable")
        contract = admission.aggregate_capacity
        if contract.candidate_max_bytes < contract.baseline_installed_public_tree_bytes:
            raise SuccessorAggregateCapacityError(
                "candidate bound is smaller than the installed baseline"
            )
        self._peak_by_role(existing_by_role={role: 0 for role in _REQUIRED_ROLES})
        self._current_epoch()

    def _current_epoch(self) -> str:
        try:
            observed = self.monotonic_epoch_authority()
        except Exception as exc:
            raise SuccessorAggregateCapacityError(
                "monotonic epoch authority could not be sampled"
            ) from exc
        return _require_epoch(
            observed,
            expected=self.admission.monotonic_epoch_sha256,
        )

    def _clock_sample(self, *, label: str) -> float:
        try:
            observed = self.monotonic_clock()
        except Exception as exc:
            raise SuccessorAggregateCapacityError(
                f"{label} could not sample the monotonic clock"
            ) from exc
        return _require_clock_sample(observed, label=label)

    def _require_deadline(self, observed: float, *, stage: str) -> None:
        remaining = self.admission.monotonic_deadline_seconds - observed
        if remaining < self.admission.minimum_pre_provider_headroom_seconds:
            raise SuccessorAggregateCapacityError(
                f"aggregate capacity deadline headroom is insufficient at {stage}"
            )

    @staticmethod
    def _require_private_snapshot(
        root: CapacityRoot,
        snapshot: _DirectorySnapshot,
    ) -> None:
        if not stat.S_ISDIR(snapshot.mode):
            raise SuccessorAggregateCapacityError(
                f"{root.role.value} capacity root is not a directory"
            )
        if (snapshot.device, snapshot.inode) != root.expected_identity:
            raise SuccessorAggregateCapacityError(
                f"{root.role.value} capacity root changed identity"
            )
        if os.name == "posix" and (
            snapshot.owner != os.geteuid() or stat.S_IMODE(snapshot.mode) != _PRIVATE_DIRECTORY_MODE
        ):
            raise SuccessorAggregateCapacityError(
                f"{root.role.value} capacity root must be owner-only mode 0700"
            )

    @classmethod
    def _require_current_snapshot(cls, opened: _OpenedCapacityRoot) -> None:
        descriptor_snapshot = _snapshot_descriptor(
            opened.descriptor,
            role=opened.root.role,
        )
        named_snapshot = _snapshot_named(opened.root.path, role=opened.root.role)
        cls._require_private_snapshot(opened.root, descriptor_snapshot)
        cls._require_private_snapshot(opened.root, named_snapshot)
        if descriptor_snapshot != opened.snapshot or named_snapshot != opened.snapshot:
            raise SuccessorAggregateCapacityError(
                f"{opened.root.role.value} capacity root mutated during admission"
            )

    def _open_roots(self) -> list[_OpenedCapacityRoot]:
        if not _NOFOLLOW or not _DIRECTORY:
            raise SuccessorAggregateCapacityError(
                "aggregate capacity admission requires POSIX O_NOFOLLOW and O_DIRECTORY"
            )
        opened_roots: list[_OpenedCapacityRoot] = []
        try:
            for root in self.roots:
                try:
                    exact = root.path.resolve(strict=True)
                except OSError as exc:
                    raise SuccessorAggregateCapacityError(
                        f"{root.role.value} capacity root cannot be resolved exactly"
                    ) from exc
                if exact != root.path:
                    raise SuccessorAggregateCapacityError(
                        f"{root.role.value} capacity root contains a lexical or symlink alias"
                    )
                try:
                    descriptor = os.open(root.path, _DIRECTORY_FLAGS)
                except OSError as exc:
                    raise SuccessorAggregateCapacityError(
                        f"{root.role.value} capacity root cannot be opened safely"
                    ) from exc
                try:
                    descriptor_snapshot = _snapshot_descriptor(
                        descriptor,
                        role=root.role,
                    )
                    named_snapshot = _snapshot_named(root.path, role=root.role)
                    self._require_private_snapshot(root, descriptor_snapshot)
                    self._require_private_snapshot(root, named_snapshot)
                    if descriptor_snapshot != named_snapshot:
                        raise SuccessorAggregateCapacityError(
                            f"{root.role.value} open and named roots differ"
                        )
                    opened_roots.append(
                        _OpenedCapacityRoot(
                            root=root,
                            descriptor=descriptor,
                            snapshot=descriptor_snapshot,
                        )
                    )
                except BaseException:
                    os.close(descriptor)
                    raise
            return opened_roots
        except BaseException:
            for opened in opened_roots:
                os.close(opened.descriptor)
            raise

    def _measure_existing_bytes(self, opened: _OpenedCapacityRoot) -> int:
        callback = opened.root.existing_bytes_callback
        if callback is None:
            return 0
        self._require_current_snapshot(opened)
        try:
            observed = callback(opened.descriptor)
        except Exception as exc:
            raise SuccessorAggregateCapacityError(
                f"{opened.root.role.value} existing bytes could not be measured"
            ) from exc
        existing = _require_nonnegative_signed63(
            observed,
            label=f"{opened.root.role.value} existing bytes",
        )
        self._require_current_snapshot(opened)
        return existing

    def _probe(self, opened: _OpenedCapacityRoot) -> tuple[int, int]:
        self._require_current_snapshot(opened)
        try:
            raw = self.descriptor_probe(opened.descriptor, opened.root)
        except SuccessorAggregateCapacityError:
            raise
        except Exception as exc:
            raise SuccessorAggregateCapacityError(
                f"{opened.root.role.value} filesystem capacity could not be measured"
            ) from exc
        if type(raw) is not tuple or len(raw) != 2:
            raise SuccessorAggregateCapacityError(
                f"{opened.root.role.value} filesystem probe result is invalid"
            )
        device = _require_nonnegative_signed63(
            raw[0],
            label=f"{opened.root.role.value} device id",
        )
        free = _require_nonnegative_signed63(
            raw[1],
            label=f"{opened.root.role.value} free bytes",
        )
        self._require_current_snapshot(opened)
        return device, free

    def _peak_by_role(
        self,
        *,
        existing_by_role: dict[SuccessorCapacityRole, int],
    ) -> dict[SuccessorCapacityRole, int]:
        capacity = self.admission.aggregate_capacity
        planning_waves = _checked_product(
            capacity.planning_wave_count,
            capacity.planning_wave_capture_max_bytes,
            label="retained planning waves",
        )
        planning_bodyless_packets = _checked_product(
            capacity.planning_wave_count,
            capacity.planning_wave_checkpoint_max_bytes,
            label="retained planning bodyless packets",
        )
        planning_driver_temporary = _checked_product(
            2,
            capacity.planning_driver_database_max_bytes,
            label="planning driver temporary databases",
        )
        inventory_duckdb_and_transform = _checked_sum(
            capacity.inventory_duckdb_snapshot_max_bytes,
            capacity.transform_scratch_max_bytes,
            label="DuckDB inventory and transform scratch",
        )
        assurance_scratch = max(
            capacity.scan_database_snapshot_max_bytes,
            capacity.inventory_sqlite_snapshot_max_bytes,
            inventory_duckdb_and_transform,
        )
        return {
            SuccessorCapacityRole.GENERATION_STORE: _checked_sum(
                _remaining(
                    capacity.candidate_max_bytes,
                    existing_by_role[SuccessorCapacityRole.GENERATION_STORE],
                ),
                capacity.rollback_reserve_bytes,
                capacity.assurance_control_max_bytes,
                label="generation store aggregate peak",
            ),
            SuccessorCapacityRole.COORDINATOR_CHECKPOINT: (
                capacity.coordinator_checkpoint_max_bytes
            ),
            SuccessorCapacityRole.PLANNING_STORE: _checked_sum(
                _remaining(
                    capacity.planning_store_generation_max_bytes,
                    existing_by_role[SuccessorCapacityRole.PLANNING_STORE],
                ),
                capacity.planning_store_control_max_bytes,
                label="planning store aggregate peak",
            ),
            SuccessorCapacityRole.PLANNING_WORK: _remaining(
                planning_driver_temporary,
                existing_by_role[SuccessorCapacityRole.PLANNING_WORK],
            ),
            SuccessorCapacityRole.PLANNING_CAPTURE: _checked_sum(
                _remaining(
                    planning_waves,
                    existing_by_role[SuccessorCapacityRole.PLANNING_CAPTURE],
                ),
                capacity.planning_wave_checkpoint_max_bytes,
                label="planning capture aggregate peak",
            ),
            SuccessorCapacityRole.BODY_BLOB: _remaining(
                planning_waves,
                existing_by_role[SuccessorCapacityRole.BODY_BLOB],
            ),
            SuccessorCapacityRole.DECLARED_BODYLESS_PACKET: _remaining(
                planning_bodyless_packets,
                existing_by_role[SuccessorCapacityRole.DECLARED_BODYLESS_PACKET],
            ),
            SuccessorCapacityRole.UPDATE_CAPTURE: _checked_sum(
                _remaining(
                    capacity.update_capture_max_bytes,
                    existing_by_role[SuccessorCapacityRole.UPDATE_CAPTURE],
                ),
                capacity.update_checkpoint_max_bytes,
                label="update capture aggregate peak",
            ),
            SuccessorCapacityRole.TERMINAL_RECEIPT: capacity.terminal_receipt_max_bytes,
            SuccessorCapacityRole.RUNTIME_LOG: capacity.runtime_log_max_bytes,
            SuccessorCapacityRole.ASSURANCE_SCRATCH: assurance_scratch,
        }

    def admit(self, stage: str) -> AggregateCapacityObservation:
        """Re-prove aggregate capacity before a named in-process stage."""

        checked_stage = _require_stage(stage)
        self._current_epoch()
        sampled_before = self._clock_sample(label="capacity admission clock")
        self._require_deadline(sampled_before, stage=checked_stage)
        opened_roots = self._open_roots()
        try:
            for opened in opened_roots:
                opened.existing_bytes = self._measure_existing_bytes(opened)
            for opened in opened_roots:
                opened.first_probe = self._probe(opened)

            first_free_by_device: dict[int, int] = {}
            for opened in opened_roots:
                assert opened.first_probe is not None
                device, free = opened.first_probe
                previous = first_free_by_device.setdefault(device, free)
                if previous != free:
                    raise SuccessorAggregateCapacityError(
                        "filesystem free bytes drifted across roots on one device"
                    )

            for opened in opened_roots:
                final_probe = self._probe(opened)
                if final_probe != opened.first_probe:
                    raise SuccessorAggregateCapacityError(
                        f"{opened.root.role.value} filesystem capacity drifted during admission"
                    )
                self._require_current_snapshot(opened)

            existing_by_role = {opened.root.role: opened.existing_bytes for opened in opened_roots}
            peak_by_role = self._peak_by_role(existing_by_role=existing_by_role)
            root_observations: list[AggregateCapacityRootObservation] = []
            demand_by_device: dict[int, int] = {}
            roles_by_device: dict[int, list[SuccessorCapacityRole]] = {}
            for opened in opened_roots:
                assert opened.first_probe is not None
                device, _free = opened.first_probe
                peak = peak_by_role[opened.root.role]
                demand_by_device[device] = _checked_sum(
                    demand_by_device.get(device, 0),
                    peak,
                    label=f"device {device} aggregate peak",
                )
                roles_by_device.setdefault(device, []).append(opened.root.role)
                root_observations.append(
                    AggregateCapacityRootObservation(
                        role=opened.root.role,
                        device_id=device,
                        existing_bytes=opened.existing_bytes,
                        peak_additional_bytes=peak,
                    )
                )

            device_observations: list[AggregateCapacityDeviceObservation] = []
            for device in sorted(demand_by_device):
                demand = demand_by_device[device]
                required = _checked_sum(
                    demand,
                    self.admission.aggregate_capacity.minimum_free_bytes,
                    label=f"device {device} aggregate requirement",
                )
                free = first_free_by_device[device]
                if free < required:
                    raise SuccessorAggregateCapacityError(
                        "insufficient aggregate successor capacity: "
                        f"device={device}, required={required}, available={free}"
                    )
                device_observations.append(
                    AggregateCapacityDeviceObservation(
                        device_id=device,
                        roles=tuple(roles_by_device[device]),
                        peak_additional_bytes=demand,
                        minimum_free_bytes=(self.admission.aggregate_capacity.minimum_free_bytes),
                        required_free_bytes=required,
                        observed_free_bytes=free,
                    )
                )

            sampled_after = self._clock_sample(label="capacity admission closing clock")
            if sampled_after < sampled_before:
                raise SuccessorAggregateCapacityError("monotonic clock moved backwards")
            self._require_deadline(sampled_after, stage=checked_stage)
            self._current_epoch()
            return AggregateCapacityObservation(
                stage=checked_stage,
                monotonic_sample_before_seconds=sampled_before,
                monotonic_sample_after_seconds=sampled_after,
                monotonic_deadline_seconds=self.admission.monotonic_deadline_seconds,
                minimum_required_headroom_seconds=(
                    self.admission.minimum_pre_provider_headroom_seconds
                ),
                remaining_headroom_seconds=(
                    self.admission.monotonic_deadline_seconds - sampled_after
                ),
                roots=tuple(root_observations),
                devices=tuple(device_observations),
            )
        finally:
            for opened in opened_roots:
                os.close(opened.descriptor)
