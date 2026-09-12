"""Post-commit bridge from extraction evidence to request closure.

The extractor runner intentionally emits only pending observations.  This
module is the single bridge that may promote a pinned-exact stats observation,
and only from read-after-commit staging journal receipts that exactly cover its
logical routes.  Lossless-drift responses remain pending until their separate
many-result-to-one-lossless-landing contract is available.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate.extractor_runner import (
    PendingRequestObservation,
    RequestClosureExecutionAuthority,
)
from nbadb.orchestrate.request_closure_runtime import (
    PersistedStagingReceipt,
    RequestClosureAdapterInput,
    RequestClosureRuntimeReceipt,
    RequestObservation,
    build_request_closure_runtime_receipt,
)
from nbadb.orchestrate.staging_batches import CommittedStagingChunkReceipt


def bind_committed_request_observation(
    pending: PendingRequestObservation,
    authority: RequestClosureExecutionAuthority,
    committed: tuple[CommittedStagingChunkReceipt, ...],
    *,
    pagination_termination_reason: str | None = None,
) -> RequestObservation:
    """Promote one pinned-exact request after exact staging readback.

    The logical-call binding already ties provider response receipts to route
    IDs.  Here each route is reconciled with its committed journal row, its
    declared result-set ordinal, and the provider row count.  The committed
    content/schema digests remain inside ``receipt_root_sha256`` while the
    result-set digest remains the decoded provider authority.
    """

    if not isinstance(pending, PendingRequestObservation):
        raise ParserInputCaptureIntegrityError(
            "post-commit request closure requires a pending observation"
        )
    if not isinstance(authority, RequestClosureExecutionAuthority):
        raise ParserInputCaptureIntegrityError(
            "post-commit request closure requires its execution authority"
        )
    authority.validate_pending(pending)
    if pending.result_contract != "pinned_exact":
        raise ParserInputCaptureIntegrityError(
            "lossless drift requires the post-commit many-to-one receipt mapper"
        )
    if type(committed) is not tuple or any(
        not isinstance(receipt, CommittedStagingChunkReceipt) for receipt in committed
    ):
        raise ParserInputCaptureIntegrityError(
            "post-commit staging receipts must be an exact typed tuple"
        )
    route_ids = tuple(receipt.result_route_id for receipt in committed)
    physical_routes = {
        alias.manifest_route_id: alias.staging_route_id for alias in authority.staging_route_aliases
    }
    try:
        pending_physical_route_ids = {physical_routes[route_id] for route_id in pending.route_ids}
    except KeyError as exc:  # pragma: no cover - authority validates pending first
        raise ParserInputCaptureIntegrityError(
            "pending request closure route lacks a staging alias"
        ) from exc
    if (
        not committed
        or route_ids != tuple(sorted(route_ids))
        or len(route_ids) != len(set(route_ids))
        or set(route_ids) != pending_physical_route_ids
    ):
        raise ParserInputCaptureIntegrityError(
            "post-commit staging receipts do not exactly cover the pending routes"
        )

    results_by_ordinal = {
        receipt.canonical_index: receipt
        for receipt in pending.bronze_result_sets
        if receipt.canonical_index is not None
    }
    if len(results_by_ordinal) != len(pending.bronze_result_sets):
        raise ParserInputCaptureIntegrityError(
            "pinned-exact request has an incomplete canonical result inventory"
        )

    projected: list[PersistedStagingReceipt] = []
    for receipt in committed:
        try:
            _endpoint_name, staging_key, ordinal_text = receipt.result_route_id.rsplit(":", 2)
            ordinal = int(ordinal_text)
        except (ValueError, TypeError) as exc:
            raise ParserInputCaptureIntegrityError(
                "committed staging receipt has a malformed result route"
            ) from exc
        if staging_key != receipt.staging_key or ordinal < 0:
            raise ParserInputCaptureIntegrityError(
                "committed staging receipt route differs from its staging key"
            )
        result = results_by_ordinal.get(ordinal)
        if result is None or receipt.persisted_row_count != result.row_count:
            raise ParserInputCaptureIntegrityError(
                "committed staging receipt does not conserve its provider result set"
            )
        projected.append(
            PersistedStagingReceipt(
                result_set_ordinal=ordinal,
                result_set_name=result.name,
                staging_key=receipt.staging_key,
                row_count=receipt.persisted_row_count,
                result_set_payload_sha256=result.normalized_output_sha256,
                staging_receipt_root_sha256=receipt.receipt_root_sha256,
            )
        )

    staging_receipts = tuple(
        sorted(
            projected,
            key=lambda item: (
                item.result_set_ordinal,
                item.staging_key,
                item.staging_receipt_root_sha256,
            ),
        )
    )
    return pending.bind_committed_staging_receipts(
        authority,
        staging_receipts,
        pagination_termination_reason=pagination_termination_reason,
    )


@dataclass(frozen=True, slots=True, order=True)
class IncompleteRequestClosureEvidence:
    """Canonical fail-closed evidence for an observed but unprovable landing."""

    provider_request_sha256: str
    pending_observation_sha256: str
    logical_call_receipt_sha256: str
    reason_code: Literal[
        "lossless_stats_many_result_to_one_unproven",
        "live_many_result_to_one_unproven",
    ]
    committed_route_ids: tuple[str, ...]
    committed_staging_receipt_roots: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (
            self.provider_request_sha256,
            self.pending_observation_sha256,
            self.logical_call_receipt_sha256,
            *self.committed_staging_receipt_roots,
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ParserInputCaptureIntegrityError(
                    "incomplete request closure contains a noncanonical SHA-256"
                )
        if (
            not self.committed_route_ids
            or self.committed_route_ids != tuple(sorted(set(self.committed_route_ids)))
            or not self.committed_staging_receipt_roots
            or self.committed_staging_receipt_roots
            != tuple(sorted(set(self.committed_staging_receipt_roots)))
        ):
            raise ParserInputCaptureIntegrityError(
                "incomplete request closure receipt inventory is not canonical"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_request_sha256": self.provider_request_sha256,
            "pending_observation_sha256": self.pending_observation_sha256,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "reason_code": self.reason_code,
            "committed_route_ids": list(self.committed_route_ids),
            "committed_staging_receipt_roots": list(self.committed_staging_receipt_roots),
        }


@dataclass(frozen=True, slots=True, order=True)
class RequestClosureScopeGap:
    """Canonical typed scope that ordinary execution cannot yet prove closed."""

    reason_code: Literal[
        "dependent_scope_unmaterialized",
        "discovery_receipt_not_bound",
        "live_many_result_to_one_unproven",
        "logical_call_identity_collision_unproven",
        "pagination_scope_unproven",
        "provider_boundary_unproven",
        "provider_request_many_call_alias_unproven",
        "result_set_persistence_not_exhaustive",
        "static_receipt_not_bound",
    ]
    endpoint_names: tuple[str, ...]
    physical_route_ids: tuple[str, ...]
    logical_call_count: int
    scope_evidence_sha256: str

    def __post_init__(self) -> None:
        if (
            not self.endpoint_names
            or self.endpoint_names != tuple(sorted(set(self.endpoint_names)))
            or any(not isinstance(item, str) or not item for item in self.endpoint_names)
            or not self.physical_route_ids
            or self.physical_route_ids != tuple(sorted(set(self.physical_route_ids)))
            or any(not isinstance(item, str) or not item for item in self.physical_route_ids)
            or isinstance(self.logical_call_count, bool)
            or not isinstance(self.logical_call_count, int)
            or self.logical_call_count <= 0
            or not isinstance(self.scope_evidence_sha256, str)
            or len(self.scope_evidence_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.scope_evidence_sha256)
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure scope gap is invalid or noncanonical"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "reason_code": self.reason_code,
            "endpoint_names": list(self.endpoint_names),
            "physical_route_ids": list(self.physical_route_ids),
            "logical_call_count": self.logical_call_count,
            "scope_evidence_sha256": self.scope_evidence_sha256,
        }


def bind_or_classify_committed_request_observation(
    pending: PendingRequestObservation,
    authority: RequestClosureExecutionAuthority,
    binding: LogicalCallReceiptBinding,
    committed: tuple[CommittedStagingChunkReceipt, ...],
    *,
    pagination_termination_reason: str | None = None,
) -> RequestObservation | IncompleteRequestClosureEvidence:
    """Promote a reconstructable landing or retain a typed incomplete reason."""

    if not isinstance(binding, LogicalCallReceiptBinding):
        raise ParserInputCaptureIntegrityError(
            "post-commit request closure requires its logical-call binding"
        )
    if (
        pending.logical_call_receipt_sha256 != binding.logical_call_receipt_sha256
        or pending.logical_parameters_sha256 != binding.logical_parameters_sha256
        or pending.provider_authority_sha256 != binding.provider_authority_sha256
    ):
        raise ParserInputCaptureIntegrityError(
            "pending request closure differs from its staging logical-call binding"
        )
    committed_route_ids = tuple(receipt.result_route_id for receipt in committed)
    if (
        not committed
        or committed_route_ids != tuple(sorted(set(committed_route_ids)))
        or set(committed_route_ids) != set(binding.result_route_ids)
        or any(
            receipt.logical_call_receipt_sha256 != binding.logical_call_receipt_sha256
            for receipt in committed
        )
    ):
        raise ParserInputCaptureIntegrityError(
            "post-commit receipts do not conserve the logical-call route inventory"
        )
    if pending.result_contract == "pinned_exact":
        return bind_committed_request_observation(
            pending,
            authority,
            committed,
            pagination_termination_reason=pagination_termination_reason,
        )
    authority.validate_pending(pending)
    return IncompleteRequestClosureEvidence(
        provider_request_sha256=pending.provider_request_sha256,
        pending_observation_sha256=pending.artifact_sha256,
        logical_call_receipt_sha256=pending.logical_call_receipt_sha256,
        reason_code="lossless_stats_many_result_to_one_unproven",
        committed_route_ids=committed_route_ids,
        committed_staging_receipt_roots=tuple(
            sorted({receipt.receipt_root_sha256 for receipt in committed})
        ),
    )


@dataclass(frozen=True, slots=True)
class RequestClosureObservationInventory:
    """Standalone canonical join inventory for terminal assurance scanners."""

    authority: RequestClosureExecutionAuthority | None
    observations: tuple[RequestObservation, ...]
    incomplete: tuple[IncompleteRequestClosureEvidence, ...] = ()
    scope_gaps: tuple[RequestClosureScopeGap, ...] = ()

    def __post_init__(self) -> None:
        if self.authority is not None and not isinstance(
            self.authority, RequestClosureExecutionAuthority
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure inventory has invalid authority"
            )
        if (
            type(self.observations) is not tuple
            or any(not isinstance(item, RequestObservation) for item in self.observations)
            or self.observations
            != tuple(sorted(self.observations, key=lambda item: item.provider_request_sha256))
            or type(self.incomplete) is not tuple
            or any(
                not isinstance(item, IncompleteRequestClosureEvidence) for item in self.incomplete
            )
            or self.incomplete
            != tuple(sorted(self.incomplete, key=lambda item: item.provider_request_sha256))
            or type(self.scope_gaps) is not tuple
            or any(not isinstance(item, RequestClosureScopeGap) for item in self.scope_gaps)
            or self.scope_gaps != tuple(sorted(self.scope_gaps, key=lambda item: item.reason_code))
            or len({item.reason_code for item in self.scope_gaps}) != len(self.scope_gaps)
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure inventory members are invalid or noncanonical"
            )
        if self.authority is None:
            if self.observations or self.incomplete or not self.scope_gaps:
                raise ParserInputCaptureIntegrityError(
                    "gap-only request closure inventory has invalid members"
                )
            return
        expected = {binding.provider_request_sha256 for binding in self.authority.bindings}
        terminal = {item.provider_request_sha256 for item in self.observations}
        incomplete = {item.provider_request_sha256 for item in self.incomplete}
        if (
            terminal & incomplete
            or len(terminal) != len(self.observations)
            or len(incomplete) != len(self.incomplete)
            or terminal | incomplete != expected
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure inventory does not account for every request exactly once"
            )

    @property
    def runtime_receipt(self) -> RequestClosureRuntimeReceipt | None:
        if self.authority is None or self.incomplete or self.scope_gaps:
            return None
        return build_request_closure_runtime_receipt(
            RequestClosureAdapterInput(
                self.authority.route_manifest,
                self.authority.scope,
                self.observations,
            )
        )

    @property
    def green(self) -> bool:
        receipt = self.runtime_receipt
        return receipt is not None and receipt.green

    @property
    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    @property
    def artifact_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def to_dict(self) -> dict[str, object]:
        runtime_receipt = self.runtime_receipt
        authority = self.authority
        return {
            "schema_version": 2,
            "kind": "nbadb_request_closure_observation_inventory",
            "request_surface_sha256": (
                authority.route_manifest.request_surface_sha256 if authority is not None else None
            ),
            "route_manifest_sha256": (
                authority.route_manifest.manifest_sha256 if authority is not None else None
            ),
            "scope_sha256": authority.scope.scope_sha256 if authority is not None else None,
            "green": runtime_receipt is not None and runtime_receipt.green,
            "runtime_receipt": (runtime_receipt.to_dict() if runtime_receipt is not None else None),
            "observations": [item.to_dict() for item in self.observations],
            "incomplete": [item.to_dict() for item in self.incomplete],
            "scope_gaps": [item.to_dict() for item in self.scope_gaps],
        }


def verify_request_closure_observation_inventory_bytes(
    encoded: bytes,
) -> RequestClosureRuntimeReceipt:
    """Strictly reproduce a green canonical inventory for terminal scanning."""

    if not isinstance(encoded, bytes):
        raise ParserInputCaptureIntegrityError("request closure inventory encoding must be bytes")

    def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ParserInputCaptureIntegrityError(
                    f"request closure inventory contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ParserInputCaptureIntegrityError(
            f"request closure inventory contains non-finite value {value}"
        )

    try:
        decoded = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except ParserInputCaptureIntegrityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParserInputCaptureIntegrityError(
            "request closure inventory is not strict UTF-8 JSON"
        ) from exc
    expected_keys = {
        "green",
        "incomplete",
        "kind",
        "observations",
        "request_surface_sha256",
        "route_manifest_sha256",
        "runtime_receipt",
        "schema_version",
        "scope_gaps",
        "scope_sha256",
    }
    if (
        not isinstance(decoded, dict)
        or set(decoded) != expected_keys
        or decoded.get("schema_version") != 2
        or decoded.get("kind") != "nbadb_request_closure_observation_inventory"
        or json.dumps(
            decoded,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        != encoded
    ):
        raise ParserInputCaptureIntegrityError(
            "request closure inventory schema or canonical encoding is invalid"
        )
    incomplete = decoded.get("incomplete")
    scope_gaps = decoded.get("scope_gaps")
    if not isinstance(incomplete, list) or not isinstance(scope_gaps, list):
        raise ParserInputCaptureIntegrityError(
            "request closure inventory incomplete scopes are invalid"
        )
    if incomplete or scope_gaps or decoded.get("green") is not True:
        reason_codes = sorted(
            str(item.get("reason_code"))
            for collection in (incomplete, scope_gaps)
            for item in collection
            if isinstance(item, dict)
        )
        raise ParserInputCaptureIntegrityError(
            "request closure inventory is not green"
            + (": " + ",".join(reason_codes) if reason_codes else "")
        )
    runtime_payload = decoded.get("runtime_receipt")
    if not isinstance(runtime_payload, dict):
        raise ParserInputCaptureIntegrityError(
            "green request closure inventory has no runtime receipt"
        )
    runtime_bytes = json.dumps(
        runtime_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    try:
        runtime_receipt = RequestClosureRuntimeReceipt.from_canonical_bytes(runtime_bytes)
    except Exception as exc:
        raise ParserInputCaptureIntegrityError(
            "request closure runtime receipt failed independent reproduction"
        ) from exc
    if (
        not runtime_receipt.green
        or decoded.get("request_surface_sha256") != runtime_receipt.request_surface_sha256
        or decoded.get("route_manifest_sha256") != runtime_receipt.route_manifest.manifest_sha256
        or decoded.get("scope_sha256") != runtime_receipt.scope.scope_sha256
        or decoded.get("observations") != [item.to_dict() for item in runtime_receipt.observations]
    ):
        raise ParserInputCaptureIntegrityError(
            "request closure inventory differs from its reproduced runtime receipt"
        )
    return runtime_receipt


__all__ = [
    "IncompleteRequestClosureEvidence",
    "RequestClosureObservationInventory",
    "RequestClosureScopeGap",
    "bind_committed_request_observation",
    "bind_or_classify_committed_request_observation",
    "verify_request_closure_observation_inventory_bytes",
]
