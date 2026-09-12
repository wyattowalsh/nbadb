from __future__ import annotations

import math
import os
from typing import TYPE_CHECKING, cast

import pytest

from nbadb.orchestrate.successor_capacity import (
    AggregateCapacityObservation,
    CapacityRoot,
    ExactSuccessorAggregateCapacityAuthority,
    SuccessorAggregateCapacityError,
    SuccessorCapacityRole,
)
from nbadb.orchestrate.successor_coordinator import (
    SuccessorAggregateCapacityContract,
    SuccessorCandidateAdmission,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

_MAX_SIGNED_63 = (1 << 63) - 1
_EPOCH = "a" * 64


def _capacity(**overrides: int) -> SuccessorAggregateCapacityContract:
    values = {
        "baseline_installed_public_tree_bytes": 10,
        "planning_store_generation_max_bytes": 100,
        "planning_store_artifact_max_bytes": 999,
        "planning_store_control_max_bytes": 7,
        "planning_driver_database_max_bytes": 11,
        "planning_wave_count": 2,
        "planning_wave_capture_max_bytes": 13,
        "planning_wave_checkpoint_max_bytes": 5,
        "update_capture_max_bytes": 17,
        "update_checkpoint_max_bytes": 3,
        "candidate_max_bytes": 200,
        "rollback_reserve_bytes": 19,
        "coordinator_checkpoint_max_bytes": 23,
        "terminal_receipt_max_bytes": 29,
        "runtime_log_max_bytes": 31,
        "scan_database_snapshot_max_bytes": 37,
        "inventory_duckdb_snapshot_max_bytes": 41,
        "inventory_sqlite_snapshot_max_bytes": 43,
        "transform_scratch_max_bytes": 47,
        "assurance_control_max_bytes": 53,
        "minimum_free_bytes": 59,
    }
    values.update(overrides)
    return SuccessorAggregateCapacityContract(**values)


def _admission(
    capacity: SuccessorAggregateCapacityContract | None = None,
    *,
    deadline: float = 1_000.0,
    pre_provider_headroom: float = 10.0,
    minimum_headroom: float = 5.0,
    epoch: str = _EPOCH,
) -> SuccessorCandidateAdmission:
    return SuccessorCandidateAdmission(
        aggregate_capacity=capacity or _capacity(),
        monotonic_deadline_seconds=deadline,
        minimum_pre_provider_headroom_seconds=pre_provider_headroom,
        minimum_deadline_headroom_seconds=minimum_headroom,
        monotonic_epoch_sha256=epoch,
    )


def _roots(
    tmp_path: Path,
    *,
    existing: Mapping[SuccessorCapacityRole, int] | None = None,
    callbacks: Mapping[SuccessorCapacityRole, Callable[[int], int]] | None = None,
) -> tuple[CapacityRoot, ...]:
    existing = existing or {}
    callbacks = callbacks or {}
    roots: list[CapacityRoot] = []
    for role in SuccessorCapacityRole:
        path = tmp_path / role.value
        path.mkdir(mode=0o700)
        path.chmod(0o700)
        observed = path.stat(follow_symlinks=False)
        callback = callbacks.get(role)
        if callback is None and role in existing:
            value = existing[role]

            def constant_existing_bytes(_descriptor: int, *, value: int = value) -> int:
                return value

            callback = constant_existing_bytes
        roots.append(
            CapacityRoot(
                role=role,
                path=path,
                expected_identity=(observed.st_dev, observed.st_ino),
                existing_bytes_callback=callback,
            )
        )
    return tuple(roots)


class _StableProbe:
    def __init__(
        self,
        *,
        device_by_role: Mapping[SuccessorCapacityRole, int] | None = None,
        free_by_device: Mapping[int, int] | None = None,
    ) -> None:
        self.device_by_role = dict(device_by_role or {})
        self.free_by_device = dict(free_by_device or {1: 10_000})

    def __call__(self, _descriptor: int, root: CapacityRoot) -> tuple[int, int]:
        device = self.device_by_role.get(root.role, 1)
        return device, self.free_by_device[device]


def _authority(
    roots: tuple[CapacityRoot, ...],
    *,
    admission: SuccessorCandidateAdmission | None = None,
    probe: Callable[[int, CapacityRoot], tuple[int, int]] | None = None,
    clock: Callable[[], float] = lambda: 1.0,
    epoch: Callable[[], str] = lambda: _EPOCH,
) -> ExactSuccessorAggregateCapacityAuthority:
    return ExactSuccessorAggregateCapacityAuthority(
        admission=admission or _admission(),
        roots=roots,
        monotonic_clock=clock,
        monotonic_epoch_authority=epoch,
        descriptor_probe=probe or _StableProbe(),
    )


def test_capacity_roles_are_a_closed_runtime_surface() -> None:
    assert tuple(role.value for role in SuccessorCapacityRole) == (
        "generation_store",
        "coordinator_checkpoint",
        "planning_store",
        "planning_work",
        "planning_capture",
        "body_blob",
        "declared_bodyless_packet",
        "update_capture",
        "terminal_receipt",
        "runtime_log",
        "assurance_scratch",
    )


def test_same_device_aggregates_exact_peaks_and_one_floor(tmp_path: Path) -> None:
    roots = _roots(
        tmp_path,
        existing={
            SuccessorCapacityRole.GENERATION_STORE: 20,
            SuccessorCapacityRole.PLANNING_STORE: 30,
            SuccessorCapacityRole.PLANNING_CAPTURE: 4,
            SuccessorCapacityRole.UPDATE_CAPTURE: 6,
        },
    )
    observation = _authority(roots).admit("initial")

    assert isinstance(observation, AggregateCapacityObservation)
    assert len(observation.devices) == 1
    device = observation.devices[0]
    assert device.roles == tuple(SuccessorCapacityRole)
    # generation=(200-20)+19+53, planning store=(100-30)+7,
    # work=2*11, planning capture=(2*13-4)+5, body blobs=2*13,
    # bodyless packets=2*5, update=(17-6)+3, fixed controls=23+29+31,
    # and scratch=max(37,43,41+47)=88.
    assert device.peak_additional_bytes == 599
    assert device.minimum_free_bytes == 59
    assert device.required_free_bytes == 658
    assert device.observed_free_bytes == 10_000
    assert observation.minimum_required_headroom_seconds == 10.0
    assert observation.remaining_headroom_seconds == 999.0
    by_role = {item.role: item for item in observation.roots}
    assert by_role[SuccessorCapacityRole.PLANNING_STORE].peak_additional_bytes == 77
    # The individual artifact cap is not a second aggregate coexistence reserve.
    assert _capacity().planning_store_artifact_max_bytes == 999
    assert by_role[SuccessorCapacityRole.ASSURANCE_SCRATCH].peak_additional_bytes == 88


def test_multi_device_applies_the_floor_once_to_each_device(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    device_by_role = {
        role: (11 if role is SuccessorCapacityRole.GENERATION_STORE else 22)
        for role in SuccessorCapacityRole
    }
    probe = _StableProbe(
        device_by_role=device_by_role,
        free_by_device={11: 10_000, 22: 10_000},
    )
    observation = _authority(roots, probe=probe).admit("initial")

    devices = {item.device_id: item for item in observation.devices}
    assert set(devices) == {11, 22}
    assert devices[11].peak_additional_bytes == 272
    assert devices[11].required_free_bytes == 331
    assert devices[11].roles == (SuccessorCapacityRole.GENERATION_STORE,)
    assert devices[22].peak_additional_bytes == 387
    assert devices[22].required_free_bytes == 446


def test_existing_bytes_saturate_remaining_without_reducing_transients(
    tmp_path: Path,
) -> None:
    roots = _roots(
        tmp_path,
        existing={
            SuccessorCapacityRole.GENERATION_STORE: 10_000,
            SuccessorCapacityRole.PLANNING_STORE: 10_000,
            SuccessorCapacityRole.PLANNING_CAPTURE: 10_000,
            SuccessorCapacityRole.UPDATE_CAPTURE: 10_000,
        },
    )
    observation = _authority(roots).admit("resume")
    by_role = {item.role: item.peak_additional_bytes for item in observation.roots}
    assert by_role[SuccessorCapacityRole.GENERATION_STORE] == 19 + 53
    assert by_role[SuccessorCapacityRole.PLANNING_STORE] == 7
    assert by_role[SuccessorCapacityRole.PLANNING_CAPTURE] == 5
    assert by_role[SuccessorCapacityRole.BODY_BLOB] == 26
    assert by_role[SuccessorCapacityRole.DECLARED_BODYLESS_PACKET] == 10
    assert by_role[SuccessorCapacityRole.UPDATE_CAPTURE] == 3


def test_provider_reentry_rejects_a_fresh_free_space_drop(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    probe = _StableProbe(free_by_device={1: 10_000})
    authority = _authority(roots, probe=probe)
    first = authority.admit("initial")
    required = first.devices[0].required_free_bytes
    probe.free_by_device[1] = required - 1

    with pytest.raises(SuccessorAggregateCapacityError, match="insufficient aggregate"):
        authority.admit("pre_provider")


def test_root_substitution_is_rejected_before_capacity_use(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    authority = _authority(roots)
    root = roots[0]
    displaced = root.path.with_name(f"{root.path.name}-displaced")
    root.path.rename(displaced)
    root.path.mkdir(mode=0o700)
    root.path.chmod(0o700)

    with pytest.raises(SuccessorAggregateCapacityError, match="changed identity"):
        authority.admit("initial")


def test_existing_byte_callback_root_mutation_is_rejected(tmp_path: Path) -> None:
    def mutate_root(descriptor: int) -> int:
        child = os.open(
            "callback-mutation",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=descriptor,
        )
        os.close(child)
        return 0

    roots = _roots(
        tmp_path,
        callbacks={SuccessorCapacityRole.PLANNING_STORE: mutate_root},
    )

    with pytest.raises(SuccessorAggregateCapacityError, match="mutated during admission"):
        _authority(roots).admit("initial")


@pytest.mark.parametrize("existing", [True, -1, _MAX_SIGNED_63 + 1])
def test_invalid_existing_byte_measurements_are_rejected(
    tmp_path: Path,
    existing: object,
) -> None:
    roots = _roots(
        tmp_path,
        callbacks={SuccessorCapacityRole.UPDATE_CAPTURE: lambda _descriptor: cast("int", existing)},
    )

    with pytest.raises(SuccessorAggregateCapacityError, match="existing bytes"):
        _authority(roots).admit("initial")


def test_aggregate_formula_overflow_is_rejected_at_authority_construction(
    tmp_path: Path,
) -> None:
    roots = _roots(tmp_path)
    capacity = _capacity(
        candidate_max_bytes=_MAX_SIGNED_63,
        baseline_installed_public_tree_bytes=1,
    )

    with pytest.raises(SuccessorAggregateCapacityError, match="signed-63-bit range"):
        _authority(roots, admission=_admission(capacity))


def test_candidate_bound_smaller_than_baseline_is_invalid(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    capacity = _capacity(
        baseline_installed_public_tree_bytes=201,
        candidate_max_bytes=200,
    )

    with pytest.raises(SuccessorAggregateCapacityError, match="smaller than"):
        _authority(roots, admission=_admission(capacity))


@pytest.mark.parametrize("clock_value", [True, -1.0, math.nan, math.inf])
def test_invalid_monotonic_clock_samples_are_rejected(
    tmp_path: Path,
    clock_value: object,
) -> None:
    roots = _roots(tmp_path)

    with pytest.raises(SuccessorAggregateCapacityError, match="finite and nonnegative"):
        _authority(
            roots,
            clock=lambda: cast("float", clock_value),
        ).admit("initial")


def test_clock_must_not_move_backwards_or_cross_headroom(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    samples = iter((100.0, 99.0))
    backwards = _authority(roots, clock=lambda: next(samples))
    with pytest.raises(SuccessorAggregateCapacityError, match="moved backwards"):
        backwards.admit("initial")

    samples = iter((989.0, 991.0))
    expires_during_probe = _authority(roots, clock=lambda: next(samples))
    with pytest.raises(SuccessorAggregateCapacityError, match="headroom is insufficient"):
        expires_during_probe.admit("pre_provider")


def test_epoch_is_validated_at_capture_and_every_reentry(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    with pytest.raises(SuccessorAggregateCapacityError, match="lowercase SHA-256"):
        _authority(roots, epoch=lambda: "invalid")

    epoch = {"value": _EPOCH}
    authority = _authority(roots, epoch=lambda: epoch["value"])
    authority.admit("initial")
    epoch["value"] = "b" * 64
    with pytest.raises(SuccessorAggregateCapacityError, match="epoch authority changed"):
        authority.admit("pre_provider")


@pytest.mark.parametrize("invalid_free", [True, -1, _MAX_SIGNED_63 + 1])
def test_invalid_free_space_probe_values_are_rejected(
    tmp_path: Path,
    invalid_free: object,
) -> None:
    roots = _roots(tmp_path)

    def invalid_probe(_descriptor: int, _root: CapacityRoot) -> tuple[int, int]:
        return 1, cast("int", invalid_free)

    with pytest.raises(SuccessorAggregateCapacityError, match="free bytes"):
        _authority(roots, probe=invalid_probe).admit("initial")


def test_free_space_drift_within_one_root_is_rejected(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    target_calls = 0

    def drifting_probe(_descriptor: int, root: CapacityRoot) -> tuple[int, int]:
        nonlocal target_calls
        if root.role is SuccessorCapacityRole.PLANNING_WORK:
            target_calls += 1
            return 1, 10_000 - (target_calls - 1)
        return 1, 10_000

    with pytest.raises(SuccessorAggregateCapacityError, match="capacity drifted"):
        _authority(roots, probe=drifting_probe).admit("initial")


def test_free_space_drift_across_same_device_roots_is_rejected(tmp_path: Path) -> None:
    roots = _roots(tmp_path)

    def inconsistent_probe(_descriptor: int, root: CapacityRoot) -> tuple[int, int]:
        return 1, 10_000 + tuple(SuccessorCapacityRole).index(root.role)

    with pytest.raises(SuccessorAggregateCapacityError, match="drifted across roots"):
        _authority(roots, probe=inconsistent_probe).admit("initial")


def test_every_closed_role_is_required_exactly_once(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    with pytest.raises(SuccessorAggregateCapacityError, match="exactly one root"):
        _authority(roots[:-1])
    with pytest.raises(SuccessorAggregateCapacityError, match="exactly one root"):
        _authority((*roots[:-1], roots[0]))


def test_private_role_requires_owner_only_mode(tmp_path: Path) -> None:
    roots = _roots(tmp_path)
    roots[0].path.chmod(0o755)

    with pytest.raises(SuccessorAggregateCapacityError, match="owner-only mode 0700"):
        _authority(roots).admit("initial")


@pytest.mark.parametrize("stage", ["", "provider work", "../provider", "x" * 129])
def test_stage_is_a_bounded_diagnostic_label(tmp_path: Path, stage: str) -> None:
    roots = _roots(tmp_path)
    with pytest.raises(SuccessorAggregateCapacityError, match="stage is invalid"):
        _authority(roots).admit(stage)
