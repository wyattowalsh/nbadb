"""Dependency-injected state machine for recurring successor generations.

This module deliberately owns no provider, workflow, storage-rights, export,
scan, or publication policy.  Callers supply those implementations together
with every path, capacity bound, and deadline measurement.  The coordinator
only sequences their already-defined contracts and persists enough canonical,
path-free authority to resume the exact same transaction after interruption.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import stat
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, Self, cast

from nbadb.orchestrate.capture_session import PrivateGenerationIdentity
from nbadb.orchestrate.successor_assurance import SuccessorTransformOutputAttestation
from nbadb.orchestrate.successor_generation_store import (
    SUCCESSOR_CANDIDATE_BASELINE_NAME,
    SUCCESSOR_TRANSACTION_NAME,
    SuccessorGenerationStore,
    SuccessorGenerationStoreError,
)
from nbadb.orchestrate.successor_planning_contract import (
    SuccessorPlanningEvidence,
    SuccessorPlanningRequest,
    finalize_successor_update_intent,
)
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    ObservedDeltaReceipt,
    RequestedRouteScope,
    SuccessorAssuranceIdentity,
    SuccessorGenerationState,
    SuccessorUpdateContractError,
    SuccessorUpdateIntent,
    SuccessorUpdateMode,
    SuccessorUpdateTransaction,
    canonical_json_bytes,
    canonical_sha256,
)

if TYPE_CHECKING:
    from nbadb.orchestrate.successor_execution_plan import SuccessorExecutionPlan

__all__ = [
    "InstalledPublicTreeDigest",
    "SuccessorAssuranceBuildInput",
    "SuccessorAssuranceBuilder",
    "SuccessorAggregateCapacityContract",
    "SuccessorCandidateAdmission",
    "SuccessorCoordinator",
    "SuccessorCoordinatorCheckpoint",
    "SuccessorCoordinatorCheckpointStore",
    "SuccessorCoordinatorError",
    "SuccessorCoordinatorPhase",
    "SuccessorCoordinatorRequest",
    "SuccessorCoordinatorResult",
    "SuccessorPlanningExecutor",
    "SuccessorUpdateRuntime",
    "SuccessorUpdateRuntimeFactory",
    "require_successor_downstream_publication",
]

_DOWNSTREAM_PUBLICATION_BLOCKED = (
    "cancellation, interruption, or an incomplete stage blocks scan, export, and upload"
)
_STALE_CHECKPOINT_PHASE = (
    "durable transaction or admission is ahead of or differs from the restored phase"
)

_CHECKPOINT_SCHEMA_VERSION = 7
_CHECKPOINT_KIND = "successor_coordinator_checkpoint"
_MAX_SIGNED_63 = (1 << 63) - 1


class SuccessorCoordinatorError(RuntimeError):
    """Raised when a successor step is incomplete, drifting, or out of order."""


class SuccessorCoordinatorPhase(StrEnum):
    """Durable coordinator phases surrounding the four-state transaction."""

    REQUESTED = "requested"
    PLANNED = "planned"
    INTENT_FINALIZED = "intent_finalized"
    CANDIDATE = "candidate"
    EXECUTING = "executing"
    EXECUTED = "executed"
    BUILT = "built"
    ASSURING = "assuring"
    ASSURED = "assured"
    VALIDATED = "validated"
    TRANSACTION_PROMOTED = "transaction_promoted"
    PROMOTED = "promoted"


_PHASE_ORDER = tuple(SuccessorCoordinatorPhase)
_PHASE_RANK = {phase: index for index, phase in enumerate(_PHASE_ORDER)}
_ALLOWED_DURABLE_TRANSACTION_STATES = {
    SuccessorCoordinatorPhase.INTENT_FINALIZED: {SuccessorGenerationState.CANDIDATE},
    SuccessorCoordinatorPhase.CANDIDATE: {SuccessorGenerationState.CANDIDATE},
    SuccessorCoordinatorPhase.EXECUTING: {SuccessorGenerationState.CANDIDATE},
    SuccessorCoordinatorPhase.EXECUTED: {
        SuccessorGenerationState.CANDIDATE,
        SuccessorGenerationState.BUILT,
    },
    SuccessorCoordinatorPhase.BUILT: {SuccessorGenerationState.BUILT},
    SuccessorCoordinatorPhase.ASSURING: {SuccessorGenerationState.BUILT},
    SuccessorCoordinatorPhase.ASSURED: {
        SuccessorGenerationState.BUILT,
        SuccessorGenerationState.VALIDATED,
    },
    SuccessorCoordinatorPhase.VALIDATED: {
        SuccessorGenerationState.VALIDATED,
        SuccessorGenerationState.PROMOTED,
    },
    SuccessorCoordinatorPhase.TRANSACTION_PROMOTED: {SuccessorGenerationState.PROMOTED},
    SuccessorCoordinatorPhase.PROMOTED: {SuccessorGenerationState.PROMOTED},
}


class _PipelineResultLike(Protocol):
    failed_extractions: int
    failed_loads: int
    errors: list[str]


class _TransformOutputLike(Protocol):
    @property
    def table_name(self) -> str: ...

    @property
    def row_count(self) -> int: ...

    @property
    def schema_sha256(self) -> str: ...

    @property
    def content_sha256(self) -> str: ...


class SuccessorPlanningExecutor(Protocol):
    """Resume-safe planning worker backed by retained private generation bytes."""

    async def __call__(self, request: SuccessorPlanningRequest) -> SuccessorPlanningEvidence: ...

    def verify(
        self,
        request: SuccessorPlanningRequest,
        evidence: SuccessorPlanningEvidence,
    ) -> SuccessorPlanningEvidence:
        """Reload every durable planning byte and return the exact sealed evidence."""
        ...


class SuccessorUpdateRuntime(Protocol):
    """Real Orchestrator-shaped update runtime for one admitted candidate.

    The runtime factory is responsible for injecting the candidate-specific
    settings, generation-aware journal, and admitted private capture session.
    An ``executing`` phase may be re-entered after a crash, so the runtime must
    resume the same generation rather than widen or replace it.
    """

    async def run_daily(self) -> _PipelineResultLike: ...

    async def run_monthly(self) -> _PipelineResultLike: ...

    def restore_same_generation_execution(self) -> None:
        """Reopen journal/capture/candidate progress without restarting execution."""
        ...

    @property
    def capture_identity(self) -> object: ...

    @property
    def successor_delta_receipts(self) -> Sequence[ObservedDeltaReceipt]: ...

    @property
    def planned_route_replacement_bindings_sha256(self) -> str: ...

    @property
    def transform_output_attestations(self) -> Sequence[_TransformOutputLike]: ...


class SuccessorUpdateRuntimeFactory(Protocol):
    def __call__(
        self,
        transaction: SuccessorUpdateTransaction,
        candidate_root: Path,
        execution_plan: SuccessorExecutionPlan,
    ) -> SuccessorUpdateRuntime: ...


class InstalledPublicTreeDigest(Protocol):
    """Return the exact descriptor-inventoried SHA-256 for an installed public root."""

    def __call__(self, public_root: Path) -> str: ...


class SuccessorAssuranceBuilder(Protocol):
    """Idempotently build and validate export/scan assurance for one build."""

    async def __call__(
        self,
        build_input: SuccessorAssuranceBuildInput,
    ) -> SuccessorAssuranceIdentity: ...


def _require_sha256(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SuccessorCoordinatorError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise SuccessorCoordinatorError(f"{field_name} must be a positive integer")
    return value


def _require_positive_signed63_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1 or value > _MAX_SIGNED_63:
        raise SuccessorCoordinatorError(f"{field_name} must be a positive signed-63-bit integer")
    return value


def _checked_signed63_sum(*values: int, field_name: str) -> int:
    total = 0
    for value in values:
        if value > _MAX_SIGNED_63 - total:
            raise SuccessorCoordinatorError(f"{field_name} exceeds signed-63-bit range")
        total += value
    return total


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise SuccessorCoordinatorError(f"{field_name} must be a nonnegative integer")
    return value


def _require_positive_finite(value: object, *, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise SuccessorCoordinatorError(f"{field_name} must be positive and finite")
    return float(value)


def _logical_call_roots(
    receipts: Sequence[ObservedDeltaReceipt],
) -> tuple[str, ...]:
    return tuple(sorted({receipt.logical_call_receipt_sha256 for receipt in receipts}))


def _peek_successor_transaction(candidate_root: Path) -> SuccessorUpdateTransaction | None:
    path = candidate_root / SUCCESSOR_TRANSACTION_NAME
    if path.is_symlink() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    try:
        return SuccessorUpdateTransaction.from_dict(cast("Mapping[str, object]", payload))
    except (SuccessorUpdateContractError, TypeError, ValueError):
        return None


def _peek_successor_admission(candidate_root: Path) -> Mapping[str, object] | None:
    path = candidate_root / SUCCESSOR_CANDIDATE_BASELINE_NAME
    if path.is_symlink() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping) or not all(isinstance(key, str) for key in payload):
        return None
    return cast("Mapping[str, object]", payload)


def _logical_call_bindings_sha256(
    *,
    baseline: BaselineAssuranceIdentity,
    intent: SuccessorUpdateIntent,
    receipts: Sequence[ObservedDeltaReceipt],
) -> str:
    scopes_by_identity = {scope.identity_sha256: scope for scope in intent.requested_scopes}
    routes_by_root: dict[str, list[RequestedRouteScope]] = {}
    for receipt in receipts:
        scope = scopes_by_identity.get(receipt.requested_scope_sha256)
        if scope is None:
            raise SuccessorCoordinatorError(
                "observed delta receipt falls outside the immutable update intent"
            )
        routes_by_root.setdefault(receipt.logical_call_receipt_sha256, []).append(scope)

    binding_payloads: list[dict[str, object]] = []
    for root in sorted(routes_by_root):
        scopes = routes_by_root[root]
        parameter_digests = {scope.scope_sha256 for scope in scopes}
        endpoint_names = {scope.endpoint_name for scope in scopes}
        route_ids = sorted(scope.route_id for scope in scopes)
        if (
            len(parameter_digests) != 1
            or len(endpoint_names) != 1
            or len(route_ids) != len(set(route_ids))
        ):
            raise SuccessorCoordinatorError(
                "observed delta logical call has inconsistent endpoint, parameters, or routes"
            )
        binding_payloads.append(
            {
                "endpoint_name": next(iter(endpoint_names)),
                "logical_call_receipt_sha256": root,
                "logical_parameters_sha256": next(iter(parameter_digests)),
                "provider_authority_sha256": baseline.provider_authority_sha256,
                "result_route_ids": route_ids,
            }
        )
    return canonical_sha256(binding_payloads)


def _private_generation_from_dict(
    payload: Mapping[str, object],
    *,
    expected_logical_call_roots: tuple[str, ...],
    expected_logical_call_bindings_sha256: str,
) -> PrivateGenerationIdentity:
    expected = {
        "schema_version",
        "kind",
        "manifest_sha256",
        "provider_authority_sha256",
        "semantic_source_sha",
        "chain_id",
        "lane_id",
        "workflow_run_id",
        "workflow_run_attempt",
        "artifact_count",
        "done_call_count",
        "done_call_receipt_sha256s",
        "done_call_receipts_sha256",
        "done_call_bindings_sha256",
        "done_attempt_count",
        "done_blob_count",
        "orphan_call_count",
        "orphan_attempt_count",
        "orphan_blob_count",
        "stored_bytes",
    }
    if set(payload) != expected:
        raise SuccessorCoordinatorError("private generation checkpoint fields are invalid")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != PrivateGenerationIdentity.schema_version
        or payload["kind"] != PrivateGenerationIdentity.kind
    ):
        raise SuccessorCoordinatorError("private generation checkpoint schema is invalid")
    string_fields = ("chain_id", "lane_id")
    if any(not isinstance(payload[field_name], str) for field_name in string_fields):
        raise SuccessorCoordinatorError("private generation checkpoint strings are invalid")
    semantic_source_sha = payload["semantic_source_sha"]
    if not isinstance(semantic_source_sha, str):
        raise SuccessorCoordinatorError("private generation source SHA is invalid")
    raw_roots = payload["done_call_receipt_sha256s"]
    if not isinstance(raw_roots, list):
        raise SuccessorCoordinatorError("private generation logical-call roots must be a list")
    result = PrivateGenerationIdentity(
        manifest_sha256=_require_sha256(
            payload["manifest_sha256"], field_name="private manifest_sha256"
        ),
        provider_authority_sha256=_require_sha256(
            payload["provider_authority_sha256"],
            field_name="private provider_authority_sha256",
        ),
        semantic_source_sha=semantic_source_sha,
        chain_id=cast("str", payload["chain_id"]),
        lane_id=cast("str", payload["lane_id"]),
        workflow_run_id=_require_positive_int(
            payload["workflow_run_id"], field_name="private workflow_run_id"
        ),
        workflow_run_attempt=_require_positive_int(
            payload["workflow_run_attempt"], field_name="private workflow_run_attempt"
        ),
        artifact_count=_require_nonnegative_int(
            payload["artifact_count"], field_name="private artifact_count"
        ),
        done_call_count=_require_nonnegative_int(
            payload["done_call_count"], field_name="private done_call_count"
        ),
        done_call_receipt_sha256s=tuple(
            _require_sha256(root, field_name="private done_call_receipt_sha256")
            for root in raw_roots
        ),
        done_call_bindings_sha256=_require_sha256(
            payload["done_call_bindings_sha256"],
            field_name="private done_call_bindings_sha256",
        ),
        done_attempt_count=_require_nonnegative_int(
            payload["done_attempt_count"], field_name="private done_attempt_count"
        ),
        done_blob_count=_require_nonnegative_int(
            payload["done_blob_count"], field_name="private done_blob_count"
        ),
        orphan_call_count=_require_nonnegative_int(
            payload["orphan_call_count"], field_name="private orphan_call_count"
        ),
        orphan_attempt_count=_require_nonnegative_int(
            payload["orphan_attempt_count"], field_name="private orphan_attempt_count"
        ),
        orphan_blob_count=_require_nonnegative_int(
            payload["orphan_blob_count"], field_name="private orphan_blob_count"
        ),
        stored_bytes=_require_nonnegative_int(
            payload["stored_bytes"], field_name="private stored_bytes"
        ),
    )
    if result.done_call_receipts_sha256 != _require_sha256(
        payload["done_call_receipts_sha256"],
        field_name="private done_call_receipts_sha256",
    ):
        raise SuccessorCoordinatorError("private generation logical-call root digest differs")
    if result.done_call_receipt_sha256s != expected_logical_call_roots:
        raise SuccessorCoordinatorError(
            "private generation logical-call roots differ from observed delta receipts"
        )
    if result.done_call_bindings_sha256 != expected_logical_call_bindings_sha256:
        raise SuccessorCoordinatorError(
            "private generation logical-call bindings differ from observed delta receipts"
        )
    return result


def _transform_inventory(
    values: Sequence[object],
) -> tuple[tuple[str, int, str, str], ...]:
    return tuple(
        (item.table_name, item.row_count, item.schema_sha256, item.content_sha256)
        for item in _validated_transform_outputs(values)
    )


def _validated_transform_outputs(
    values: Sequence[object],
) -> tuple[SuccessorTransformOutputAttestation, ...]:
    converted: list[SuccessorTransformOutputAttestation] = []
    for value in values:
        if isinstance(value, SuccessorTransformOutputAttestation):
            converted.append(value)
            continue
        try:
            attestation = cast("_TransformOutputLike", value)
            converted.append(
                SuccessorTransformOutputAttestation(
                    table_name=attestation.table_name,
                    row_count=attestation.row_count,
                    schema_sha256=attestation.schema_sha256,
                    content_sha256=attestation.content_sha256,
                )
            )
        except (AttributeError, TypeError, ValueError) as exc:
            raise SuccessorCoordinatorError(
                "successor transform output inventory contains an invalid attestation"
            ) from exc
    converted.sort(key=lambda item: item.table_name)
    names = tuple(item.table_name for item in converted)
    from nbadb.orchestrate.transformers import expected_transform_output_tables

    expected_names = tuple(sorted(expected_transform_output_tables(include_live=True)))
    if names != expected_names:
        missing = sorted(set(expected_names) - set(names))
        unexpected = sorted(set(names) - set(expected_names))
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        if len(names) != len(set(names)):
            details.append("duplicates=true")
        raise SuccessorCoordinatorError(
            "successor transform output inventory is incomplete: " + "; ".join(details)
        )
    return tuple(converted)


def _validate_private_generation(
    identity: PrivateGenerationIdentity,
    *,
    baseline: BaselineAssuranceIdentity,
    intent: SuccessorUpdateIntent,
    receipts: Sequence[ObservedDeltaReceipt],
) -> None:
    roots = _logical_call_roots(receipts)
    expected_artifacts = (
        identity.done_call_count
        + identity.done_attempt_count
        + identity.done_blob_count
        + identity.orphan_call_count
        + identity.orphan_attempt_count
        + identity.orphan_blob_count
    )
    mismatches: list[str] = []
    if identity.semantic_source_sha != intent.source_sha:
        mismatches.append("semantic_source_sha")
    if identity.provider_authority_sha256 != baseline.provider_authority_sha256:
        mismatches.append("provider_authority_sha256")
    if identity.done_call_count != len(roots):
        mismatches.append("done_call_count")
    if identity.done_call_receipt_sha256s != roots:
        mismatches.append("done_call_receipt_sha256s")
    if identity.done_call_bindings_sha256 != _logical_call_bindings_sha256(
        baseline=baseline,
        intent=intent,
        receipts=receipts,
    ):
        mismatches.append("done_call_bindings_sha256")
    if identity.done_attempt_count < identity.done_call_count:
        mismatches.append("done_attempt_count")
    if identity.artifact_count != expected_artifacts:
        mismatches.append("artifact_count")
    if identity.stored_bytes <= 0:
        mismatches.append("stored_bytes")
    if mismatches:
        raise SuccessorCoordinatorError(
            "sealed update private generation does not reconcile: " + ", ".join(mismatches)
        )


@dataclass(frozen=True, slots=True)
class SuccessorAggregateCapacityContract:
    """Path-free worst-case byte bounds admitted before planning provider work."""

    baseline_installed_public_tree_bytes: int
    planning_store_generation_max_bytes: int
    planning_store_artifact_max_bytes: int
    planning_store_control_max_bytes: int
    planning_driver_database_max_bytes: int
    planning_wave_count: int
    planning_wave_capture_max_bytes: int
    planning_wave_checkpoint_max_bytes: int
    update_capture_max_bytes: int
    update_checkpoint_max_bytes: int
    candidate_max_bytes: int
    rollback_reserve_bytes: int
    coordinator_checkpoint_max_bytes: int
    terminal_receipt_max_bytes: int
    runtime_log_max_bytes: int
    scan_database_snapshot_max_bytes: int
    inventory_duckdb_snapshot_max_bytes: int
    inventory_sqlite_snapshot_max_bytes: int
    transform_scratch_max_bytes: int
    assurance_control_max_bytes: int
    minimum_free_bytes: int

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "successor_aggregate_capacity_contract"

    def __post_init__(self) -> None:
        for field_name in self._bound_field_names():
            _require_positive_signed63_int(getattr(self, field_name), field_name=field_name)
        if self.planning_wave_count != 2:
            raise SuccessorCoordinatorError("planning_wave_count must be exactly 2")

    @classmethod
    def _bound_field_names(cls) -> tuple[str, ...]:
        return (
            "baseline_installed_public_tree_bytes",
            "planning_store_generation_max_bytes",
            "planning_store_artifact_max_bytes",
            "planning_store_control_max_bytes",
            "planning_driver_database_max_bytes",
            "planning_wave_count",
            "planning_wave_capture_max_bytes",
            "planning_wave_checkpoint_max_bytes",
            "update_capture_max_bytes",
            "update_checkpoint_max_bytes",
            "candidate_max_bytes",
            "rollback_reserve_bytes",
            "coordinator_checkpoint_max_bytes",
            "terminal_receipt_max_bytes",
            "runtime_log_max_bytes",
            "scan_database_snapshot_max_bytes",
            "inventory_duckdb_snapshot_max_bytes",
            "inventory_sqlite_snapshot_max_bytes",
            "transform_scratch_max_bytes",
            "assurance_control_max_bytes",
            "minimum_free_bytes",
        )

    @property
    def update_private_generation_max_bytes(self) -> int:
        """Exact retained update capture plus its durable checkpoint bound."""

        return _checked_signed63_sum(
            self.update_capture_max_bytes,
            self.update_checkpoint_max_bytes,
            field_name="update private generation byte bound",
        )

    def to_dict(self) -> dict[str, int | str]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{field_name: getattr(self, field_name) for field_name in self._bound_field_names()},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {"schema_version", "kind", *cls._bound_field_names()}
        if set(payload) != expected:
            raise SuccessorCoordinatorError("aggregate capacity contract fields are invalid")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise SuccessorCoordinatorError("aggregate capacity contract schema is invalid")
        return cls(
            **{
                field_name: _require_positive_signed63_int(
                    payload[field_name],
                    field_name=field_name,
                )
                for field_name in cls._bound_field_names()
            }
        )


@dataclass(frozen=True, slots=True)
class SuccessorCandidateAdmission:
    """Aggregate capacity, deadline, and exact monotonic-clock epoch authority."""

    aggregate_capacity: SuccessorAggregateCapacityContract
    monotonic_deadline_seconds: float
    minimum_pre_provider_headroom_seconds: float
    minimum_deadline_headroom_seconds: float
    monotonic_epoch_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.aggregate_capacity, SuccessorAggregateCapacityContract):
            raise SuccessorCoordinatorError(
                "aggregate_capacity must be a SuccessorAggregateCapacityContract"
            )
        for field_name in (
            "monotonic_deadline_seconds",
            "minimum_pre_provider_headroom_seconds",
            "minimum_deadline_headroom_seconds",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_positive_finite(getattr(self, field_name), field_name=field_name),
            )
        if self.minimum_pre_provider_headroom_seconds < self.minimum_deadline_headroom_seconds:
            raise SuccessorCoordinatorError(
                "minimum_pre_provider_headroom_seconds must be at least "
                "minimum_deadline_headroom_seconds"
            )
        _require_sha256(
            self.monotonic_epoch_sha256,
            field_name="monotonic_epoch_sha256",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "aggregate_capacity": self.aggregate_capacity.to_dict(),
            "monotonic_deadline_seconds": self.monotonic_deadline_seconds,
            "minimum_pre_provider_headroom_seconds": (self.minimum_pre_provider_headroom_seconds),
            "minimum_deadline_headroom_seconds": self.minimum_deadline_headroom_seconds,
            "monotonic_epoch_sha256": self.monotonic_epoch_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {
            "aggregate_capacity",
            "monotonic_deadline_seconds",
            "minimum_pre_provider_headroom_seconds",
            "minimum_deadline_headroom_seconds",
            "monotonic_epoch_sha256",
        }
        if set(payload) != expected:
            raise SuccessorCoordinatorError("candidate admission fields are invalid")
        aggregate_capacity = payload["aggregate_capacity"]
        if not isinstance(aggregate_capacity, Mapping) or not all(
            isinstance(key, str) for key in aggregate_capacity
        ):
            raise SuccessorCoordinatorError("aggregate capacity contract must be an object")
        return cls(
            aggregate_capacity=SuccessorAggregateCapacityContract.from_dict(
                cast("Mapping[str, object]", aggregate_capacity)
            ),
            monotonic_deadline_seconds=_require_positive_finite(
                payload["monotonic_deadline_seconds"],
                field_name="monotonic_deadline_seconds",
            ),
            minimum_pre_provider_headroom_seconds=_require_positive_finite(
                payload["minimum_pre_provider_headroom_seconds"],
                field_name="minimum_pre_provider_headroom_seconds",
            ),
            minimum_deadline_headroom_seconds=_require_positive_finite(
                payload["minimum_deadline_headroom_seconds"],
                field_name="minimum_deadline_headroom_seconds",
            ),
            monotonic_epoch_sha256=_require_sha256(
                payload["monotonic_epoch_sha256"],
                field_name="monotonic_epoch_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class SuccessorCoordinatorRequest:
    """Exact already-admitted parent and pre-intent request for one generation."""

    baseline: BaselineAssuranceIdentity
    planning_request: SuccessorPlanningRequest
    generation: int
    baseline_public_root: Path
    candidate_admission: SuccessorCandidateAdmission

    def __post_init__(self) -> None:
        if not isinstance(self.baseline, BaselineAssuranceIdentity):
            raise SuccessorCoordinatorError("baseline must be a BaselineAssuranceIdentity")
        if not isinstance(self.planning_request, SuccessorPlanningRequest):
            raise SuccessorCoordinatorError("planning_request must be a SuccessorPlanningRequest")
        _require_positive_int(self.generation, field_name="generation")
        if self.planning_request.baseline_identity_sha256 != self.baseline.identity_sha256:
            raise SuccessorCoordinatorError("planning request baseline identity differs")
        if not isinstance(self.baseline_public_root, Path):
            raise SuccessorCoordinatorError("baseline_public_root must be an explicit Path")
        if not isinstance(self.candidate_admission, SuccessorCandidateAdmission):
            raise SuccessorCoordinatorError(
                "candidate_admission must be a SuccessorCandidateAdmission"
            )
        if (
            self.candidate_admission.aggregate_capacity.baseline_installed_public_tree_bytes
            != self.baseline.installed_public_tree_bytes
        ):
            raise SuccessorCoordinatorError(
                "aggregate capacity baseline byte count differs from admitted baseline"
            )


@dataclass(frozen=True, slots=True)
class SuccessorAssuranceBuildInput:
    """Complete dependency-injected input for export, scan, and assurance."""

    candidate_root: Path
    baseline: BaselineAssuranceIdentity
    planning_evidence: SuccessorPlanningEvidence
    execution_plan: SuccessorExecutionPlan
    planned_route_replacement_bindings_sha256: str
    transaction: SuccessorUpdateTransaction
    update_private_generation: PrivateGenerationIdentity
    transform_outputs: tuple[SuccessorTransformOutputAttestation, ...]
    execution_installed_public_tree_sha256: str

    def __post_init__(self) -> None:
        if self.transaction.state is not SuccessorGenerationState.BUILT:
            raise SuccessorCoordinatorError("assurance input requires a built transaction")
        assert self.transaction.build is not None
        if self.execution_plan.to_dict() != self.planning_evidence.execution_plan.to_dict():
            raise SuccessorCoordinatorError(
                "assurance execution plan differs from sealed planning evidence"
            )
        planned_bindings_sha256 = _require_sha256(
            self.planned_route_replacement_bindings_sha256,
            field_name="planned_route_replacement_bindings_sha256",
        )
        if any(
            authority != planned_bindings_sha256
            for authority in (
                self.planning_evidence.planned_route_replacement_bindings_sha256,
                self.execution_plan.planned_route_replacement_bindings_sha256,
                self.transaction.intent.planned_route_replacement_bindings_sha256,
                self.transaction.build.planned_route_replacement_bindings_sha256,
            )
        ):
            raise SuccessorCoordinatorError(
                "assurance planned route replacement binding authority differs"
            )
        _require_sha256(
            self.execution_installed_public_tree_sha256,
            field_name="execution_installed_public_tree_sha256",
        )


@dataclass(frozen=True, slots=True)
class SuccessorCoordinatorCheckpoint:
    """Canonical path-free resume authority for one coordinator transaction."""

    phase: SuccessorCoordinatorPhase
    baseline: BaselineAssuranceIdentity
    planning_request: SuccessorPlanningRequest
    generation: int
    candidate_admission: SuccessorCandidateAdmission
    planned_route_replacement_bindings_sha256: str | None = None
    planning_evidence: SuccessorPlanningEvidence | None = None
    intent: SuccessorUpdateIntent | None = None
    transaction: SuccessorUpdateTransaction | None = None
    update_private_generation: PrivateGenerationIdentity | None = None
    observed_delta_receipts: tuple[ObservedDeltaReceipt, ...] = ()
    transform_outputs: tuple[SuccessorTransformOutputAttestation, ...] = ()
    candidate_installed_public_tree_sha256: str | None = None
    assurance: SuccessorAssuranceIdentity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, SuccessorCoordinatorPhase):
            raise SuccessorCoordinatorError("checkpoint phase is invalid")
        if not isinstance(self.baseline, BaselineAssuranceIdentity):
            raise SuccessorCoordinatorError("checkpoint baseline is invalid")
        if not isinstance(self.planning_request, SuccessorPlanningRequest):
            raise SuccessorCoordinatorError("checkpoint planning request is invalid")
        _require_positive_int(self.generation, field_name="checkpoint generation")
        if not isinstance(self.candidate_admission, SuccessorCandidateAdmission):
            raise SuccessorCoordinatorError("checkpoint candidate admission is invalid")
        if self.planning_request.baseline_identity_sha256 != self.baseline.identity_sha256:
            raise SuccessorCoordinatorError("checkpoint planning baseline differs")
        if (
            self.candidate_admission.aggregate_capacity.baseline_installed_public_tree_bytes
            != self.baseline.installed_public_tree_bytes
        ):
            raise SuccessorCoordinatorError(
                "checkpoint aggregate capacity baseline byte count differs"
            )

        rank = _PHASE_RANK[self.phase]
        has_planning = rank >= _PHASE_RANK[SuccessorCoordinatorPhase.PLANNED]
        has_intent = rank >= _PHASE_RANK[SuccessorCoordinatorPhase.INTENT_FINALIZED]
        has_transaction = rank >= _PHASE_RANK[SuccessorCoordinatorPhase.CANDIDATE]
        has_execution = rank >= _PHASE_RANK[SuccessorCoordinatorPhase.EXECUTED]
        has_assurance = rank >= _PHASE_RANK[SuccessorCoordinatorPhase.ASSURED]
        if (self.planned_route_replacement_bindings_sha256 is not None) != has_planning:
            raise SuccessorCoordinatorError(
                "checkpoint planned route replacement binding phase is invalid"
            )
        if self.planned_route_replacement_bindings_sha256 is not None:
            _require_sha256(
                self.planned_route_replacement_bindings_sha256,
                field_name="checkpoint planned_route_replacement_bindings_sha256",
            )
        if (self.planning_evidence is not None) != has_planning:
            raise SuccessorCoordinatorError("checkpoint planning evidence phase is invalid")
        if (self.intent is not None) != has_intent:
            raise SuccessorCoordinatorError("checkpoint intent phase is invalid")
        if (self.transaction is not None) != has_transaction:
            raise SuccessorCoordinatorError("checkpoint transaction phase is invalid")
        execution_inventory_present = bool(
            self.update_private_generation is not None
            or self.observed_delta_receipts
            or self.transform_outputs
        )
        if execution_inventory_present != has_execution:
            raise SuccessorCoordinatorError("checkpoint execution inventory phase is invalid")
        if (self.assurance is not None) != has_assurance:
            raise SuccessorCoordinatorError("checkpoint assurance phase is invalid")

        if self.planning_evidence is not None and (
            self.planning_evidence.request.to_dict() != self.planning_request.to_dict()
        ):
            raise SuccessorCoordinatorError("checkpoint planning evidence request differs")
        if self.planning_evidence is not None and any(
            authority != self.planned_route_replacement_bindings_sha256
            for authority in (
                self.planning_evidence.planned_route_replacement_bindings_sha256,
                self.planning_evidence.execution_plan.planned_route_replacement_bindings_sha256,
            )
        ):
            raise SuccessorCoordinatorError(
                "checkpoint planning route replacement binding authority differs"
            )
        if self.intent is not None:
            assert self.planning_evidence is not None
            expected_intent = finalize_successor_update_intent(self.planning_evidence)
            if self.intent.to_dict() != expected_intent.to_dict():
                raise SuccessorCoordinatorError("checkpoint finalized intent differs")
            if (
                self.intent.planned_route_replacement_bindings_sha256
                != self.planned_route_replacement_bindings_sha256
            ):
                raise SuccessorCoordinatorError(
                    "checkpoint intent route replacement binding authority differs"
                )
        if self.transaction is not None:
            assert self.intent is not None
            if (
                self.transaction.generation != self.generation
                or self.transaction.baseline.to_dict() != self.baseline.to_dict()
                or self.transaction.intent.to_dict() != self.intent.to_dict()
            ):
                raise SuccessorCoordinatorError("checkpoint candidate authority differs")
            if (
                self.transaction.intent.planned_route_replacement_bindings_sha256
                != self.planned_route_replacement_bindings_sha256
            ):
                raise SuccessorCoordinatorError(
                    "checkpoint transaction route replacement binding authority differs"
                )
            if self.transaction.build is not None and (
                self.transaction.build.planned_route_replacement_bindings_sha256
                != self.planned_route_replacement_bindings_sha256
            ):
                raise SuccessorCoordinatorError(
                    "checkpoint build route replacement binding authority differs"
                )

        expected_transaction_state = {
            SuccessorCoordinatorPhase.CANDIDATE: SuccessorGenerationState.CANDIDATE,
            SuccessorCoordinatorPhase.EXECUTING: SuccessorGenerationState.CANDIDATE,
            SuccessorCoordinatorPhase.EXECUTED: SuccessorGenerationState.CANDIDATE,
            SuccessorCoordinatorPhase.BUILT: SuccessorGenerationState.BUILT,
            SuccessorCoordinatorPhase.ASSURING: SuccessorGenerationState.BUILT,
            SuccessorCoordinatorPhase.ASSURED: SuccessorGenerationState.BUILT,
            SuccessorCoordinatorPhase.VALIDATED: SuccessorGenerationState.VALIDATED,
            SuccessorCoordinatorPhase.TRANSACTION_PROMOTED: SuccessorGenerationState.PROMOTED,
            SuccessorCoordinatorPhase.PROMOTED: SuccessorGenerationState.PROMOTED,
        }.get(self.phase)
        if (
            expected_transaction_state is not None
            and self.transaction is not None
            and self.transaction.state is not expected_transaction_state
        ):
            raise SuccessorCoordinatorError("checkpoint transaction state differs from phase")

        digest_required = self.phase is SuccessorCoordinatorPhase.CANDIDATE or has_execution
        if (self.candidate_installed_public_tree_sha256 is not None) != digest_required:
            raise SuccessorCoordinatorError("checkpoint candidate tree phase is invalid")
        if self.candidate_installed_public_tree_sha256 is not None:
            _require_sha256(
                self.candidate_installed_public_tree_sha256,
                field_name="candidate_installed_public_tree_sha256",
            )
        if (
            self.phase is SuccessorCoordinatorPhase.CANDIDATE
            and self.candidate_installed_public_tree_sha256
            != self.baseline.installed_public_tree_sha256
        ):
            raise SuccessorCoordinatorError("new candidate does not bind the installed baseline")

        if has_execution:
            assert self.transaction is not None
            assert self.update_private_generation is not None
            receipts = tuple(self.observed_delta_receipts)
            transforms = _validated_transform_outputs(self.transform_outputs)
            object.__setattr__(self, "transform_outputs", transforms)
            candidate = SuccessorUpdateTransaction.candidate(
                generation=self.generation,
                baseline=self.baseline,
                intent=cast("SuccessorUpdateIntent", self.intent),
            )
            expected_built = candidate.mark_built(observed_delta_receipts=receipts)
            assert expected_built.build is not None
            if (
                expected_built.build.planned_route_replacement_bindings_sha256
                != self.planned_route_replacement_bindings_sha256
            ):
                raise SuccessorCoordinatorError(
                    "checkpoint receipt-derived route replacement binding authority differs"
                )
            if self.transaction.state is not SuccessorGenerationState.CANDIDATE and (
                self.transaction.build is None
                or expected_built.build is None
                or self.transaction.build.to_dict() != expected_built.build.to_dict()
            ):
                raise SuccessorCoordinatorError("checkpoint built receipt inventory differs")
            _validate_private_generation(
                self.update_private_generation,
                baseline=self.baseline,
                intent=cast("SuccessorUpdateIntent", self.intent),
                receipts=receipts,
            )
        if self.assurance is not None:
            assert self.transaction is not None
            assert self.update_private_generation is not None
            assert self.candidate_installed_public_tree_sha256 is not None
            if self.transaction.state is SuccessorGenerationState.BUILT:
                validated = self.transaction.mark_validated(self.assurance)
            else:
                candidate = SuccessorUpdateTransaction.candidate(
                    generation=self.generation,
                    baseline=self.baseline,
                    intent=cast("SuccessorUpdateIntent", self.intent),
                )
                validated = candidate.mark_built(
                    observed_delta_receipts=self.observed_delta_receipts
                ).mark_validated(self.assurance)
            if self.assurance.private_generation_receipt_sha256 != (
                self.update_private_generation.identity_sha256
            ):
                raise SuccessorCoordinatorError("checkpoint assurance private receipt differs")
            transform_digest = canonical_sha256([item.to_dict() for item in self.transform_outputs])
            if self.assurance.transform_inventory_sha256 != transform_digest:
                raise SuccessorCoordinatorError("checkpoint assurance transform inventory differs")
            if (
                self.assurance.installed_public_tree_sha256
                != self.candidate_installed_public_tree_sha256
            ):
                raise SuccessorCoordinatorError(
                    "checkpoint assurance installed public tree differs"
                )
            if (
                self.phase
                in {
                    SuccessorCoordinatorPhase.VALIDATED,
                    SuccessorCoordinatorPhase.TRANSACTION_PROMOTED,
                    SuccessorCoordinatorPhase.PROMOTED,
                }
                and self.transaction.assurance != validated.assurance
            ):
                raise SuccessorCoordinatorError("checkpoint transaction assurance differs")

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict()) + b"\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": _CHECKPOINT_SCHEMA_VERSION,
            "kind": _CHECKPOINT_KIND,
            "phase": self.phase.value,
            "generation": self.generation,
            "baseline": self.baseline.to_dict(),
            "planning_request": self.planning_request.to_dict(),
            "candidate_admission": self.candidate_admission.to_dict(),
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
            "planning_evidence": (
                None if self.planning_evidence is None else self.planning_evidence.to_dict()
            ),
            "intent": None if self.intent is None else self.intent.to_dict(),
            "transaction": (None if self.transaction is None else self.transaction.to_dict()),
            "update_private_generation": (
                None
                if self.update_private_generation is None
                else self.update_private_generation.to_dict()
            ),
            "observed_delta_receipts": [
                receipt.to_dict() for receipt in self.observed_delta_receipts
            ],
            "transform_outputs": [item.to_dict() for item in self.transform_outputs],
            "candidate_installed_public_tree_sha256": (self.candidate_installed_public_tree_sha256),
            "assurance": None if self.assurance is None else self.assurance.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = {
            "schema_version",
            "kind",
            "phase",
            "generation",
            "baseline",
            "planning_request",
            "candidate_admission",
            "planned_route_replacement_bindings_sha256",
            "planning_evidence",
            "intent",
            "transaction",
            "update_private_generation",
            "observed_delta_receipts",
            "transform_outputs",
            "candidate_installed_public_tree_sha256",
            "assurance",
        }
        if set(payload) != expected:
            raise SuccessorCoordinatorError("coordinator checkpoint fields are invalid")
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != _CHECKPOINT_SCHEMA_VERSION
            or payload["kind"] != _CHECKPOINT_KIND
        ):
            raise SuccessorCoordinatorError("coordinator checkpoint schema is invalid")
        try:
            phase = SuccessorCoordinatorPhase(payload["phase"])
        except (TypeError, ValueError) as exc:
            raise SuccessorCoordinatorError("coordinator checkpoint phase is invalid") from exc

        def required_mapping(field_name: str) -> Mapping[str, object]:
            value = payload[field_name]
            if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
                raise SuccessorCoordinatorError(
                    f"coordinator checkpoint {field_name} must be an object"
                )
            return cast("Mapping[str, object]", value)

        def optional_mapping(field_name: str) -> Mapping[str, object] | None:
            value = payload[field_name]
            if value is None:
                return None
            return required_mapping(field_name)

        raw_receipts = payload["observed_delta_receipts"]
        raw_transforms = payload["transform_outputs"]
        if not isinstance(raw_receipts, list) or not isinstance(raw_transforms, list):
            raise SuccessorCoordinatorError("coordinator checkpoint inventories must be lists")
        planning = optional_mapping("planning_evidence")
        intent = optional_mapping("intent")
        transaction = optional_mapping("transaction")
        private = optional_mapping("update_private_generation")
        assurance = optional_mapping("assurance")
        try:
            receipts = tuple(
                ObservedDeltaReceipt.from_dict(cast("Mapping[str, object]", item))
                for item in raw_receipts
                if isinstance(item, Mapping)
            )
            if len(receipts) != len(raw_receipts):
                raise SuccessorCoordinatorError(
                    "coordinator checkpoint observed delta receipts are invalid"
                )
            baseline_value = BaselineAssuranceIdentity.from_dict(required_mapping("baseline"))
            intent_value = None if intent is None else SuccessorUpdateIntent.from_dict(intent)
            expected_binding_digest = (
                canonical_sha256([])
                if intent_value is None
                else _logical_call_bindings_sha256(
                    baseline=baseline_value,
                    intent=intent_value,
                    receipts=receipts,
                )
            )
            private_generation = (
                None
                if private is None
                else _private_generation_from_dict(
                    private,
                    expected_logical_call_roots=_logical_call_roots(receipts),
                    expected_logical_call_bindings_sha256=expected_binding_digest,
                )
            )
            return cls(
                phase=phase,
                baseline=baseline_value,
                planning_request=SuccessorPlanningRequest.from_dict(
                    required_mapping("planning_request")
                ),
                generation=_require_positive_int(
                    payload["generation"], field_name="checkpoint generation"
                ),
                candidate_admission=SuccessorCandidateAdmission.from_dict(
                    required_mapping("candidate_admission")
                ),
                planned_route_replacement_bindings_sha256=(
                    None
                    if payload["planned_route_replacement_bindings_sha256"] is None
                    else _require_sha256(
                        payload["planned_route_replacement_bindings_sha256"],
                        field_name=("checkpoint planned_route_replacement_bindings_sha256"),
                    )
                ),
                planning_evidence=(
                    None if planning is None else SuccessorPlanningEvidence.from_dict(planning)
                ),
                intent=intent_value,
                transaction=(
                    None
                    if transaction is None
                    else SuccessorUpdateTransaction.from_dict(transaction)
                ),
                update_private_generation=private_generation,
                observed_delta_receipts=receipts,
                transform_outputs=tuple(
                    SuccessorTransformOutputAttestation.from_dict(
                        cast("Mapping[str, object]", item)
                    )
                    for item in raw_transforms
                    if isinstance(item, Mapping)
                ),
                candidate_installed_public_tree_sha256=(
                    None
                    if payload["candidate_installed_public_tree_sha256"] is None
                    else _require_sha256(
                        payload["candidate_installed_public_tree_sha256"],
                        field_name="candidate_installed_public_tree_sha256",
                    )
                ),
                assurance=(
                    None if assurance is None else SuccessorAssuranceIdentity.from_dict(assurance)
                ),
            )
        except ValueError as exc:
            raise SuccessorCoordinatorError("coordinator checkpoint is invalid") from exc


class SuccessorCoordinatorCheckpointStore:
    """Atomic single-transaction checkpoint at one caller-supplied path."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise SuccessorCoordinatorError("checkpoint path must be an explicit Path")
        self.path = path

    def load(self) -> SuccessorCoordinatorCheckpoint | None:
        if not self.path.exists() and not self.path.is_symlink():
            return None
        encoded = self._read_regular_file()
        try:
            payload = json.loads(encoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorCoordinatorError("coordinator checkpoint is not valid JSON") from exc
        if not isinstance(payload, Mapping):
            raise SuccessorCoordinatorError("coordinator checkpoint must be an object")
        checkpoint = SuccessorCoordinatorCheckpoint.from_dict(cast("Mapping[str, object]", payload))
        if encoded != checkpoint.canonical_bytes:
            raise SuccessorCoordinatorError("coordinator checkpoint is not canonical")
        return checkpoint

    def write(self, checkpoint: SuccessorCoordinatorCheckpoint) -> None:
        if not isinstance(checkpoint, SuccessorCoordinatorCheckpoint):
            raise SuccessorCoordinatorError(
                "checkpoint persistence requires a SuccessorCoordinatorCheckpoint"
            )
        prior = self.load()
        if prior is not None:
            if prior.canonical_bytes == checkpoint.canonical_bytes:
                return
            if (
                prior.baseline.to_dict() != checkpoint.baseline.to_dict()
                or prior.planning_request.to_dict() != checkpoint.planning_request.to_dict()
                or prior.generation != checkpoint.generation
                or prior.candidate_admission.to_dict() != checkpoint.candidate_admission.to_dict()
            ):
                raise SuccessorCoordinatorError(
                    "coordinator checkpoint transaction identity changed"
                )
            if _PHASE_RANK[checkpoint.phase] != _PHASE_RANK[prior.phase] + 1:
                raise SuccessorCoordinatorError(
                    "coordinator checkpoint must advance by exactly one phase"
                )
        elif checkpoint.phase is not SuccessorCoordinatorPhase.REQUESTED:
            raise SuccessorCoordinatorError("first coordinator checkpoint must be requested")
        self._atomic_write(checkpoint.canonical_bytes)

    def _read_regular_file(self) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        try:
            descriptor = os.open(self.path, flags)
        except OSError as exc:
            raise SuccessorCoordinatorError(
                "coordinator checkpoint cannot be opened safely"
            ) from exc
        try:
            opened = os.fstat(descriptor)
            current = os.stat(self.path, follow_symlinks=False)
            if not stat.S_ISREG(opened.st_mode) or (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
            ) != (current.st_dev, current.st_ino, current.st_size):
                raise SuccessorCoordinatorError(
                    "coordinator checkpoint must be one stable regular file"
                )
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def _atomic_write(self, encoded: bytes) -> None:
        parent = self.path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise SuccessorCoordinatorError(
                "coordinator checkpoint parent must be an existing regular directory"
            )
        temporary = parent / f".{self.path.name}.{secrets.token_hex(8)}.tmp"
        descriptor = -1
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short coordinator checkpoint write")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, self.path)
            directory_descriptor = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError as exc:
            raise SuccessorCoordinatorError(
                "coordinator checkpoint cannot be installed atomically"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()


@dataclass(frozen=True, slots=True)
class SuccessorCoordinatorResult:
    candidate_root: Path
    transaction: SuccessorUpdateTransaction
    checkpoint: SuccessorCoordinatorCheckpoint
    current_pointer: dict[str, Any]

    def __post_init__(self) -> None:
        if self.transaction.state is not SuccessorGenerationState.PROMOTED:
            raise SuccessorCoordinatorError("coordinator result requires a promoted transaction")
        if self.checkpoint.phase is not SuccessorCoordinatorPhase.PROMOTED:
            raise SuccessorCoordinatorError("coordinator result requires a promoted checkpoint")
        if (
            self.checkpoint.transaction is None
            or self.checkpoint.transaction.to_dict() != self.transaction.to_dict()
        ):
            raise SuccessorCoordinatorError(
                "coordinator result transaction differs from the promoted checkpoint"
            )
        assert self.transaction.build is not None
        if any(
            authority != self.checkpoint.planned_route_replacement_bindings_sha256
            for authority in (
                self.transaction.intent.planned_route_replacement_bindings_sha256,
                self.transaction.build.planned_route_replacement_bindings_sha256,
            )
        ):
            raise SuccessorCoordinatorError(
                "coordinator result route replacement binding authority differs"
            )


def require_successor_downstream_publication(
    *,
    checkpoint: SuccessorCoordinatorCheckpoint | None,
    current_pointer: Mapping[str, Any] | None,
) -> None:
    """Admit scan, export, and upload only after a promoted schema-v7 successor.

    Cancellation, interruption, and any incomplete coordinator stage fail closed
    before those downstream commands can treat a partial candidate as current.
    """

    if not isinstance(checkpoint, SuccessorCoordinatorCheckpoint):
        raise SuccessorCoordinatorError(_DOWNSTREAM_PUBLICATION_BLOCKED)
    if checkpoint.phase is not SuccessorCoordinatorPhase.PROMOTED:
        raise SuccessorCoordinatorError(_DOWNSTREAM_PUBLICATION_BLOCKED)
    transaction = checkpoint.transaction
    assurance = checkpoint.assurance
    if (
        transaction is None
        or transaction.state is not SuccessorGenerationState.PROMOTED
        or transaction.promoted_assurance is None
        or assurance is None
        or transaction.promoted_assurance.to_dict() != assurance.to_dict()
    ):
        raise SuccessorCoordinatorError(_DOWNSTREAM_PUBLICATION_BLOCKED)
    if not isinstance(current_pointer, Mapping) or not current_pointer:
        raise SuccessorCoordinatorError(_DOWNSTREAM_PUBLICATION_BLOCKED)


class SuccessorCoordinator:
    """Orchestrate and exactly resume one recurring successor transaction."""

    def __init__(
        self,
        *,
        generation_store: SuccessorGenerationStore,
        checkpoint_store: SuccessorCoordinatorCheckpointStore,
        planning_executor: SuccessorPlanningExecutor,
        runtime_factory: SuccessorUpdateRuntimeFactory,
        assurance_builder: SuccessorAssuranceBuilder,
        installed_public_tree_digest: InstalledPublicTreeDigest,
        monotonic_epoch_authority: Callable[[], str],
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(generation_store, SuccessorGenerationStore):
            raise SuccessorCoordinatorError("generation_store must be a SuccessorGenerationStore")
        if not isinstance(checkpoint_store, SuccessorCoordinatorCheckpointStore):
            raise SuccessorCoordinatorError(
                "checkpoint_store must be a SuccessorCoordinatorCheckpointStore"
            )
        if not callable(monotonic_clock):
            raise SuccessorCoordinatorError("monotonic_clock must be callable")
        if not callable(monotonic_epoch_authority):
            raise SuccessorCoordinatorError("monotonic_epoch_authority must be callable")
        self._generation_store = generation_store
        self._checkpoint_store = checkpoint_store
        self._planning_executor = planning_executor
        self._runtime_factory = runtime_factory
        self._assurance_builder = assurance_builder
        self._installed_public_tree_digest = installed_public_tree_digest
        self._monotonic_clock = monotonic_clock
        self._monotonic_epoch_authority = monotonic_epoch_authority

    def require_downstream_publication(self) -> None:
        """Fail closed unless this transaction is the promoted current successor."""

        require_successor_downstream_publication(
            checkpoint=self._checkpoint_store.load(),
            current_pointer=self._generation_store.read_current(),
        )

    async def run(self, request: SuccessorCoordinatorRequest) -> SuccessorCoordinatorResult:
        """Run or resume until the exact candidate pointer is promoted."""

        if not isinstance(request, SuccessorCoordinatorRequest):
            raise SuccessorCoordinatorError("request must be a SuccessorCoordinatorRequest")
        checkpoint = self._checkpoint_store.load()
        if checkpoint is None:
            self._require_current_monotonic_epoch(request.candidate_admission)
            self._fresh_monotonic_now(
                request.candidate_admission,
                minimum_headroom_seconds=(
                    request.candidate_admission.minimum_pre_provider_headroom_seconds
                ),
            )
            checkpoint = SuccessorCoordinatorCheckpoint(
                phase=SuccessorCoordinatorPhase.REQUESTED,
                baseline=request.baseline,
                planning_request=request.planning_request,
                generation=request.generation,
                candidate_admission=request.candidate_admission,
            )
            self._checkpoint_store.write(checkpoint)
        else:
            self._require_resume_transaction(checkpoint, request)
            self._require_durable_state_matches_phase(checkpoint)
            self._require_current_monotonic_epoch(checkpoint.candidate_admission)
            self._fresh_monotonic_now(
                checkpoint.candidate_admission,
                minimum_headroom_seconds=(
                    checkpoint.candidate_admission.minimum_pre_provider_headroom_seconds
                    if checkpoint.phase is SuccessorCoordinatorPhase.REQUESTED
                    else checkpoint.candidate_admission.minimum_deadline_headroom_seconds
                ),
            )

        entry_phase = checkpoint.phase
        planning_verified_this_entry = False
        if checkpoint.phase is SuccessorCoordinatorPhase.REQUESTED:
            self._fresh_monotonic_now(
                checkpoint.candidate_admission,
                minimum_headroom_seconds=(
                    checkpoint.candidate_admission.minimum_pre_provider_headroom_seconds
                ),
            )
            planning = await self._planning_executor(request.planning_request)
            planning = self._verify_planning_evidence(request.planning_request, planning)
            planning_verified_this_entry = True
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.PLANNED,
                planning_evidence=planning,
                planned_route_replacement_bindings_sha256=(
                    planning.planned_route_replacement_bindings_sha256
                ),
            )

        if checkpoint.planning_evidence is not None and not planning_verified_this_entry:
            verified_planning = self._verify_planning_evidence(
                request.planning_request,
                checkpoint.planning_evidence,
            )
            if verified_planning.to_dict() != checkpoint.planning_evidence.to_dict():
                raise SuccessorCoordinatorError(
                    "durable planning generation differs from the coordinator checkpoint"
                )

        if checkpoint.phase is SuccessorCoordinatorPhase.PLANNED:
            assert checkpoint.planning_evidence is not None
            intent = finalize_successor_update_intent(checkpoint.planning_evidence)
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.INTENT_FINALIZED,
                intent=intent,
            )

        if checkpoint.phase is SuccessorCoordinatorPhase.INTENT_FINALIZED:
            assert checkpoint.intent is not None
            candidate_transaction = SuccessorUpdateTransaction.candidate(
                generation=checkpoint.generation,
                baseline=checkpoint.baseline,
                intent=checkpoint.intent,
            )
            monotonic_now_seconds = self._fresh_monotonic_now(checkpoint.candidate_admission)
            capacity = checkpoint.candidate_admission.aggregate_capacity
            candidate_root = self._generation_store.prepare_candidate_from_baseline(
                request.baseline_public_root,
                candidate_transaction,
                candidate_max_bytes=capacity.candidate_max_bytes,
                private_generation_estimated_bytes=(capacity.update_private_generation_max_bytes),
                rollback_reserve_bytes=capacity.rollback_reserve_bytes,
                minimum_free_bytes=capacity.minimum_free_bytes,
                monotonic_now_seconds=monotonic_now_seconds,
                monotonic_deadline_seconds=(
                    checkpoint.candidate_admission.monotonic_deadline_seconds
                ),
                minimum_deadline_headroom_seconds=(
                    checkpoint.candidate_admission.minimum_deadline_headroom_seconds
                ),
            )
            self._generation_store.record_transaction(candidate_root, candidate_transaction)
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.CANDIDATE,
                transaction=candidate_transaction,
                candidate_installed_public_tree_sha256=(
                    checkpoint.baseline.installed_public_tree_sha256
                ),
            )

        candidate_root = self._require_candidate(checkpoint, request)

        if checkpoint.phase is SuccessorCoordinatorPhase.CANDIDATE:
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.EXECUTING,
                candidate_installed_public_tree_sha256=None,
            )

        if checkpoint.phase is SuccessorCoordinatorPhase.EXECUTING:
            assert checkpoint.transaction is not None
            assert checkpoint.planning_evidence is not None
            runtime = self._runtime_factory(
                checkpoint.transaction,
                candidate_root,
                checkpoint.planning_evidence.execution_plan,
            )
            self._fresh_monotonic_now(checkpoint.candidate_admission)
            with self._generation_store.candidate_mutation(
                candidate_root,
                checkpoint.transaction,
            ):
                self._require_runtime_route_replacement_bindings(runtime, checkpoint)
                if checkpoint.planning_request.mode is SuccessorUpdateMode.DAILY:
                    result = await runtime.run_daily()
                else:
                    result = await runtime.run_monthly()
                self._require_complete_pipeline_result(result)
                self._require_runtime_route_replacement_bindings(runtime, checkpoint)
                capture = runtime.capture_identity
                if not isinstance(capture, PrivateGenerationIdentity):
                    raise SuccessorCoordinatorError(
                        "successor update did not finish with a sealed private generation"
                    )
                receipts = tuple(runtime.successor_delta_receipts)
                candidate_built = checkpoint.transaction.mark_built(
                    observed_delta_receipts=receipts
                )
                assert candidate_built.build is not None
                if (
                    candidate_built.build.planned_route_replacement_bindings_sha256
                    != checkpoint.planned_route_replacement_bindings_sha256
                ):
                    raise SuccessorCoordinatorError(
                        "runtime receipt-derived route replacement binding authority differs"
                    )
                transforms = _validated_transform_outputs(runtime.transform_output_attestations)
                _validate_private_generation(
                    capture,
                    baseline=checkpoint.baseline,
                    intent=checkpoint.transaction.intent,
                    receipts=receipts,
                )
                public_digest = self._measure_candidate(candidate_root)
                self._require_runtime_route_replacement_bindings(runtime, checkpoint)
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.EXECUTED,
                update_private_generation=capture,
                observed_delta_receipts=receipts,
                transform_outputs=transforms,
                candidate_installed_public_tree_sha256=public_digest,
            )

        if checkpoint.phase is SuccessorCoordinatorPhase.EXECUTED:
            assert checkpoint.transaction is not None
            if entry_phase is SuccessorCoordinatorPhase.EXECUTED:
                self._restore_executed_runtime_state(checkpoint, candidate_root)
            built = checkpoint.transaction.mark_built(
                observed_delta_receipts=checkpoint.observed_delta_receipts
            )
            assert built.build is not None
            if (
                built.build.planned_route_replacement_bindings_sha256
                != checkpoint.planned_route_replacement_bindings_sha256
            ):
                raise SuccessorCoordinatorError(
                    "built transaction route replacement binding authority differs"
                )
            self._generation_store.record_transaction(candidate_root, built)
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.BUILT,
                transaction=built,
            )

        if checkpoint.phase is SuccessorCoordinatorPhase.BUILT:
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.ASSURING,
            )

        if checkpoint.phase is SuccessorCoordinatorPhase.ASSURING:
            assert checkpoint.planning_evidence is not None
            assert checkpoint.transaction is not None
            assert checkpoint.update_private_generation is not None
            assert checkpoint.candidate_installed_public_tree_sha256 is not None
            build_input = SuccessorAssuranceBuildInput(
                candidate_root=candidate_root,
                baseline=checkpoint.baseline,
                planning_evidence=checkpoint.planning_evidence,
                execution_plan=checkpoint.planning_evidence.execution_plan,
                planned_route_replacement_bindings_sha256=cast(
                    "str", checkpoint.planned_route_replacement_bindings_sha256
                ),
                transaction=checkpoint.transaction,
                update_private_generation=checkpoint.update_private_generation,
                transform_outputs=checkpoint.transform_outputs,
                execution_installed_public_tree_sha256=(
                    checkpoint.candidate_installed_public_tree_sha256
                ),
            )
            self._fresh_monotonic_now(checkpoint.candidate_admission)
            with self._generation_store.candidate_mutation(
                candidate_root,
                checkpoint.transaction,
            ):
                assurance = await self._assurance_builder(build_input)
                if not isinstance(assurance, SuccessorAssuranceIdentity):
                    raise SuccessorCoordinatorError(
                        "assurance builder did not return a SuccessorAssuranceIdentity"
                    )
                _ = checkpoint.transaction.mark_validated(assurance)
                if assurance.private_generation_receipt_sha256 != (
                    checkpoint.update_private_generation.identity_sha256
                ):
                    raise SuccessorCoordinatorError(
                        "successor assurance private generation receipt differs"
                    )
                transform_digest = canonical_sha256(
                    [item.to_dict() for item in checkpoint.transform_outputs]
                )
                if assurance.transform_inventory_sha256 != transform_digest:
                    raise SuccessorCoordinatorError(
                        "successor assurance transform inventory differs"
                    )
                public_digest = self._measure_candidate(candidate_root)
                if assurance.installed_public_tree_sha256 != public_digest:
                    raise SuccessorCoordinatorError(
                        "successor assurance installed public tree differs from the candidate"
                    )
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.ASSURED,
                assurance=assurance,
                candidate_installed_public_tree_sha256=public_digest,
            )

        if checkpoint.phase is SuccessorCoordinatorPhase.ASSURED:
            assert checkpoint.transaction is not None
            assert checkpoint.assurance is not None
            validated = checkpoint.transaction.mark_validated(checkpoint.assurance)
            self._generation_store.record_transaction(candidate_root, validated)
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.VALIDATED,
                transaction=validated,
            )

        if checkpoint.phase is SuccessorCoordinatorPhase.VALIDATED:
            assert checkpoint.transaction is not None
            promoted = checkpoint.transaction.promote()
            self._generation_store.record_transaction(candidate_root, promoted)
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.TRANSACTION_PROMOTED,
                transaction=promoted,
            )

        if checkpoint.phase is SuccessorCoordinatorPhase.TRANSACTION_PROMOTED:
            assert checkpoint.transaction is not None
            self._generation_store.record_promoted_candidate(
                candidate_root,
                checkpoint.transaction,
            )
            current_pointer = self._generation_store.promote(
                candidate_root,
                checkpoint.transaction,
            )
            checkpoint = self._advance(
                checkpoint,
                phase=SuccessorCoordinatorPhase.PROMOTED,
            )
        else:
            current_pointer = self._generation_store.promote(
                candidate_root,
                cast("SuccessorUpdateTransaction", checkpoint.transaction),
            )
        try:
            self._generation_store.collect_retired_generations()
        except SuccessorGenerationStoreError as exc:
            raise SuccessorCoordinatorError(
                "retired generation collection failed after durable promotion"
            ) from exc

        assert checkpoint.transaction is not None
        require_successor_downstream_publication(
            checkpoint=checkpoint,
            current_pointer=current_pointer,
        )
        return SuccessorCoordinatorResult(
            candidate_root=candidate_root,
            transaction=checkpoint.transaction,
            checkpoint=checkpoint,
            current_pointer=current_pointer,
        )

    def _verify_planning_evidence(
        self,
        request: SuccessorPlanningRequest,
        evidence: object,
    ) -> SuccessorPlanningEvidence:
        if not isinstance(evidence, SuccessorPlanningEvidence):
            raise SuccessorCoordinatorError(
                "planning executor did not return sealed planning evidence"
            )
        if evidence.request.to_dict() != request.to_dict():
            raise SuccessorCoordinatorError(
                "planning executor did not seal the exact requested planning transaction"
            )
        try:
            verified = self._planning_executor.verify(request, evidence)
        except SuccessorCoordinatorError:
            raise
        except Exception as exc:
            raise SuccessorCoordinatorError(
                "durable planning generation could not be reverified"
            ) from exc
        if not isinstance(verified, SuccessorPlanningEvidence):
            raise SuccessorCoordinatorError(
                "planning verifier did not return sealed planning evidence"
            )
        if verified.request.to_dict() != request.to_dict():
            raise SuccessorCoordinatorError("durable planning generation request differs")
        return verified

    def _advance(
        self,
        checkpoint: SuccessorCoordinatorCheckpoint,
        *,
        phase: SuccessorCoordinatorPhase,
        **changes: object,
    ) -> SuccessorCoordinatorCheckpoint:
        advanced = replace(checkpoint, phase=phase, **changes)
        self._checkpoint_store.write(advanced)
        return advanced

    def _require_resume_transaction(
        self,
        checkpoint: SuccessorCoordinatorCheckpoint,
        request: SuccessorCoordinatorRequest,
    ) -> None:
        """Restore only the exact persisted transaction; reject identity drift."""

        self._require_request(checkpoint, request)
        self._require_resume_baseline_tree(checkpoint, request)
        self._require_resume_current_pointer(checkpoint, request)

    @staticmethod
    def _require_request(
        checkpoint: SuccessorCoordinatorCheckpoint,
        request: SuccessorCoordinatorRequest,
    ) -> None:
        if checkpoint.baseline.to_dict() != request.baseline.to_dict():
            raise SuccessorCoordinatorError(
                "resume baseline differs from the persisted successor transaction"
            )
        if checkpoint.planning_request.to_dict() != request.planning_request.to_dict():
            raise SuccessorCoordinatorError(
                "resume request differs from the persisted successor transaction"
            )
        if checkpoint.generation != request.generation:
            raise SuccessorCoordinatorError(
                "resume request differs from the persisted successor transaction"
            )
        if checkpoint.candidate_admission.to_dict() != request.candidate_admission.to_dict():
            raise SuccessorCoordinatorError(
                "resume admission differs from the persisted successor transaction"
            )

    def _require_durable_state_matches_phase(
        self,
        checkpoint: SuccessorCoordinatorCheckpoint,
    ) -> None:
        """Reject a reloaded checkpoint that lags or disagrees with durable store state."""

        if checkpoint.phase in {
            SuccessorCoordinatorPhase.REQUESTED,
            SuccessorCoordinatorPhase.PLANNED,
        }:
            if self._existing_generation_directory(checkpoint.generation) is not None:
                raise SuccessorCoordinatorError(_STALE_CHECKPOINT_PHASE)
            return

        locator = checkpoint.transaction
        if locator is None:
            assert checkpoint.intent is not None
            locator = SuccessorUpdateTransaction.candidate(
                generation=checkpoint.generation,
                baseline=checkpoint.baseline,
                intent=checkpoint.intent,
            )
        candidate_root = self._generation_store.candidate_path(locator)
        if not candidate_root.exists() and not candidate_root.is_symlink():
            return
        stored = self._load_resume_transaction(candidate_root, checkpoint)
        allowed = _ALLOWED_DURABLE_TRANSACTION_STATES[checkpoint.phase]
        if stored.state not in allowed:
            raise SuccessorCoordinatorError(_STALE_CHECKPOINT_PHASE)
        self._require_durable_admission_matches_phase(checkpoint, candidate_root, locator)
        if (
            checkpoint.transaction is not None
            and stored.state is checkpoint.transaction.state
            and stored.to_dict() != checkpoint.transaction.to_dict()
        ):
            self._reject_resume_transaction_payload_drift(stored, checkpoint)

    def _existing_generation_directory(self, generation: int) -> Path | None:
        root = self._generation_store.generations_root
        if root.is_symlink() or not root.is_dir():
            return None
        prefix = f"generation-{generation:08d}-"
        matches: list[Path] = []
        with os.scandir(root) as iterator:
            for entry in iterator:
                if not entry.name.startswith(prefix):
                    continue
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    raise SuccessorCoordinatorError(_STALE_CHECKPOINT_PHASE)
                matches.append(Path(entry.path))
        if len(matches) > 1:
            raise SuccessorCoordinatorError(_STALE_CHECKPOINT_PHASE)
        return matches[0] if matches else None

    @staticmethod
    def _require_durable_admission_matches_phase(
        checkpoint: SuccessorCoordinatorCheckpoint,
        candidate_root: Path,
        locator: SuccessorUpdateTransaction,
    ) -> None:
        admission = _peek_successor_admission(candidate_root)
        if (
            admission is None
            or admission.get("schema_version") != 2
            or admission.get("kind") != "successor_candidate_baseline"
            or admission.get("generation") != checkpoint.generation
            or admission.get("generation_identity_sha256") != locator.generation_identity_sha256
            or admission.get("baseline_identity_sha256") != checkpoint.baseline.identity_sha256
            or admission.get("baseline_installed_public_tree_sha256")
            != checkpoint.baseline.installed_public_tree_sha256
        ):
            raise SuccessorCoordinatorError(_STALE_CHECKPOINT_PHASE)

    def _require_resume_baseline_tree(
        self,
        checkpoint: SuccessorCoordinatorCheckpoint,
        request: SuccessorCoordinatorRequest,
    ) -> None:
        try:
            digest = self._installed_public_tree_digest(request.baseline_public_root)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise SuccessorCoordinatorError(
                "resume baseline installed public tree differs from the persisted "
                "successor transaction"
            ) from exc
        digest = _require_sha256(digest, field_name="resume baseline installed public tree")
        if digest != checkpoint.baseline.installed_public_tree_sha256:
            raise SuccessorCoordinatorError(
                "resume baseline installed public tree differs from the persisted "
                "successor transaction"
            )

    def _require_resume_current_pointer(
        self,
        checkpoint: SuccessorCoordinatorCheckpoint,
        request: SuccessorCoordinatorRequest,
    ) -> None:
        try:
            current_pointer = self._generation_store.read_current()
        except SuccessorGenerationStoreError as exc:
            raise SuccessorCoordinatorError(
                "resume current pointer differs from the persisted successor transaction"
            ) from exc
        promoted_phases = {
            SuccessorCoordinatorPhase.TRANSACTION_PROMOTED,
            SuccessorCoordinatorPhase.PROMOTED,
        }
        if checkpoint.phase in promoted_phases:
            if (
                current_pointer is None
                or checkpoint.transaction is None
                or checkpoint.transaction.state is not SuccessorGenerationState.PROMOTED
            ):
                raise SuccessorCoordinatorError(
                    "resume current pointer differs from the persisted successor transaction"
                )
            current = current_pointer["current"]
            if (
                current.get("generation") != checkpoint.transaction.generation
                or current.get("transaction_sha256") != checkpoint.transaction.content_sha256
                or current.get("candidate_name")
                != self._generation_store.candidate_name(checkpoint.transaction)
            ):
                raise SuccessorCoordinatorError(
                    "resume current pointer differs from the persisted successor transaction"
                )
            return
        if request.generation == 1:
            if current_pointer is not None:
                raise SuccessorCoordinatorError(
                    "resume current pointer differs from the persisted successor transaction"
                )
            return
        if current_pointer is None:
            raise SuccessorCoordinatorError(
                "resume current pointer differs from the persisted successor transaction"
            )
        current = current_pointer["current"]
        if current.get("generation") != request.generation - 1:
            raise SuccessorCoordinatorError(
                "resume current pointer differs from the persisted successor transaction"
            )
        if (
            current.get("installed_public_tree_sha256")
            != checkpoint.baseline.installed_public_tree_sha256
            or current.get("private_generation_receipt_sha256")
            != checkpoint.baseline.private_baseline_receipt_sha256
            or current.get("data_tree_fingerprint") != checkpoint.baseline.data_tree_fingerprint
        ):
            raise SuccessorCoordinatorError(
                "resume current pointer differs from the persisted successor transaction"
            )

    def _require_candidate(
        self,
        checkpoint: SuccessorCoordinatorCheckpoint,
        request: SuccessorCoordinatorRequest,
    ) -> Path:
        assert checkpoint.intent is not None
        candidate = SuccessorUpdateTransaction.candidate(
            generation=checkpoint.generation,
            baseline=checkpoint.baseline,
            intent=checkpoint.intent,
        )
        candidate_root = self._generation_store.candidate_path(candidate)
        if checkpoint.phase not in {
            SuccessorCoordinatorPhase.EXECUTING,
            SuccessorCoordinatorPhase.EXECUTED,
            SuccessorCoordinatorPhase.ASSURING,
        }:
            expected_digest = checkpoint.candidate_installed_public_tree_sha256
            monotonic_now_seconds = self._fresh_monotonic_now(checkpoint.candidate_admission)
            capacity = checkpoint.candidate_admission.aggregate_capacity
            candidate_root = self._generation_store.prepare_candidate_from_baseline(
                request.baseline_public_root,
                candidate,
                candidate_max_bytes=capacity.candidate_max_bytes,
                private_generation_estimated_bytes=(capacity.update_private_generation_max_bytes),
                rollback_reserve_bytes=capacity.rollback_reserve_bytes,
                minimum_free_bytes=capacity.minimum_free_bytes,
                monotonic_now_seconds=monotonic_now_seconds,
                monotonic_deadline_seconds=(
                    checkpoint.candidate_admission.monotonic_deadline_seconds
                ),
                minimum_deadline_headroom_seconds=(
                    checkpoint.candidate_admission.minimum_deadline_headroom_seconds
                ),
                expected_resume_installed_public_tree_sha256=expected_digest,
            )
        stored = self._load_resume_transaction(candidate_root, checkpoint)
        if stored.intent.to_dict() != checkpoint.intent.to_dict():
            raise SuccessorCoordinatorError(
                "resume intent differs from the persisted successor transaction"
            )
        if stored.generation_identity_sha256 != candidate.generation_identity_sha256:
            raise SuccessorCoordinatorError("candidate transaction identity differs on resume")
        allowed = _ALLOWED_DURABLE_TRANSACTION_STATES[checkpoint.phase]
        if stored.state not in allowed:
            raise SuccessorCoordinatorError(_STALE_CHECKPOINT_PHASE)
        self._require_durable_admission_matches_phase(checkpoint, candidate_root, stored)
        assert checkpoint.transaction is not None
        if stored.state is checkpoint.transaction.state and (
            stored.to_dict() != checkpoint.transaction.to_dict()
        ):
            self._reject_resume_transaction_payload_drift(stored, checkpoint)
        return candidate_root

    def _load_resume_transaction(
        self,
        candidate_root: Path,
        checkpoint: SuccessorCoordinatorCheckpoint,
    ) -> SuccessorUpdateTransaction:
        try:
            return self._generation_store.load_transaction(candidate_root)
        except SuccessorGenerationStoreError as exc:
            peeked = _peek_successor_transaction(candidate_root)
            if (
                peeked is not None
                and checkpoint.intent is not None
                and peeked.intent.to_dict() != checkpoint.intent.to_dict()
            ):
                raise SuccessorCoordinatorError(
                    "resume intent differs from the persisted successor transaction"
                ) from exc
            raise SuccessorCoordinatorError(
                "candidate transaction identity differs on resume"
            ) from exc

    @staticmethod
    def _reject_resume_transaction_payload_drift(
        stored: SuccessorUpdateTransaction,
        checkpoint: SuccessorCoordinatorCheckpoint,
    ) -> None:
        assert checkpoint.transaction is not None
        if stored.intent.to_dict() != checkpoint.transaction.intent.to_dict():
            raise SuccessorCoordinatorError(
                "resume intent differs from the persisted successor transaction"
            )
        stored_receipts = None if stored.build is None else stored.build.observed_delta_receipts
        checkpoint_receipts = (
            None
            if checkpoint.transaction.build is None
            else checkpoint.transaction.build.observed_delta_receipts
        )
        if stored_receipts != checkpoint_receipts:
            raise SuccessorCoordinatorError(
                "resume receipt inventory differs from the persisted successor transaction"
            )
        raise SuccessorCoordinatorError("durable candidate transaction differs")

    def _fresh_monotonic_now(
        self,
        admission: SuccessorCandidateAdmission,
        *,
        minimum_headroom_seconds: float | None = None,
    ) -> float:
        try:
            raw_now = self._monotonic_clock()
        except Exception as exc:
            raise SuccessorCoordinatorError("monotonic clock measurement failed") from exc
        now = _require_positive_finite(raw_now, field_name="monotonic clock reading")
        required_headroom = (
            admission.minimum_deadline_headroom_seconds
            if minimum_headroom_seconds is None
            else _require_positive_finite(
                minimum_headroom_seconds,
                field_name="minimum coordinator deadline headroom",
            )
        )
        if admission.monotonic_deadline_seconds - now < required_headroom:
            raise SuccessorCoordinatorError(
                "successor coordinator deadline headroom is insufficient"
            )
        return now

    def _require_current_monotonic_epoch(
        self,
        admission: SuccessorCandidateAdmission,
    ) -> None:
        try:
            raw_epoch = self._monotonic_epoch_authority()
        except Exception as exc:
            raise SuccessorCoordinatorError("monotonic epoch authority measurement failed") from exc
        current_epoch = _require_sha256(
            raw_epoch,
            field_name="current monotonic epoch authority",
        )
        if current_epoch != admission.monotonic_epoch_sha256:
            raise SuccessorCoordinatorError(
                "current monotonic epoch differs from candidate admission"
            )

    def _restore_executed_runtime_state(
        self,
        checkpoint: SuccessorCoordinatorCheckpoint,
        candidate_root: Path,
    ) -> None:
        """Reopen the exact candidate and verify executed runtime authorities."""

        assert checkpoint.transaction is not None
        assert checkpoint.planning_evidence is not None
        runtime = self._runtime_factory(
            checkpoint.transaction,
            candidate_root,
            checkpoint.planning_evidence.execution_plan,
        )
        self._require_runtime_route_replacement_bindings(runtime, checkpoint)
        restore = getattr(runtime, "restore_same_generation_execution", None)
        if not callable(restore):
            raise SuccessorCoordinatorError(
                "successor runtime cannot restore executed candidate state"
            )
        try:
            restore()
        except SuccessorCoordinatorError:
            raise
        except Exception as exc:
            raise SuccessorCoordinatorError(
                "executed successor runtime state could not be restored"
            ) from exc
        capture = runtime.capture_identity
        if capture != checkpoint.update_private_generation:
            raise SuccessorCoordinatorError(
                "restored capture authority differs from the executed checkpoint"
            )
        if tuple(runtime.successor_delta_receipts) != tuple(checkpoint.observed_delta_receipts):
            raise SuccessorCoordinatorError(
                "restored replacement receipts differ from the executed checkpoint"
            )
        if _transform_inventory(runtime.transform_output_attestations) != _transform_inventory(
            checkpoint.transform_outputs
        ):
            raise SuccessorCoordinatorError(
                "restored transform inventory differs from the executed checkpoint"
            )
        public_digest = self._measure_candidate(candidate_root)
        if public_digest != checkpoint.candidate_installed_public_tree_sha256:
            raise SuccessorCoordinatorError(
                "restored candidate bytes differ from the executed checkpoint"
            )

    @staticmethod
    def _require_runtime_route_replacement_bindings(
        runtime: SuccessorUpdateRuntime,
        checkpoint: SuccessorCoordinatorCheckpoint,
    ) -> None:
        assert checkpoint.planning_evidence is not None
        assert checkpoint.intent is not None
        assert checkpoint.transaction is not None
        expected = checkpoint.planned_route_replacement_bindings_sha256
        if expected is None:
            raise SuccessorCoordinatorError(
                "executing checkpoint lacks route replacement binding authority"
            )
        try:
            runtime_digest = runtime.planned_route_replacement_bindings_sha256
        except Exception as exc:
            raise SuccessorCoordinatorError(
                "successor runtime route replacement binding authority is unavailable"
            ) from exc
        runtime_digest = _require_sha256(
            runtime_digest,
            field_name="runtime planned_route_replacement_bindings_sha256",
        )
        if any(
            authority != expected
            for authority in (
                runtime_digest,
                checkpoint.planning_evidence.planned_route_replacement_bindings_sha256,
                checkpoint.planning_evidence.execution_plan.planned_route_replacement_bindings_sha256,
                checkpoint.intent.planned_route_replacement_bindings_sha256,
                checkpoint.transaction.intent.planned_route_replacement_bindings_sha256,
            )
        ):
            raise SuccessorCoordinatorError(
                "successor runtime route replacement binding authority differs"
            )

    def _measure_candidate(self, candidate_root: Path) -> str:
        try:
            digest = self._installed_public_tree_digest(candidate_root / "public")
        except (OSError, RuntimeError, ValueError) as exc:
            raise SuccessorCoordinatorError(
                "successor candidate public inventory cannot be measured"
            ) from exc
        return _require_sha256(digest, field_name="candidate installed public tree")

    @staticmethod
    def _require_complete_pipeline_result(result: object) -> None:
        try:
            pipeline_result = cast("_PipelineResultLike", result)
            failed_extractions = pipeline_result.failed_extractions
            failed_loads = pipeline_result.failed_loads
            errors = pipeline_result.errors
        except AttributeError as exc:
            raise SuccessorCoordinatorError(
                "successor runtime did not return a complete pipeline result"
            ) from exc
        if type(failed_extractions) is not int or failed_extractions < 0:
            raise SuccessorCoordinatorError("pipeline failed_extractions is invalid")
        if type(failed_loads) is not int or failed_loads < 0:
            raise SuccessorCoordinatorError("pipeline failed_loads is invalid")
        if (
            not isinstance(errors, Sequence)
            or isinstance(errors, (str, bytes, bytearray))
            or any(not isinstance(error, str) for error in errors)
        ):
            raise SuccessorCoordinatorError("pipeline errors inventory is invalid")
        if failed_extractions or failed_loads or errors:
            raise SuccessorCoordinatorError(
                "successor pipeline result is incomplete; promotion is blocked"
            )
