"""Pure post-commit closure for public raw-request capture evidence.

The provider boundary can prove parser input and parsed result occurrences before
staging, but a successful request is not terminal until every route derived from
that response has a read-after-commit staging receipt.  This module performs the
strict, no-I/O join between those two authorities.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal, Never, cast

import polars as pl

from nbadb.contracts.logical_provider_parameter_binding import (
    LogicalProviderParameterBindingV1,
    verify_logical_provider_parameter_binding,
)
from nbadb.contracts.raw_request_authority import (
    LandingDisposition,
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RawRequestAuthorityError,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultContainerKind,
    ResultOccurrenceV2,
    ResultPresence,
    RouteAuthorityKind,
    RouteLandingSemantic,
    decode_parser_input_object,
    validate_parser_input_object,
    validate_request_attempt_identity,
    validate_request_observation,
)
from nbadb.contracts.raw_request_reconstruction import (
    LiveSnapshotPlanAuthorityV2,
    RawRequestReconstructionError,
)
from nbadb.contracts.raw_transport_contract import (
    source_family_for_transport,
    validate_raw_transport,
)
from nbadb.core.errors import ParserInputCaptureIntegrityError, ResponseContractError
from nbadb.core.nba_api_runtime_contract import pinned_live_contracts, pinned_runtime_contracts
from nbadb.extract.bronze import (
    LogicalCallReceiptBinding,
    ResultSetReceipt,
)
from nbadb.extract.live_lossless import LIVE_LOSSLESS_STAGING_KEY
from nbadb.extract.nba_api_adapter import (
    RawAuthorityRouteFrameDerivation,
    rederive_raw_authority_result_sets,
    rederive_raw_authority_route_frames,
    rederive_raw_authority_stats_wide_rows,
    rederive_raw_authority_unknown_stats_response,
)
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    PendingResultOccurrenceV2,
    RawRequestCaptureIssueV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.extract.stats_lossless import build_unknown_stats_lossless_fallback
from nbadb.orchestrate.staging_batches import (
    CommittedStagingChunkReceiptV2,
    frame_content_hash,
    frame_schema_hash,
)
from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nbadb.contracts.staging_route_contract import (
        ConditionalLiveStagingRouteAdmission,
        KnownConditionalStagingRouteAdmission,
        StagingRouteContract,
    )

__all__ = [
    "RawRequestFinalizationError",
    "finalize_raw_request_capture",
    "materialize_raw_request_failure_snapshot",
    "materialize_raw_request_incomplete_success_snapshot",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_UNKNOWN_STATS_FIXED_ZERO_ENDPOINT_IDS = frozenset({"VideoDetails", "VideoDetailsAsset"})
_UNKNOWN_STATS_CANONICAL_ALIAS_ENDPOINT_IDS = frozenset({"VideoEvents", "VideoEventsAsset"})
_UNKNOWN_STATS_ENDPOINT_IDS = (
    _UNKNOWN_STATS_FIXED_ZERO_ENDPOINT_IDS | _UNKNOWN_STATS_CANONICAL_ALIAS_ENDPOINT_IDS
)


class RawRequestFinalizationError(RawRequestAuthorityError):
    """Raised when pre-commit capture and post-commit receipts do not close."""


def _fail(message: str) -> Never:
    raise RawRequestFinalizationError(message)


def _rebuild_exact_dataclass(value: object, expected_type: type[Any], *, label: str) -> Any:
    if type(value) is not expected_type:
        _fail(f"{label} does not have its exact contract type")
    try:
        return expected_type(
            **{field.name: getattr(value, field.name) for field in fields(expected_type)}
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RawRequestFinalizationError(f"{label} failed strict revalidation") from exc


def _revalidate_binding(value: object) -> LogicalCallReceiptBinding:
    return cast(
        "LogicalCallReceiptBinding",
        _rebuild_exact_dataclass(value, LogicalCallReceiptBinding, label="logical-call binding"),
    )


def _revalidate_result_set(value: object) -> ResultSetReceipt:
    return cast(
        "ResultSetReceipt",
        _rebuild_exact_dataclass(value, ResultSetReceipt, label="result-set receipt"),
    )


def _revalidate_committed_receipt(value: object) -> CommittedStagingChunkReceiptV2:
    return cast(
        "CommittedStagingChunkReceiptV2",
        _rebuild_exact_dataclass(
            value,
            CommittedStagingChunkReceiptV2,
            label="committed staging receipt",
        ),
    )


def _headers_sha256(headers: Sequence[str]) -> str:
    encoded = json.dumps(list(headers), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_attempt(value: object, *, label: str) -> RequestAttemptIdentityV2:
    if type(value) is not RequestAttemptIdentityV2:
        _fail(f"{label} has no exact request-attempt identity")
    try:
        return validate_request_attempt_identity(value)
    except (TypeError, ValueError) as exc:
        raise RawRequestFinalizationError(
            f"{label} request-attempt identity failed strict revalidation"
        ) from exc


def _safe_object(value: object) -> ParserInputObjectV2:
    if type(value) is not ParserInputObjectV2:
        _fail("parser-input object does not have its exact contract type")
    try:
        return validate_parser_input_object(value)
    except (TypeError, ValueError) as exc:
        raise RawRequestFinalizationError("parser-input object failed strict revalidation") from exc


def _safe_observation(value: object) -> RequestObservationV2:
    if type(value) is not RequestObservationV2:
        _fail("request observation does not have its exact contract type")
    try:
        return validate_request_observation(value)
    except (TypeError, ValueError) as exc:
        raise RawRequestFinalizationError("request observation failed strict revalidation") from exc


class _RouteAuthority:
    __slots__ = (
        "conditional",
        "endpoint_contract_sha256",
        "expected_staging_keys",
        "provider_endpoint_id",
        "source_family",
        "static_routes",
    )

    def __init__(
        self,
        *,
        static_routes: tuple[StagingRouteContract, ...],
        conditional: KnownConditionalStagingRouteAdmission | None,
        source_family: Literal["stats", "live", "static"],
        provider_endpoint_id: str,
        endpoint_contract_sha256: str,
        expected_staging_keys: Mapping[str, str],
    ) -> None:
        self.static_routes = static_routes
        self.conditional = conditional
        self.source_family = source_family
        self.provider_endpoint_id = provider_endpoint_id
        self.endpoint_contract_sha256 = endpoint_contract_sha256
        self.expected_staging_keys = dict(expected_staging_keys)


def _resolve_route_authority(binding: LogicalCallReceiptBinding) -> _RouteAuthority:
    from nbadb.contracts.staging_route_contract import (
        admit_known_conditional_staging_route,
        conditional_staging_key_from_route_id,
        staging_route_contract_bundle,
        validate_staging_route_contract_bundle,
    )

    bundle = staging_route_contract_bundle()
    try:
        validate_staging_route_contract_bundle(bundle)
    except ValueError as exc:
        raise RawRequestFinalizationError(
            "current staging-route authority failed exact validation"
        ) from exc

    static_routes: list[StagingRouteContract] = []
    conditional_ids: list[str] = []
    for route_id in binding.result_route_ids:
        route = bundle.by_route_id.get(route_id)
        if route is not None:
            static_routes.append(route)
        elif conditional_staging_key_from_route_id(route_id) is not None:
            conditional_ids.append(route_id)
        else:
            _fail("logical-call binding contains a foreign staging route")
    if not static_routes:
        _fail("logical-call binding has no fixed provider route authority")
    if len(conditional_ids) > 1:
        _fail("logical-call binding contains multiple conditional routes")

    endpoint_names = {route.endpoint_name for route in static_routes}
    source_families = {route.source_family for route in static_routes}
    provider_endpoint_ids = {route.provider_endpoint_id for route in static_routes}
    endpoint_contracts = {route.endpoint_contract_sha256 for route in static_routes}
    provider_authorities = {route.provider_authority_sha256 for route in static_routes}
    if (
        endpoint_names != {binding.endpoint_name}
        or len(source_families) != 1
        or len(provider_endpoint_ids) != 1
        or len(endpoint_contracts) != 1
        or provider_authorities != {binding.provider_authority_sha256}
    ):
        _fail("logical-call routes cross endpoint or provider authority")

    ordered_static_routes = tuple(sorted(static_routes, key=lambda item: item.ordinal))
    ordered_static_ids = tuple(route.route_id for route in ordered_static_routes)
    conditional: KnownConditionalStagingRouteAdmission | None = None
    if conditional_ids:
        try:
            conditional = admit_known_conditional_staging_route(
                endpoint_name=binding.endpoint_name,
                static_route_ids=ordered_static_ids,
                conditional_route_ids=(conditional_ids[0],),
                provider_authority_sha256=binding.provider_authority_sha256,
            )
        except ValueError as exc:
            raise RawRequestFinalizationError(
                "conditional staging route lacks its typed endpoint authority"
            ) from exc

    source_family = next(iter(source_families))
    conditional_key = None if conditional is None else conditional.staging_key
    if source_family == "live" and conditional_key != LIVE_LOSSLESS_STAGING_KEY:
        _fail("live request closure requires its universal lossless route")
    if source_family == "stats" and conditional_key not in {
        None,
        LOSSLESS_FALLBACK_STAGING_KEY,
    }:
        _fail("stats request closure has a foreign conditional route")
    if source_family == "static" and conditional is not None:
        _fail("static request closure cannot use a conditional route")

    expected_staging_keys = {route.route_id: route.staging_key for route in static_routes}
    if conditional is not None:
        expected_staging_keys[conditional.route_id] = conditional.staging_key
    if set(expected_staging_keys) != set(binding.result_route_ids):
        _fail("logical-call route authority is incomplete")
    return _RouteAuthority(
        static_routes=ordered_static_routes,
        conditional=conditional,
        source_family=source_family,
        provider_endpoint_id=next(iter(provider_endpoint_ids)),
        endpoint_contract_sha256=next(iter(endpoint_contracts)),
        expected_staging_keys=expected_staging_keys,
    )


def _receipt_inventory(
    binding: LogicalCallReceiptBinding,
    route_authority: _RouteAuthority,
    receipts: object,
) -> dict[str, CommittedStagingChunkReceiptV2]:
    if type(receipts) is not tuple:
        _fail("committed staging receipts must be an exact tuple")
    by_route: dict[str, CommittedStagingChunkReceiptV2] = {}
    roots: set[str] = set()
    for value in receipts:
        receipt = _revalidate_committed_receipt(value)
        if receipt.result_route_id in by_route:
            _fail("committed staging receipts repeat a route")
        if receipt.receipt_root_sha256 in roots:
            _fail("committed staging receipts repeat a receipt root")
        roots.add(receipt.receipt_root_sha256)
        by_route[receipt.result_route_id] = receipt

    if set(by_route) != set(binding.result_route_ids):
        _fail("committed staging receipt inventory is missing, duplicate, or foreign")
    for route_id, receipt in by_route.items():
        if (
            receipt.logical_call_receipt_sha256 != binding.logical_call_receipt_sha256
            or receipt.provider_authority_sha256 != binding.provider_authority_sha256
            or receipt.logical_parameters_sha256 != binding.logical_parameters_sha256
            or receipt.staging_key != route_authority.expected_staging_keys[route_id]
        ):
            _fail("committed staging receipt crosses logical or route authority")
    return by_route


def _validate_pending_result(value: object) -> PendingResultOccurrenceV2:
    if type(value) is not PendingResultOccurrenceV2:
        _fail("pending result occurrence does not have its exact contract type")
    item = value
    receipt = _revalidate_result_set(item.result_set)
    if (
        type(item.duplicate_name_ordinal) is not int
        or item.duplicate_name_ordinal < 0
        or type(item.ordered_headers) is not tuple
        or any(type(header) is not str or not header for header in item.ordered_headers)
        or _headers_sha256(item.ordered_headers) != receipt.headers_sha256
    ):
        _fail("pending result occurrence has malformed ordered-header authority")
    return PendingResultOccurrenceV2(
        result_set=receipt,
        duplicate_name_ordinal=item.duplicate_name_ordinal,
        ordered_headers=item.ordered_headers,
    )


def _validate_pending_success(
    value: object,
    *,
    result_policy: Literal["required", "forbidden"] = "required",
) -> PendingRawRequestSuccessV2:
    if type(value) is not PendingRawRequestSuccessV2:
        _fail("pending success does not have its exact contract type")
    item = value
    attempt = _safe_attempt(item.attempt, label="pending success")
    try:
        transport = validate_raw_transport(item.transport)
    except (TypeError, ValueError) as exc:
        raise RawRequestFinalizationError(
            "pending success transport failed strict revalidation"
        ) from exc
    if source_family_for_transport(transport) != attempt.source_family:
        _fail("pending success transport crosses source family")
    if (
        type(item.private_receipt_sha256) is not str
        or _SHA256_RE.fullmatch(item.private_receipt_sha256) is None
        or type(item.started_at) is not datetime
        or type(item.finished_at) is not datetime
        or item.started_at.tzinfo is None
        or item.finished_at.tzinfo is None
        or item.started_at.utcoffset() is None
        or item.finished_at.utcoffset() is None
        or item.finished_at < item.started_at
        or type(item.elapsed_ns) is not int
        or item.elapsed_ns < 0
        or item.outcome not in {"success_nonempty", "success_empty", "static_snapshot_success"}
        or type(item.results) is not tuple
        or type(item.aggregate_route_ids) is not tuple
    ):
        _fail("pending success has malformed completion authority")
    if result_policy == "forbidden" and item.results:
        _fail("result-authority-pending success contains a result occurrence")

    body = None if item.body_object is None else _safe_object(item.body_object)
    if attempt.source_family == "static":
        if (
            item.outcome != "static_snapshot_success"
            or item.body_disposition != "declared_bodyless"
            or body is not None
        ):
            _fail("static pending success has body-bearing or HTTP semantics")
    elif (
        item.outcome == "static_snapshot_success"
        or item.body_disposition != "public_parser_input"
        or body is None
    ):
        _fail("HTTP pending success lacks its exact public parser input")

    results = tuple(_validate_pending_result(result) for result in item.results)
    duplicate_ordinals: defaultdict[str, list[int]] = defaultdict(list)
    for result in results:
        duplicate_ordinals[result.result_set.name].append(result.duplicate_name_ordinal)
    if any(
        sorted(ordinals) != list(range(len(ordinals))) for ordinals in duplicate_ordinals.values()
    ):
        _fail("pending result duplicate-name ordinals are not contiguous")
    if result_policy == "required":
        has_rows = any(result.result_set.row_count > 0 for result in results)
        if item.outcome == "success_nonempty" and item.results and not has_rows:
            _fail("pending nonempty success has no nonempty result")
        if item.outcome == "success_empty" and has_rows:
            _fail("pending empty success has nonempty result rows")
    elif item.outcome != "success_nonempty":
        _fail("result-authority-pending success must retain its nonempty body projection")

    return PendingRawRequestSuccessV2(
        private_receipt_sha256=item.private_receipt_sha256,
        attempt=attempt,
        transport=transport,
        started_at=item.started_at,
        finished_at=item.finished_at,
        elapsed_ns=item.elapsed_ns,
        outcome=item.outcome,
        body_disposition=item.body_disposition,
        body_object=body,
        results=results,
        logical_receipt_sha256=item.logical_receipt_sha256,
        aggregate_route_ids=item.aggregate_route_ids,
    )


def _validate_snapshot(
    snapshot: object,
    *,
    pending_policy: Literal["required", "forbidden"],
) -> tuple[
    tuple[ParserInputObjectV2, ...],
    tuple[RequestObservationV2, ...],
    tuple[PendingRawRequestSuccessV2, ...],
]:
    if type(snapshot) is not RawRequestCaptureSnapshotV2:
        _fail("raw-request snapshot does not have its exact contract type")
    parsed = snapshot
    if any(
        type(values) is not tuple
        for values in (
            parsed.objects,
            parsed.observations,
            parsed.pending_successes,
            parsed.issues,
        )
    ):
        _fail("raw-request snapshot inventories must be exact tuples")
    if parsed.issues:
        _fail("raw-request snapshot contains unresolved capture issues")
    objects = tuple(_safe_object(item) for item in parsed.objects)
    observations = tuple(_safe_observation(item) for item in parsed.observations)
    pending = tuple(_validate_pending_success(item) for item in parsed.pending_successes)
    if pending_policy == "required" and not pending:
        _fail("raw-request snapshot has no success awaiting transactional closure")
    if pending_policy == "forbidden" and pending:
        _fail("failure-only raw-request snapshot contains a pending success")
    if any(item.lifecycle == "selected_terminal" for item in observations):
        _fail("raw-request snapshot already contains a selected terminal observation")
    return objects, observations, pending


def _validate_object_closure(
    *,
    objects: Sequence[ParserInputObjectV2],
    observations: Sequence[RequestObservationV2],
    pending: Sequence[PendingRawRequestSuccessV2],
) -> None:
    object_by_sha: dict[str, ParserInputObjectV2] = {}
    for item in objects:
        if item.object_sha256 in object_by_sha:
            _fail("raw-request snapshot repeats a parser-input object")
        object_by_sha[item.object_sha256] = item
    referenced_objects = {
        item.body_object_sha256 for item in observations if item.body_object_sha256 is not None
    }
    for success in pending:
        if success.body_object is not None:
            if object_by_sha.get(success.body_object.object_sha256) != success.body_object:
                _fail("pending success body differs from the parser-input inventory")
            referenced_objects.add(success.body_object.object_sha256)
    if referenced_objects != set(object_by_sha):
        _fail("raw-request snapshot contains a missing or orphan parser-input object")


def _attempt_context_key(attempt: RequestAttemptIdentityV2) -> tuple[object, ...]:
    return (
        attempt.semantic_request_sha256,
        attempt.logical_invocation_sha256,
        attempt.source_sha,
        attempt.run_id,
        attempt.run_attempt,
        attempt.chain_id,
        attempt.lane_id,
        attempt.provider_authority_sha256,
        attempt.source_family,
    )


def _validate_attempt_closure(
    *,
    observations: Sequence[RequestObservationV2],
    pending: Sequence[PendingRawRequestSuccessV2],
    binding: LogicalCallReceiptBinding,
    routes: _RouteAuthority,
    logical_provider_parameter_binding: LogicalProviderParameterBindingV1 | None,
    expected_logical_provider_parameter_binding_sha256: str | None,
) -> LogicalProviderParameterBindingV1 | None:
    attempts = [item.attempt for item in observations]
    attempts.extend(item.attempt for item in pending)
    if len({_attempt_context_key(item) for item in attempts}) != 1:
        _fail("raw-request attempts cross logical execution contexts")
    if any(
        item.provider_authority_sha256 != binding.provider_authority_sha256
        or item.source_family != routes.source_family
        or item.endpoint_id != routes.provider_endpoint_id
        or item.endpoint_contract_sha256 != routes.endpoint_contract_sha256
        for item in attempts
    ):
        _fail("raw-request attempts cross provider or endpoint authority")

    coordinates: set[tuple[int, int]] = set()
    request_to_call: dict[int, str] = {}
    call_to_request: dict[str, int] = {}
    retry_requests: defaultdict[int, set[int]] = defaultdict(set)
    for attempt in attempts:
        coordinate = (attempt.retry_ordinal, attempt.request_ordinal)
        if coordinate in coordinates:
            _fail("raw-request attempts repeat a retry/request coordinate")
        coordinates.add(coordinate)
        retry_requests[attempt.retry_ordinal].add(attempt.request_ordinal)
        prior_call = request_to_call.setdefault(
            attempt.request_ordinal,
            attempt.provider_call_sha256,
        )
        prior_request = call_to_request.setdefault(
            attempt.provider_call_sha256,
            attempt.request_ordinal,
        )
        if prior_call != attempt.provider_call_sha256 or prior_request != attempt.request_ordinal:
            _fail("raw-request retries reorder provider-call identities")
    if any(sorted(values) != list(range(len(values))) for values in retry_requests.values()):
        _fail("raw-request attempts are not contiguous within a retry")

    selected_calls = Counter(item.attempt.provider_call_sha256 for item in pending)
    if any(count != 1 for count in selected_calls.values()):
        _fail("a provider call has more than one pending terminal success")
    if set(call_to_request) != set(selected_calls):
        _fail("a provider call lacks one unique terminal success")
    selected_requests = sorted(item.attempt.request_ordinal for item in pending)
    selected_call_ordinals = sorted(item.attempt.provider_call_ordinal for item in pending)
    if selected_requests != list(range(len(selected_requests))) or selected_call_ordinals != list(
        range(len(selected_call_ordinals))
    ):
        _fail("selected provider calls are not a contiguous logical invocation")

    private_receipts = [item.private_receipt_sha256 for item in pending]
    if len(private_receipts) != len(set(private_receipts)):
        _fail("pending terminal successes repeat a private response receipt")
    for item in pending:
        if (
            item.logical_receipt_sha256 != binding.logical_call_receipt_sha256
            or item.aggregate_route_ids != binding.result_route_ids
        ):
            _fail("pending success is unbound from the exact logical call")
    parameter_digests_match = all(
        item.attempt.safe_parameters_sha256 == binding.logical_parameters_sha256 for item in pending
    )
    parameter_binding_supplied = (
        logical_provider_parameter_binding is not None
        or expected_logical_provider_parameter_binding_sha256 is not None
    )
    if parameter_digests_match:
        if parameter_binding_supplied:
            _fail("direct logical/provider parameter equality cannot carry an alias binding")
        return None
    if (
        type(logical_provider_parameter_binding) is not LogicalProviderParameterBindingV1
        or type(expected_logical_provider_parameter_binding_sha256) is not str
    ):
        _fail("logical/provider parameters differ but lack their independently pinned binding")
    try:
        parameter_binding = verify_logical_provider_parameter_binding(
            logical_provider_parameter_binding,
            expected_binding_sha256=(expected_logical_provider_parameter_binding_sha256),
        )
    except Exception:
        _fail("logical/provider parameter binding failed exact external verification")
    if (
        parameter_binding.logical_endpoint_name != binding.endpoint_name
        or parameter_binding.logical_parameters_sha256 != binding.logical_parameters_sha256
        or parameter_binding.result_route_ids != binding.result_route_ids
    ):
        _fail("logical/provider parameter binding differs from the logical call")
    ordered_pending = tuple(
        sorted(
            pending,
            key=lambda item: (
                item.attempt.request_ordinal,
                item.attempt.provider_call_ordinal,
            ),
        )
    )
    if len(parameter_binding.provider_entries) != len(ordered_pending):
        _fail("logical/provider parameter binding does not bijectively cover selected calls")
    for entry, selected in zip(
        parameter_binding.provider_entries,
        ordered_pending,
        strict=True,
    ):
        attempt = selected.attempt
        if (
            entry.request_ordinal != attempt.request_ordinal
            or entry.provider_call_ordinal != attempt.provider_call_ordinal
            or entry.provider_call_sha256 != attempt.provider_call_sha256
            or entry.provider_request_sha256 != attempt.provider_request_sha256
            or entry.safe_parameters_sha256 != attempt.safe_parameters_sha256
            or entry.source_family != attempt.source_family
            or entry.endpoint_id != attempt.endpoint_id
            or entry.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
        ):
            _fail("logical/provider parameter binding differs from a selected provider call")
    return parameter_binding


def _route_result_identity_matches(
    route: StagingRouteContract,
    result: PendingResultOccurrenceV2,
) -> bool:
    receipt = result.result_set
    if route.provider_result_set_name != receipt.name:
        return False
    if route.source_family == "stats":
        if receipt.canonical_index is not None:
            return route.canonical_result_set_ordinal == receipt.canonical_index
        contract = pinned_runtime_contracts().get(route.provider_endpoint_id)
        if contract is None or route.canonical_result_set_ordinal >= len(contract.result_sets):
            return False
        expected = contract.result_sets[route.canonical_result_set_ordinal]
        duplicate_ordinal = sum(
            prior.result_set_name == expected.result_set_name
            for prior in contract.result_sets[: route.canonical_result_set_ordinal]
        )
        return (
            expected.result_set_name == receipt.name
            and result.duplicate_name_ordinal == duplicate_ordinal
        )
    if route.source_family == "live":
        return (
            receipt.canonical_index is not None
            and route.provider_result_set_ordinal == receipt.canonical_index
        )
    return (
        receipt.provider_index == route.provider_result_set_ordinal
        and receipt.canonical_index == route.canonical_result_set_ordinal
    )


def _wide_route_matches(
    route: StagingRouteContract,
    result: PendingResultOccurrenceV2,
) -> bool:
    return _route_result_identity_matches(route, result) and (
        result.ordered_headers == route.provider_columns
    )


def _validate_result_family_identity(
    success: PendingRawRequestSuccessV2,
    routes: _RouteAuthority,
) -> None:
    """Recheck result identities that the generic receipt type cannot pin."""

    results = success.results
    if routes.source_family == "live":
        contract = pinned_live_contracts().get(routes.provider_endpoint_id)
        if contract is None:
            _fail("live result inventory has no pinned endpoint authority")
        if len(results) != len(contract.result_sets):
            _fail("live result inventory differs from its exact pinned endpoint")
        for expected, result in zip(contract.result_sets, results, strict=True):
            receipt = result.result_set
            if (
                receipt.name != expected.name
                or receipt.provider_index is not None
                or receipt.canonical_index != expected.ordinal
                or receipt.json_path != expected.json_path
                or receipt.container_kind != expected.container_kind
                or result.duplicate_name_ordinal != 0
                or result.ordered_headers != tuple(field.name for field in expected.fields)
                or (
                    expected.parent_result_set_name is None
                    and receipt.parent_observation_count != 1
                )
            ):
                _fail("live result identity differs from its exact pinned endpoint")
        return

    if routes.source_family == "static":
        if len(results) != 1:
            _fail("static request closure requires exactly one result occurrence")
        receipt = results[0].result_set
        if (
            receipt.provider_index != 0
            or receipt.canonical_index != 0
            or receipt.json_path is not None
            or receipt.container_kind != "nba_api_static_records"
            or receipt.parent_observation_count != 1
            or receipt.container_count != 1
            or receipt.missing_count
            or receipt.null_count
        ):
            _fail("static result identity differs from its exact provider snapshot")
        return

    is_fallback = any(item.result_set.canonical_index is None for item in results)
    if is_fallback:
        if any(item.result_set.canonical_index is not None for item in results):
            _fail("stats fallback mixes pinned and fallback result identities")
        provider_indexes: list[int] = []
        for result in results:
            receipt = result.result_set
            if (
                receipt.json_path is not None
                or receipt.container_kind != "nba_api_result_set"
                or receipt.parent_observation_count != 1
                or receipt.null_count
            ):
                _fail("stats fallback result identity is malformed")
            if receipt.provider_index is None:
                if receipt.row_count or receipt.container_count or receipt.missing_count != 1:
                    _fail("missing stats fallback result identity is malformed")
            else:
                provider_indexes.append(receipt.provider_index)
                if receipt.container_count != 1 or receipt.missing_count:
                    _fail("present stats fallback result identity is malformed")
        if provider_indexes != list(range(len(provider_indexes))):
            _fail("stats fallback provider result order is not contiguous")
        return

    provider_indexes: set[int] = set()
    for result in results:
        receipt = result.result_set
        if (
            receipt.provider_index is None
            or receipt.canonical_index is None
            or receipt.json_path is not None
            or receipt.container_kind != "nba_api_result_set"
            or receipt.parent_observation_count != 1
            or receipt.container_count != 1
            or receipt.missing_count
            or receipt.null_count
        ):
            _fail("pinned stats result identity is malformed")
        provider_indexes.add(receipt.provider_index)
    if provider_indexes != set(range(len(results))):
        _fail("pinned stats provider result order is not complete")


def _presence_and_counts(
    result: PendingResultOccurrenceV2,
) -> tuple[
    ResultPresence,
    tuple[str, ...],
    int,
    int,
    int,
    int,
    int,
    int,
]:
    receipt = result.result_set
    present_containers = receipt.container_count
    missing = receipt.missing_count
    nulls = receipt.null_count
    if present_containers == 0:
        if receipt.parent_observation_count == 0:
            if (
                receipt.row_count
                or missing
                or nulls
                or receipt.json_path is None
                or receipt.container_kind
                not in {
                    "nba_api_live_json_array",
                    "nba_api_live_json_object",
                }
            ):
                _fail("zero-parent result state is not an exact live child observation")
            return (
                "not_observed_parent_empty",
                result.ordered_headers,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        if missing > 0 and nulls == 0:
            return "missing", (), 0, 0, 0, 0, missing, 0
        if nulls > 0 and missing == 0:
            return "null", (), 0, 0, nulls, nulls, 0, nulls
        if missing > 0 and nulls > 0:
            return "mixed_absent", (), 0, 0, nulls, nulls, missing, nulls
        _fail("result occurrence has no unique missing/null presence state")

    row_count = receipt.row_count
    container_count = present_containers + nulls
    if row_count > 0:
        headers = result.ordered_headers
        return (
            "present",
            headers,
            row_count,
            row_count * len(headers),
            0 if receipt.container_kind == "nba_api_result_set" else row_count,
            container_count,
            missing,
            nulls,
        )
    if receipt.container_kind == "nba_api_result_set":
        return (
            "present_empty",
            result.ordered_headers,
            0,
            0,
            0,
            container_count,
            missing,
            nulls,
        )
    if (
        receipt.container_kind in {"nba_api_live_json_array", "nba_api_static_records"}
        and present_containers == 1
        and missing == 0
        and nulls == 0
    ):
        return "empty_array", (), 0, 0, 1, 1, 0, 0
    return (
        "present",
        result.ordered_headers,
        0,
        0,
        present_containers,
        container_count,
        missing,
        nulls,
    )


def _landing_disposition(
    *,
    wide_route_ids: Sequence[str],
    conditional_route_id: str | None,
) -> LandingDisposition:
    if wide_route_ids and conditional_route_id is not None:
        return "wide_plus_lossless"
    if wide_route_ids:
        return "wide_only"
    if conditional_route_id is not None:
        return "lossless_only"
    _fail("result occurrence has no exact public landing route")


def _is_unknown_stats_route_authority(routes: _RouteAuthority) -> bool:
    if routes.source_family != "stats":
        return False
    contract = pinned_runtime_contracts().get(routes.provider_endpoint_id)
    return contract is not None and contract.response_mode == "unknown_dynamic_response"


def _rederive_unknown_stats_fallback(
    success: PendingRawRequestSuccessV2,
) -> pl.DataFrame | None:
    """Reparse one unknown-mode response and rebuild its receipt-bound frame."""

    body = success.body_object
    if body is None:
        _fail("unknown stats response omitted its exact public parser input")
    try:
        unknown = rederive_raw_authority_unknown_stats_response(
            endpoint_id=success.attempt.endpoint_id,
            parser_input=decode_parser_input_object(body),
            safe_parameters_json=success.attempt.safe_parameters_json,
            provider_authority_sha256=success.attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=success.attempt.endpoint_contract_sha256,
        )
        duplicate_names: Counter[str] = Counter()
        expected_pending_items: list[PendingResultOccurrenceV2] = []
        for item in unknown.occurrences:
            duplicate_ordinal = duplicate_names[item.name]
            duplicate_names[item.name] += 1
            expected_pending_items.append(
                PendingResultOccurrenceV2(
                    result_set=item.receipt,
                    duplicate_name_ordinal=duplicate_ordinal,
                    ordered_headers=item.headers,
                )
            )
        if tuple(expected_pending_items) != success.results:
            _fail("unknown stats result authority differs from exact parser-input rederivation")
        if unknown.outcome != success.outcome:
            _fail("unknown stats outcome differs from exact parser-input rederivation")
        bound = unknown.bind_response_receipt(success.private_receipt_sha256)
        fallback = build_unknown_stats_lossless_fallback(
            bound,
            expected_response_receipt_sha256=success.private_receipt_sha256,
            expected_parameters_sha256=unknown.parameters_sha256,
            expected_parser_input_sha256=unknown.parser_input_sha256,
        )
    except RawRequestFinalizationError:
        raise
    except (ResponseContractError, RawRequestAuthorityError, TypeError, ValueError) as exc:
        raise RawRequestFinalizationError(
            "unknown stats response cannot be rederived from its exact public parser input"
        ) from exc
    return None if fallback is None else fallback.frame


def _require_receipt_exact_frame(
    receipt: CommittedStagingChunkReceiptV2,
    frame: pl.DataFrame,
    *,
    label: str,
) -> None:
    try:
        expected_content = frame_content_hash(frame)
        expected_schema = frame_schema_hash(frame)
    except ParserInputCaptureIntegrityError as exc:
        raise RawRequestFinalizationError(f"{label} exact frame cannot be canonicalized") from exc
    if (
        receipt.persisted_row_count != frame.height
        or receipt.content_hash != expected_content
        or receipt.persisted_content_sha256 != expected_content
        or receipt.persisted_schema_sha256 != expected_schema
    ):
        _fail(f"{label} receipt differs from exact parser-input reconstruction")


def _validate_unknown_stats_route_policy(
    pending: Sequence[PendingRawRequestSuccessV2],
    routes: _RouteAuthority,
    receipts: Mapping[str, CommittedStagingChunkReceiptV2],
) -> None:
    """Close the four response-level Video route policies without invented results."""

    if (
        not _is_unknown_stats_route_authority(routes)
        or routes.provider_endpoint_id not in _UNKNOWN_STATS_ENDPOINT_IDS
        or len(routes.static_routes) != 1
    ):
        _fail("unknown stats route policy is outside the exact Video authority")
    fixed_route = routes.static_routes[0]
    if (
        fixed_route.provider_endpoint_id != routes.provider_endpoint_id
        or fixed_route.provider_result_set_name is not None
        or fixed_route.canonical_result_set_ordinal != 0
    ):
        _fail("unknown stats fixed route differs from the exact response-level authority")

    frames: list[pl.DataFrame] = []
    for success in sorted(
        pending,
        key=lambda item: (
            item.attempt.provider_call_ordinal,
            item.attempt.request_ordinal,
        ),
    ):
        frame = _rederive_unknown_stats_fallback(success)
        if frame is not None:
            frames.append(frame)
    expected_frame = (
        None if not frames else frames[0] if len(frames) == 1 else pl.concat(frames, how="vertical")
    )

    conditional_id = None if routes.conditional is None else routes.conditional.route_id
    if expected_frame is None:
        if conditional_id is not None:
            _fail("unknown stats no-drift response invented a conditional route")
    else:
        if conditional_id is None:
            _fail("unknown stats observed drift lacks its conditional lossless route")
        _require_receipt_exact_frame(
            receipts[conditional_id],
            expected_frame,
            label="unknown stats conditional",
        )

    fixed_receipt = receipts[fixed_route.route_id]
    if routes.provider_endpoint_id in _UNKNOWN_STATS_FIXED_ZERO_ENDPOINT_IDS:
        _require_receipt_exact_frame(
            fixed_receipt,
            pl.DataFrame(),
            label="unknown VideoDetails fixed-zero route",
        )
        return
    if expected_frame is None:
        _require_receipt_exact_frame(
            fixed_receipt,
            pl.DataFrame(),
            label="unknown VideoEvents no-drift fixed-zero route",
        )
        return
    _require_receipt_exact_frame(
        fixed_receipt,
        expected_frame,
        label="unknown VideoEvents canonical alias",
    )
    assert conditional_id is not None
    conditional_receipt = receipts[conditional_id]
    if (
        fixed_receipt.persisted_row_count != conditional_receipt.persisted_row_count
        or fixed_receipt.content_hash != conditional_receipt.content_hash
        or fixed_receipt.persisted_content_sha256 != conditional_receipt.persisted_content_sha256
        or fixed_receipt.persisted_schema_sha256 != conditional_receipt.persisted_schema_sha256
    ):
        _fail("unknown VideoEvents fixed and conditional routes are not exact frame aliases")


def _stats_fallback_wide_result_indexes(
    success: PendingRawRequestSuccessV2,
    routes: _RouteAuthority,
) -> dict[str, int]:
    """Rebuild exact fallback receipts and response-wide safe wide membership."""

    body = success.body_object
    if body is None:
        _fail("stats fallback omitted its exact public parser input")
    parser_input = decode_parser_input_object(body)
    contract = pinned_runtime_contracts().get(success.attempt.endpoint_id)
    if contract is None:
        _fail("stats fallback lacks its pinned endpoint contract")
    try:
        if contract.response_mode == "unknown_dynamic_response":
            unknown = rederive_raw_authority_unknown_stats_response(
                endpoint_id=success.attempt.endpoint_id,
                parser_input=parser_input,
                safe_parameters_json=success.attempt.safe_parameters_json,
                provider_authority_sha256=success.attempt.provider_authority_sha256,
                endpoint_contract_sha256_value=(success.attempt.endpoint_contract_sha256),
            )
            duplicate_names: Counter[str] = Counter()
            expected_pending_items: list[PendingResultOccurrenceV2] = []
            for item in unknown.occurrences:
                duplicate_ordinal = duplicate_names[item.name]
                duplicate_names[item.name] += 1
                expected_pending_items.append(
                    PendingResultOccurrenceV2(
                        result_set=item.receipt,
                        duplicate_name_ordinal=duplicate_ordinal,
                        ordered_headers=item.headers,
                    )
                )
            expected_pending = tuple(expected_pending_items)
            safe_rows = ()
        else:
            rederived = rederive_raw_authority_result_sets(
                source_family="stats",
                endpoint_id=success.attempt.endpoint_id,
                parser_input=parser_input,
                provider_authority_sha256=success.attempt.provider_authority_sha256,
                endpoint_contract_sha256_value=(success.attempt.endpoint_contract_sha256),
            )
            expected_pending = tuple(
                PendingResultOccurrenceV2(
                    result_set=item.result_set,
                    duplicate_name_ordinal=item.duplicate_name_ordinal,
                    ordered_headers=item.ordered_headers,
                )
                for item in rederived
            )
            safe_rows = rederive_raw_authority_stats_wide_rows(
                endpoint_id=success.attempt.endpoint_id,
                parser_input=parser_input,
                provider_authority_sha256=success.attempt.provider_authority_sha256,
                endpoint_contract_sha256_value=(success.attempt.endpoint_contract_sha256),
            )
    except (ResponseContractError, RawRequestAuthorityError) as exc:
        raise RawRequestFinalizationError(
            "stats fallback cannot be rederived from its exact public parser input"
        ) from exc
    if expected_pending != success.results:
        _fail("stats fallback result authority differs from exact parser-input rederivation")

    wide_result_indexes: dict[str, int] = {}
    for route in routes.static_routes:
        candidates = tuple(
            item
            for item in safe_rows
            if item.result_set.name == route.provider_result_set_name
            and item.result_set.canonical_index == route.canonical_result_set_ordinal
            and item.ordered_headers == route.provider_columns
        )
        if not candidates:
            if safe_rows:
                _fail("stats fallback safe-wide authority omits a declared route")
            continue
        if len(candidates) != 1:
            _fail("stats fallback safe-wide authority is ambiguous")
        candidate = candidates[0]
        matching_indexes = tuple(
            index
            for index, result in enumerate(success.results)
            if result.result_set.name == candidate.result_set.name
            and result.result_set.provider_index == candidate.result_set.provider_index
            and result.ordered_headers == candidate.ordered_headers
            and result.result_set.row_count == candidate.result_set.row_count
        )
        if len(matching_indexes) != 1:
            _fail("stats fallback safe-wide packet lacks one exact result occurrence")
        wide_result_indexes[route.route_id] = matching_indexes[0]
    return wide_result_indexes


def _live_logical_parameter_check(
    pending: PendingRawRequestSuccessV2,
    binding: LogicalCallReceiptBinding,
    admission: ConditionalLiveStagingRouteAdmission,
) -> None:
    try:
        semantic_parameters = json.loads(pending.attempt.safe_parameters_json)
        if not isinstance(semantic_parameters, dict):
            raise ValueError("semantic parameters are not an object")
        query_by_name = dict(admission.request_parameter_mapping)
        if set(semantic_parameters) != set(query_by_name):
            raise ValueError("semantic parameters differ from live route authority")
        provider_parameters_json = json.dumps(
            {
                query_by_name[name]: semantic_parameters[name]
                for name in sorted(semantic_parameters)
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        observed = admission.logical_parameters_sha256(provider_parameters_json)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RawRequestFinalizationError(
            "live request parameters cannot be joined to logical authority"
        ) from exc
    if observed != binding.logical_parameters_sha256:
        _fail("live request parameters differ from the logical-call binding")


def _build_occurrences(
    *,
    pending: Sequence[PendingRawRequestSuccessV2],
    binding: LogicalCallReceiptBinding,
    routes: _RouteAuthority,
    receipts: Mapping[str, CommittedStagingChunkReceiptV2],
) -> tuple[ResultOccurrenceV2, ...]:
    from nbadb.contracts.staging_route_contract import (
        ConditionalLiveStagingRouteAdmission,
    )

    conditional_id = None if routes.conditional is None else routes.conditional.route_id
    if isinstance(routes.conditional, ConditionalLiveStagingRouteAdmission):
        for item in pending:
            _live_logical_parameter_check(item, binding, routes.conditional)

    unknown_stats_authority = _is_unknown_stats_route_authority(routes)
    if unknown_stats_authority:
        _validate_unknown_stats_route_policy(pending, routes, receipts)

    wide_row_counts: Counter[str] = Counter()
    occurrences: list[ResultOccurrenceV2] = []
    for success in pending:
        _validate_result_family_identity(success, routes)
        fallback_results = [
            item for item in success.results if item.result_set.canonical_index is None
        ]
        stats_fallback = routes.source_family == "stats" and bool(fallback_results)
        if (
            routes.source_family == "stats"
            and not unknown_stats_authority
            and bool(fallback_results) != (conditional_id is not None)
        ):
            _fail("stats result receipts and lossless-fallback route disagree")
        if routes.source_family == "live" and any(
            item.result_set.canonical_index is None for item in success.results
        ):
            _fail("live result occurrence lacks its pinned result ordinal")
        identity_matches_by_route: defaultdict[str, list[int]] = defaultdict(list)
        wide_matches_by_route: defaultdict[str, list[int]] = defaultdict(list)
        declared_route_ids_by_result: defaultdict[int, list[str]] = defaultdict(list)
        wide_route_ids_by_result: defaultdict[int, list[str]] = defaultdict(list)
        fallback_wide_indexes = (
            _stats_fallback_wide_result_indexes(success, routes)
            if stats_fallback and not unknown_stats_authority
            else {}
        )
        for result_index, result in enumerate(success.results):
            for route in routes.static_routes:
                if unknown_stats_authority:
                    continue
                if _route_result_identity_matches(route, result):
                    identity_matches_by_route[route.route_id].append(result_index)
                    declared_route_ids_by_result[result_index].append(route.route_id)
                if (
                    fallback_wide_indexes.get(route.route_id) == result_index
                    if stats_fallback
                    else _wide_route_matches(route, result)
                ):
                    wide_matches_by_route[route.route_id].append(result_index)
                    wide_route_ids_by_result[result_index].append(route.route_id)
        for route in routes.static_routes:
            if unknown_stats_authority:
                continue
            identity_matches = identity_matches_by_route.get(route.route_id, [])
            wide_matches = wide_matches_by_route.get(route.route_id, [])
            if len(identity_matches) != 1 or len(wide_matches) > 1:
                _fail("wide staging route has a missing or ambiguous result occurrence")
            if not wide_matches and (
                routes.source_family != "stats"
                or conditional_id is None
                or not fallback_results
                or receipts[route.route_id].persisted_row_count != 0
            ):
                _fail("unlanded wide staging route lacks exact lossless fallback evidence")

        for occurrence_ordinal, result in enumerate(success.results):
            receipt = result.result_set
            declared_route_ids = tuple(
                sorted(declared_route_ids_by_result.get(occurrence_ordinal, ()))
            )
            wide_route_ids = tuple(sorted(wide_route_ids_by_result.get(occurrence_ordinal, ())))
            for route_id in wide_route_ids:
                wide_row_counts[route_id] += receipt.row_count
            route_ids = tuple(
                sorted(
                    (
                        *declared_route_ids,
                        *((conditional_id,) if conditional_id is not None else ()),
                    )
                )
            )
            landing = _landing_disposition(
                wide_route_ids=wide_route_ids,
                conditional_route_id=conditional_id,
            )
            (
                presence,
                ordered_headers,
                row_count,
                cell_count,
                node_count,
                container_count,
                missing_count,
                null_count,
            ) = _presence_and_counts(result)
            if (
                presence == "missing"
                and any(
                    route.presence_policy == "required"
                    for route in routes.static_routes
                    if route.route_id in declared_route_ids
                )
                and not stats_fallback
            ):
                _fail("required wide staging route has a missing provider result")
            json_path = receipt.json_path
            if routes.source_family == "static":
                json_path = "$"
            try:
                occurrence = ResultOccurrenceV2.build(
                    observation_sha256=success.attempt.observation_sha256,
                    occurrence_ordinal=occurrence_ordinal,
                    result_name=receipt.name,
                    duplicate_name_ordinal=result.duplicate_name_ordinal,
                    provider_result_ordinal=receipt.provider_index,
                    canonical_result_ordinal=receipt.canonical_index,
                    json_path=json_path,
                    container_kind=cast("ResultContainerKind", receipt.container_kind),
                    presence=presence,
                    ordered_headers=ordered_headers,
                    row_count=row_count,
                    cell_count=cell_count,
                    node_count=node_count,
                    container_count=container_count,
                    missing_count=missing_count,
                    null_count=null_count,
                    parent_state_sha256=receipt.parent_occurrence_states_sha256,
                    output_sha256=receipt.normalized_output_sha256,
                    canonical_route_ids=route_ids,
                    committed_staging_receipts=[
                        {
                            "receipt_sha256": receipts[route_id].receipt_root_sha256,
                            "route_id": route_id,
                        }
                        for route_id in route_ids
                    ],
                    landing_disposition=landing,
                )
            except (TypeError, ValueError) as exc:
                raise RawRequestFinalizationError(
                    "result occurrence cannot be represented by the closed raw authority"
                ) from exc
            occurrences.append(occurrence)

    for route in routes.static_routes:
        if not unknown_stats_authority and (
            receipts[route.route_id].persisted_row_count != wide_row_counts[route.route_id]
        ):
            _fail("wide staging receipt row count differs from exact result occurrences")
    if conditional_id is not None and receipts[conditional_id].persisted_row_count < 1:
        _fail("conditional lossless route has no committed public rows")
    return tuple(occurrences)


def _require_receipt_matches_route_derivation(
    receipt: CommittedStagingChunkReceiptV2,
    derivation: RawAuthorityRouteFrameDerivation,
) -> None:
    if (
        receipt.result_route_id != derivation.route_id
        or receipt.staging_key != derivation.staging_key
        or receipt.canonical_frame_format != derivation.canonical_frame_format
        or receipt.frame_content_hash_contract != derivation.frame_content_hash_contract
        or receipt.frame_schema_hash_contract != derivation.frame_schema_hash_contract
        or receipt.persisted_row_count != derivation.row_count
        or receipt.content_hash != derivation.frame_content_sha256
        or receipt.persisted_content_sha256 != derivation.frame_content_sha256
        or receipt.persisted_schema_sha256 != derivation.frame_schema_sha256
    ):
        _fail("committed staging receipt differs from exact route-frame rederivation")


def _ordered_route_ids(routes: _RouteAuthority) -> tuple[str, ...]:
    return tuple(route.route_id for route in routes.static_routes) + (
        () if routes.conditional is None else (routes.conditional.route_id,)
    )


def _resolve_live_plan_snapshot_at(
    *,
    pending: Sequence[PendingRawRequestSuccessV2],
    routes: _RouteAuthority,
    live_plan_authority: LiveSnapshotPlanAuthorityV2 | None,
    expected_live_plan_authority_sha256: str | None,
    plan_live_snapshot_at: datetime | None,
) -> datetime | None:
    """Join one live call to an independently rooted sealed-plan projection."""

    if plan_live_snapshot_at is not None:
        _fail("a bare live plan timestamp is not an admissible sealed-plan authority")
    if routes.source_family != "live":
        if live_plan_authority is not None or expected_live_plan_authority_sha256 is not None:
            _fail("non-live request closure received live sealed-plan authority")
        return None
    if len(pending) != 1:
        _fail("live sealed-plan authority requires one terminal response observation")
    if type(live_plan_authority) is not LiveSnapshotPlanAuthorityV2:
        _fail("live request closure lacks its exact sealed-plan authority")
    if (
        type(expected_live_plan_authority_sha256) is not str
        or _SHA256_RE.fullmatch(expected_live_plan_authority_sha256) is None
    ):
        _fail("live request closure lacks an independent sealed-plan authority digest")
    try:
        rebuilt = LiveSnapshotPlanAuthorityV2(
            **{
                field.name: getattr(live_plan_authority, field.name)
                for field in fields(LiveSnapshotPlanAuthorityV2)
            }
        )
    except (AttributeError, TypeError, ValueError, RawRequestReconstructionError) as exc:
        raise RawRequestFinalizationError(
            "live sealed-plan authority failed strict reconstruction"
        ) from exc
    if rebuilt != live_plan_authority:
        _fail("live sealed-plan authority changed during strict reconstruction")
    if rebuilt.authority_sha256 != expected_live_plan_authority_sha256:
        _fail("live sealed-plan authority differs from its independent receipt")

    attempt = pending[0].attempt
    if (
        rebuilt.source_sha != attempt.source_sha
        or rebuilt.run_id != attempt.run_id
        or rebuilt.run_attempt != attempt.run_attempt
        or rebuilt.chain_id != attempt.chain_id
        or rebuilt.lane_id != attempt.lane_id
        or rebuilt.observation_sha256 != attempt.observation_sha256
        or rebuilt.scope_sha256 != attempt.scope_sha256
        or rebuilt.safe_parameters_sha256 != attempt.safe_parameters_sha256
        or rebuilt.endpoint_id != attempt.endpoint_id
        or rebuilt.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
        or rebuilt.provider_authority_sha256 != attempt.provider_authority_sha256
        or rebuilt.route_ids != _ordered_route_ids(routes)
    ):
        _fail("live sealed-plan authority crosses its exact request or route inventory")
    snapshot_at = rebuilt.live_snapshot_at
    if type(snapshot_at) is not datetime or snapshot_at.tzinfo is not UTC or snapshot_at.fold != 0:
        _fail("live sealed-plan snapshot must be the exact built-in UTC datetime")
    return snapshot_at


def _rederive_static_or_live_route_frames(
    *,
    success: PendingRawRequestSuccessV2,
    binding: LogicalCallReceiptBinding,
    routes: _RouteAuthority,
    receipts: Mapping[str, CommittedStagingChunkReceiptV2],
    occurrences: Sequence[ResultOccurrenceV2],
    live_snapshot_at: datetime | None,
) -> dict[str, RawAuthorityRouteFrameDerivation]:
    if routes.source_family not in {"static", "live"}:
        if live_snapshot_at is not None:
            _fail("non-live request closure received a live plan timestamp")
        return {}
    if routes.source_family == "live":
        if (
            type(live_snapshot_at) is not datetime
            or live_snapshot_at.tzinfo is None
            or live_snapshot_at.utcoffset() != timedelta(0)
        ):
            _fail("live request closure lacks its validated aware UTC plan timestamp")
        live_snapshot_at = live_snapshot_at.astimezone(UTC)
        if success.body_object is None:
            _fail("live request closure omitted its exact parser input")
        parser_input = decode_parser_input_object(success.body_object)
    else:
        if live_snapshot_at is not None:
            _fail("static request closure received a live plan timestamp")
        live_snapshot_at = None
        parser_input = None

    try:
        derived = rederive_raw_authority_route_frames(
            source_family=routes.source_family,
            endpoint_name=binding.endpoint_name,
            endpoint_id=routes.provider_endpoint_id,
            selected_route_ids=binding.result_route_ids,
            parser_input=parser_input,
            safe_parameters_json=success.attempt.safe_parameters_json,
            provider_authority_sha256=binding.provider_authority_sha256,
            endpoint_contract_sha256_value=routes.endpoint_contract_sha256,
            capture_response_receipt_sha256=success.private_receipt_sha256,
            live_snapshot_at=live_snapshot_at,
        )
    except (
        ParserInputCaptureIntegrityError,
        RawRequestAuthorityError,
        ResponseContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise RawRequestFinalizationError(
            "static/live route frames cannot be rederived from exact capture authority"
        ) from exc

    ordered_route_ids = _ordered_route_ids(routes)
    if tuple(item.route_id for item in derived) != ordered_route_ids:
        _fail("static/live route-frame inventory differs from canonical route order")
    by_route = {item.route_id: item for item in derived}
    if len(by_route) != len(derived) or set(by_route) != set(receipts):
        _fail("static/live route-frame inventory differs from committed receipts")

    fixed_contracts = {route.route_id: route.contract_sha256 for route in routes.static_routes}
    if routes.conditional is not None:
        fixed_contracts[routes.conditional.route_id] = routes.conditional.contract_sha256
    for route_id, derivation in by_route.items():
        if (
            derivation.route_contract_sha256 != fixed_contracts[route_id]
            or derivation.capture_response_receipt_sha256 != success.private_receipt_sha256
            or derivation.logical_parameters_sha256 != binding.logical_parameters_sha256
        ):
            _fail("static/live route-frame derivation crosses capture or route authority")
        _require_receipt_matches_route_derivation(receipts[route_id], derivation)
        source_ordinals = tuple(
            item.occurrence_ordinal
            for item in occurrences
            if route_id in item.canonical_route_ids()
        )
        if source_ordinals != derivation.source_result_ordinals:
            _fail("static/live route-frame source ordinals differ from result authority")
    return by_route


def _build_route_landings(
    *,
    pending: Sequence[PendingRawRequestSuccessV2],
    occurrences: Sequence[ResultOccurrenceV2],
    binding: LogicalCallReceiptBinding,
    routes: _RouteAuthority,
    receipts: Mapping[str, CommittedStagingChunkReceiptV2],
    live_snapshot_at: datetime | None,
) -> tuple[ObservationRouteLandingV2, ...]:
    # A committed receipt is route-unique and the V2 landing row is
    # observation-local.  Aggregated multi-response receipts cannot be split
    # into observation receipts without inventing post-commit authority.
    if len(pending) != 1:
        _fail("route-unique committed receipts require one terminal response observation")
    success = pending[0]
    observation_sha256 = success.attempt.observation_sha256
    observation_occurrences = tuple(
        sorted(
            (item for item in occurrences if item.observation_sha256 == observation_sha256),
            key=lambda item: item.occurrence_ordinal,
        )
    )
    _rederive_static_or_live_route_frames(
        success=success,
        binding=binding,
        routes=routes,
        receipts=receipts,
        occurrences=observation_occurrences,
        live_snapshot_at=live_snapshot_at,
    )
    if routes.source_family != "live" and live_snapshot_at is not None:
        _fail("non-live request closure received a live plan timestamp")
    normalized_snapshot_at = (
        cast("datetime", live_snapshot_at).astimezone(UTC)
        if routes.source_family == "live"
        else None
    )

    landings: list[ObservationRouteLandingV2] = []
    route_ordinal = 0
    for route in routes.static_routes:
        source_rows = tuple(
            item for item in observation_occurrences if route.route_id in item.canonical_route_ids()
        )
        semantic: RouteLandingSemantic = "occurrence_bound"
        alias_target: str | None = None
        if _is_unknown_stats_route_authority(routes):
            if (
                routes.provider_endpoint_id in _UNKNOWN_STATS_FIXED_ZERO_ENDPOINT_IDS
                or routes.conditional is None
            ):
                semantic = "response_fixed_zero"
            else:
                semantic = "response_canonical_alias"
                alias_target = routes.conditional.route_id
        try:
            landings.append(
                ObservationRouteLandingV2.build(
                    observation_sha256=observation_sha256,
                    logical_receipt_sha256=binding.logical_call_receipt_sha256,
                    route_ordinal=route_ordinal,
                    route_authority_kind=cast("RouteAuthorityKind", "staging_route_contract_v1"),
                    route_authority_sha256=route.contract_sha256,
                    landing_semantic=semantic,
                    conditional_lossless=False,
                    alias_target_route_id=alias_target,
                    live_snapshot_at=normalized_snapshot_at,
                    source_occurrence_sha256s=[item.occurrence_sha256 for item in source_rows],
                    committed_receipt=receipts[route.route_id],
                )
            )
        except (TypeError, ValueError) as exc:
            raise RawRequestFinalizationError(
                "fixed route landing cannot be represented by exact post-commit authority"
            ) from exc
        route_ordinal += 1

    if routes.conditional is not None:
        conditional = routes.conditional
        source_rows = tuple(
            item
            for item in observation_occurrences
            if conditional.route_id in item.canonical_route_ids()
        )
        try:
            landings.append(
                ObservationRouteLandingV2.build(
                    observation_sha256=observation_sha256,
                    logical_receipt_sha256=binding.logical_call_receipt_sha256,
                    route_ordinal=route_ordinal,
                    route_authority_kind=cast(
                        "RouteAuthorityKind", "conditional_staging_route_admission_v1"
                    ),
                    route_authority_sha256=conditional.contract_sha256,
                    landing_semantic="conditional_lossless",
                    conditional_lossless=True,
                    alias_target_route_id=None,
                    live_snapshot_at=normalized_snapshot_at,
                    source_occurrence_sha256s=[item.occurrence_sha256 for item in source_rows],
                    committed_receipt=receipts[conditional.route_id],
                )
            )
        except (TypeError, ValueError) as exc:
            raise RawRequestFinalizationError(
                "conditional route landing cannot be represented by exact post-commit authority"
            ) from exc
    return tuple(landings)


def _build_terminal_observations(
    pending: Sequence[PendingRawRequestSuccessV2],
    occurrences: Sequence[ResultOccurrenceV2],
    landings: Sequence[ObservationRouteLandingV2],
    binding: LogicalCallReceiptBinding,
    logical_provider_parameter_binding: LogicalProviderParameterBindingV1 | None,
) -> tuple[RequestObservationV2, ...]:
    by_observation: defaultdict[str, list[ResultOccurrenceV2]] = defaultdict(list)
    for occurrence in occurrences:
        by_observation[occurrence.observation_sha256].append(occurrence)
    landings_by_observation: defaultdict[str, list[ObservationRouteLandingV2]] = defaultdict(list)
    for landing in landings:
        landings_by_observation[landing.observation_sha256].append(landing)
    observations: list[RequestObservationV2] = []
    for success in pending:
        rows = sorted(
            by_observation[success.attempt.observation_sha256],
            key=lambda item: item.occurrence_ordinal,
        )
        if len(rows) != len(success.results):
            _fail("pending success did not produce one row per result occurrence")
        landing_rows = sorted(
            landings_by_observation[success.attempt.observation_sha256],
            key=lambda item: item.route_ordinal,
        )
        if not landing_rows:
            _fail("pending success did not produce response-level route landings")
        body_sha256 = None if success.body_object is None else success.body_object.object_sha256
        bodyless_sha256 = None
        if success.body_object is None:
            bodyless_sha256 = hashlib.sha256(
                json.dumps(
                    {
                        "attempt_sha256": success.attempt.attempt_sha256,
                        "body_disposition": success.body_disposition,
                        "private_receipt_sha256": success.private_receipt_sha256,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        try:
            observations.append(
                RequestObservationV2.build(
                    attempt=success.attempt,
                    transport=success.transport,
                    started_at=success.started_at,
                    finished_at=success.finished_at,
                    elapsed_ns=success.elapsed_ns,
                    lifecycle="selected_terminal",
                    outcome=success.outcome,
                    failure_class=None,
                    root_exception_class=None,
                    body_disposition=success.body_disposition,
                    body_object_sha256=body_sha256,
                    bodyless_evidence_sha256=bodyless_sha256,
                    result_occurrence_sha256s=[item.occurrence_sha256 for item in rows],
                    route_landing_sha256s=[item.landing_sha256 for item in landing_rows],
                    capture_response_receipt_sha256=success.private_receipt_sha256,
                    logical_receipt_sha256=binding.logical_call_receipt_sha256,
                    logical_provider_parameter_binding_sha256=(
                        None
                        if logical_provider_parameter_binding is None
                        else logical_provider_parameter_binding.binding_sha256
                    ),
                    logical_provider_parameter_binding_json=(
                        None
                        if logical_provider_parameter_binding is None
                        else logical_provider_parameter_binding.canonical_bytes().decode(
                            "utf-8",
                            errors="strict",
                        )
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            raise RawRequestFinalizationError(
                "pending success cannot become a terminal request observation"
            ) from exc
    return tuple(observations)


def finalize_raw_request_capture(
    snapshot: RawRequestCaptureSnapshotV2,
    binding: LogicalCallReceiptBinding,
    committed_receipts: tuple[CommittedStagingChunkReceiptV2, ...],
    *,
    live_plan_authority: LiveSnapshotPlanAuthorityV2 | None = None,
    expected_live_plan_authority_sha256: str | None = None,
    logical_provider_parameter_binding: LogicalProviderParameterBindingV1 | None = None,
    expected_logical_provider_parameter_binding_sha256: str | None = None,
    plan_live_snapshot_at: datetime | None = None,
) -> RawRequestAuthorityBundleV2:
    """Close one exact raw-request snapshot after staging readback succeeds.

    The function performs no filesystem, database, network, clock, or mutable
    registry operation.  Every output fact is a deterministic join of the
    supplied immutable capture rows, the current pinned route authority, and
    exact committed staging receipts.  Live responses additionally require an
    exact ``LiveSnapshotPlanAuthorityV2`` and a separately supplied authority
    digest rooted in durable sealed-plan/control-plane evidence.  The legacy
    bare timestamp argument is retained only as an explicit fail-closed trap
    while production call sites migrate; it is never accepted as authority.
    """

    parsed_binding = _revalidate_binding(binding)
    route_authority = _resolve_route_authority(parsed_binding)
    receipt_by_route = _receipt_inventory(
        parsed_binding,
        route_authority,
        committed_receipts,
    )
    objects, existing_observations, pending = _validate_snapshot(
        snapshot,
        pending_policy="required",
    )
    parameter_binding = _validate_attempt_closure(
        observations=existing_observations,
        pending=pending,
        binding=parsed_binding,
        routes=route_authority,
        logical_provider_parameter_binding=logical_provider_parameter_binding,
        expected_logical_provider_parameter_binding_sha256=(
            expected_logical_provider_parameter_binding_sha256
        ),
    )

    _validate_object_closure(
        objects=objects,
        observations=existing_observations,
        pending=pending,
    )
    validated_live_snapshot_at = _resolve_live_plan_snapshot_at(
        pending=pending,
        routes=route_authority,
        live_plan_authority=live_plan_authority,
        expected_live_plan_authority_sha256=expected_live_plan_authority_sha256,
        plan_live_snapshot_at=plan_live_snapshot_at,
    )

    occurrences = _build_occurrences(
        pending=pending,
        binding=parsed_binding,
        routes=route_authority,
        receipts=receipt_by_route,
    )
    landings = _build_route_landings(
        pending=pending,
        occurrences=occurrences,
        binding=parsed_binding,
        routes=route_authority,
        receipts=receipt_by_route,
        live_snapshot_at=validated_live_snapshot_at,
    )
    terminal_observations = _build_terminal_observations(
        pending,
        occurrences,
        landings,
        parsed_binding,
        parameter_binding,
    )
    all_observations = (*existing_observations, *terminal_observations)
    try:
        bundle = RawRequestAuthorityBundleV2.build(
            objects=tuple(sorted(objects, key=lambda item: item.object_sha256)),
            observations=tuple(
                sorted(
                    all_observations,
                    key=lambda item: (
                        item.attempt.retry_ordinal,
                        item.attempt.request_ordinal,
                        item.attempt.observation_sha256,
                    ),
                )
            ),
            occurrences=tuple(
                sorted(
                    occurrences,
                    key=lambda item: (
                        item.observation_sha256,
                        item.occurrence_ordinal,
                    ),
                )
            ),
            landings=tuple(
                sorted(
                    landings,
                    key=lambda item: (
                        item.observation_sha256,
                        item.route_ordinal,
                    ),
                )
            ),
        )
        bundle.require_complete_terminal_selection()
    except (TypeError, ValueError) as exc:
        raise RawRequestFinalizationError(
            "raw-request post-commit authority is not closed"
        ) from exc
    return bundle


def materialize_raw_request_failure_snapshot(
    snapshot: RawRequestCaptureSnapshotV2,
) -> RawRequestAuthorityBundleV2:
    """Materialize completed unresolved attempts without claiming route success.

    Failure-only bundles deliberately contain no result occurrences and no
    selected-terminal observation.  They are valid public persistence payloads,
    but ``require_complete_terminal_selection`` continues to fail for them.
    """

    objects, observations, pending = _validate_snapshot(
        snapshot,
        pending_policy="forbidden",
    )
    if not observations or not any(
        item.lifecycle == "incomplete" and item.finished_at is not None for item in observations
    ):
        _fail("failure-only raw-request snapshot has no completed observation")
    attempts = [item.attempt for item in observations]
    if len({_attempt_context_key(item) for item in attempts}) != 1:
        _fail("failure-only raw-request attempts cross logical execution contexts")
    coordinates = [(item.retry_ordinal, item.request_ordinal) for item in attempts]
    if len(coordinates) != len(set(coordinates)):
        _fail("failure-only raw-request attempts repeat a retry/request coordinate")
    retry_requests: defaultdict[int, set[int]] = defaultdict(set)
    for retry_ordinal, request_ordinal in coordinates:
        retry_requests[retry_ordinal].add(request_ordinal)
    if any(sorted(values) != list(range(len(values))) for values in retry_requests.values()):
        _fail("failure-only raw-request attempts are not contiguous within a retry")
    _validate_object_closure(
        objects=objects,
        observations=observations,
        pending=pending,
    )
    try:
        bundle = RawRequestAuthorityBundleV2.build(
            objects=tuple(sorted(objects, key=lambda item: item.object_sha256)),
            observations=tuple(
                sorted(
                    observations,
                    key=lambda item: (
                        item.attempt.retry_ordinal,
                        item.attempt.request_ordinal,
                        item.attempt.observation_sha256,
                    ),
                )
            ),
            occurrences=(),
            landings=(),
        )
    except (TypeError, ValueError) as exc:
        raise RawRequestFinalizationError("failure-only raw-request authority is invalid") from exc
    if not bundle.incomplete_provider_call_sha256s():
        _fail("failure-only raw-request authority lost its explicit incompleteness")
    return bundle


def materialize_raw_request_incomplete_success_snapshot(
    snapshot: RawRequestCaptureSnapshotV2,
    binding: LogicalCallReceiptBinding,
    committed_receipts: tuple[CommittedStagingChunkReceiptV2, ...],
    *,
    logical_provider_parameter_binding: LogicalProviderParameterBindingV1 | None = None,
    expected_logical_provider_parameter_binding_sha256: str | None = None,
) -> RawRequestAuthorityBundleV2:
    """Persist one lossless stats response whose result identity is unprovable.

    A dynamic stats response can be valid JSON and therefore eligible for the
    conditional lossless landing while exposing no named ``resultSets``
    occurrence. Such a response must survive staging, but it must never be
    promoted to a selected terminal observation or assigned an invented result
    identity. This function admits only that exact post-commit state and turns
    it into explicit, body-bearing incomplete authority.
    """

    parsed_binding = _revalidate_binding(binding)
    route_authority = _resolve_route_authority(parsed_binding)
    receipt_by_route = _receipt_inventory(
        parsed_binding,
        route_authority,
        committed_receipts,
    )
    if type(snapshot) is not RawRequestCaptureSnapshotV2:
        _fail("raw-request snapshot does not have its exact contract type")
    if any(
        type(values) is not tuple
        for values in (
            snapshot.objects,
            snapshot.observations,
            snapshot.pending_successes,
            snapshot.issues,
        )
    ):
        _fail("raw-request snapshot inventories must be exact tuples")
    if len(snapshot.pending_successes) != 1 or len(snapshot.issues) != 1:
        _fail("result-authority-pending snapshot is not singular")

    issue = snapshot.issues[0]
    if type(issue) is not RawRequestCaptureIssueV2:
        _fail("result-authority-pending issue does not have its exact contract type")
    pending = _validate_pending_success(
        snapshot.pending_successes[0],
        result_policy="forbidden",
    )
    if (
        issue.code != "success_result_authority_pending"
        or issue.retry_ordinal != pending.attempt.retry_ordinal
        or issue.request_ordinal != pending.attempt.request_ordinal
        or issue.root_exception_class is not None
    ):
        _fail("result-authority-pending issue differs from its exact request attempt")

    objects = tuple(_safe_object(item) for item in snapshot.objects)
    observations = tuple(_safe_observation(item) for item in snapshot.observations)
    if any(item.lifecycle == "selected_terminal" for item in observations):
        _fail("raw-request snapshot already contains a selected terminal observation")
    if not _is_unknown_stats_route_authority(route_authority):
        _fail("result-authority-pending success is not an exact unknown stats response")
    if (
        route_authority.conditional is not None
        and route_authority.conditional.staging_key != LOSSLESS_FALLBACK_STAGING_KEY
    ):
        _fail("result-authority-pending success has a foreign conditional route")
    _validate_unknown_stats_route_policy(
        (pending,),
        route_authority,
        receipt_by_route,
    )

    _validate_attempt_closure(
        observations=observations,
        pending=(pending,),
        binding=parsed_binding,
        routes=route_authority,
        logical_provider_parameter_binding=logical_provider_parameter_binding,
        expected_logical_provider_parameter_binding_sha256=(
            expected_logical_provider_parameter_binding_sha256
        ),
    )
    _validate_object_closure(
        objects=objects,
        observations=observations,
        pending=(pending,),
    )
    if pending.body_object is None:
        _fail("result-authority-pending success lacks its exact parser input")
    try:
        incomplete = RequestObservationV2.build(
            attempt=pending.attempt,
            transport=pending.transport,
            started_at=pending.started_at,
            finished_at=pending.finished_at,
            elapsed_ns=pending.elapsed_ns,
            lifecycle="incomplete",
            outcome="downstream_incomplete",
            failure_class="response_contract",
            root_exception_class="ResponseContractError",
            body_disposition="public_parser_input",
            body_object_sha256=pending.body_object.object_sha256,
            bodyless_evidence_sha256=None,
            result_occurrence_sha256s=(),
            route_landing_sha256s=(),
            capture_response_receipt_sha256=pending.private_receipt_sha256,
            logical_receipt_sha256=None,
        )
    except (TypeError, ValueError) as exc:
        raise RawRequestFinalizationError(
            "result-authority-pending success cannot become incomplete authority"
        ) from exc

    return materialize_raw_request_failure_snapshot(
        RawRequestCaptureSnapshotV2(
            objects=objects,
            observations=(*observations, incomplete),
            pending_successes=(),
            issues=(),
        )
    )
