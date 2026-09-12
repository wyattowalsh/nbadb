"""Exact production composition for one recurring successor generation.

This module wires the already-fail-closed planning, copy-plus-delta, retained
capture, assurance, and promotion components.  It adds only whole-graph
filesystem admission: every private authority is disjoint, one public baseline
is measured before coordinator persistence, and a baseline inside the
generation store is accepted only when the verified current pointer names it.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import stat
import threading
import time
import weakref
from collections.abc import Callable, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final, cast

from nbadb.contracts.field_fate_structure import compile_field_fate_structure
from nbadb.contracts.logical_provider_parameter_binding import (
    LogicalProviderParameterBindingV1,
    compile_logical_provider_parameter_binding,
)
from nbadb.contracts.raw_request_authority import canonical_semantic_parameters
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME,
)
from nbadb.core.config import NbaDbSettings
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    pinned_runtime_contracts,
)
from nbadb.extract.bronze import BronzeLimits, canonical_parameters_sha256
from nbadb.extract.raw_request_capture import (
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
)
from nbadb.extract.registry import (
    EndpointRegistry,
    EndpointRegistryAuthority,
    EndpointRegistryAuthorityError,
)
from nbadb.orchestrate.body_blob_store import BodyBlobStore
from nbadb.orchestrate.capture_session import CaptureRunScope
from nbadb.orchestrate.declared_bodyless_packet_store import (
    DeclaredBodylessPacketStore,
)
from nbadb.orchestrate.public_value_authority_store import PublicValueAuthorityStore
from nbadb.orchestrate.raw_request_store import RawRequestAuthorityStore
from nbadb.orchestrate.successor_assurance_builder import (
    ExactSuccessorAssuranceBuilder,
    validate_successor_baseline_controls,
)
from nbadb.orchestrate.successor_capacity import (
    CapacityRoot,
    ExactSuccessorAggregateCapacityAuthority,
    SuccessorAggregateCapacityError,
    SuccessorCapacityRole,
)
from nbadb.orchestrate.successor_coordinator import (
    SuccessorCoordinator,
    SuccessorCoordinatorCheckpoint,
    SuccessorCoordinatorCheckpointStore,
    SuccessorCoordinatorError,
    SuccessorCoordinatorPhase,
    SuccessorCoordinatorRequest,
    SuccessorCoordinatorResult,
    require_successor_downstream_publication,
)
from nbadb.orchestrate.successor_generation_store import SuccessorGenerationStore
from nbadb.orchestrate.successor_inventory import (
    InstalledPublicTreeInventory,
    measure_installed_public_tree,
)
from nbadb.orchestrate.successor_planner import deterministic_planning_generation_id
from nbadb.orchestrate.successor_planning_driver import PlanningExactCallRuntimeRequest
from nbadb.orchestrate.successor_planning_request_builder import (
    validate_successor_planning_request,
)
from nbadb.orchestrate.successor_planning_runtime import (
    ExactPlanningRuntimeConfig,
    PlanningW2AuthorityResourcesV1,
    build_successor_planning_executor,
    unavailable_live_plan_binding_factory,
)
from nbadb.orchestrate.successor_planning_store import PlanningStoreBudget, SuccessorPlanningStore
from nbadb.orchestrate.successor_publication_inventory import (
    SuccessorPublicationInventoryEvidence,
    build_successor_publication_inventory,
)
from nbadb.orchestrate.successor_runtime import ExactPlanSuccessorRuntimeFactory
from nbadb.orchestrate.successor_scan_evidence import (
    FreeBytesProbe,
    ScanFunction,
    SuccessorFullPublicationScanner,
    filesystem_free_bytes,
    run_data_scanner_full_publication,
)
from nbadb.orchestrate.successor_update_capture_resolver import RetainedBronzeUpdateResolver
from nbadb.orchestrate.successor_update_contract import (
    SuccessorGenerationState,
    canonical_sha256,
)
from nbadb.orchestrate.w2_operation_store import W2OperationStore
from nbadb.orchestrate.w2_source_call_preparation import W2SourceCallPreparationRuntime

__all__ = [
    "ExactSuccessorComposition",
    "ExactSuccessorCompositionConfig",
    "ExactSuccessorCompositionError",
    "ExactSuccessorTopologyAuthority",
    "build_exact_successor_composition",
    "build_production_successor_w2_authority_resources",
]

_PRIVATE_MODE: Final = 0o700
_CHECKPOINT_MODE: Final = 0o600
_MAX_BASELINE_CONTROL_BYTES: Final = 64 * 1024 * 1024
_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)
_ASYNC_STORE_GATES_GUARD = threading.Lock()
_ASYNC_STORE_GATES: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Lock]
] = weakref.WeakKeyDictionary()


class ExactSuccessorCompositionError(RuntimeError):
    """Raised before coordinator persistence when composition authority is unsafe."""


class _BoundSuccessorCoordinatorCheckpointStore(SuccessorCoordinatorCheckpointStore):
    """Descriptor-relative checkpoint persistence under one admitted parent inode."""

    def __init__(
        self,
        path: Path,
        *,
        expected_parent_identity: tuple[int, int],
        max_bytes: int,
    ) -> None:
        super().__init__(path)
        if (
            type(expected_parent_identity) is not tuple
            or len(expected_parent_identity) != 2
            or any(type(value) is not int or value < 0 for value in expected_parent_identity)
        ):
            raise ExactSuccessorCompositionError("checkpoint parent identity is invalid")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ExactSuccessorCompositionError("coordinator checkpoint byte bound is invalid")
        self._expected_parent_identity = expected_parent_identity
        self._max_bytes = max_bytes
        self._parent_lock = threading.RLock()
        self._parent_state = threading.local()

    def _require_parent_descriptor(self, descriptor: int) -> None:
        try:
            opened = os.fstat(descriptor)
            current = os.stat(self.path.parent, follow_symlinks=False)
        except OSError as exc:
            raise SuccessorCoordinatorError(
                "coordinator checkpoint parent changed identity"
            ) from exc
        expected = self._expected_parent_identity
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(current.st_mode)
            or (opened.st_dev, opened.st_ino) != expected
            or (current.st_dev, current.st_ino) != expected
            or (
                os.name == "posix"
                and (
                    opened.st_uid != os.geteuid()
                    or stat.S_IMODE(opened.st_mode) != _PRIVATE_MODE
                    or current.st_uid != os.geteuid()
                    or stat.S_IMODE(current.st_mode) != _PRIVATE_MODE
                )
            )
        ):
            raise SuccessorCoordinatorError("coordinator checkpoint parent changed identity")

    @contextmanager
    def _parent_operation(self) -> Any:
        descriptor = int(getattr(self._parent_state, "descriptor", -1))
        depth = int(getattr(self._parent_state, "depth", 0))
        if descriptor >= 0 and depth:
            self._require_parent_descriptor(descriptor)
            self._parent_state.depth = depth + 1
            try:
                yield descriptor
                self._require_parent_descriptor(descriptor)
            finally:
                self._parent_state.depth = depth
            return

        directory_flags = (
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW | _CLOEXEC | _NONBLOCK
        )
        with self._parent_lock:
            descriptor = -1
            try:
                descriptor = os.open(self.path.parent, directory_flags)
                self._require_parent_descriptor(descriptor)
                self._parent_state.descriptor = descriptor
                self._parent_state.depth = 1
                yield descriptor
                self._require_parent_descriptor(descriptor)
            except OSError as exc:
                raise SuccessorCoordinatorError(
                    "coordinator checkpoint parent cannot be opened safely"
                ) from exc
            finally:
                self._parent_state.depth = 0
                self._parent_state.descriptor = -1
                if descriptor >= 0:
                    os.close(descriptor)

    def _read_bound_file(self, parent_descriptor: int, name: str) -> bytes | None:
        try:
            named_before = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return None
        flags = os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK
        descriptor = -1
        try:
            descriptor = os.open(name, flags, dir_fd=parent_descriptor)
            opened_before = os.fstat(descriptor)
            admitted = (
                opened_before.st_dev,
                opened_before.st_ino,
                opened_before.st_mode,
                opened_before.st_nlink,
                opened_before.st_size,
                opened_before.st_mtime_ns,
                opened_before.st_ctime_ns,
            )
            if (
                not stat.S_ISREG(opened_before.st_mode)
                or opened_before.st_nlink != 1
                or opened_before.st_size > self._max_bytes
                or admitted
                != (
                    named_before.st_dev,
                    named_before.st_ino,
                    named_before.st_mode,
                    named_before.st_nlink,
                    named_before.st_size,
                    named_before.st_mtime_ns,
                    named_before.st_ctime_ns,
                )
            ):
                raise SuccessorCoordinatorError(
                    "coordinator checkpoint must be one stable regular file"
                )
            remaining = opened_before.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise SuccessorCoordinatorError(
                        "coordinator checkpoint ended before its admitted size"
                    )
                chunks.append(chunk)
                remaining -= len(chunk)
            opened_after = os.fstat(descriptor)
            named_after = os.stat(
                name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if admitted != (
                opened_after.st_dev,
                opened_after.st_ino,
                opened_after.st_mode,
                opened_after.st_nlink,
                opened_after.st_size,
                opened_after.st_mtime_ns,
                opened_after.st_ctime_ns,
            ) or admitted != (
                named_after.st_dev,
                named_after.st_ino,
                named_after.st_mode,
                named_after.st_nlink,
                named_after.st_size,
                named_after.st_mtime_ns,
                named_after.st_ctime_ns,
            ):
                raise SuccessorCoordinatorError("coordinator checkpoint changed while being read")
            return b"".join(chunks)
        except OSError as exc:
            raise SuccessorCoordinatorError(
                "coordinator checkpoint cannot be opened safely"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def load(self) -> SuccessorCoordinatorCheckpoint | None:
        with self._parent_operation() as parent_descriptor:
            encoded = self._read_bound_file(parent_descriptor, self.path.name)
            if encoded is None:
                return None
            try:
                payload = json.loads(encoded)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SuccessorCoordinatorError("coordinator checkpoint is not valid JSON") from exc
            if not isinstance(payload, Mapping):
                raise SuccessorCoordinatorError("coordinator checkpoint must be an object")
            checkpoint = SuccessorCoordinatorCheckpoint.from_dict(
                cast("Mapping[str, object]", payload)
            )
            if encoded != checkpoint.canonical_bytes:
                raise SuccessorCoordinatorError("coordinator checkpoint is not canonical")
            return checkpoint

    def write(self, checkpoint: SuccessorCoordinatorCheckpoint) -> None:
        with self._parent_operation():
            super().write(checkpoint)

    def _atomic_write(self, encoded: bytes) -> None:
        if len(encoded) > self._max_bytes:
            raise SuccessorCoordinatorError(
                "coordinator checkpoint exceeds its admitted byte bound"
            )
        with self._parent_operation() as parent_descriptor:
            temporary_name = f".{self.path.name}.{secrets.token_hex(8)}.tmp"
            descriptor = -1
            try:
                descriptor = os.open(
                    temporary_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                    0o600,
                    dir_fd=parent_descriptor,
                )
                view = memoryview(encoded)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("short coordinator checkpoint write")
                    view = view[written:]
                os.fchmod(descriptor, _CHECKPOINT_MODE)
                os.fsync(descriptor)
                os.close(descriptor)
                descriptor = -1
                self._require_parent_descriptor(parent_descriptor)
                os.replace(
                    temporary_name,
                    self.path.name,
                    src_dir_fd=parent_descriptor,
                    dst_dir_fd=parent_descriptor,
                )
                os.fsync(parent_descriptor)
                self._require_parent_descriptor(parent_descriptor)
            except OSError as exc:
                raise SuccessorCoordinatorError(
                    "coordinator checkpoint cannot be installed atomically"
                ) from exc
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                with suppress(FileNotFoundError):
                    os.unlink(temporary_name, dir_fd=parent_descriptor)


@dataclass(frozen=True, slots=True)
class ExactSuccessorCompositionConfig:
    """Caller-owned paths and dependencies for one exact successor request."""

    generation_store_root: Path
    checkpoint_path: Path
    planning_store_root: Path
    planning_work_root: Path
    planning_capture_root: Path
    body_blob_root: Path
    declared_bodyless_packet_root: Path
    update_capture_root: Path
    update_terminal_receipt_root: Path
    runtime_log_root: Path
    assurance_scratch_root: Path
    settings: NbaDbSettings
    planning_registry: EndpointRegistry
    capture_limits: BronzeLimits
    fresh_planning_budget: Callable[[], PlanningStoreBudget]
    monotonic_epoch_authority: Callable[[], str]
    contract_blocked_evidence: Mapping[str, Any]
    w2_authority_resources: PlanningW2AuthorityResourcesV1
    monotonic_clock: Callable[[], float] = time.monotonic
    free_bytes_probe: FreeBytesProbe = filesystem_free_bytes
    scan_function: ScanFunction = run_data_scanner_full_publication

    def __post_init__(self) -> None:
        path_fields = (
            "generation_store_root",
            "checkpoint_path",
            "planning_store_root",
            "planning_work_root",
            "planning_capture_root",
            "body_blob_root",
            "declared_bodyless_packet_root",
            "update_capture_root",
            "update_terminal_receipt_root",
            "runtime_log_root",
            "assurance_scratch_root",
        )
        if any(not isinstance(getattr(self, field_name), Path) for field_name in path_fields):
            raise ExactSuccessorCompositionError("composition paths must be explicit Path values")
        if not isinstance(self.settings, NbaDbSettings):
            raise ExactSuccessorCompositionError("settings must be NbaDbSettings")
        if not isinstance(self.planning_registry, EndpointRegistry):
            raise ExactSuccessorCompositionError("planning_registry must be EndpointRegistry")
        if not isinstance(self.capture_limits, BronzeLimits):
            raise ExactSuccessorCompositionError("capture_limits must be BronzeLimits")
        if type(self.w2_authority_resources) is not PlanningW2AuthorityResourcesV1:
            raise ExactSuccessorCompositionError(
                "w2_authority_resources must be the exact planning W2 authority DTO"
            )
        if not isinstance(self.contract_blocked_evidence, Mapping):
            raise ExactSuccessorCompositionError("contract_blocked_evidence must be an object")
        callables = (
            self.fresh_planning_budget,
            self.monotonic_epoch_authority,
            self.monotonic_clock,
            self.free_bytes_probe,
            self.scan_function,
        )
        if any(not callable(value) for value in callables):
            raise ExactSuccessorCompositionError("composition dependencies must be callable")


@dataclass(frozen=True, slots=True)
class _DirectoryAuthority:
    path: Path
    label: str
    identity: tuple[int, int]
    owner_only: bool

    def require_current(self) -> os.stat_result:
        path, observed = _require_directory(
            self.path,
            label=self.label,
            owner_only=self.owner_only,
        )
        if path != self.path or _identity(observed) != self.identity:
            raise ExactSuccessorCompositionError(f"{self.label} changed identity")
        return observed


@dataclass(frozen=True, slots=True)
class ExactSuccessorTopologyAuthority:
    """Captured whole-graph authority rechecked before coordinator writes."""

    request: SuccessorCoordinatorRequest
    generation_store: SuccessorGenerationStore
    checkpoint_store: SuccessorCoordinatorCheckpointStore
    private_roots: tuple[_DirectoryAuthority, ...]
    generation_store_authority: _DirectoryAuthority
    generations_authority: _DirectoryAuthority
    baseline_authority: _DirectoryAuthority
    update_capture_authority: _DirectoryAuthority
    update_terminal_receipt_authority: _DirectoryAuthority
    runtime_log_authority: _DirectoryAuthority
    assurance_scratch_authority: _DirectoryAuthority
    contract_blocked_evidence: Mapping[str, Any]
    planning_registry: EndpointRegistry
    planning_registry_authority: EndpointRegistryAuthority
    update_registry_authority: EndpointRegistryAuthority
    fresh_planning_budget: Callable[[], PlanningStoreBudget]
    aggregate_capacity_authority: ExactSuccessorAggregateCapacityAuthority
    planning_store_authority: _DirectoryAuthority
    planning_work_authority: _DirectoryAuthority
    planning_capture_authority: _DirectoryAuthority

    def require_fresh_planning_budget(self) -> PlanningStoreBudget:
        """Re-prove the request-bound planning deadline before any store lock write."""

        return _require_planning_budget(
            self.fresh_planning_budget(),
            request=self.request,
        )

    def require_aggregate_capacity(self, stage: str) -> None:
        """Re-prove the exact per-device aggregate before a runtime boundary."""

        try:
            self.aggregate_capacity_authority.admit(stage)
        except SuccessorAggregateCapacityError as exc:
            detail = str(exc).replace("_", " ")
            raise ExactSuccessorCompositionError(
                f"aggregate capacity authority failed at {stage}: {detail}"
            ) from exc

    def require_current(self) -> None:
        """Re-prove path identities, disjointness, baseline bytes, and lineage."""

        validate_successor_planning_request(self.request.planning_request)
        self.require_fresh_planning_budget()
        try:
            self.planning_registry_authority.require_current(self.planning_registry)
            self.update_registry_authority.require_current(self.planning_registry)
        except EndpointRegistryAuthorityError as exc:
            raise ExactSuccessorCompositionError(
                "planning endpoint registry authority differs"
            ) from exc
        _require_inherited_control_authority(
            self.request,
            self.contract_blocked_evidence,
        )
        private_observations = tuple(
            (authority, authority.require_current()) for authority in self.private_roots
        )
        generation_observed = self.generation_store_authority.require_current()
        self.generations_authority.require_current()
        baseline_observed = self.baseline_authority.require_current()

        _require_pairwise_disjoint(private_observations)
        for authority, observed in private_observations:
            if _paths_overlap(
                authority.path,
                self.baseline_authority.path,
                left_stat=observed,
                right_stat=baseline_observed,
            ):
                raise ExactSuccessorCompositionError(
                    f"{authority.label} and baseline public root must be disjoint"
                )
            if _paths_overlap(
                authority.path,
                self.generation_store_authority.path,
                left_stat=observed,
                right_stat=generation_observed,
            ):
                raise ExactSuccessorCompositionError(
                    f"{authority.label} and generation store must be disjoint"
                )

        _require_checkpoint_file(self.checkpoint_store.path)
        measured = measure_installed_public_tree(
            self.baseline_authority.path,
            expected_root_identity=self.baseline_authority.identity,
        )
        if (
            measured.installed_public_tree_sha256
            != self.request.baseline.installed_public_tree_sha256
            or measured.byte_count != self.request.baseline.installed_public_tree_bytes
        ):
            raise ExactSuccessorCompositionError(
                "baseline installed public tree differs from request authority"
            )
        self.require_baseline_controls_current()
        self._require_lineage(
            baseline_observed=baseline_observed,
            generation_observed=generation_observed,
        )

    def require_baseline_controls_current(self) -> None:
        """Descriptor-read and authenticate both immutable baseline controls."""

        report_bytes, manifest_bytes = _read_baseline_control_bytes(
            self.baseline_authority.path,
            expected_root_identity=self.baseline_authority.identity,
        )
        try:
            validate_successor_baseline_controls(
                baseline=self.request.baseline,
                terminal_assurance_report_bytes=report_bytes,
                assured_artifact_manifest_bytes=manifest_bytes,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            raise ExactSuccessorCompositionError("baseline assurance controls are invalid") from exc

    def _require_lineage(
        self,
        *,
        baseline_observed: os.stat_result,
        generation_observed: os.stat_result,
    ) -> None:
        baseline_inside_store = _paths_overlap(
            self.baseline_authority.path,
            self.generation_store_authority.path,
            left_stat=baseline_observed,
            right_stat=generation_observed,
        )
        pointer_path = self.generation_store.pointer_path
        if not pointer_path.exists() and not pointer_path.is_symlink():
            pointer = None
        else:
            pointer = self.generation_store.read_current()
        if pointer is None:
            checkpoint = self.checkpoint_store.load()
            if checkpoint is not None:
                if not _checkpoint_matches_request(checkpoint, self.request):
                    raise ExactSuccessorCompositionError(
                        "unpointed checkpoint differs from the exact successor request"
                    )
                if checkpoint.phase is SuccessorCoordinatorPhase.PROMOTED:
                    raise ExactSuccessorCompositionError(
                        "promoted checkpoint requires its installed current pointer"
                    )
            if self.request.generation != 1 or baseline_inside_store:
                raise ExactSuccessorCompositionError(
                    "first successor generation requires one external baseline"
                )
            return

        current = _pointer_reference(pointer.get("current"), label="current")
        current_generation = current["generation"]
        if current_generation == self.request.generation - 1:
            self._require_baseline_reference(current, label="current predecessor")
            return
        if current_generation != self.request.generation:
            raise ExactSuccessorCompositionError(
                "current successor generation is not this request or its predecessor"
            )

        checkpoint = self.checkpoint_store.load()
        if not _is_exact_promoted_reentry(checkpoint, self.request, current):
            raise ExactSuccessorCompositionError(
                "current request generation requires its exact promoted checkpoint"
            )
        previous_raw = pointer.get("previous")
        if self.request.generation == 1:
            if previous_raw is not None or baseline_inside_store:
                raise ExactSuccessorCompositionError(
                    "promoted first generation must retain its external baseline"
                )
            return
        previous = _pointer_reference(previous_raw, label="previous")
        if previous["generation"] != self.request.generation - 1:
            raise ExactSuccessorCompositionError(
                "promoted request previous generation is not contiguous"
            )
        self._require_baseline_reference(previous, label="previous baseline")

    def _require_baseline_reference(self, reference: Mapping[str, object], *, label: str) -> None:
        candidate_name = reference["candidate_name"]
        assert isinstance(candidate_name, str)
        candidate_root = self.generation_store.generations_root / candidate_name
        expected_root = candidate_root / "public"
        if self.baseline_authority.path != expected_root:
            raise ExactSuccessorCompositionError(f"{label} does not name the baseline public root")
        try:
            transaction = self.generation_store.load_transaction(candidate_root)
            if transaction.state is not SuccessorGenerationState.PROMOTED:
                raise ExactSuccessorCompositionError(
                    f"{label} transaction is not promoted authority"
                )
            assurance = transaction.promoted_assurance
        except ExactSuccessorCompositionError:
            raise
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            raise ExactSuccessorCompositionError(
                f"{label} transaction authority cannot be re-proved"
            ) from exc
        derived_reference = {
            "generation": transaction.generation,
            "candidate_name": self.generation_store.candidate_name(transaction),
            "transaction_sha256": transaction.content_sha256,
            "assurance_sha256": assurance.identity_sha256,
            "data_tree_fingerprint": assurance.successor_data_tree_fingerprint,
            "installed_public_tree_sha256": assurance.installed_public_tree_sha256,
            "private_generation_receipt_sha256": (assurance.private_generation_receipt_sha256),
        }
        if dict(reference) != derived_reference:
            raise ExactSuccessorCompositionError(f"{label} differs from stored promoted authority")
        if (
            reference["installed_public_tree_sha256"]
            != self.request.baseline.installed_public_tree_sha256
        ):
            raise ExactSuccessorCompositionError(f"{label} installed tree differs from baseline")
        if (
            reference["private_generation_receipt_sha256"]
            != self.request.baseline.private_baseline_receipt_sha256
        ):
            raise ExactSuccessorCompositionError(f"{label} private receipt differs from baseline")
        if reference["data_tree_fingerprint"] != self.request.baseline.data_tree_fingerprint:
            raise ExactSuccessorCompositionError(f"{label} data tree differs from baseline")


@dataclass(frozen=True, slots=True)
class ExactSuccessorComposition:
    """Request-bound coordinator whose topology is re-proved on every entry."""

    request: SuccessorCoordinatorRequest
    coordinator: SuccessorCoordinator
    topology: ExactSuccessorTopologyAuthority

    async def run(self) -> SuccessorCoordinatorResult:
        gate_key = str(self.topology.generation_store.root.resolve(strict=True))
        event_loop = asyncio.get_running_loop()
        with _ASYNC_STORE_GATES_GUARD:
            gates = _ASYNC_STORE_GATES.setdefault(event_loop, {})
            gate = gates.setdefault(gate_key, asyncio.Lock())
        async with gate:
            self.topology.require_fresh_planning_budget()
            self.topology.require_aggregate_capacity("composition_run_prelock")
            with self.topology.generation_store.transaction_authority():
                self.topology.require_current()
                self.topology.require_aggregate_capacity("composition_run_locked")
                result = await self.coordinator.run(self.request)
                require_successor_downstream_publication(
                    checkpoint=result.checkpoint,
                    current_pointer=result.current_pointer,
                )
                return result


def _identity(observed: os.stat_result) -> tuple[int, int]:
    return observed.st_dev, observed.st_ino


def _read_baseline_control_bytes(
    root: Path,
    *,
    expected_root_identity: tuple[int, int],
) -> tuple[bytes, bytes]:
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW | _CLOEXEC | _NONBLOCK
    root_descriptor = -1
    try:
        root_descriptor = os.open(root, directory_flags)
        root_before = os.fstat(root_descriptor)
        if not stat.S_ISDIR(root_before.st_mode) or _identity(root_before) != (
            expected_root_identity
        ):
            raise ExactSuccessorCompositionError("baseline public root changed identity")

        identity_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )

        def open_control(name: str) -> tuple[int, os.stat_result]:
            descriptor = os.open(
                name,
                os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
                dir_fd=root_descriptor,
            )
            try:
                before = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(before.st_mode)
                    or before.st_nlink != 1
                    or before.st_size < 1
                    or before.st_size > _MAX_BASELINE_CONTROL_BYTES
                ):
                    raise ExactSuccessorCompositionError(
                        f"baseline {name} is not an admissible regular control"
                    )
                return descriptor, before
            except BaseException:
                os.close(descriptor)
                raise

        def read_control(
            descriptor: int,
            before: os.stat_result,
            *,
            name: str,
        ) -> bytes:
            remaining = before.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise ExactSuccessorCompositionError(
                        f"baseline {name} ended before its admitted size"
                    )
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            before_identity = tuple(getattr(before, field) for field in identity_fields)
            if before_identity != tuple(getattr(after, field) for field in identity_fields):
                raise ExactSuccessorCompositionError(f"baseline {name} changed while being read")
            return b"".join(chunks)

        report_descriptor = manifest_descriptor = -1
        try:
            report_descriptor, report_before = open_control(
                SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME
            )
            manifest_descriptor, manifest_before = open_control(ASSURED_ARTIFACT_MANIFEST_NAME)
            report = read_control(
                report_descriptor,
                report_before,
                name=SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME,
            )
            manifest = read_control(
                manifest_descriptor,
                manifest_before,
                name=ASSURED_ARTIFACT_MANIFEST_NAME,
            )
            for name, descriptor, before in (
                (
                    SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME,
                    report_descriptor,
                    report_before,
                ),
                (ASSURED_ARTIFACT_MANIFEST_NAME, manifest_descriptor, manifest_before),
            ):
                after = os.fstat(descriptor)
                current = os.stat(name, dir_fd=root_descriptor, follow_symlinks=False)
                admitted = tuple(getattr(before, field) for field in identity_fields)
                if admitted != tuple(
                    getattr(after, field) for field in identity_fields
                ) or admitted != tuple(getattr(current, field) for field in identity_fields):
                    raise ExactSuccessorCompositionError(
                        f"baseline {name} changed during paired control read"
                    )
        finally:
            if manifest_descriptor >= 0:
                os.close(manifest_descriptor)
            if report_descriptor >= 0:
                os.close(report_descriptor)
        root_after = os.fstat(root_descriptor)
        current_root = os.stat(root, follow_symlinks=False)
        if (
            _identity(root_after) != expected_root_identity
            or _identity(current_root) != expected_root_identity
        ):
            raise ExactSuccessorCompositionError("baseline public root changed identity")
        return report, manifest
    except ExactSuccessorCompositionError:
        raise
    except OSError as exc:
        raise ExactSuccessorCompositionError(
            "baseline assurance controls cannot be read safely"
        ) from exc
    finally:
        if root_descriptor >= 0:
            os.close(root_descriptor)


def _require_exact_path(path: Path, *, label: str, must_exist: bool) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ExactSuccessorCompositionError(f"{label} must be an absolute Path")
    try:
        resolved = path.resolve(strict=must_exist)
    except OSError as exc:
        raise ExactSuccessorCompositionError(f"{label} cannot be resolved exactly") from exc
    if resolved != path:
        raise ExactSuccessorCompositionError(
            f"{label} must not contain lexical aliases or symlink ancestors"
        )
    return path


def _require_directory(
    path: Path,
    *,
    label: str,
    owner_only: bool,
) -> tuple[Path, os.stat_result]:
    exact = _require_exact_path(path, label=label, must_exist=True)
    try:
        observed = os.stat(exact, follow_symlinks=False)
    except OSError as exc:
        raise ExactSuccessorCompositionError(f"{label} cannot be inspected") from exc
    if not stat.S_ISDIR(observed.st_mode):
        raise ExactSuccessorCompositionError(f"{label} must be a non-symlink directory")
    if (
        owner_only
        and os.name == "posix"
        and (observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != _PRIVATE_MODE)
    ):
        raise ExactSuccessorCompositionError(f"{label} must be owner-only mode 0700")
    return exact, observed


def _has_ancestor_identity(path: Path, identity: tuple[int, int]) -> bool:
    current = path
    while True:
        observed = os.stat(current, follow_symlinks=False)
        if _identity(observed) == identity:
            return True
        if current == current.parent:
            return False
        current = current.parent


def _paths_overlap(
    left: Path,
    right: Path,
    *,
    left_stat: os.stat_result,
    right_stat: os.stat_result,
) -> bool:
    left_parts = tuple(part.casefold() for part in left.parts)
    right_parts = tuple(part.casefold() for part in right.parts)
    try:
        return (
            left == right
            or left.is_relative_to(right)
            or right.is_relative_to(left)
            or left_parts[: len(right_parts)] == right_parts
            or right_parts[: len(left_parts)] == left_parts
            or _identity(left_stat) == _identity(right_stat)
            or _has_ancestor_identity(left, _identity(right_stat))
            or _has_ancestor_identity(right, _identity(left_stat))
        )
    except OSError as exc:
        raise ExactSuccessorCompositionError("composition root overlap cannot be verified") from exc


def _require_pairwise_disjoint(
    observations: tuple[tuple[_DirectoryAuthority, os.stat_result], ...],
) -> None:
    for index, (left, left_stat) in enumerate(observations):
        for right, right_stat in observations[index + 1 :]:
            if _paths_overlap(left.path, right.path, left_stat=left_stat, right_stat=right_stat):
                raise ExactSuccessorCompositionError(
                    f"{left.label} and {right.label} must be disjoint"
                )


def _require_checkpoint_file(path: Path) -> None:
    _require_exact_path(path.parent, label="checkpoint parent", must_exist=True)
    if not path.exists() and not path.is_symlink():
        _require_exact_path(path, label="checkpoint path", must_exist=False)
        return
    _require_exact_path(path, label="checkpoint path", must_exist=True)
    try:
        observed = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ExactSuccessorCompositionError("checkpoint path cannot be inspected") from exc
    if not stat.S_ISREG(observed.st_mode):
        raise ExactSuccessorCompositionError("checkpoint path must be a regular non-symlink file")
    if os.name == "posix" and (
        observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != _CHECKPOINT_MODE
    ):
        raise ExactSuccessorCompositionError("checkpoint file must be owner-only mode 0600")


def _pointer_reference(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ExactSuccessorCompositionError(f"{label} successor pointer reference is invalid")
    required = {
        "generation",
        "candidate_name",
        "transaction_sha256",
        "assurance_sha256",
        "data_tree_fingerprint",
        "installed_public_tree_sha256",
        "private_generation_receipt_sha256",
    }
    if set(value) != required or type(value.get("generation")) is not int:
        raise ExactSuccessorCompositionError(f"{label} successor pointer reference is invalid")
    return cast("Mapping[str, object]", value)


def _is_exact_promoted_reentry(
    checkpoint: SuccessorCoordinatorCheckpoint | None,
    request: SuccessorCoordinatorRequest,
    current: Mapping[str, object],
) -> bool:
    if (
        checkpoint is None
        or checkpoint.phase
        not in {
            SuccessorCoordinatorPhase.TRANSACTION_PROMOTED,
            SuccessorCoordinatorPhase.PROMOTED,
        }
        or checkpoint.transaction is None
        or checkpoint.transaction.promoted_assurance is None
        or checkpoint.assurance is None
        or checkpoint.candidate_installed_public_tree_sha256 is None
    ):
        return False
    assurance = checkpoint.transaction.promoted_assurance
    expected_current = {
        "generation": checkpoint.transaction.generation,
        "candidate_name": SuccessorGenerationStore.candidate_name(checkpoint.transaction),
        "transaction_sha256": checkpoint.transaction.content_sha256,
        "assurance_sha256": assurance.identity_sha256,
        "data_tree_fingerprint": assurance.successor_data_tree_fingerprint,
        "installed_public_tree_sha256": assurance.installed_public_tree_sha256,
        "private_generation_receipt_sha256": assurance.private_generation_receipt_sha256,
    }
    return (
        checkpoint.baseline.to_dict() == request.baseline.to_dict()
        and checkpoint.planning_request.to_dict() == request.planning_request.to_dict()
        and checkpoint.candidate_admission.to_dict() == request.candidate_admission.to_dict()
        and checkpoint.generation == request.generation
        and checkpoint.transaction.baseline.to_dict() == request.baseline.to_dict()
        and checkpoint.assurance.to_dict() == assurance.to_dict()
        and checkpoint.candidate_installed_public_tree_sha256
        == assurance.installed_public_tree_sha256
        and dict(current) == expected_current
    )


def _checkpoint_matches_request(
    checkpoint: SuccessorCoordinatorCheckpoint,
    request: SuccessorCoordinatorRequest,
) -> bool:
    return (
        checkpoint.baseline.to_dict() == request.baseline.to_dict()
        and checkpoint.planning_request.to_dict() == request.planning_request.to_dict()
        and checkpoint.candidate_admission.to_dict() == request.candidate_admission.to_dict()
        and checkpoint.generation == request.generation
    )


def _capture_authority(path: Path, *, label: str, owner_only: bool) -> _DirectoryAuthority:
    exact, observed = _require_directory(path, label=label, owner_only=owner_only)
    return _DirectoryAuthority(
        path=exact,
        label=label,
        identity=_identity(observed),
        owner_only=owner_only,
    )


def _require_inherited_control_authority(
    request: SuccessorCoordinatorRequest,
    contract_blocked_evidence: Mapping[str, Any],
) -> None:
    from nbadb.orchestrate.full_extraction_control import (
        _validated_checkpoint_contract_blocked_evidence,
    )

    provider_digest = expected_nba_api_provider_authority()["authority_sha256"]
    if request.baseline.provider_authority_sha256 != provider_digest:
        raise ExactSuccessorCompositionError(
            "baseline provider authority differs from the current pinned provider"
        )
    lanes = contract_blocked_evidence.get("contract_blocked_lanes")
    if not isinstance(lanes, list):
        raise ExactSuccessorCompositionError("contract-blocked lane evidence is invalid")
    supplied_digest = canonical_sha256(contract_blocked_evidence)
    try:
        _rows, validated_digest = _validated_checkpoint_contract_blocked_evidence(
            {
                "contract_blocked_lane_count": len(lanes),
                "contract_blocked_evidence": contract_blocked_evidence,
                "contract_blocked_evidence_sha256": supplied_digest,
            }
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ExactSuccessorCompositionError("contract-blocked lane evidence is invalid") from exc
    if (
        validated_digest != supplied_digest
        or validated_digest != request.baseline.contract_blocked_evidence_sha256
    ):
        raise ExactSuccessorCompositionError(
            "contract-blocked evidence differs from baseline authority"
        )


def _capture_planning_registry_authority(
    request: SuccessorCoordinatorRequest,
    registry: EndpointRegistry,
) -> EndpointRegistryAuthority:
    endpoint_names = tuple(
        sorted(
            {scope.endpoint_name for scope in request.planning_request.requested_planning_scopes}
        )
    )
    if not endpoint_names:
        raise ExactSuccessorCompositionError("planning request has no required endpoints")
    try:
        return registry.capture_authority(endpoint_names)
    except EndpointRegistryAuthorityError as exc:
        raise ExactSuccessorCompositionError(
            "planning registry cannot bind the exact request endpoints"
        ) from exc


def _capture_update_registry_authority(
    registry: EndpointRegistry,
) -> EndpointRegistryAuthority:
    endpoint_names = tuple(
        sorted({route.endpoint_name for route in staging_route_contract_bundle().routes})
    )
    try:
        return registry.capture_authority(endpoint_names)
    except EndpointRegistryAuthorityError as exc:
        raise ExactSuccessorCompositionError(
            "update registry cannot bind the complete staging-route endpoint inventory"
        ) from exc


def _require_planning_budget(
    budget: object,
    *,
    request: SuccessorCoordinatorRequest,
) -> PlanningStoreBudget:
    if not isinstance(budget, PlanningStoreBudget):
        raise ExactSuccessorCompositionError("fresh planning budget must be PlanningStoreBudget")
    admission = request.candidate_admission
    capacity = admission.aggregate_capacity
    if (
        budget.generation_max_bytes != capacity.planning_store_generation_max_bytes
        or budget.artifact_max_bytes != capacity.planning_store_artifact_max_bytes
        or budget.control_max_bytes != capacity.planning_store_control_max_bytes
        or budget.minimum_free_bytes != capacity.minimum_free_bytes
    ):
        raise ExactSuccessorCompositionError(
            "fresh planning budget byte bounds differ from aggregate capacity"
        )
    if budget.monotonic_deadline_seconds != admission.monotonic_deadline_seconds:
        raise ExactSuccessorCompositionError(
            "fresh planning budget deadline differs from candidate admission"
        )
    if budget.minimum_deadline_headroom_seconds < admission.minimum_pre_provider_headroom_seconds:
        raise ExactSuccessorCompositionError(
            "fresh planning budget headroom is below candidate admission"
        )
    return budget


def _admit_topology(
    *,
    request: SuccessorCoordinatorRequest,
    config: ExactSuccessorCompositionConfig,
    generation_store: SuccessorGenerationStore,
    planning_store_object: SuccessorPlanningStore,
    checkpoint_store: SuccessorCoordinatorCheckpointStore,
    generation_authority: _DirectoryAuthority,
    generations_authority: _DirectoryAuthority,
    checkpoint_parent_authority: _DirectoryAuthority,
    planning_registry_authority: EndpointRegistryAuthority,
    update_registry_authority: EndpointRegistryAuthority,
    fresh_planning_budget: Callable[[], PlanningStoreBudget],
) -> ExactSuccessorTopologyAuthority:
    generation = generation_authority
    generations = generations_authority
    if generations.path.parent != generation.path:
        raise ExactSuccessorCompositionError("generation directory is not store-owned")

    checkpoint_parent = checkpoint_parent_authority
    planning_store = _capture_authority(
        config.planning_store_root,
        label="planning store",
        owner_only=True,
    )
    planning_work = _capture_authority(
        config.planning_work_root,
        label="planning work root",
        owner_only=True,
    )
    planning_capture = _capture_authority(
        config.planning_capture_root,
        label="planning capture",
        owner_only=True,
    )
    body_blob = _capture_authority(
        config.body_blob_root,
        label="body-blob root",
        owner_only=True,
    )
    declared_bodyless_packet = _capture_authority(
        config.declared_bodyless_packet_root,
        label="declared-bodyless packet root",
        owner_only=True,
    )
    update_capture = _capture_authority(
        config.update_capture_root,
        label="update capture",
        owner_only=True,
    )
    update_terminal = _capture_authority(
        config.update_terminal_receipt_root,
        label="update terminal receipt root",
        owner_only=True,
    )
    runtime_log = _capture_authority(
        config.runtime_log_root,
        label="runtime log root",
        owner_only=True,
    )
    assurance_scratch = _capture_authority(
        config.assurance_scratch_root,
        label="assurance scratch root",
        owner_only=True,
    )
    private = (
        checkpoint_parent,
        planning_store,
        planning_work,
        planning_capture,
        body_blob,
        declared_bodyless_packet,
        update_capture,
        update_terminal,
        runtime_log,
        assurance_scratch,
    )
    baseline = _capture_authority(
        request.baseline_public_root,
        label="baseline public root",
        owner_only=False,
    )
    _require_checkpoint_file(config.checkpoint_path)

    planning_generation_id = deterministic_planning_generation_id(request.planning_request)

    def existing_planning_bytes(root_descriptor: int) -> int:
        return planning_store_object.existing_generation_logical_bytes(
            request.planning_request,
            planning_generation_id,
            root_descriptor=root_descriptor,
            budget=fresh_planning_budget(),
        )

    def descriptor_capacity_probe(
        descriptor: int,
        _root: CapacityRoot,
    ) -> tuple[int, int]:
        return os.fstat(descriptor).st_dev, config.free_bytes_probe(descriptor)

    capacity_authority = ExactSuccessorAggregateCapacityAuthority(
        admission=request.candidate_admission,
        roots=(
            CapacityRoot(
                role=SuccessorCapacityRole.GENERATION_STORE,
                path=generation.path,
                expected_identity=generation.identity,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.COORDINATOR_CHECKPOINT,
                path=checkpoint_parent.path,
                expected_identity=checkpoint_parent.identity,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.PLANNING_STORE,
                path=planning_store.path,
                expected_identity=planning_store.identity,
                existing_bytes_callback=existing_planning_bytes,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.PLANNING_WORK,
                path=planning_work.path,
                expected_identity=planning_work.identity,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.PLANNING_CAPTURE,
                path=planning_capture.path,
                expected_identity=planning_capture.identity,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.BODY_BLOB,
                path=body_blob.path,
                expected_identity=body_blob.identity,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.DECLARED_BODYLESS_PACKET,
                path=declared_bodyless_packet.path,
                expected_identity=declared_bodyless_packet.identity,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.UPDATE_CAPTURE,
                path=update_capture.path,
                expected_identity=update_capture.identity,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.TERMINAL_RECEIPT,
                path=update_terminal.path,
                expected_identity=update_terminal.identity,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.RUNTIME_LOG,
                path=runtime_log.path,
                expected_identity=runtime_log.identity,
            ),
            CapacityRoot(
                role=SuccessorCapacityRole.ASSURANCE_SCRATCH,
                path=assurance_scratch.path,
                expected_identity=assurance_scratch.identity,
            ),
        ),
        monotonic_clock=config.monotonic_clock,
        monotonic_epoch_authority=config.monotonic_epoch_authority,
        descriptor_probe=descriptor_capacity_probe,
    )
    authority = ExactSuccessorTopologyAuthority(
        request=request,
        generation_store=generation_store,
        checkpoint_store=checkpoint_store,
        private_roots=private,
        generation_store_authority=generation,
        generations_authority=generations,
        baseline_authority=baseline,
        update_capture_authority=update_capture,
        update_terminal_receipt_authority=update_terminal,
        runtime_log_authority=runtime_log,
        assurance_scratch_authority=assurance_scratch,
        contract_blocked_evidence=config.contract_blocked_evidence,
        planning_registry=config.planning_registry,
        planning_registry_authority=planning_registry_authority,
        update_registry_authority=update_registry_authority,
        fresh_planning_budget=fresh_planning_budget,
        aggregate_capacity_authority=capacity_authority,
        planning_store_authority=planning_store,
        planning_work_authority=planning_work,
        planning_capture_authority=planning_capture,
    )
    authority.require_current()
    authority.require_aggregate_capacity("composition_build")
    return authority


_PLANNING_PROVIDER_ENDPOINT_IDS: Final = {
    "league_game_log": "LeagueGameLog",
    "player_game_logs": "PlayerGameLogs",
    "common_all_players": "CommonAllPlayers",
    "common_team_years": "CommonTeamYears",
}


def _provider_semantic_parameters(
    endpoint_name: str,
    logical_parameters: Mapping[str, object],
) -> dict[str, object]:
    """Project one sealed successor call onto its pinned provider parameters."""

    if endpoint_name == "league_game_log":
        return {
            "season": logical_parameters["season"],
            "season_type_all_star": logical_parameters["season_type"],
        }
    if endpoint_name == "player_game_logs":
        return {
            "season_nullable": logical_parameters["season"],
            "season_type_nullable": logical_parameters["season_type"],
        }
    if endpoint_name == "common_all_players":
        is_only_current_season = logical_parameters["is_only_current_season"]
        if isinstance(is_only_current_season, bool) or not isinstance(is_only_current_season, int):
            raise ExactSuccessorCompositionError(
                "common_all_players is_only_current_season must be an int"
            )
        semantic: dict[str, object] = {"is_only_current_season": is_only_current_season}
        season = logical_parameters.get("season")
        if season:
            semantic["season"] = season
        return semantic
    if endpoint_name == "common_team_years":
        return {}
    raise ExactSuccessorCompositionError(
        f"successor planning endpoint {endpoint_name!r} has no pinned provider projection"
    )


def build_production_successor_w2_authority_resources(
    *,
    body_blob_root: Path,
    declared_bodyless_packet_root: Path,
) -> PlanningW2AuthorityResourcesV1:
    """Build the seven real W2 authorities for one production successor run.

    Every factory is a real constructor over pinned provider contracts, the
    admitted private capacity roots, or the run-owned DuckDB connection.  The
    live-plan authority is the typed unavailable sentinel: the planning runtime
    rejects a live dispatch that carries it before any provider, store, intent,
    or upload effect.  No mock, fallback orchestrator, or fabricated live
    authority participates in this construction.
    """

    for label, root in (
        ("body-blob", body_blob_root),
        ("declared-bodyless packet", declared_bodyless_packet_root),
    ):
        if not isinstance(root, Path) or not root.is_absolute():
            raise ExactSuccessorCompositionError(
                f"production {label} root must be an absolute Path"
            )
        try:
            observed = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise ExactSuccessorCompositionError(f"production {label} root is unavailable") from exc
        if not stat.S_ISDIR(observed.st_mode) or (
            os.name == "posix"
            and (observed.st_uid != os.geteuid() or stat.S_IMODE(observed.st_mode) != _PRIVATE_MODE)
        ):
            raise ExactSuccessorCompositionError(
                f"production {label} root lacks owner-only 0700 authority"
            )

    provider_authority_sha256 = staging_route_contract_bundle().provider_authority_sha256

    def raw_request_context_factory(
        scope: CaptureRunScope,
        endpoint_name: str,
        parameters: dict[str, object],
    ) -> RawRequestCaptureContextV2:
        endpoint_id = _PLANNING_PROVIDER_ENDPOINT_IDS.get(endpoint_name)
        if endpoint_id is None:
            raise ExactSuccessorCompositionError(
                f"successor planning endpoint {endpoint_name!r} has no pinned runtime contract"
            )
        contract = pinned_runtime_contracts()[endpoint_id]
        semantic = _provider_semantic_parameters(endpoint_name, parameters)
        _safe_json, _safe_sha256, provider_request_sha256 = canonical_semantic_parameters(
            "stats",
            endpoint_id,
            semantic,
        )
        scope_sha256 = canonical_parameters_sha256(parameters)
        semantic_request_sha256 = canonical_sha256(
            {
                "endpoint_id": endpoint_id,
                "provider_request_sha256": provider_request_sha256,
                "scope_identity_sha256": scope.identity_sha256,
            }
        )
        logical_invocation_sha256 = canonical_sha256(
            {
                "endpoint_name": endpoint_name,
                "scope_identity_sha256": scope.identity_sha256,
                "scope_sha256": scope_sha256,
            }
        )
        return RawRequestCaptureContextV2(
            provider_authority_sha256=provider_authority_sha256,
            source_sha=scope.semantic_source_sha,
            run_id=scope.workflow_run_id,
            run_attempt=scope.workflow_run_attempt,
            chain_id=scope.chain_id,
            lane_id=scope.lane_id,
            provider_calls=(
                RawProviderCallContextV2(
                    request_ordinal=0,
                    semantic_request_sha256=semantic_request_sha256,
                    logical_invocation_sha256=logical_invocation_sha256,
                    provider_call_role="primary",
                    provider_call_ordinal=0,
                    source_family="stats",
                    endpoint_id=endpoint_id,
                    provider_request_sha256=provider_request_sha256,
                    endpoint_contract_sha256=endpoint_contract_sha256(contract),
                    scope_sha256=scope_sha256,
                ),
            ),
        )

    def logical_provider_parameter_binding_factory(
        scope: CaptureRunScope,
        request: PlanningExactCallRuntimeRequest,
        context: RawRequestCaptureContextV2,
    ) -> tuple[LogicalProviderParameterBindingV1, str]:
        if not isinstance(request, PlanningExactCallRuntimeRequest):
            raise ExactSuccessorCompositionError(
                "successor planning binding requires a PlanningExactCallRuntimeRequest"
            )
        dispatch = request.dispatch
        endpoint_name = dispatch.endpoint_name
        semantic = _provider_semantic_parameters(endpoint_name, dispatch.parameters)
        binding = compile_logical_provider_parameter_binding(
            raw_request_context=context,
            logical_endpoint_name=endpoint_name,
            logical_parameters=dict(dispatch.parameters),
            result_route_ids=tuple(sorted(dispatch.staging_route_ids)),
            provider_semantic_parameters=(semantic,),
        )
        return binding, binding.binding_sha256

    def w2_preparation_runtime_factory(
        scope: CaptureRunScope,
    ) -> W2SourceCallPreparationRuntime:
        identity = {
            "source_sha": scope.semantic_source_sha,
            "run_id": scope.workflow_run_id,
            "run_attempt": scope.workflow_run_attempt,
            "chain_id": scope.chain_id,
            "lane_id": scope.lane_id,
        }
        return W2SourceCallPreparationRuntime(
            body_blob_store=BodyBlobStore(body_blob_root, **identity),
            declared_bodyless_packet_store=DeclaredBodylessPacketStore(
                declared_bodyless_packet_root,
                **identity,
            ),
            field_fate=compile_field_fate_structure(),
        )

    return PlanningW2AuthorityResourcesV1(
        raw_request_context_factory=raw_request_context_factory,
        w2_preparation_runtime_factory=w2_preparation_runtime_factory,
        raw_authority_store_factory=RawRequestAuthorityStore,
        public_value_store_factory=PublicValueAuthorityStore,
        w2_operation_store_factory=W2OperationStore,
        live_plan_binding_factory=unavailable_live_plan_binding_factory,
        logical_provider_parameter_binding_factory=logical_provider_parameter_binding_factory,
    )


def build_exact_successor_composition(
    *,
    request: SuccessorCoordinatorRequest,
    config: ExactSuccessorCompositionConfig,
) -> ExactSuccessorComposition:
    """Compose one exact request only after whole-graph topology admission."""

    if not isinstance(request, SuccessorCoordinatorRequest):
        raise ExactSuccessorCompositionError("request must be SuccessorCoordinatorRequest")
    if not isinstance(config, ExactSuccessorCompositionConfig):
        raise ExactSuccessorCompositionError("config must be ExactSuccessorCompositionConfig")
    validate_successor_planning_request(request.planning_request)
    _require_inherited_control_authority(request, config.contract_blocked_evidence)
    planning_registry_authority = _capture_planning_registry_authority(
        request,
        config.planning_registry,
    )
    update_registry_authority = _capture_update_registry_authority(
        config.planning_registry,
    )
    _require_planning_budget(config.fresh_planning_budget(), request=request)
    generation_authority = _capture_authority(
        config.generation_store_root,
        label="generation store",
        owner_only=True,
    )
    generations_authority = _capture_authority(
        config.generation_store_root / "generations",
        label="generation directory",
        owner_only=True,
    )
    generation_store = SuccessorGenerationStore(
        config.generation_store_root,
        expected_root_identity=generation_authority.identity,
        expected_generations_identity=generations_authority.identity,
    )
    checkpoint_parent_authority = _capture_authority(
        config.checkpoint_path.parent,
        label="checkpoint parent",
        owner_only=True,
    )
    checkpoint_store = _BoundSuccessorCoordinatorCheckpointStore(
        config.checkpoint_path,
        expected_parent_identity=checkpoint_parent_authority.identity,
        max_bytes=(request.candidate_admission.aggregate_capacity.coordinator_checkpoint_max_bytes),
    )

    def fresh_planning_budget() -> PlanningStoreBudget:
        return _require_planning_budget(config.fresh_planning_budget(), request=request)

    public_roots = (request.baseline_public_root,)
    planning_store = SuccessorPlanningStore(
        config.planning_store_root,
        public_roots=public_roots,
        monotonic_clock=config.monotonic_clock,
    )
    topology = _admit_topology(
        request=request,
        config=config,
        generation_store=generation_store,
        planning_store_object=planning_store,
        checkpoint_store=checkpoint_store,
        generation_authority=generation_authority,
        generations_authority=generations_authority,
        checkpoint_parent_authority=checkpoint_parent_authority,
        planning_registry_authority=planning_registry_authority,
        update_registry_authority=update_registry_authority,
        fresh_planning_budget=fresh_planning_budget,
    )

    capacity = request.candidate_admission.aggregate_capacity
    planning_capture_limits = replace(
        config.capture_limits,
        max_generation_stored_bytes=capacity.planning_wave_capture_max_bytes,
        minimum_free_bytes=capacity.minimum_free_bytes,
        max_checkpoint_bytes=capacity.planning_wave_checkpoint_max_bytes,
        minimum_deadline_headroom_seconds=(
            request.candidate_admission.minimum_pre_provider_headroom_seconds
        ),
    )
    update_capture_limits = replace(
        config.capture_limits,
        max_generation_stored_bytes=capacity.update_capture_max_bytes,
        minimum_free_bytes=capacity.minimum_free_bytes,
        max_checkpoint_bytes=capacity.update_checkpoint_max_bytes,
        minimum_deadline_headroom_seconds=(
            request.candidate_admission.minimum_deadline_headroom_seconds
        ),
    )
    planning_runtime_config = ExactPlanningRuntimeConfig(
        w2_authority_resources=config.w2_authority_resources,
        settings=config.settings,
        registry=config.planning_registry,
        registry_authority=planning_registry_authority,
        capture_base=config.planning_capture_root,
        planning_store_root=config.planning_store_root,
        public_roots=public_roots,
        capture_limits=planning_capture_limits,
        estimated_checkpoint_bytes=capacity.planning_wave_checkpoint_max_bytes,
        planning_driver_database_max_bytes=capacity.planning_driver_database_max_bytes,
        monotonic_deadline_seconds=request.candidate_admission.monotonic_deadline_seconds,
        minimum_deadline_headroom_seconds=(
            request.candidate_admission.minimum_pre_provider_headroom_seconds
        ),
        before_planning_effects_authority=lambda: topology.require_aggregate_capacity(
            "before_planning_effects"
        ),
        before_provider_authority=lambda: topology.require_aggregate_capacity(
            "before_planning_provider"
        ),
        monotonic_clock=config.monotonic_clock,
    )

    planning_executor = build_successor_planning_executor(
        store=planning_store,
        config=planning_runtime_config,
        fresh_budget=fresh_planning_budget,
        planning_work_root=config.planning_work_root,
        expected_planning_work_root_identity=topology.planning_work_authority.identity,
    )
    capture_scope_template = CaptureRunScope(
        semantic_source_sha=request.planning_request.source_sha,
        chain_id=request.baseline.chain_id,
        lane_id="composition-template",
        workflow_run_id=request.planning_request.workflow_run_id,
        workflow_run_attempt=request.planning_request.workflow_run_attempt,
    )
    runtime_factory = ExactPlanSuccessorRuntimeFactory(
        base_settings=config.settings,
        capture_scope_template=capture_scope_template,
        capture_limits=update_capture_limits,
        capture_base_root=config.update_capture_root,
        expected_capture_base_identity=topology.update_capture_authority.identity,
        terminal_receipt_base_root=config.update_terminal_receipt_root,
        expected_terminal_receipt_base_identity=(
            topology.update_terminal_receipt_authority.identity
        ),
        log_dir=config.runtime_log_root,
        expected_log_root_identity=topology.runtime_log_authority.identity,
        registry=config.planning_registry,
        registry_authority=topology.update_registry_authority,
        transform_scratch_parent=config.assurance_scratch_root,
        expected_transform_scratch_identity=(topology.assurance_scratch_authority.identity),
        transform_scratch_max_bytes=capacity.transform_scratch_max_bytes,
        terminal_receipt_max_bytes=capacity.terminal_receipt_max_bytes,
        runtime_log_max_bytes=capacity.runtime_log_max_bytes,
        candidate_max_bytes=capacity.candidate_max_bytes,
        estimated_checkpoint_bytes=capacity.update_checkpoint_max_bytes,
        monotonic_deadline_seconds=request.candidate_admission.monotonic_deadline_seconds,
        monotonic_clock=config.monotonic_clock,
    )
    private_resolver = RetainedBronzeUpdateResolver(
        config.update_capture_root,
        limits=update_capture_limits,
    )
    scanner = SuccessorFullPublicationScanner(
        scratch_root=config.assurance_scratch_root,
        expected_scratch_root_identity=topology.assurance_scratch_authority.identity,
        max_database_bytes=capacity.scan_database_snapshot_max_bytes,
        minimum_free_bytes=capacity.minimum_free_bytes,
        deadline_monotonic=request.candidate_admission.monotonic_deadline_seconds,
        headroom_seconds=request.candidate_admission.minimum_deadline_headroom_seconds,
        monotonic_clock=config.monotonic_clock,
        free_bytes_probe=config.free_bytes_probe,
        scan_function=config.scan_function,
    )

    def publication_inventory(
        public_root: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> SuccessorPublicationInventoryEvidence:
        return build_successor_publication_inventory(
            public_root,
            scratch_parent=config.assurance_scratch_root,
            expected_scratch_root_identity=topology.assurance_scratch_authority.identity,
            inventory_duckdb_snapshot_max_bytes=(capacity.inventory_duckdb_snapshot_max_bytes),
            inventory_sqlite_snapshot_max_bytes=(capacity.inventory_sqlite_snapshot_max_bytes),
            transform_scratch_max_bytes=capacity.transform_scratch_max_bytes,
            expected_root_identity=expected_root_identity,
        )

    def installed_tree(
        public_root: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> InstalledPublicTreeInventory:
        return measure_installed_public_tree(
            public_root,
            expected_root_identity=expected_root_identity,
        )

    assurance_builder = ExactSuccessorAssuranceBuilder(
        chain_id=request.baseline.chain_id,
        contract_blocked_evidence=config.contract_blocked_evidence,
        provider_authority=expected_nba_api_provider_authority(),
        scanner=scanner,
        inventory=publication_inventory,
        installed_tree=installed_tree,
        private_generation_resolver=private_resolver,
    )

    def installed_public_tree_digest(public_root: Path) -> str:
        return measure_installed_public_tree(public_root).installed_public_tree_sha256

    coordinator = SuccessorCoordinator(
        generation_store=generation_store,
        checkpoint_store=checkpoint_store,
        planning_executor=planning_executor,
        runtime_factory=runtime_factory,
        assurance_builder=assurance_builder,
        installed_public_tree_digest=installed_public_tree_digest,
        monotonic_epoch_authority=config.monotonic_epoch_authority,
        monotonic_clock=config.monotonic_clock,
    )
    return ExactSuccessorComposition(
        request=request,
        coordinator=coordinator,
        topology=topology,
    )
