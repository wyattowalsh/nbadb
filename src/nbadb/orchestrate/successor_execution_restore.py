"""Same-generation journal/Bronze/private-root restoration substrate.

This module reconstructs dispatch-member progress from an already reopened
candidate DuckDB journal and admitted private capture session.  It does not
create those authorities; the coordinator/runtime factory must reopen the
exact candidate root, runtime journal, and capture generation first.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate.staging_batches import SourceScopeReplacementAttestation
from nbadb.orchestrate.successor_update_contract import (
    DeltaDisposition,
    ObservedDeltaReceipt,
    RequestedRouteScope,
    SuccessorUpdateContractError,
    SuccessorUpdateTransaction,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nbadb.orchestrate.capture_session import PrivateCaptureSession
    from nbadb.orchestrate.successor_execution_plan import (
        SealedUpdateExecutionDispatch,
        SuccessorExecutionPlan,
    )

__all__ = [
    "SameGenerationExecutionRestore",
    "logical_bindings_from_replacement_attestations",
    "reopen_same_generation_journal_attestations",
    "restore_same_generation_replacements",
    "successor_receipts_from_replacement_attestations",
]

_DUCKDB_MAGIC = b"DUCK"


@dataclass(frozen=True, slots=True)
class SameGenerationExecutionRestore:
    """Exact partial execution authority recovered from journal plus Bronze."""

    attestations: tuple[SourceScopeReplacementAttestation, ...]
    bindings: tuple[LogicalCallReceiptBinding, ...]
    receipts: tuple[ObservedDeltaReceipt, ...]
    completed_dispatch_identity_sha256s: tuple[str, ...]


def logical_bindings_from_replacement_attestations(
    attestations: Sequence[SourceScopeReplacementAttestation],
) -> tuple[LogicalCallReceiptBinding, ...]:
    """Group generation-scoped route attestations into Bronze-v6 logical roots."""

    grouped: dict[str, list[SourceScopeReplacementAttestation]] = {}
    for attestation in attestations:
        if not isinstance(attestation, SourceScopeReplacementAttestation):
            raise SuccessorUpdateContractError(
                "durable successor replacements do not form exact logical calls"
            )
        grouped.setdefault(attestation.logical_call_receipt_sha256, []).append(attestation)
    bindings: list[LogicalCallReceiptBinding] = []
    for root, logical_attestations in sorted(grouped.items()):
        endpoints = {item.result_route_id.rsplit(":", 2)[0] for item in logical_attestations}
        parameters = {item.logical_parameters_sha256 for item in logical_attestations}
        providers = {item.provider_authority_sha256 for item in logical_attestations}
        routes = tuple(sorted(item.result_route_id for item in logical_attestations))
        if (
            len(endpoints) != 1
            or len(parameters) != 1
            or len(providers) != 1
            or len(routes) != len(set(routes))
        ):
            raise SuccessorUpdateContractError(
                "durable successor replacements do not form exact logical calls"
            )
        bindings.append(
            LogicalCallReceiptBinding(
                logical_call_receipt_sha256=root,
                endpoint_name=next(iter(endpoints)),
                logical_parameters_sha256=next(iter(parameters)),
                provider_authority_sha256=next(iter(providers)),
                result_route_ids=routes,
            )
        )
    return tuple(bindings)


def successor_receipts_from_replacement_attestations(
    *,
    transaction: SuccessorUpdateTransaction,
    execution_plan: SuccessorExecutionPlan,
    attestations: Sequence[SourceScopeReplacementAttestation],
    active_dispatch_identity_sha256: str | None = None,
) -> tuple[ObservedDeltaReceipt, ...]:
    """Reconstruct exact route replacement receipts from journal attestations."""

    from nbadb.contracts.staging_route_contract import (
        admit_known_conditional_staging_route,
        conditional_staging_key_from_route_id,
        staging_route_contract_bundle,
    )
    from nbadb.orchestrate.successor_execution_plan import SuccessorExecutionPlan

    if not isinstance(transaction, SuccessorUpdateTransaction):
        raise SuccessorUpdateContractError(
            "successor replacements require an exact candidate transaction"
        )
    if not isinstance(execution_plan, SuccessorExecutionPlan):
        raise SuccessorUpdateContractError(
            "successor replacements require a validated execution plan"
        )
    routes = staging_route_contract_bundle().by_route_id
    scopes_by_route_and_params = {
        (scope.route_id, scope.scope_sha256): scope for scope in transaction.intent.requested_scopes
    }
    dispatch_by_scope = {
        scope.identity_sha256: dispatch
        for dispatch in execution_plan.dispatches
        for scope in dispatch.requested_scopes
    }
    grouped: dict[str, list[SourceScopeReplacementAttestation]] = {}
    for attestation in attestations:
        if not isinstance(attestation, SourceScopeReplacementAttestation):
            raise SuccessorUpdateContractError(
                "durable successor replacements do not form exact logical calls"
            )
        grouped.setdefault(attestation.logical_call_receipt_sha256, []).append(attestation)
    logical_root_by_dispatch: dict[str, str] = {}
    resolved: list[
        tuple[
            SourceScopeReplacementAttestation,
            RequestedRouteScope,
            SealedUpdateExecutionDispatch,
        ]
    ] = []
    for logical_root, logical_attestations in sorted(grouped.items()):
        logical_dispatches: dict[str, SealedUpdateExecutionDispatch] = {}
        logical_rows: list[
            tuple[
                SourceScopeReplacementAttestation,
                RequestedRouteScope,
                SealedUpdateExecutionDispatch,
            ]
        ] = []
        conditional_attestations: list[SourceScopeReplacementAttestation] = []
        for attestation in logical_attestations:
            scope = scopes_by_route_and_params.get(
                (attestation.result_route_id, attestation.source_scope_sha256)
            )
            if scope is None:
                if (
                    attestation.result_route_id in routes
                    or conditional_staging_key_from_route_id(attestation.result_route_id) is None
                ):
                    raise SuccessorUpdateContractError(
                        "persisted successor replacement falls outside the sealed execution plan"
                    )
                conditional_attestations.append(attestation)
                continue
            dispatch = dispatch_by_scope.get(scope.identity_sha256)
            if dispatch is None:
                raise SuccessorUpdateContractError(
                    "persisted successor replacement falls outside the sealed execution plan"
                )
            logical_dispatches[dispatch.identity_sha256] = dispatch
            logical_rows.append((attestation, scope, dispatch))
        if len(logical_dispatches) != 1:
            raise SuccessorUpdateContractError(
                "one logical replacement receipt spans multiple execution dispatches"
            )
        dispatch = next(iter(logical_dispatches.values()))
        prior_root = logical_root_by_dispatch.setdefault(dispatch.identity_sha256, logical_root)
        if prior_root != logical_root:
            raise SuccessorUpdateContractError(
                "one execution dispatch is split across logical replacement receipts"
            )
        static_route_ids = tuple(sorted(item[0].result_route_id for item in logical_rows))
        conditional_route_ids = tuple(
            sorted(item.result_route_id for item in conditional_attestations)
        )
        if (
            logical_root != logical_attestations[0].logical_call_receipt_sha256
            or len(static_route_ids) != len(set(static_route_ids))
            or set(static_route_ids) != set(dispatch.staging_route_ids)
            or len(static_route_ids) != len(dispatch.staging_route_ids)
        ):
            raise SuccessorUpdateContractError(
                "durable successor replacements do not exactly cover one execution dispatch"
            )
        conditional_admission = None
        if conditional_route_ids:
            try:
                conditional_admission = admit_known_conditional_staging_route(
                    endpoint_name=dispatch.endpoint_name,
                    static_route_ids=dispatch.staging_route_ids,
                    conditional_route_ids=conditional_route_ids,
                    provider_authority_sha256=transaction.baseline.provider_authority_sha256,
                )
            except ValueError as exc:
                raise SuccessorUpdateContractError(
                    "persisted conditional replacement lacks typed response authority"
                ) from exc
        if conditional_admission is not None and any(
            attestation.result_route_id != conditional_admission.route_id
            or attestation.staging_key != conditional_admission.staging_key
            or attestation.successor_generation_sha256 != transaction.generation_identity_sha256
            or attestation.source_scope_sha256 != dispatch.parameters_sha256
            or attestation.logical_parameters_sha256 != dispatch.parameters_sha256
            or attestation.provider_authority_sha256
            != transaction.baseline.provider_authority_sha256
            for attestation in conditional_attestations
        ):
            raise SuccessorUpdateContractError(
                "persisted conditional replacement differs from its response authority"
            )
        if (
            active_dispatch_identity_sha256 is not None
            and active_dispatch_identity_sha256 != dispatch.identity_sha256
        ):
            raise SuccessorUpdateContractError(
                "persisted successor replacement differs from the active execution dispatch"
            )
        resolved.extend(logical_rows)

    receipts: list[ObservedDeltaReceipt] = []
    for attestation, scope, dispatch in resolved:
        route = routes.get(attestation.result_route_id)
        if route is None:
            raise SuccessorUpdateContractError(
                "persisted successor replacement falls outside the immutable update intent"
            )
        if (
            attestation.successor_generation_sha256 != transaction.generation_identity_sha256
            or scope.route_contract_sha256 != route.contract_sha256
            or attestation.staging_key != route.staging_key
            or attestation.source_scope_sha256 != dispatch.parameters_sha256
            or attestation.logical_parameters_sha256 != dispatch.parameters_sha256
            or scope.identity_sha256 not in dispatch.requested_scope_identity_sha256s
            or attestation.provider_authority_sha256
            != transaction.baseline.provider_authority_sha256
            or route.provider_authority_sha256 != transaction.baseline.provider_authority_sha256
        ):
            raise SuccessorUpdateContractError(
                "persisted successor replacement does not match route/provider authority"
            )
        typed_zero = attestation.persisted_row_count == 0
        receipts.append(
            ObservedDeltaReceipt(
                baseline_identity_sha256=transaction.baseline.identity_sha256,
                update_intent_sha256=transaction.intent.identity_sha256,
                source_sha=transaction.intent.source_sha,
                requested_scope_sha256=scope.identity_sha256,
                execution_dispatch_identity_sha256=dispatch.identity_sha256,
                planning_dependency_identity_sha256s=dispatch.dependency_identity_sha256s,
                disposition=(
                    DeltaDisposition.TYPED_ZERO if typed_zero else DeltaDisposition.OBSERVED
                ),
                logical_call_receipt_sha256=attestation.logical_call_receipt_sha256,
                prior_persisted_content_sha256=attestation.prior_persisted_content_sha256,
                source_scope_replacement_sha256=attestation.replacement_sha256,
                persisted_content_sha256=attestation.persisted_content_sha256,
                persisted_schema_sha256=attestation.persisted_schema_sha256,
                persisted_row_count=attestation.persisted_row_count,
                typed_zero_reason_code="provider_success_empty" if typed_zero else None,
            )
        )
    return tuple(receipts)


def reopen_same_generation_journal_attestations(
    duckdb_path: Path,
    *,
    generation_identity_sha256: str,
) -> tuple[SourceScopeReplacementAttestation, ...]:
    """Reopen the candidate runtime journal and load this generation's attestations.

    Placeholder or non-DuckDB public bytes are treated as no journal progress.
    A real DuckDB whose replacement inventory is present but invalid fails closed.
    """

    import duckdb

    from nbadb.orchestrate.journal import PipelineJournal

    if not isinstance(duckdb_path, Path) or not duckdb_path.is_absolute():
        raise SuccessorUpdateContractError("runtime journal path must be an absolute Path")
    if (
        not isinstance(generation_identity_sha256, str)
        or len(generation_identity_sha256) != 64
        or any(character not in "0123456789abcdef" for character in generation_identity_sha256)
    ):
        raise SuccessorUpdateContractError(
            "runtime journal generation identity must be a lowercase SHA-256"
        )
    try:
        named = os.stat(duckdb_path, follow_symlinks=False)
    except OSError as exc:
        raise SuccessorUpdateContractError("runtime journal DuckDB is missing") from exc
    if not stat.S_ISREG(named.st_mode):
        raise SuccessorUpdateContractError("runtime journal DuckDB is unreadable")
    if named.st_size < 16:
        return ()
    try:
        with open(duckdb_path, "rb") as handle:
            header = handle.read(16)
    except OSError as exc:
        raise SuccessorUpdateContractError("runtime journal DuckDB is unreadable") from exc
    if _DUCKDB_MAGIC not in header:
        return ()

    connection = None
    try:
        connection = duckdb.connect(str(duckdb_path), read_only=True)
        present = connection.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_name = '_successor_staging_replacement_journal'
            """
        ).fetchone()
        if present is None:
            return ()
        journal = PipelineJournal(
            connection,
            migrate_schema=False,
            successor_generation_sha256=generation_identity_sha256,
        )
        return journal.load_successor_replacement_attestations()
    except SuccessorUpdateContractError:
        raise
    except ParserInputCaptureIntegrityError as exc:
        raise SuccessorUpdateContractError(
            "same-generation runtime journal restoration inventory is invalid"
        ) from exc
    except Exception as exc:
        raise SuccessorUpdateContractError(
            "same-generation runtime journal could not be reopened"
        ) from exc
    finally:
        if connection is not None:
            connection.close()


def restore_same_generation_replacements(
    *,
    transaction: SuccessorUpdateTransaction,
    execution_plan: SuccessorExecutionPlan,
    capture_session: PrivateCaptureSession,
    attestations: Sequence[SourceScopeReplacementAttestation],
    active_dispatch_identity_sha256: str | None = None,
) -> SameGenerationExecutionRestore:
    """Reload Bronze-v6 bindings and delta receipts into an admitted session."""

    receipts = successor_receipts_from_replacement_attestations(
        transaction=transaction,
        execution_plan=execution_plan,
        attestations=attestations,
        active_dispatch_identity_sha256=active_dispatch_identity_sha256,
    )
    bindings = logical_bindings_from_replacement_attestations(attestations)
    if bindings:
        capture_session.restore_completed_bindings(bindings)
    completed = tuple(sorted({receipt.execution_dispatch_identity_sha256 for receipt in receipts}))
    return SameGenerationExecutionRestore(
        attestations=tuple(attestations),
        bindings=bindings,
        receipts=receipts,
        completed_dispatch_identity_sha256s=completed,
    )
