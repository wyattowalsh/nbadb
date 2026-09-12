"""Exact sealed-plan runtime for recurring successor updates."""

from __future__ import annotations

import fcntl
import json
import math
import os
import stat
import threading
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.extract.registry import (
    EndpointRegistry,
    EndpointRegistryAuthority,
    EndpointRegistryAuthorityError,
)
from nbadb.orchestrate.capture_session import (
    CaptureRunScope,
    CaptureSessionState,
    PrivateCaptureSession,
    PrivateGenerationIdentity,
)
from nbadb.orchestrate.orchestrator import (
    Orchestrator,
    PipelineResult,
    SuccessorExecutionOutcome,
    TransformOutputAttestation,
    validate_successor_runtime_plan,
)
from nbadb.orchestrate.successor_execution_restore import (
    reopen_same_generation_journal_attestations,
    restore_same_generation_replacements,
)
from nbadb.orchestrate.successor_inventory import (
    InstalledPublicTreeInventory,
    measure_installed_public_tree,
)
from nbadb.orchestrate.successor_update_contract import (
    ObservedDeltaReceipt,
    SuccessorGenerationBuild,
    SuccessorGenerationState,
    SuccessorUpdateContractError,
    SuccessorUpdateMode,
    SuccessorUpdateTransaction,
    canonical_json_bytes,
    canonical_sha256,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from nbadb.core.config import NbaDbSettings
    from nbadb.extract.bronze import BronzeLimits
    from nbadb.orchestrate.successor_execution_plan import SuccessorExecutionPlan

__all__ = [
    "ExactPlanRuntimePipelineResult",
    "ExactPlanRuntimeTerminalReceipt",
    "ExactPlanRuntimeTerminalReceiptStore",
    "ExactPlanSuccessorRuntime",
    "ExactPlanSuccessorRuntimeFactory",
]

_SIGNED_63_MAX = (1 << 63) - 1
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


def _paths_overlap(first: Path, second: Path) -> bool:
    first_resolved = first.resolve(strict=False)
    second_resolved = second.resolve(strict=False)
    return (
        first_resolved == second_resolved
        or first_resolved in second_resolved.parents
        or second_resolved in first_resolved.parents
    )


def _validate_directory_identity(value: object, *, label: str) -> tuple[int, int]:
    if (
        type(value) is not tuple
        or len(value) != 2
        or any(type(item) is not int or item < 0 for item in value)
        or value[1] == 0
    ):
        raise SuccessorUpdateContractError(f"{label} must be a (device, inode) integer pair")
    return cast("tuple[int, int]", value)


def _require_positive_byte_limit(value: object, *, label: str) -> int:
    if type(value) is not int or value <= 0 or value > _SIGNED_63_MAX:
        raise SuccessorUpdateContractError(f"{label} must be a positive signed-63-bit integer")
    return value


def _require_candidate_directory_authority(
    candidate_root: Path,
    *,
    expected_candidate_identity: tuple[int, int] | None = None,
    expected_public_identity: tuple[int, int] | None = None,
) -> tuple[tuple[int, int], tuple[int, int]]:
    if os.name != "posix" or not _NOFOLLOW:
        raise SuccessorUpdateContractError(
            "successor candidate authority requires POSIX O_NOFOLLOW"
        )
    if not isinstance(candidate_root, Path) or not candidate_root.is_absolute():
        raise SuccessorUpdateContractError("candidate root must be an absolute path")
    if candidate_root.resolve(strict=False) != candidate_root:
        raise SuccessorUpdateContractError(
            "candidate root must not contain aliases or symlink ancestors"
        )
    candidate_fd = -1
    public_fd = -1
    try:
        parts = candidate_root.parts
        candidate_fd = os.open(
            parts[0],
            os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
        )
        for component in parts[1:]:
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
                dir_fd=candidate_fd,
            )
            os.close(candidate_fd)
            candidate_fd = child
        public_fd = os.open(
            "public",
            os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
            dir_fd=candidate_fd,
        )
        candidate_stat = os.fstat(candidate_fd)
        public_stat = os.fstat(public_fd)
        named_candidate = os.stat(candidate_root, follow_symlinks=False)
        named_public = os.stat(candidate_root / "public", follow_symlinks=False)
        candidate_identity = (candidate_stat.st_dev, candidate_stat.st_ino)
        public_identity = (public_stat.st_dev, public_stat.st_ino)
        if (
            not stat.S_ISDIR(candidate_stat.st_mode)
            or not stat.S_ISDIR(public_stat.st_mode)
            or candidate_stat.st_uid != os.geteuid()
            or public_stat.st_uid != os.geteuid()
            or candidate_identity != (named_candidate.st_dev, named_candidate.st_ino)
            or public_identity != (named_public.st_dev, named_public.st_ino)
        ):
            raise SuccessorUpdateContractError("candidate public authority is invalid")
        if expected_candidate_identity is not None and candidate_identity != (
            _validate_directory_identity(
                expected_candidate_identity,
                label="expected candidate root identity",
            )
        ):
            raise SuccessorUpdateContractError("candidate root identity changed")
        if expected_public_identity is not None and public_identity != (
            _validate_directory_identity(
                expected_public_identity,
                label="expected candidate public identity",
            )
        ):
            raise SuccessorUpdateContractError("candidate public identity changed")
        return candidate_identity, public_identity
    except (OSError, ValueError) as exc:
        if isinstance(exc, SuccessorUpdateContractError):
            raise
        raise SuccessorUpdateContractError("candidate public authority is invalid") from exc
    finally:
        if public_fd >= 0:
            os.close(public_fd)
        if candidate_fd >= 0:
            os.close(candidate_fd)


def _measure_authorized_private_directory_bytes(
    descriptor: int,
    *,
    maximum_bytes: int,
    label: str,
) -> int:
    limit = _require_positive_byte_limit(maximum_bytes, label=f"{label} maximum bytes")

    def walk(directory_fd: int, observed: int) -> int:
        before = os.fstat(directory_fd)
        if not stat.S_ISDIR(before.st_mode):
            raise SuccessorUpdateContractError(f"{label} contains a non-directory authority")
        try:
            names = sorted(os.listdir(directory_fd))
        except OSError as exc:
            raise SuccessorUpdateContractError(f"{label} cannot be inventoried") from exc
        for name in names:
            child_fd = os.open(
                name,
                os.O_RDONLY | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
                dir_fd=directory_fd,
            )
            try:
                child = os.fstat(child_fd)
                if stat.S_ISDIR(child.st_mode):
                    observed = walk(child_fd, observed)
                elif stat.S_ISREG(child.st_mode):
                    if child.st_uid != os.geteuid() or child.st_nlink != 1:
                        raise SuccessorUpdateContractError(
                            f"{label} contains an invalid regular-file authority"
                        )
                    observed += child.st_size
                    if observed > limit:
                        raise SuccessorUpdateContractError(f"{label} exceeds its maximum size")
                else:
                    raise SuccessorUpdateContractError(f"{label} contains a non-regular entry")
            finally:
                os.close(child_fd)
        after = os.fstat(directory_fd)
        if (
            before.st_dev,
            before.st_ino,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise SuccessorUpdateContractError(f"{label} changed while being inventoried")
        return observed

    return walk(descriptor, 0)


def _open_authorized_private_directory(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    label: str,
) -> int:
    if os.name != "posix" or not _NOFOLLOW:
        raise SuccessorUpdateContractError(
            "successor private-root authority requires POSIX O_NOFOLLOW"
        )
    if not isinstance(path, Path) or not path.is_absolute():
        raise SuccessorUpdateContractError(f"{label} must be an absolute Path")
    expected = _validate_directory_identity(expected_identity, label=f"expected {label} identity")
    absolute = Path(os.path.abspath(path))
    descriptor = -1
    try:
        parts = absolute.parts
        descriptor = os.open(
            parts[0], os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC | _NONBLOCK
        )
        for component in parts[1:]:
            child = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC | _NONBLOCK,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
        opened = os.fstat(descriptor)
        named = os.stat(absolute, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or (opened.st_dev, opened.st_ino) != expected
            or (named.st_dev, named.st_ino) != expected
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o700
        ):
            raise SuccessorUpdateContractError(f"{label} authority is invalid")
        return descriptor
    except (OSError, ValueError) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        if isinstance(exc, SuccessorUpdateContractError):
            raise
        raise SuccessorUpdateContractError(f"{label} cannot be opened safely") from exc


@dataclass(frozen=True, slots=True)
class ExactPlanRuntimePipelineResult:
    """Immutable, canonical terminal form of a complete pipeline result."""

    tables_updated: int
    rows_total: int
    duration_seconds: float
    failed_extractions: int
    failed_loads: int
    skipped_extractions: int
    errors: tuple[str, ...]

    def __post_init__(self) -> None:
        from nbadb.orchestrate.transformers import expected_transform_output_tables

        for field_name in (
            "tables_updated",
            "rows_total",
            "failed_extractions",
            "failed_loads",
            "skipped_extractions",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise SuccessorUpdateContractError(
                    f"terminal pipeline {field_name} must be a nonnegative integer"
                )
        if (
            not isinstance(self.duration_seconds, int | float)
            or isinstance(self.duration_seconds, bool)
            or not math.isfinite(self.duration_seconds)
            or self.duration_seconds < 0
        ):
            raise SuccessorUpdateContractError(
                "terminal pipeline duration_seconds must be finite and nonnegative"
            )
        if type(self.errors) is not tuple or any(
            not isinstance(error, str) or not error for error in self.errors
        ):
            raise SuccessorUpdateContractError(
                "terminal pipeline errors must be an immutable string tuple"
            )
        if (
            self.tables_updated != len(expected_transform_output_tables(include_live=True))
            or self.failed_extractions
            or self.failed_loads
            or self.errors
        ):
            raise SuccessorUpdateContractError("terminal pipeline result is incomplete")

    @classmethod
    def from_pipeline_result(cls, result: PipelineResult) -> Self:
        if not isinstance(result, PipelineResult):
            raise SuccessorUpdateContractError("terminal pipeline result has an invalid type")
        return cls(
            tables_updated=result.tables_updated,
            rows_total=result.rows_total,
            duration_seconds=float(result.duration_seconds),
            failed_extractions=result.failed_extractions,
            failed_loads=result.failed_loads,
            skipped_extractions=result.skipped_extractions,
            errors=tuple(result.errors),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "tables_updated": self.tables_updated,
            "rows_total": self.rows_total,
            "duration_seconds": self.duration_seconds,
            "failed_extractions": self.failed_extractions,
            "failed_loads": self.failed_loads,
            "skipped_extractions": self.skipped_extractions,
            "errors": list(self.errors),
        }

    def to_pipeline_result(self) -> PipelineResult:
        return PipelineResult(
            tables_updated=self.tables_updated,
            rows_total=self.rows_total,
            duration_seconds=self.duration_seconds,
            failed_extractions=self.failed_extractions,
            failed_loads=self.failed_loads,
            skipped_extractions=self.skipped_extractions,
            errors=list(self.errors),
        )


def _logical_call_authority(
    transaction: SuccessorUpdateTransaction,
    receipts: Sequence[ObservedDeltaReceipt],
) -> tuple[tuple[str, ...], str]:
    scopes = {scope.identity_sha256: scope for scope in transaction.intent.requested_scopes}
    by_root: dict[str, list[object]] = {}
    for receipt in receipts:
        scope = scopes.get(receipt.requested_scope_sha256)
        if scope is None:
            raise SuccessorUpdateContractError(
                "terminal receipt contains a delta outside the immutable intent"
            )
        by_root.setdefault(receipt.logical_call_receipt_sha256, []).append(scope)
    bindings: list[dict[str, object]] = []
    for root in sorted(by_root):
        logical_scopes = by_root[root]
        endpoints = {cast("Any", scope).endpoint_name for scope in logical_scopes}
        parameters = {cast("Any", scope).scope_sha256 for scope in logical_scopes}
        routes = sorted(cast("Any", scope).route_id for scope in logical_scopes)
        if len(endpoints) != 1 or len(parameters) != 1 or len(routes) != len(set(routes)):
            raise SuccessorUpdateContractError(
                "terminal receipt logical-call bindings are inconsistent"
            )
        bindings.append(
            {
                "endpoint_name": next(iter(endpoints)),
                "logical_call_receipt_sha256": root,
                "logical_parameters_sha256": next(iter(parameters)),
                "provider_authority_sha256": transaction.baseline.provider_authority_sha256,
                "result_route_ids": routes,
            }
        )
    return tuple(sorted(by_root)), canonical_sha256(bindings)


def _logical_call_bindings(
    transaction: SuccessorUpdateTransaction,
    receipts: tuple[ObservedDeltaReceipt, ...],
) -> tuple[LogicalCallReceiptBinding, ...]:
    scopes = {scope.identity_sha256: scope for scope in transaction.intent.requested_scopes}
    by_root: dict[str, list[object]] = {}
    for receipt in receipts:
        scope = scopes.get(receipt.requested_scope_sha256)
        if scope is None:
            raise SuccessorUpdateContractError(
                "terminal receipt contains a delta outside the immutable intent"
            )
        by_root.setdefault(receipt.logical_call_receipt_sha256, []).append(scope)
    bindings: list[LogicalCallReceiptBinding] = []
    for root in sorted(by_root):
        logical_scopes = by_root[root]
        endpoints = {cast("Any", scope).endpoint_name for scope in logical_scopes}
        parameters = {cast("Any", scope).scope_sha256 for scope in logical_scopes}
        routes = tuple(sorted(cast("Any", scope).route_id for scope in logical_scopes))
        if len(endpoints) != 1 or len(parameters) != 1 or len(routes) != len(set(routes)):
            raise SuccessorUpdateContractError(
                "terminal receipt logical-call bindings are inconsistent"
            )
        bindings.append(
            LogicalCallReceiptBinding(
                logical_call_receipt_sha256=root,
                endpoint_name=next(iter(endpoints)),
                logical_parameters_sha256=next(iter(parameters)),
                provider_authority_sha256=transaction.baseline.provider_authority_sha256,
                result_route_ids=routes,
            )
        )
    return tuple(bindings)


def _classified_live_transform_tables() -> frozenset[str]:
    from nbadb.orchestrate.transformers import expected_transform_output_tables

    return expected_transform_output_tables(include_live=True) - expected_transform_output_tables(
        include_live=False
    )


def _stable_non_live_identity(attestations: Sequence[TransformOutputAttestation]) -> str:
    live = _classified_live_transform_tables()
    stable = [
        item.to_dict()
        for item in sorted(attestations, key=lambda item: item.table_name)
        if item.table_name not in live
    ]
    return canonical_sha256(stable)


def _measure_public_stable_non_live_identity(
    duckdb_path: Path,
    *,
    scratch_parent: Path,
    expected_scratch_identity: tuple[int, int],
    transform_scratch_max_bytes: int,
) -> str:
    import duckdb

    from nbadb.orchestrate.successor_transform_authority import _attest_exact_tables
    from nbadb.orchestrate.transformers import expected_transform_output_tables

    if not isinstance(duckdb_path, Path) or not duckdb_path.is_absolute():
        raise SuccessorUpdateContractError("public DuckDB path is invalid")
    try:
        named = os.stat(duckdb_path, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorUpdateContractError("public DuckDB is missing") from exc
    if not stat.S_ISREG(named.st_mode):
        raise SuccessorUpdateContractError("public DuckDB is unreadable")
    non_live = tuple(sorted(expected_transform_output_tables(include_live=False)))
    connection = None
    try:
        connection = duckdb.connect(str(duckdb_path), read_only=True)
        connection.execute("SET temp_directory = ?", [""])
        connection.execute("SET max_temp_directory_size = ?", ["0B"])
        configured = connection.execute(
            "SELECT current_setting('temp_directory'), current_setting('max_temp_directory_size')"
        ).fetchone()
        if configured != ("", "0 bytes"):
            raise SuccessorUpdateContractError("public DuckDB spill could not be disabled")
        attestations = _attest_exact_tables(
            connection,
            non_live,
            scratch_parent=scratch_parent,
            expected_scratch_parent_identity=expected_scratch_identity,
            transform_scratch_max_bytes=transform_scratch_max_bytes,
        )
    except SuccessorUpdateContractError:
        raise
    except Exception as exc:
        raise SuccessorUpdateContractError("public DuckDB is unreadable") from exc
    finally:
        if connection is not None:
            connection.close()
    return _stable_non_live_identity(attestations)


def _reject_unclassified_public_drift(
    *,
    current_public_tree_sha256: str,
    expected_public_tree_sha256: str,
    current_stable_identity: str | None = None,
    expected_stable_identity: str | None = None,
) -> None:
    if current_public_tree_sha256 == expected_public_tree_sha256:
        return
    if (
        current_stable_identity is not None
        and expected_stable_identity is not None
        and current_stable_identity == expected_stable_identity
    ):
        return
    raise SuccessorUpdateContractError(
        "no-change replay rejected unclassified public-tree drift: installed_public_tree_sha256"
    )


def _validate_receipts_against_transaction(
    transaction: SuccessorUpdateTransaction,
    receipts: Sequence[ObservedDeltaReceipt],
) -> None:
    expected_scopes = {scope.identity_sha256 for scope in transaction.intent.requested_scopes}
    observed_scopes = {receipt.requested_scope_sha256 for receipt in receipts}
    mismatches: list[str] = []
    if observed_scopes != expected_scopes or len(receipts) != len(expected_scopes):
        mismatches.append("requested_scopes")
    if any(
        receipt.baseline_identity_sha256 != transaction.baseline.identity_sha256
        for receipt in receipts
    ):
        mismatches.append("baseline_identity_sha256")
    if any(
        receipt.update_intent_sha256 != transaction.intent.identity_sha256 for receipt in receipts
    ):
        mismatches.append("update_intent_sha256")
    if any(receipt.source_sha != transaction.intent.source_sha for receipt in receipts):
        mismatches.append("source_sha")
    try:
        build = SuccessorGenerationBuild(
            baseline_identity_sha256=transaction.baseline.identity_sha256,
            update_intent_sha256=transaction.intent.identity_sha256,
            source_sha=transaction.intent.source_sha,
            observed_delta_receipts=tuple(receipts),
        )
    except SuccessorUpdateContractError:
        mismatches.append("planned_route_replacement_bindings")
    else:
        if (
            build.planned_route_replacement_bindings_sha256
            != transaction.intent.planned_route_replacement_bindings_sha256
        ):
            mismatches.append("planned_route_replacement_bindings_sha256")
    if mismatches:
        raise SuccessorUpdateContractError(
            "terminal delta receipts differ from the immutable transaction: "
            + ", ".join(mismatches)
        )


def _validate_runtime_authority(
    transaction: SuccessorUpdateTransaction,
    plan: SuccessorExecutionPlan,
    capture_scope: CaptureRunScope,
) -> None:
    if transaction.state is not SuccessorGenerationState.CANDIDATE:
        raise SuccessorUpdateContractError("runtime requires an exact candidate transaction")
    logical_call_keys = [
        (dispatch.endpoint_name, dispatch.parameters_sha256) for dispatch in plan.dispatches
    ]
    if len(logical_call_keys) != len(set(logical_call_keys)):
        raise SuccessorUpdateContractError(
            "successor runtime plan dispatches a logical provider call more than once"
        )
    projected_scopes = tuple(
        sorted(
            (scope for dispatch in plan.dispatches for scope in dispatch.requested_scopes),
            key=lambda scope: scope.identity_sha256,
        )
    )
    expected_provider = expected_nba_api_provider_authority()["authority_sha256"]
    mismatches: list[str] = []
    if plan.identity_sha256 != transaction.intent.successor_execution_plan_sha256:
        mismatches.append("successor_execution_plan_sha256")
    if plan.baseline_identity_sha256 != transaction.baseline.identity_sha256:
        mismatches.append("baseline_identity_sha256")
    if plan.requested_route_scopes_sha256 != transaction.intent.requested_scopes_sha256:
        mismatches.append("requested_route_scopes_sha256")
    if (
        plan.planned_route_replacement_bindings_sha256
        != transaction.intent.planned_route_replacement_bindings_sha256
    ):
        mismatches.append("planned_route_replacement_bindings_sha256")
    if projected_scopes != transaction.intent.requested_scopes:
        mismatches.append("requested_scopes")
    if transaction.baseline.provider_authority_sha256 != expected_provider:
        mismatches.append("provider_authority_sha256")
    if capture_scope.semantic_source_sha != transaction.intent.source_sha:
        mismatches.append("capture_scope.semantic_source_sha")
    if capture_scope.chain_id != transaction.baseline.chain_id:
        mismatches.append("capture_scope.chain_id")
    if capture_scope.lane_id != transaction.generation_identity_sha256:
        mismatches.append("capture_scope.lane_id")
    if mismatches:
        raise SuccessorUpdateContractError(
            "successor runtime authority does not reconcile: " + ", ".join(mismatches)
        )


def _reconcile_private_identity(
    identity: PrivateGenerationIdentity,
    *,
    transaction: SuccessorUpdateTransaction,
    capture_scope: CaptureRunScope,
    terminal: ExactPlanRuntimeTerminalReceipt,
) -> None:
    roots, bindings = _logical_call_authority(transaction, terminal.delta_receipts)
    mismatches: list[str] = []
    if roots != terminal.logical_call_receipt_sha256s:
        mismatches.append("terminal_logical_call_roots")
    if roots != identity.done_call_receipt_sha256s or identity.done_call_count != len(roots):
        mismatches.append("private_logical_call_roots")
    if bindings != terminal.logical_call_bindings_sha256:
        mismatches.append("terminal_logical_call_bindings")
    if bindings != identity.done_call_bindings_sha256:
        mismatches.append("private_logical_call_bindings")
    expected_scope = {
        "semantic_source_sha": capture_scope.semantic_source_sha,
        "chain_id": capture_scope.chain_id,
        "lane_id": capture_scope.lane_id,
        "workflow_run_id": capture_scope.workflow_run_id,
        "workflow_run_attempt": capture_scope.workflow_run_attempt,
    }
    if any(getattr(identity, name) != value for name, value in expected_scope.items()):
        mismatches.append("capture_scope")
    if identity.provider_authority_sha256 != terminal.provider_authority_sha256:
        mismatches.append("provider_authority_sha256")
    if mismatches:
        raise SuccessorUpdateContractError(
            "successor private generation does not reconcile: " + ", ".join(mismatches)
        )


@dataclass(frozen=True, slots=True)
class ExactPlanRuntimeTerminalReceipt:
    """Path-free authority persisted after public DB close and before capture seal."""

    generation_identity_sha256: str
    transaction_content_sha256: str
    update_intent_sha256: str
    successor_execution_plan_sha256: str
    planning_generation_manifest_sha256: str
    planned_route_replacement_bindings_sha256: str
    provider_authority_sha256: str
    capture_scope_identity_sha256: str
    delta_receipts: tuple[ObservedDeltaReceipt, ...]
    logical_call_receipt_sha256s: tuple[str, ...]
    logical_call_bindings_sha256: str
    transform_output_attestations: tuple[TransformOutputAttestation, ...]
    pipeline_result: ExactPlanRuntimePipelineResult
    installed_public_tree_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "exact_plan_successor_runtime_terminal_receipt"

    @classmethod
    def build(
        cls,
        *,
        transaction: SuccessorUpdateTransaction,
        execution_plan: SuccessorExecutionPlan,
        capture_scope: CaptureRunScope,
        outcome: SuccessorExecutionOutcome,
        installed_public_tree_sha256: str,
    ) -> Self:
        receipts = tuple(
            sorted(outcome.delta_receipts, key=lambda item: item.requested_scope_sha256)
        )
        _validate_receipts_against_transaction(transaction, receipts)
        build = SuccessorGenerationBuild(
            baseline_identity_sha256=transaction.baseline.identity_sha256,
            update_intent_sha256=transaction.intent.identity_sha256,
            source_sha=transaction.intent.source_sha,
            observed_delta_receipts=receipts,
        )
        binding_digest = build.planned_route_replacement_bindings_sha256
        if (
            binding_digest != execution_plan.planned_route_replacement_bindings_sha256
            or binding_digest != transaction.intent.planned_route_replacement_bindings_sha256
            or binding_digest != outcome.planned_route_replacement_bindings_sha256
        ):
            raise SuccessorUpdateContractError(
                "terminal replacement bindings differ from the sealed execution plan"
            )
        roots, bindings_sha256 = _logical_call_authority(transaction, receipts)
        return cls(
            generation_identity_sha256=transaction.generation_identity_sha256,
            transaction_content_sha256=transaction.content_sha256,
            update_intent_sha256=transaction.intent.identity_sha256,
            successor_execution_plan_sha256=execution_plan.identity_sha256,
            planning_generation_manifest_sha256=(
                transaction.intent.planning_generation_manifest_sha256
            ),
            planned_route_replacement_bindings_sha256=binding_digest,
            provider_authority_sha256=transaction.baseline.provider_authority_sha256,
            capture_scope_identity_sha256=capture_scope.identity_sha256,
            delta_receipts=receipts,
            logical_call_receipt_sha256s=roots,
            logical_call_bindings_sha256=bindings_sha256,
            transform_output_attestations=tuple(
                sorted(outcome.transform_output_attestations, key=lambda item: item.table_name)
            ),
            pipeline_result=ExactPlanRuntimePipelineResult.from_pipeline_result(outcome.result),
            installed_public_tree_sha256=installed_public_tree_sha256,
        )

    def __post_init__(self) -> None:
        for field_name in (
            "generation_identity_sha256",
            "transaction_content_sha256",
            "update_intent_sha256",
            "successor_execution_plan_sha256",
            "planning_generation_manifest_sha256",
            "planned_route_replacement_bindings_sha256",
            "provider_authority_sha256",
            "capture_scope_identity_sha256",
            "logical_call_bindings_sha256",
            "installed_public_tree_sha256",
        ):
            value = getattr(self, field_name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise SuccessorUpdateContractError(f"{field_name} must be a lowercase SHA-256")
        receipts = tuple(sorted(self.delta_receipts, key=lambda item: item.requested_scope_sha256))
        if not receipts or receipts != self.delta_receipts:
            raise SuccessorUpdateContractError(
                "terminal delta receipts must be nonempty and sorted"
            )
        if len({item.requested_scope_sha256 for item in receipts}) != len(receipts):
            raise SuccessorUpdateContractError("terminal delta receipts contain duplicate scopes")
        embedded_build = SuccessorGenerationBuild(
            baseline_identity_sha256=receipts[0].baseline_identity_sha256,
            update_intent_sha256=receipts[0].update_intent_sha256,
            source_sha=receipts[0].source_sha,
            observed_delta_receipts=receipts,
        )
        if (
            embedded_build.planned_route_replacement_bindings_sha256
            != self.planned_route_replacement_bindings_sha256
        ):
            raise SuccessorUpdateContractError(
                "terminal planned route replacement binding digest differs"
            )
        roots = tuple(sorted({item.logical_call_receipt_sha256 for item in receipts}))
        if roots != self.logical_call_receipt_sha256s:
            raise SuccessorUpdateContractError("terminal logical-call root inventory differs")
        transforms = self.transform_output_attestations
        from nbadb.orchestrate.transformers import expected_transform_output_tables

        expected_names = tuple(sorted(expected_transform_output_tables(include_live=True)))
        if (
            transforms != tuple(sorted(transforms, key=lambda item: item.table_name))
            or len({item.table_name for item in transforms}) != len(transforms)
            or tuple(item.table_name for item in transforms) != expected_names
        ):
            raise SuccessorUpdateContractError(
                "terminal transform inventory must exactly match the sorted unique "
                "schema-backed output universe"
            )
        for item in transforms:
            if type(item.row_count) is not int or item.row_count < 0:
                raise SuccessorUpdateContractError(
                    "terminal transform row counts must be nonnegative integers"
                )
            for digest in (item.schema_sha256, item.content_sha256):
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                ):
                    raise SuccessorUpdateContractError(
                        "terminal transform digests must be lowercase SHA-256 values"
                    )
        if not isinstance(self.pipeline_result, ExactPlanRuntimePipelineResult):
            raise SuccessorUpdateContractError("terminal pipeline result has an invalid type")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "generation_identity_sha256": self.generation_identity_sha256,
            "transaction_content_sha256": self.transaction_content_sha256,
            "update_intent_sha256": self.update_intent_sha256,
            "successor_execution_plan_sha256": self.successor_execution_plan_sha256,
            "planning_generation_manifest_sha256": self.planning_generation_manifest_sha256,
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
            "provider_authority_sha256": self.provider_authority_sha256,
            "capture_scope_identity_sha256": self.capture_scope_identity_sha256,
            "delta_receipts": [item.to_dict() for item in self.delta_receipts],
            "delta_receipts_sha256": canonical_sha256(
                [item.to_dict() for item in self.delta_receipts]
            ),
            "logical_call_receipt_sha256s": list(self.logical_call_receipt_sha256s),
            "logical_call_bindings_sha256": self.logical_call_bindings_sha256,
            "transform_output_attestations": [
                item.to_dict() for item in self.transform_output_attestations
            ],
            "transform_output_attestations_sha256": canonical_sha256(
                [item.to_dict() for item in self.transform_output_attestations]
            ),
            "pipeline_result": self.pipeline_result.to_dict(),
            "installed_public_tree_sha256": self.installed_public_tree_sha256,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        if not isinstance(encoded, bytes):
            raise SuccessorUpdateContractError("terminal receipt encoding must be bytes")

        def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise SuccessorUpdateContractError(
                        f"terminal receipt contains duplicate key {key!r}"
                    )
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise SuccessorUpdateContractError(
                f"terminal receipt contains non-finite JSON value {value}"
            )

        try:
            payload = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=reject_duplicate_pairs,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorUpdateContractError("terminal receipt is not strict JSON") from exc
        if not isinstance(payload, dict) or canonical_json_bytes(payload) != encoded:
            raise SuccessorUpdateContractError("terminal receipt bytes are not canonical")
        expected = {
            "schema_version",
            "kind",
            "generation_identity_sha256",
            "transaction_content_sha256",
            "update_intent_sha256",
            "successor_execution_plan_sha256",
            "planning_generation_manifest_sha256",
            "planned_route_replacement_bindings_sha256",
            "provider_authority_sha256",
            "capture_scope_identity_sha256",
            "delta_receipts",
            "delta_receipts_sha256",
            "logical_call_receipt_sha256s",
            "logical_call_bindings_sha256",
            "transform_output_attestations",
            "transform_output_attestations_sha256",
            "pipeline_result",
            "installed_public_tree_sha256",
        }
        if (
            set(payload) != expected
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise SuccessorUpdateContractError("terminal receipt fields are invalid")
        raw_receipts = payload["delta_receipts"]
        raw_transforms = payload["transform_output_attestations"]
        raw_result = payload["pipeline_result"]
        if (
            not isinstance(raw_receipts, list)
            or not isinstance(raw_transforms, list)
            or not isinstance(raw_result, dict)
        ):
            raise SuccessorUpdateContractError("terminal receipt inventories are invalid")
        if any(not isinstance(item, dict) for item in raw_receipts):
            raise SuccessorUpdateContractError("terminal delta receipt inventory is invalid")
        receipts = tuple(ObservedDeltaReceipt.from_dict(item) for item in raw_receipts)
        if canonical_sha256(raw_receipts) != payload["delta_receipts_sha256"]:
            raise SuccessorUpdateContractError("terminal delta receipt digest differs")
        transforms: list[TransformOutputAttestation] = []
        for item in raw_transforms:
            if (
                not isinstance(item, dict)
                or set(item) != {"table_name", "row_count", "schema_sha256", "content_sha256"}
                or not isinstance(item["table_name"], str)
                or type(item["row_count"]) is not int
                or not isinstance(item["schema_sha256"], str)
                or not isinstance(item["content_sha256"], str)
            ):
                raise SuccessorUpdateContractError("terminal transform inventory member is invalid")
            transforms.append(
                TransformOutputAttestation(
                    table_name=item["table_name"],
                    row_count=item["row_count"],
                    schema_sha256=item["schema_sha256"],
                    content_sha256=item["content_sha256"],
                )
            )
        transform_tuple = tuple(transforms)
        if canonical_sha256(raw_transforms) != payload["transform_output_attestations_sha256"]:
            raise SuccessorUpdateContractError("terminal transform inventory digest differs")
        expected_result = {
            "tables_updated",
            "rows_total",
            "duration_seconds",
            "failed_extractions",
            "failed_loads",
            "skipped_extractions",
            "errors",
        }
        integer_result_fields = (
            "tables_updated",
            "rows_total",
            "failed_extractions",
            "failed_loads",
            "skipped_extractions",
        )
        if (
            set(raw_result) != expected_result
            or any(type(raw_result[field]) is not int for field in integer_result_fields)
            or not isinstance(raw_result["duration_seconds"], int | float)
            or isinstance(raw_result["duration_seconds"], bool)
            or not isinstance(raw_result["errors"], list)
            or any(not isinstance(error, str) for error in raw_result["errors"])
        ):
            raise SuccessorUpdateContractError("terminal pipeline result fields are invalid")
        raw_roots = payload["logical_call_receipt_sha256s"]
        if not isinstance(raw_roots, list) or not all(isinstance(root, str) for root in raw_roots):
            raise SuccessorUpdateContractError("terminal logical-call roots are invalid")
        result = cls(
            generation_identity_sha256=cast("str", payload["generation_identity_sha256"]),
            transaction_content_sha256=cast("str", payload["transaction_content_sha256"]),
            update_intent_sha256=cast("str", payload["update_intent_sha256"]),
            successor_execution_plan_sha256=cast("str", payload["successor_execution_plan_sha256"]),
            planning_generation_manifest_sha256=cast(
                "str", payload["planning_generation_manifest_sha256"]
            ),
            planned_route_replacement_bindings_sha256=cast(
                "str", payload["planned_route_replacement_bindings_sha256"]
            ),
            provider_authority_sha256=cast("str", payload["provider_authority_sha256"]),
            capture_scope_identity_sha256=cast("str", payload["capture_scope_identity_sha256"]),
            delta_receipts=receipts,
            logical_call_receipt_sha256s=tuple(cast("list[str]", raw_roots)),
            logical_call_bindings_sha256=cast("str", payload["logical_call_bindings_sha256"]),
            transform_output_attestations=transform_tuple,
            pipeline_result=ExactPlanRuntimePipelineResult(
                tables_updated=cast("int", raw_result["tables_updated"]),
                rows_total=cast("int", raw_result["rows_total"]),
                duration_seconds=float(cast("int | float", raw_result["duration_seconds"])),
                failed_extractions=cast("int", raw_result["failed_extractions"]),
                failed_loads=cast("int", raw_result["failed_loads"]),
                skipped_extractions=cast("int", raw_result["skipped_extractions"]),
                errors=tuple(cast("list[str]", raw_result["errors"])),
            ),
            installed_public_tree_sha256=cast("str", payload["installed_public_tree_sha256"]),
        )
        if result.canonical_bytes != encoded:
            raise SuccessorUpdateContractError(
                "terminal receipt reconstructed bytes differ from their authority"
            )
        return result


class ExactPlanRuntimeTerminalReceiptStore:
    """Owner-only locked terminal receipt with descriptor-bound replace/read."""

    def __init__(
        self,
        path: Path,
        *,
        forbidden_roots: Sequence[Path],
        expected_parent_identity: tuple[int, int],
        maximum_bytes: int,
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute() or not path.name:
            raise SuccessorUpdateContractError("terminal receipt path must be absolute")
        if path.resolve(strict=False) != path:
            raise SuccessorUpdateContractError(
                "terminal receipt path must not contain aliases or symlink ancestors"
            )
        self._path = path
        self._lock_path = path.with_name(path.name + ".lock")
        self._name = path.name
        self._lock_name = self._lock_path.name
        self._thread_lock = threading.RLock()
        resolved_path = path.resolve(strict=False)
        for root in forbidden_roots:
            root_path = Path(root)
            if not root_path.is_absolute():
                raise SuccessorUpdateContractError("terminal forbidden roots must be absolute")
            resolved_root = root_path.resolve(strict=False)
            if (
                resolved_path == resolved_root
                or resolved_root in resolved_path.parents
                or resolved_path in resolved_root.parents
            ):
                raise SuccessorUpdateContractError(
                    "terminal receipt overlaps public or capture data"
                )
        self._parent_identity = _validate_directory_identity(
            expected_parent_identity,
            label="expected terminal receipt parent identity",
        )
        self._maximum_bytes = _require_positive_byte_limit(
            maximum_bytes,
            label="terminal receipt maximum bytes",
        )
        self._parent_fd = _open_authorized_private_directory(
            path.parent,
            expected_identity=self._parent_identity,
            label="terminal receipt parent",
        )

    def _require_parent_identity(self) -> None:
        if self._parent_fd < 0:
            raise SuccessorUpdateContractError("terminal receipt parent descriptor is closed")
        named = os.fstat(self._parent_fd)
        if (
            not stat.S_ISDIR(named.st_mode)
            or named.st_uid != os.geteuid()
            or stat.S_IMODE(named.st_mode) != 0o700
            or (named.st_dev, named.st_ino) != self._parent_identity
        ):
            raise SuccessorUpdateContractError("terminal receipt parent identity changed")

    def close(self) -> None:
        descriptor = getattr(self, "_parent_fd", -1)
        if descriptor >= 0:
            self._parent_fd = -1
            os.close(descriptor)

    def __del__(self) -> None:  # pragma: no cover - explicit owner lifetime is preferred.
        with suppress(Exception):
            self.close()

    def _open_lock(self) -> int:
        self._require_parent_identity()
        created = False
        try:
            fd = os.open(
                self._lock_name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                0o600,
                dir_fd=self._parent_fd,
            )
            created = True
        except FileExistsError:
            fd = os.open(
                self._lock_name,
                os.O_RDWR | _NOFOLLOW | _CLOEXEC,
                dir_fd=self._parent_fd,
            )
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise SuccessorUpdateContractError("terminal receipt lock is not regular")
        if created:
            os.fchmod(fd, 0o600)
            os.fsync(self._parent_fd)
        self._require_lock_identity(fd)
        return fd

    def _require_lock_identity(self, fd: int) -> None:
        opened = os.fstat(fd)
        named = os.stat(
            self._lock_name,
            dir_fd=self._parent_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) & 0o077
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1
            or named.st_nlink != 1
        ):
            raise SuccessorUpdateContractError("terminal receipt lock identity changed")
        self._require_parent_identity()

    def _verify_published(
        self,
        encoded: bytes,
        *,
        expected_identity: tuple[int, int],
    ) -> None:
        fd = os.open(
            self._name,
            os.O_RDONLY | _NOFOLLOW | _NONBLOCK | _CLOEXEC,
            dir_fd=self._parent_fd,
        )
        try:
            before = os.fstat(fd)
            named = os.stat(
                self._name,
                dir_fd=self._parent_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_IMODE(before.st_mode) & 0o077
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or named.st_nlink != 1
                or (before.st_dev, before.st_ino) != expected_identity
                or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
                or before.st_size != len(encoded)
            ):
                raise SuccessorUpdateContractError("terminal receipt publication identity changed")
            observed = b""
            while len(observed) < before.st_size:
                chunk = os.read(fd, before.st_size - len(observed))
                if not chunk:
                    break
                observed += chunk
            after = os.fstat(fd)
            if observed != encoded or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise SuccessorUpdateContractError("terminal receipt publication bytes changed")
        finally:
            os.close(fd)
        self._require_parent_identity()

    def write(self, receipt: ExactPlanRuntimeTerminalReceipt) -> None:
        encoded = receipt.canonical_bytes
        if len(encoded) > self._maximum_bytes:
            raise SuccessorUpdateContractError("terminal receipt exceeds its maximum size")
        with self._thread_lock:
            lock_fd = self._open_lock()
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                self._require_lock_identity(lock_fd)
                temp_name = f".{self._name}.{uuid.uuid4().hex}.tmp"
                temp_fd = os.open(
                    temp_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC,
                    0o600,
                    dir_fd=self._parent_fd,
                )
                try:
                    os.fchmod(temp_fd, 0o600)
                    written = 0
                    while written < len(encoded):
                        count = os.write(temp_fd, encoded[written:])
                        if count <= 0:
                            raise OSError("terminal receipt write made no progress")
                        written += count
                    os.fsync(temp_fd)
                    published_identity = os.fstat(temp_fd).st_dev, os.fstat(temp_fd).st_ino
                    os.replace(
                        temp_name,
                        self._name,
                        src_dir_fd=self._parent_fd,
                        dst_dir_fd=self._parent_fd,
                    )
                    os.fsync(self._parent_fd)
                    self._verify_published(
                        encoded,
                        expected_identity=published_identity,
                    )
                    self._require_lock_identity(lock_fd)
                finally:
                    os.close(temp_fd)
                    with suppress(FileNotFoundError):
                        os.unlink(temp_name, dir_fd=self._parent_fd)
            finally:
                os.close(lock_fd)

    def load(self) -> ExactPlanRuntimeTerminalReceipt:
        with self._thread_lock:
            lock_fd = self._open_lock()
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                self._require_lock_identity(lock_fd)
                fd = os.open(
                    self._name,
                    os.O_RDONLY | _NOFOLLOW | _NONBLOCK | _CLOEXEC,
                    dir_fd=self._parent_fd,
                )
                try:
                    before = os.fstat(fd)
                    named = os.stat(
                        self._name,
                        dir_fd=self._parent_fd,
                        follow_symlinks=False,
                    )
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or stat.S_IMODE(before.st_mode) & 0o077
                        or before.st_uid != os.geteuid()
                        or before.st_nlink != 1
                        or named.st_nlink != 1
                        or (before.st_dev, before.st_ino) != (named.st_dev, named.st_ino)
                        or before.st_size > self._maximum_bytes
                    ):
                        raise SuccessorUpdateContractError(
                            "terminal receipt descriptor authority is invalid"
                        )
                    encoded = b""
                    while len(encoded) < before.st_size:
                        chunk = os.read(fd, before.st_size - len(encoded))
                        if not chunk:
                            break
                        encoded += chunk
                    after = os.fstat(fd)
                    named_after = os.stat(
                        self._name,
                        dir_fd=self._parent_fd,
                        follow_symlinks=False,
                    )
                    if (
                        len(encoded) != before.st_size
                        or (
                            before.st_dev,
                            before.st_ino,
                            before.st_size,
                            before.st_mtime_ns,
                            before.st_ctime_ns,
                        )
                        != (
                            after.st_dev,
                            after.st_ino,
                            after.st_size,
                            after.st_mtime_ns,
                            after.st_ctime_ns,
                        )
                        or (after.st_dev, after.st_ino) != (named_after.st_dev, named_after.st_ino)
                    ):
                        raise SuccessorUpdateContractError("terminal receipt changed during read")
                    self._require_lock_identity(lock_fd)
                finally:
                    os.close(fd)
            finally:
                os.close(lock_fd)
        return ExactPlanRuntimeTerminalReceipt.from_canonical_bytes(encoded)


class ExactPlanSuccessorRuntime:
    def __init__(
        self,
        *,
        transaction: SuccessorUpdateTransaction,
        execution_plan: SuccessorExecutionPlan,
        candidate_root: Path,
        candidate_public_root: Path,
        expected_candidate_root_identity: tuple[int, int],
        expected_candidate_public_identity: tuple[int, int],
        candidate_max_bytes: int,
        registry: EndpointRegistry,
        registry_authority: EndpointRegistryAuthority,
        transform_scratch_parent: Path,
        expected_transform_scratch_identity: tuple[int, int],
        transform_scratch_max_bytes: int,
        settings: NbaDbSettings,
        capture_session: PrivateCaptureSession,
        capture_scope: CaptureRunScope,
        terminal_store: ExactPlanRuntimeTerminalReceiptStore,
        estimated_checkpoint_bytes: int,
        monotonic_deadline_seconds: float,
        monotonic_clock: Callable[[], float],
        private_root_authority: Callable[[], None] | None = None,
        preloaded_journal_attestations: tuple[Any, ...] = (),
    ) -> None:
        self._transaction = transaction
        self._plan = execution_plan
        self._candidate_root = candidate_root
        self._public_root = candidate_public_root
        self._candidate_root_identity = _validate_directory_identity(
            expected_candidate_root_identity,
            label="expected candidate root identity",
        )
        self._candidate_public_identity = _validate_directory_identity(
            expected_candidate_public_identity,
            label="expected candidate public identity",
        )
        self._candidate_max_bytes = _require_positive_byte_limit(
            candidate_max_bytes,
            label="candidate maximum bytes",
        )
        if not isinstance(registry, EndpointRegistry) or not isinstance(
            registry_authority, EndpointRegistryAuthority
        ):
            raise SuccessorUpdateContractError("successor endpoint registry authority is invalid")
        try:
            registry_authority.require_current(registry)
        except EndpointRegistryAuthorityError as exc:
            raise SuccessorUpdateContractError(
                "successor endpoint registry authority differs"
            ) from exc
        if (
            not isinstance(transform_scratch_parent, Path)
            or not transform_scratch_parent.is_absolute()
            or transform_scratch_parent.resolve(strict=False) != transform_scratch_parent
        ):
            raise SuccessorUpdateContractError(
                "transform scratch parent must be an exact absolute Path"
            )
        self._registry = registry
        self._registry_authority = registry_authority
        self._transform_scratch_parent = transform_scratch_parent
        self._expected_transform_scratch_identity = _validate_directory_identity(
            expected_transform_scratch_identity,
            label="expected transform scratch identity",
        )
        self._transform_scratch_max_bytes = _require_positive_byte_limit(
            transform_scratch_max_bytes,
            label="transform scratch maximum bytes",
        )
        self._settings = settings
        self._capture_session = capture_session
        self._capture_scope = capture_scope
        self._terminal_store = terminal_store
        self._estimated_checkpoint_bytes = estimated_checkpoint_bytes
        self._monotonic_deadline_seconds = monotonic_deadline_seconds
        self._monotonic_clock = monotonic_clock
        self._private_root_authority = private_root_authority
        self._preloaded_journal_attestations = tuple(preloaded_journal_attestations)
        self._restored_delta_receipts: tuple[ObservedDeltaReceipt, ...] = ()
        self._capture_identity: PrivateGenerationIdentity | None = None
        self._successor_delta_receipts: tuple[ObservedDeltaReceipt, ...] = ()
        self._transform_output_attestations: tuple[TransformOutputAttestation, ...] = ()

    @property
    def capture_identity(self) -> PrivateGenerationIdentity | None:
        return self._capture_identity

    @property
    def successor_delta_receipts(self) -> tuple[ObservedDeltaReceipt, ...]:
        return self._successor_delta_receipts

    @property
    def transform_output_attestations(self) -> tuple[TransformOutputAttestation, ...]:
        return self._transform_output_attestations

    @property
    def planned_route_replacement_bindings_sha256(self) -> str:
        return self._plan.planned_route_replacement_bindings_sha256

    async def run_daily(self) -> PipelineResult:
        return await self._run(SuccessorUpdateMode.DAILY)

    async def run_monthly(self) -> PipelineResult:
        return await self._run(SuccessorUpdateMode.MONTHLY)

    async def _run(self, expected_mode: SuccessorUpdateMode) -> PipelineResult:
        self._require_runtime_authorities_current()
        self._measure_candidate_public()
        if self._transaction.intent.mode is not expected_mode:
            raise SuccessorUpdateContractError("runtime method differs from successor update mode")
        _validate_runtime_authority(
            self._transaction,
            self._plan,
            self._capture_scope,
        )
        validate_successor_runtime_plan(self._transaction, self._plan)
        self._require_runtime_authorities_current()
        sealed = self._capture_session.restore_sealed_identity_if_present()
        if sealed is not None:
            try:
                return self._restore_sealed(sealed)
            except BaseException:
                self._capture_session.close()
                raise
        return await self._run_unsealed()

    async def _run_unsealed(self) -> PipelineResult:
        self._require_runtime_authorities_current()
        terminal = self._load_optional_terminal()
        if terminal is not None:
            try:
                return self._restore_unsealed_from_terminal(terminal)
            except BaseException:
                self._capture_session.close()
                raise
        self._restore_unsealed_same_generation_progress()
        self._require_runtime_authorities_current()
        orchestrator = Orchestrator(
            settings=self._settings,
            capture_session=self._capture_session,
            successor_transaction=self._transaction,
            successor_registry=self._registry,
            successor_registry_authority=self._registry_authority,
            successor_transform_scratch_parent=self._transform_scratch_parent,
            expected_successor_transform_scratch_identity=(
                self._expected_transform_scratch_identity
            ),
            successor_transform_scratch_max_bytes=self._transform_scratch_max_bytes,
        )
        try:
            self._require_runtime_authorities_current()
            outcome = await orchestrator.execute_successor_plan(self._plan)
            self._require_runtime_authorities_current()
            self._require_candidate_public_publication_formats()
            installed = self._measure_candidate_public().installed_public_tree_sha256
            terminal = ExactPlanRuntimeTerminalReceipt.build(
                transaction=self._transaction,
                execution_plan=self._plan,
                capture_scope=self._capture_scope,
                outcome=outcome,
                installed_public_tree_sha256=installed,
            )
            self._require_runtime_authorities_current()
            self._terminal_store.write(terminal)
            self._require_runtime_authorities_current()
            identity = orchestrator.seal_successor_capture()
            _reconcile_private_identity(
                identity,
                transaction=self._transaction,
                capture_scope=self._capture_scope,
                terminal=terminal,
            )
            self._capture_identity = identity
            self._successor_delta_receipts = terminal.delta_receipts
            self._transform_output_attestations = terminal.transform_output_attestations
            return terminal.pipeline_result.to_pipeline_result()
        except BaseException:
            orchestrator.close()
            raise

    def _require_private_roots_current(self) -> None:
        if self._private_root_authority is not None:
            self._private_root_authority()

    def _require_runtime_authorities_current(self) -> None:
        self._require_private_roots_current()
        try:
            self._registry_authority.require_current(self._registry)
        except EndpointRegistryAuthorityError as exc:
            raise SuccessorUpdateContractError(
                "successor endpoint registry authority differs"
            ) from exc
        _require_candidate_directory_authority(
            self._candidate_root,
            expected_candidate_identity=self._candidate_root_identity,
            expected_public_identity=self._candidate_public_identity,
        )

    def _require_candidate_public_publication_formats(self) -> None:
        """Require DuckDB, SQLite, CSV, and Parquet under the candidate public root."""

        from nbadb.orchestrate.successor_publication_inventory import (
            require_successor_publication_formats,
        )

        self._require_runtime_authorities_current()
        try:
            require_successor_publication_formats(self._public_root)
        except ValueError as exc:
            raise SuccessorUpdateContractError(
                "candidate public tree is missing required publication formats"
            ) from exc
        self._require_runtime_authorities_current()

    def _measure_candidate_public(self) -> InstalledPublicTreeInventory:
        self._require_runtime_authorities_current()
        try:
            inventory = measure_installed_public_tree(
                self._public_root,
                expected_root_identity=self._candidate_public_identity,
            )
        except (OSError, ValueError) as exc:
            raise SuccessorUpdateContractError(
                "candidate public tree cannot be measured under its admitted authority"
            ) from exc
        if inventory.byte_count > self._candidate_max_bytes:
            raise SuccessorUpdateContractError("candidate public tree exceeds its maximum size")
        self._require_runtime_authorities_current()
        return inventory

    def _capture_session_already_admitted(self) -> bool:
        return getattr(self._capture_session, "state", None) is CaptureSessionState.ADMITTED

    def _load_optional_terminal(self) -> ExactPlanRuntimeTerminalReceipt | None:
        try:
            return self._terminal_store.load()
        except FileNotFoundError:
            return None

    def _require_terminal_matches_runtime(
        self,
        terminal: ExactPlanRuntimeTerminalReceipt,
    ) -> None:
        _validate_receipts_against_transaction(self._transaction, terminal.delta_receipts)
        mismatches: list[str] = []
        if (
            terminal.generation_identity_sha256 != self._transaction.generation_identity_sha256
            or terminal.transaction_content_sha256 != self._transaction.content_sha256
            or terminal.update_intent_sha256 != self._transaction.intent.identity_sha256
        ):
            mismatches.append("transaction")
        if (
            terminal.successor_execution_plan_sha256 != self._plan.identity_sha256
            or terminal.planning_generation_manifest_sha256
            != self._transaction.intent.planning_generation_manifest_sha256
            or terminal.planned_route_replacement_bindings_sha256
            != self._plan.planned_route_replacement_bindings_sha256
            or terminal.planned_route_replacement_bindings_sha256
            != self._transaction.intent.planned_route_replacement_bindings_sha256
        ):
            mismatches.append("plan")
        if (
            terminal.provider_authority_sha256
            != self._transaction.baseline.provider_authority_sha256
            or terminal.capture_scope_identity_sha256 != self._capture_scope.identity_sha256
        ):
            mismatches.append("provider_or_scope")
        if mismatches:
            raise SuccessorUpdateContractError(
                "sealed successor runtime recovery does not reconcile: " + ", ".join(mismatches)
            )
        current_public_tree_sha256 = self._measure_candidate_public().installed_public_tree_sha256
        expected_public_tree_sha256 = terminal.installed_public_tree_sha256
        current_stable_identity: str | None = None
        expected_stable_identity: str | None = None
        if current_public_tree_sha256 != expected_public_tree_sha256:
            try:
                expected_stable_identity = _stable_non_live_identity(
                    terminal.transform_output_attestations
                )
                current_stable_identity = _measure_public_stable_non_live_identity(
                    self._public_root / "nba.duckdb",
                    scratch_parent=self._transform_scratch_parent,
                    expected_scratch_identity=self._expected_transform_scratch_identity,
                    transform_scratch_max_bytes=self._transform_scratch_max_bytes,
                )
            except Exception:
                current_stable_identity = None
        _reject_unclassified_public_drift(
            current_public_tree_sha256=current_public_tree_sha256,
            expected_public_tree_sha256=expected_public_tree_sha256,
            current_stable_identity=current_stable_identity,
            expected_stable_identity=expected_stable_identity,
        )

    def _prepare_same_generation_unsealed_session(self) -> None:
        """Admit a factory-reopened CREATED session without widening the generation."""

        self._require_runtime_authorities_current()
        if self._capture_scope.lane_id != self._transaction.generation_identity_sha256:
            raise SuccessorUpdateContractError(
                "unsealed successor resume capture is not the same generation"
            )
        state = getattr(self._capture_session, "state", None)
        if state is CaptureSessionState.ADMITTED:
            return
        if state in {
            CaptureSessionState.SEALED,
            CaptureSessionState.INCOMPLETE,
        }:
            raise SuccessorUpdateContractError(
                "unsealed successor resume requires the created or admitted same-generation capture"
            )
        self._capture_session.admit(
            estimated_checkpoint_bytes=self._estimated_checkpoint_bytes,
            monotonic_now_seconds=self._monotonic_clock(),
            monotonic_deadline_seconds=self._monotonic_deadline_seconds,
        )

    def restore_same_generation_execution(self) -> None:
        """Restore journal/capture/candidate state without restarting execution."""

        self._require_runtime_authorities_current()
        self._measure_candidate_public()
        if self._transaction.intent.mode not in {
            SuccessorUpdateMode.DAILY,
            SuccessorUpdateMode.MONTHLY,
        }:
            raise SuccessorUpdateContractError("runtime method differs from successor update mode")
        _validate_runtime_authority(
            self._transaction,
            self._plan,
            self._capture_scope,
        )
        validate_successor_runtime_plan(self._transaction, self._plan)
        self._require_runtime_authorities_current()
        sealed = self._capture_session.restore_sealed_identity_if_present()
        if sealed is not None:
            try:
                self._restore_sealed(sealed)
                return
            except BaseException:
                self._capture_session.close()
                raise
        terminal = self._load_optional_terminal()
        if terminal is not None:
            try:
                self._restore_unsealed_from_terminal(terminal)
                return
            except BaseException:
                self._capture_session.close()
                raise
        try:
            self._restore_unsealed_same_generation_progress()
        except BaseException:
            self._capture_session.close()
            raise
        receipts = self._restored_delta_receipts
        expected = {dispatch.identity_sha256 for dispatch in self._plan.dispatches}
        observed = {receipt.execution_dispatch_identity_sha256 for receipt in receipts}
        if not receipts or observed != expected:
            raise SuccessorUpdateContractError(
                "executed resume has no journal, capture, or terminal restoration authority"
            )
        raise SuccessorUpdateContractError(
            "executed resume did not restore sealed capture authority"
        )

    def _inventory_unsealed_bronze_contexts(self) -> tuple[Any, ...]:
        inventory = getattr(self._capture_session, "inventory_unsealed_contexts", None)
        if not callable(inventory):
            raise SuccessorUpdateContractError(
                "factory-reopened capture cannot inventory unsealed Bronze contexts"
            )
        return tuple(inventory())

    def _reopen_generation_journal_attestations(self) -> tuple[Any, ...]:
        if self._preloaded_journal_attestations:
            return self._preloaded_journal_attestations
        return reopen_same_generation_journal_attestations(
            self._public_root / "nba.duckdb",
            generation_identity_sha256=self._transaction.generation_identity_sha256,
        )

    def _restore_unsealed_same_generation_progress(self) -> None:
        """Adopt existing writer progress and restore journal/Bronze receipts."""

        self._require_runtime_authorities_current()
        if self._capture_scope.lane_id != self._transaction.generation_identity_sha256:
            raise SuccessorUpdateContractError(
                "unsealed successor resume capture is not the same generation"
            )
        contexts = self._inventory_unsealed_bronze_contexts()
        attestations = self._reopen_generation_journal_attestations()
        has_progress = bool(contexts) or bool(attestations)
        state = getattr(self._capture_session, "state", None)
        if state is CaptureSessionState.ADMITTED:
            pass
        elif state is CaptureSessionState.CREATED:
            if has_progress:
                adopter = getattr(
                    self._capture_session,
                    "adopt_unsealed_same_generation_writer",
                    None,
                )
                if not callable(adopter):
                    raise SuccessorUpdateContractError(
                        "factory-reopened CREATED capture cannot adopt the unsealed writer"
                    )
                adopter()
            else:
                self._capture_session.admit(
                    estimated_checkpoint_bytes=self._estimated_checkpoint_bytes,
                    monotonic_now_seconds=self._monotonic_clock(),
                    monotonic_deadline_seconds=self._monotonic_deadline_seconds,
                )
        elif state in {
            CaptureSessionState.SEALED,
            CaptureSessionState.INCOMPLETE,
        }:
            raise SuccessorUpdateContractError(
                "unsealed successor resume requires the created or admitted same-generation capture"
            )
        else:
            raise SuccessorUpdateContractError(
                "unsealed successor resume requires the created or admitted same-generation capture"
            )
        if not self._capture_session_already_admitted():
            raise SuccessorUpdateContractError(
                "unsealed successor resume requires the admitted same-generation capture"
            )
        if not attestations:
            self._restored_delta_receipts = ()
            self._require_runtime_authorities_current()
            return
        restored = restore_same_generation_replacements(
            transaction=self._transaction,
            execution_plan=self._plan,
            capture_session=self._capture_session,
            attestations=attestations,
        )
        self._restored_delta_receipts = restored.receipts
        self._require_runtime_authorities_current()

    def _restore_unsealed_from_terminal(
        self,
        terminal: ExactPlanRuntimeTerminalReceipt,
    ) -> PipelineResult:
        self._require_runtime_authorities_current()
        self._require_terminal_matches_runtime(terminal)
        if self._capture_scope.lane_id != self._transaction.generation_identity_sha256:
            raise SuccessorUpdateContractError(
                "unsealed successor resume capture is not the same generation"
            )
        state = getattr(self._capture_session, "state", None)
        if state is CaptureSessionState.CREATED:
            adopter = getattr(
                self._capture_session,
                "adopt_unsealed_same_generation_writer",
                None,
            )
            if not callable(adopter):
                raise SuccessorUpdateContractError(
                    "factory-reopened CREATED capture cannot adopt the unsealed writer"
                )
            adopter()
        if not self._capture_session_already_admitted():
            raise SuccessorUpdateContractError(
                "unsealed terminal restore requires the admitted same-generation capture"
            )
        bindings = _logical_call_bindings(self._transaction, terminal.delta_receipts)
        self._capture_session.restore_completed_bindings(bindings)
        identity = self._capture_session.seal()
        if not isinstance(identity, PrivateGenerationIdentity):
            raise SuccessorUpdateContractError(
                "unsealed terminal restore did not seal the same-generation capture"
            )
        self._require_runtime_authorities_current()
        _reconcile_private_identity(
            identity,
            transaction=self._transaction,
            capture_scope=self._capture_scope,
            terminal=terminal,
        )
        self._require_runtime_authorities_current()
        closed = self._capture_session.close()
        if closed is not identity:
            raise SuccessorUpdateContractError("unsealed capture identity changed during close")
        self._capture_identity = identity
        self._successor_delta_receipts = terminal.delta_receipts
        self._transform_output_attestations = terminal.transform_output_attestations
        return terminal.pipeline_result.to_pipeline_result()

    def _restore_sealed(self, identity: PrivateGenerationIdentity) -> PipelineResult:
        self._require_runtime_authorities_current()
        terminal = self._terminal_store.load()
        self._require_terminal_matches_runtime(terminal)
        self._require_runtime_authorities_current()
        _reconcile_private_identity(
            identity,
            transaction=self._transaction,
            capture_scope=self._capture_scope,
            terminal=terminal,
        )
        self._require_runtime_authorities_current()
        closed = self._capture_session.close()
        if closed is not identity:
            raise SuccessorUpdateContractError("sealed capture identity changed during close")
        self._capture_identity = identity
        self._successor_delta_receipts = terminal.delta_receipts
        self._transform_output_attestations = terminal.transform_output_attestations
        return terminal.pipeline_result.to_pipeline_result()


class ExactPlanSuccessorRuntimeFactory:
    """Build a generation-bound runtime from a source/run capture-scope template.

    The template's lane is intentionally not authority.  Each call derives the
    capture lane from the candidate generation identity after planning has
    finalized the transaction.
    """

    def __init__(
        self,
        *,
        base_settings: NbaDbSettings,
        capture_scope_template: CaptureRunScope,
        capture_limits: BronzeLimits,
        capture_base_root: Path,
        expected_capture_base_identity: tuple[int, int],
        terminal_receipt_base_root: Path,
        expected_terminal_receipt_base_identity: tuple[int, int],
        log_dir: Path,
        expected_log_root_identity: tuple[int, int],
        registry: EndpointRegistry,
        registry_authority: EndpointRegistryAuthority,
        transform_scratch_parent: Path,
        expected_transform_scratch_identity: tuple[int, int],
        transform_scratch_max_bytes: int,
        terminal_receipt_max_bytes: int,
        runtime_log_max_bytes: int,
        candidate_max_bytes: int,
        estimated_checkpoint_bytes: int,
        monotonic_deadline_seconds: float,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        from nbadb.core.config import NbaDbSettings
        from nbadb.extract.bronze import BronzeLimits

        if not isinstance(base_settings, NbaDbSettings):
            raise TypeError("base_settings must be NbaDbSettings")
        if not isinstance(capture_scope_template, CaptureRunScope):
            raise TypeError("capture_scope_template must be CaptureRunScope")
        if not isinstance(capture_limits, BronzeLimits):
            raise TypeError("capture_limits must be BronzeLimits")
        if not all(
            isinstance(path, Path) and path.is_absolute()
            for path in (
                capture_base_root,
                terminal_receipt_base_root,
                log_dir,
                transform_scratch_parent,
            )
        ):
            raise SuccessorUpdateContractError("runtime private and log paths must be absolute")
        if any(
            path.resolve(strict=False) != path
            for path in (
                capture_base_root,
                terminal_receipt_base_root,
                log_dir,
                transform_scratch_parent,
            )
        ):
            raise SuccessorUpdateContractError(
                "runtime private and log paths must not contain aliases or symlink ancestors"
            )
        private_paths = (
            capture_base_root,
            terminal_receipt_base_root,
            log_dir,
            transform_scratch_parent,
        )
        if any(
            _paths_overlap(first, second)
            for index, first in enumerate(private_paths)
            for second in private_paths[index + 1 :]
        ):
            raise SuccessorUpdateContractError(
                "runtime capture, terminal receipt, and log paths must be disjoint"
            )
        private_root_authorities = (
            (
                capture_base_root,
                _validate_directory_identity(
                    expected_capture_base_identity,
                    label="expected capture base identity",
                ),
                "runtime capture base",
            ),
            (
                terminal_receipt_base_root,
                _validate_directory_identity(
                    expected_terminal_receipt_base_identity,
                    label="expected terminal receipt base identity",
                ),
                "runtime terminal receipt base",
            ),
            (
                log_dir,
                _validate_directory_identity(
                    expected_log_root_identity,
                    label="expected log root identity",
                ),
                "runtime log root",
            ),
            (
                transform_scratch_parent,
                _validate_directory_identity(
                    expected_transform_scratch_identity,
                    label="expected transform scratch identity",
                ),
                "runtime transform scratch root",
            ),
        )
        if not isinstance(registry, EndpointRegistry) or not isinstance(
            registry_authority, EndpointRegistryAuthority
        ):
            raise SuccessorUpdateContractError("runtime endpoint registry authority is invalid")
        try:
            registry_authority.require_current(registry)
        except EndpointRegistryAuthorityError as exc:
            raise SuccessorUpdateContractError(
                "runtime endpoint registry authority differs"
            ) from exc
        if (
            not callable(monotonic_clock)
            or type(terminal_receipt_max_bytes) is not int
            or terminal_receipt_max_bytes <= 0
            or terminal_receipt_max_bytes > _SIGNED_63_MAX
            or type(runtime_log_max_bytes) is not int
            or runtime_log_max_bytes <= 0
            or runtime_log_max_bytes > _SIGNED_63_MAX
            or type(candidate_max_bytes) is not int
            or candidate_max_bytes <= 0
            or candidate_max_bytes > _SIGNED_63_MAX
            or type(transform_scratch_max_bytes) is not int
            or transform_scratch_max_bytes <= 0
            or transform_scratch_max_bytes > _SIGNED_63_MAX
            or type(estimated_checkpoint_bytes) is not int
            or estimated_checkpoint_bytes <= 0
            or not isinstance(monotonic_deadline_seconds, int | float)
            or isinstance(monotonic_deadline_seconds, bool)
            or not math.isfinite(monotonic_deadline_seconds)
            or monotonic_deadline_seconds <= 0
        ):
            raise SuccessorUpdateContractError("runtime admission authority is invalid")
        self._base_settings = base_settings
        self._capture_scope_template = capture_scope_template
        self._capture_limits = capture_limits
        self._capture_base_root = capture_base_root
        self._terminal_base_root = terminal_receipt_base_root
        self._log_dir = log_dir
        self._registry = registry
        self._registry_authority = registry_authority
        self._transform_scratch_parent = transform_scratch_parent
        self._transform_scratch_max_bytes = transform_scratch_max_bytes
        self._private_root_authorities = private_root_authorities
        self._terminal_receipt_max_bytes = terminal_receipt_max_bytes
        self._runtime_log_max_bytes = runtime_log_max_bytes
        self._candidate_max_bytes = candidate_max_bytes
        self._estimated_checkpoint_bytes = estimated_checkpoint_bytes
        self._deadline = monotonic_deadline_seconds
        self._clock = monotonic_clock
        self._require_private_roots_current()

    def _require_private_roots_current(self) -> None:
        for index, (path, identity, label) in enumerate(self._private_root_authorities):
            descriptor = _open_authorized_private_directory(
                path,
                expected_identity=identity,
                label=label,
            )
            try:
                if index == 2:
                    _measure_authorized_private_directory_bytes(
                        descriptor,
                        maximum_bytes=self._runtime_log_max_bytes,
                        label="runtime log root",
                    )
            finally:
                os.close(descriptor)

    def __call__(
        self,
        transaction: SuccessorUpdateTransaction,
        candidate_root: Path,
        execution_plan: SuccessorExecutionPlan,
    ) -> ExactPlanSuccessorRuntime:
        from nbadb.core.config import NbaDbSettings

        candidate_identity, public_identity = _require_candidate_directory_authority(candidate_root)
        public_root = candidate_root / "public"
        try:
            candidate_inventory = measure_installed_public_tree(
                public_root,
                expected_root_identity=public_identity,
            )
        except (OSError, ValueError) as exc:
            raise SuccessorUpdateContractError(
                "candidate public tree cannot be measured under its admitted authority"
            ) from exc
        if candidate_inventory.byte_count > self._candidate_max_bytes:
            raise SuccessorUpdateContractError("candidate public tree exceeds its maximum size")
        _require_candidate_directory_authority(
            candidate_root,
            expected_candidate_identity=candidate_identity,
            expected_public_identity=public_identity,
        )
        capture_scope = CaptureRunScope(
            semantic_source_sha=self._capture_scope_template.semantic_source_sha,
            chain_id=self._capture_scope_template.chain_id,
            lane_id=transaction.generation_identity_sha256,
            workflow_run_id=self._capture_scope_template.workflow_run_id,
            workflow_run_attempt=self._capture_scope_template.workflow_run_attempt,
        )
        self._require_private_roots_current()
        _validate_runtime_authority(transaction, execution_plan, capture_scope)
        validate_successor_runtime_plan(transaction, execution_plan)
        try:
            for endpoint_name in sorted(
                {dispatch.endpoint_name for dispatch in execution_plan.dispatches}
            ):
                self._registry_authority.require_current(
                    self._registry,
                    required_endpoint_name=endpoint_name,
                )
        except EndpointRegistryAuthorityError as exc:
            raise SuccessorUpdateContractError(
                "runtime execution endpoint is absent from registry authority"
            ) from exc
        self._require_private_roots_current()
        generation_id = transaction.generation_identity_sha256
        capture_root = self._capture_base_root / generation_id
        terminal_path = self._terminal_base_root / f"{generation_id}.json"
        scoped_paths = (
            public_root,
            capture_root,
            terminal_path,
            self._log_dir,
            self._transform_scratch_parent,
        )
        if any(
            _paths_overlap(first, second)
            for index, first in enumerate(scoped_paths)
            for second in scoped_paths[index + 1 :]
        ):
            raise SuccessorUpdateContractError(
                "runtime public, capture, terminal receipt, log, and scratch paths must be disjoint"
            )
        settings_payload = self._base_settings.model_dump()
        settings_payload.update(
            {
                "data_dir": public_root,
                "duckdb_path": public_root / "nba.duckdb",
                "sqlite_path": public_root / "nba.sqlite",
                "log_dir": self._log_dir,
                "formats": ["sqlite", "duckdb", "csv", "parquet"],
            }
        )
        settings = NbaDbSettings.model_validate(settings_payload)
        self._require_private_roots_current()
        store = ExactPlanRuntimeTerminalReceiptStore(
            terminal_path,
            forbidden_roots=(public_root, capture_root, self._log_dir),
            expected_parent_identity=self._private_root_authorities[1][1],
            maximum_bytes=self._terminal_receipt_max_bytes,
        )
        session: PrivateCaptureSession | None = None
        try:
            self._require_private_roots_current()
            session = PrivateCaptureSession.create_under_authorized_base(
                self._capture_base_root,
                generation_id,
                expected_base_identity=self._private_root_authorities[0][1],
                limits=self._capture_limits,
                public_roots=(public_root,),
                scope=capture_scope,
            )
            journal_attestations = reopen_same_generation_journal_attestations(
                public_root / "nba.duckdb",
                generation_identity_sha256=generation_id,
            )
        except BaseException:
            store.close()
            if session is not None:
                session.close()
            raise
        return ExactPlanSuccessorRuntime(
            transaction=transaction,
            execution_plan=execution_plan,
            candidate_root=candidate_root,
            candidate_public_root=public_root,
            expected_candidate_root_identity=candidate_identity,
            expected_candidate_public_identity=public_identity,
            candidate_max_bytes=self._candidate_max_bytes,
            registry=self._registry,
            registry_authority=self._registry_authority,
            transform_scratch_parent=self._transform_scratch_parent,
            expected_transform_scratch_identity=self._private_root_authorities[3][1],
            transform_scratch_max_bytes=self._transform_scratch_max_bytes,
            settings=settings,
            capture_session=session,
            capture_scope=capture_scope,
            terminal_store=store,
            estimated_checkpoint_bytes=self._estimated_checkpoint_bytes,
            monotonic_deadline_seconds=self._deadline,
            monotonic_clock=self._clock,
            private_root_authority=self._require_private_roots_current,
            preloaded_journal_attestations=journal_attestations,
        )
