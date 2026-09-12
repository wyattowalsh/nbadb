"""Transparent public raw-request capture at the shared provider boundary.

This module decorates the existing private Bronze sink.  It records only facts
available before transactional staging and deliberately leaves successful
observations pending until a route-aware writer can bind each result occurrence
to its committed staging receipts.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from nbadb.contracts.raw_request_authority import (
    FailureClass,
    ParserInputObjectV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    canonical_json_bytes,
    canonical_semantic_parameters,
)
from nbadb.contracts.raw_transport_contract import RawTransportV1, validate_raw_transport
from nbadb.core.extraction_failures import safe_root_error_type
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_request_surface import pinned_request_surface_authority
from nbadb.core.nba_api_runtime_contract import (
    pinned_live_contracts,
    pinned_runtime_contracts,
    pinned_static_dataset_contract,
)
from nbadb.extract.bronze import (
    CapturedParserInput,
    Outcome,
    ParserInputCaptureSink,
    ParserInputContext,
    RecordedParserInput,
    ResultSetReceipt,
    TransportKind,
)
from nbadb.extract.nba_api_adapter import (
    NbaApiCaptureContract,
    rederive_raw_authority_result_sets,
    rederive_raw_authority_unknown_stats_response,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "PendingRawRequestSuccessV2",
    "PendingResultOccurrenceV2",
    "RawProviderCallContextV2",
    "RawRequestCaptureContextV2",
    "RawRequestCaptureContract",
    "RawRequestCaptureIssueV2",
    "RawRequestCaptureSink",
    "RawRequestCaptureSnapshotV2",
    "wrap_raw_request_capture_contract",
]

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
SafeId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}$"),
]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
PositiveInt = Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]
_FORBIDDEN_IDENTITY_RE = re.compile(
    r"(?:authorization|cookie|credential|header|password|proxy|secret|token|vpn|"
    r"(?:^|[._:-])(?:path|host|ip)(?:$|[._:-]))",
    re.IGNORECASE,
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
    )


class RawProviderCallContextV2(_StrictFrozenModel):
    """Caller-owned identity for one request ordinal across bounded retries."""

    request_ordinal: NonNegativeInt
    semantic_request_sha256: Sha256
    logical_invocation_sha256: Sha256
    provider_call_role: SafeId
    provider_call_ordinal: NonNegativeInt
    source_family: Literal["stats", "live", "static"]
    endpoint_id: SafeId
    provider_request_sha256: Sha256
    endpoint_contract_sha256: Sha256
    competition_id: SafeId | None = None
    competition_identity_sha256: Sha256 | None = None
    scope_sha256: Sha256
    pagination_sha256: Sha256 | None = None
    page_ordinal: NonNegativeInt | None = None

    @model_validator(mode="after")
    def _validate_pairs(self) -> Self:
        public_ids = (self.provider_call_role, self.endpoint_id, self.competition_id)
        if any(value is not None and _FORBIDDEN_IDENTITY_RE.search(value) for value in public_ids):
            raise ValueError("provider call context contains a prohibited public identifier")
        if (self.competition_id is None) != (self.competition_identity_sha256 is None):
            raise ValueError("competition identity must be wholly present or absent")
        if (self.pagination_sha256 is None) != (self.page_ordinal is None):
            raise ValueError("pagination identity must be wholly present or absent")
        return self


class RawRequestCaptureContextV2(_StrictFrozenModel):
    """Complete public authority supplied before any provider request begins."""

    provider_authority_sha256: Sha256
    source_sha: GitSha
    run_id: PositiveInt
    run_attempt: PositiveInt
    chain_id: SafeId
    lane_id: SafeId
    provider_calls: tuple[RawProviderCallContextV2, ...]

    @model_validator(mode="after")
    def _validate_calls(self) -> Self:
        if any(_FORBIDDEN_IDENTITY_RE.search(value) for value in (self.chain_id, self.lane_id)):
            raise ValueError("capture context contains a prohibited public identifier")
        ordinals = tuple(item.request_ordinal for item in self.provider_calls)
        if not ordinals or ordinals != tuple(range(len(ordinals))):
            raise ValueError("provider call request ordinals must be contiguous from zero")
        return self

    def call_for(self, request_ordinal: int) -> RawProviderCallContextV2:
        if request_ordinal < 0 or request_ordinal >= len(self.provider_calls):
            raise ValueError("request ordinal has no explicit public call authority")
        return self.provider_calls[request_ordinal]


@dataclass(frozen=True, slots=True)
class PendingResultOccurrenceV2:
    """Exact parser result evidence awaiting route-specific staging receipts."""

    result_set: ResultSetReceipt
    duplicate_name_ordinal: int
    ordered_headers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PendingRawRequestSuccessV2:
    """Parsed success that cannot yet claim transactional route completion."""

    private_receipt_sha256: str
    attempt: RequestAttemptIdentityV2
    transport: RawTransportV1
    started_at: datetime
    finished_at: datetime
    elapsed_ns: int
    outcome: Literal["success_nonempty", "success_empty", "static_snapshot_success"]
    body_disposition: Literal["public_parser_input", "declared_bodyless"]
    body_object: ParserInputObjectV2 | None
    results: tuple[PendingResultOccurrenceV2, ...]
    logical_receipt_sha256: str | None = None
    aggregate_route_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RawRequestCaptureIssueV2:
    """Public-safe fail-closed reason why a sidecar row was not emitted."""

    code: str
    retry_ordinal: int | None
    request_ordinal: int | None
    root_exception_class: str | None


@dataclass(frozen=True, slots=True)
class RawRequestCaptureSnapshotV2:
    """Immutable pre-transaction evidence exposed to the staging boundary."""

    objects: tuple[ParserInputObjectV2, ...]
    observations: tuple[RequestObservationV2, ...]
    pending_successes: tuple[PendingRawRequestSuccessV2, ...]
    issues: tuple[RawRequestCaptureIssueV2, ...]

    @property
    def requires_transactional_finalization(self) -> bool:
        return bool(self.pending_successes)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_digest(value: object) -> str:
    return _sha256(canonical_json_bytes(value))


def _headers_sha256(headers: Sequence[str]) -> str:
    return _sha256(json.dumps(list(headers), separators=(",", ":")).encode())


def _semantic_parameters(
    source_family: str,
    endpoint_id: str,
    wire_parameters: Mapping[str, Any],
) -> tuple[dict[str, object], str]:
    if source_family == "static":
        if wire_parameters:
            raise ValueError("static request authority cannot contain parameters")
        _json, _digest, provider_request_sha256 = canonical_semantic_parameters(
            "static", endpoint_id, {}
        )
        return {}, provider_request_sha256

    source = cast("Literal['stats', 'live']", source_family)
    endpoint = pinned_request_surface_authority().endpoint(source, endpoint_id)
    by_query_name = {item.query_name: item.name for item in endpoint.parameters}
    if len(by_query_name) != len(endpoint.parameters) or set(wire_parameters) - set(by_query_name):
        raise ValueError("provider parameters differ from the pinned request surface")
    semantic = {by_query_name[name]: value for name, value in wire_parameters.items()}
    _json, _digest, provider_request_sha256 = canonical_semantic_parameters(
        source,
        endpoint_id,
        semantic,
    )
    return semantic, provider_request_sha256


def _result_headers(
    source_family: str,
    endpoint_id: str,
    parser_input: str | None,
    receipt: ResultSetReceipt,
) -> tuple[str, ...]:
    if source_family == "stats":
        raise ValueError("stats ordered headers require exact-body rederivation")
    if source_family == "live":
        contract = pinned_live_contracts()[endpoint_id]
        matches = tuple(
            tuple(field.name for field in result.fields)
            for result in contract.result_sets
            if result.name == receipt.name
        )
        if len(matches) != 1:
            raise ValueError("live result has no unique pinned header authority")
        headers = matches[0]
    else:
        contract = pinned_static_dataset_contract(endpoint_id)
        headers = tuple(field.name for field in contract.raw_fields)
    if _headers_sha256(headers) != receipt.headers_sha256:
        raise ValueError("ordered result headers differ from their receipt")
    return headers


class RawRequestCaptureSink(ParserInputCaptureSink):
    """Thread-safe transparent decorator for provisional public authority."""

    def __init__(
        self,
        delegate: ParserInputCaptureSink,
        context: RawRequestCaptureContextV2 | None,
        *,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic_ns: Callable[[], int] | None = None,
    ) -> None:
        self._delegate = delegate
        self._context = context
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._lock = threading.RLock()
        self._starts: dict[tuple[int, int], tuple[datetime, int]] = {}
        self._parser_inputs: dict[str, list[str]] = {}
        self._objects: dict[str, ParserInputObjectV2] = {}
        self._observations: dict[str, RequestObservationV2] = {}
        self._pending: dict[str, PendingRawRequestSuccessV2] = {}
        self._issues: list[RawRequestCaptureIssueV2] = []

    def begin_request(self, context: ParserInputContext) -> None:
        with self._lock:
            self._starts[(context.retry_ordinal, context.request_ordinal)] = (
                self._wall_clock(),
                self._monotonic_ns(),
            )

    def _issue(
        self,
        code: str,
        context: ParserInputContext | None,
        exc: BaseException | None = None,
    ) -> None:
        self._issues.append(
            RawRequestCaptureIssueV2(
                code=code,
                retry_ordinal=None if context is None else context.retry_ordinal,
                request_ordinal=None if context is None else context.request_ordinal,
                root_exception_class=None if exc is None else safe_root_error_type(exc),
            )
        )

    def _guard(
        self,
        code: str,
        context: ParserInputContext,
        operation: Callable[[], None],
    ) -> None:
        with self._lock:
            try:
                operation()
            except Exception as exc:  # public sidecar must not alter extraction behavior
                self._issue(code, context, exc)

    def _timing(self, context: ParserInputContext) -> tuple[datetime, datetime, int]:
        finished_at = self._wall_clock()
        finished_ns = self._monotonic_ns()
        started_at, started_ns = self._starts.pop(
            (context.retry_ordinal, context.request_ordinal),
            (finished_at, finished_ns),
        )
        return started_at, finished_at, max(0, finished_ns - started_ns)

    def _take_parser_input(self, object_sha256: str) -> str:
        parser_inputs = self._parser_inputs.get(object_sha256)
        if not parser_inputs:
            raise ValueError("exact parser input was not retained for this response")
        parser_input = parser_inputs.pop()
        if not parser_inputs:
            del self._parser_inputs[object_sha256]
        return parser_input

    def _discard_parser_input(self, object_sha256: str) -> None:
        parser_inputs = self._parser_inputs.get(object_sha256)
        if not parser_inputs:
            return
        parser_inputs.pop()
        if not parser_inputs:
            del self._parser_inputs[object_sha256]

    def _attempt(
        self,
        *,
        context: ParserInputContext,
        source_family: str,
        endpoint_id: str,
        parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        contract_sha256: str,
    ) -> RequestAttemptIdentityV2:
        public = self._context
        if public is None:
            raise ValueError("explicit public capture context is absent")
        expected_authority = expected_nba_api_provider_authority()
        provider_contract = cast("dict[str, object]", expected_authority["provider_contract"])
        distribution_name = cast("str", provider_contract["distribution_name"])
        distribution_version = cast("str", provider_contract["distribution_version"])
        if (
            importlib.metadata.version(distribution_name) != distribution_version
            or provider_authority_sha256 != expected_authority["authority_sha256"]
            or provider_authority_sha256 != public.provider_authority_sha256
        ):
            raise ValueError("installed provider authority differs from public capture context")
        if (
            context.workflow_run_id != public.run_id
            or context.workflow_run_attempt != public.run_attempt
            or context.chain_id != public.chain_id
            or context.lane_id != public.lane_id
            or context.semantic_source_sha != public.source_sha
        ):
            raise ValueError("private and public execution provenance differ")
        call = public.call_for(context.request_ordinal)
        if (
            call.source_family != source_family
            or call.endpoint_id != endpoint_id
            or call.endpoint_contract_sha256 != contract_sha256
        ):
            raise ValueError("runtime call differs from explicit public call authority")
        semantic_parameters, provider_request_sha256 = _semantic_parameters(
            source_family,
            endpoint_id,
            parameters,
        )
        if provider_request_sha256 != call.provider_request_sha256:
            raise ValueError("runtime request differs from explicit provider request authority")
        return RequestAttemptIdentityV2.build(
            semantic_request_sha256=call.semantic_request_sha256,
            logical_invocation_sha256=call.logical_invocation_sha256,
            provider_call_role=call.provider_call_role,
            provider_call_ordinal=call.provider_call_ordinal,
            retry_ordinal=context.retry_ordinal,
            request_ordinal=context.request_ordinal,
            source_family=cast("Literal['stats', 'live', 'static']", source_family),
            endpoint_id=endpoint_id,
            parameters=semantic_parameters,
            provider_authority_sha256=provider_authority_sha256,
            endpoint_contract_sha256=contract_sha256,
            competition_id=call.competition_id,
            competition_identity_sha256=call.competition_identity_sha256,
            scope_sha256=call.scope_sha256,
            pagination_sha256=call.pagination_sha256,
            page_ordinal=call.page_ordinal,
            source_sha=public.source_sha,
            run_id=public.run_id,
            run_attempt=public.run_attempt,
            chain_id=public.chain_id,
            lane_id=public.lane_id,
        )

    @staticmethod
    def _transport(
        source_family: str,
        status_code: int | None,
        effective_status_code: int | None,
    ) -> RawTransportV1:
        if source_family == "static":
            return validate_raw_transport({"transport_kind": "static_snapshot"})
        return validate_raw_transport(
            {
                "transport_kind": f"{source_family}_http",
                "status_code": status_code,
                "effective_status_code": effective_status_code,
            }
        )

    def replay_parser_input(self, receipt_sha256: str) -> bytes:
        return self._delegate.replay_parser_input(receipt_sha256)

    def load_recorded_attempt(self, receipt_sha256: str) -> RecordedParserInput:
        return self._delegate.load_recorded_attempt(receipt_sha256)

    def store_parser_input(
        self,
        payload: str,
        *,
        representation: str,
    ) -> CapturedParserInput:
        captured = self._delegate.store_parser_input(payload, representation=representation)
        with self._lock:
            self._parser_inputs.setdefault(captured.object_sha256, []).append(payload)
        return captured

    def store_static_records(self, records: object) -> CapturedParserInput:
        return self._delegate.store_static_records(records)

    def _pending_result_rows(
        self,
        *,
        source_family: str,
        endpoint_id: str,
        parser_input: str | None,
        provider_authority_sha256: str,
        endpoint_contract_sha256: str,
        safe_parameters_json: str,
        result_sets: Sequence[ResultSetReceipt],
    ) -> tuple[PendingResultOccurrenceV2, ...]:
        if source_family == "stats":
            if parser_input is None:
                raise ValueError("stats result lacks its exact parser input")
            contract = pinned_runtime_contracts()[endpoint_id]
            if contract.response_mode == "unknown_dynamic_response":
                unknown = rederive_raw_authority_unknown_stats_response(
                    endpoint_id=endpoint_id,
                    parser_input=parser_input.encode("utf-8", errors="strict"),
                    safe_parameters_json=safe_parameters_json,
                    provider_authority_sha256=provider_authority_sha256,
                    endpoint_contract_sha256_value=endpoint_contract_sha256,
                )
                duplicate_names: Counter[str] = Counter()
                derivation_items: list[tuple[ResultSetReceipt, tuple[str, ...], int]] = []
                for item in unknown.occurrences:
                    duplicate_ordinal = duplicate_names[item.name]
                    duplicate_names[item.name] += 1
                    derivation_items.append((item.receipt, item.headers, duplicate_ordinal))
                derivations = tuple(derivation_items)
                rederived_receipts = tuple(item[0] for item in derivations)
            else:
                declared = rederive_raw_authority_result_sets(
                    source_family=source_family,
                    endpoint_id=endpoint_id,
                    parser_input=parser_input.encode("utf-8", errors="strict"),
                    provider_authority_sha256=provider_authority_sha256,
                    endpoint_contract_sha256_value=endpoint_contract_sha256,
                )
                derivations = tuple(
                    (
                        item.result_set,
                        item.ordered_headers,
                        item.duplicate_name_ordinal,
                    )
                    for item in declared
                )
                rederived_receipts = tuple(item.result_set for item in declared)
            if rederived_receipts != tuple(result_sets):
                raise ValueError(
                    "stats result receipts differ from exact parser-input rederivation"
                )
            return tuple(
                PendingResultOccurrenceV2(
                    result_set=result_set,
                    duplicate_name_ordinal=duplicate_name_ordinal,
                    ordered_headers=ordered_headers,
                )
                for result_set, ordered_headers, duplicate_name_ordinal in derivations
            )

        duplicates: Counter[str] = Counter()
        rows: list[PendingResultOccurrenceV2] = []
        for result_set in result_sets:
            duplicate_ordinal = duplicates[result_set.name]
            duplicates[result_set.name] += 1
            rows.append(
                PendingResultOccurrenceV2(
                    result_set=result_set,
                    duplicate_name_ordinal=duplicate_ordinal,
                    ordered_headers=_result_headers(
                        source_family,
                        endpoint_id,
                        parser_input,
                        result_set,
                    ),
                )
            )
        return tuple(rows)

    def record_response_attempt(
        self,
        *,
        context: ParserInputContext,
        transport_kind: TransportKind,
        source_family: str,
        endpoint_id: str,
        endpoint_slug: str,
        parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        contract_sha256: str,
        status_code: int | None,
        captured: CapturedParserInput,
        outcome: Outcome,
        failure_class: str | None,
        root_exception_class: str | None,
        result_sets: Sequence[ResultSetReceipt],
        effective_status_code: int | None = None,
    ) -> str:
        try:
            receipt = self._delegate.record_response_attempt(
                context=context,
                transport_kind=transport_kind,
                source_family=source_family,
                endpoint_id=endpoint_id,
                endpoint_slug=endpoint_slug,
                parameters=parameters,
                provider_authority_sha256=provider_authority_sha256,
                contract_sha256=contract_sha256,
                status_code=status_code,
                captured=captured,
                outcome=outcome,
                failure_class=failure_class,
                root_exception_class=root_exception_class,
                result_sets=result_sets,
                effective_status_code=effective_status_code,
            )
        except Exception:
            with self._lock:
                self._timing(context)
                self._discard_parser_input(captured.object_sha256)
            raise

        with self._lock:
            started_at, finished_at, elapsed_ns = self._timing(context)
            parser_input: str | None = None
            if source_family != "static":
                try:
                    parser_input = self._take_parser_input(captured.object_sha256)
                except Exception as exc:
                    self._issue("response_observation_unavailable", context, exc)
                    return receipt

        def record_public() -> None:
            attempt = self._attempt(
                context=context,
                source_family=source_family,
                endpoint_id=endpoint_id,
                parameters=parameters,
                provider_authority_sha256=provider_authority_sha256,
                contract_sha256=contract_sha256,
            )
            if (
                parser_input is not None
                and _sha256(parser_input.encode("utf-8", errors="strict"))
                != captured.response_sha256
            ):
                raise ValueError("private capture digest differs from exact parser input")
            effective = status_code if effective_status_code is None else effective_status_code
            transport = self._transport(source_family, status_code, effective)
            if outcome in {"success_nonempty", "success_empty"}:
                if parser_input is None:
                    raise ValueError("HTTP success lacks its exact parser input")
                body = ParserInputObjectV2.from_parser_input(parser_input)
                results = self._pending_result_rows(
                    source_family=source_family,
                    endpoint_id=endpoint_id,
                    parser_input=parser_input,
                    provider_authority_sha256=provider_authority_sha256,
                    endpoint_contract_sha256=contract_sha256,
                    safe_parameters_json=attempt.safe_parameters_json,
                    result_sets=result_sets,
                )
                pending = PendingRawRequestSuccessV2(
                    private_receipt_sha256=receipt,
                    attempt=attempt,
                    transport=transport,
                    started_at=started_at,
                    finished_at=finished_at,
                    elapsed_ns=elapsed_ns,
                    outcome=cast(
                        "Literal['success_nonempty', 'success_empty']",
                        outcome,
                    ),
                    body_disposition="public_parser_input",
                    body_object=body,
                    results=results,
                )
                self._objects.setdefault(body.object_sha256, body)
                self._pending[receipt] = pending
                if not result_sets:
                    self._issue("success_result_authority_pending", context)
                return
            if source_family == "static":
                bodyless = _safe_digest(
                    {
                        "attempt_sha256": attempt.attempt_sha256,
                        "failure_class": failure_class,
                        "private_outcome": outcome,
                        "private_receipt_sha256": receipt,
                        "public_projection": "static_failure_no_public_body_v2",
                        "root_exception_class": root_exception_class,
                        "snapshot_materialized": True,
                    }
                )
                observation = RequestObservationV2.build(
                    attempt=attempt,
                    transport=transport,
                    started_at=started_at,
                    finished_at=finished_at,
                    elapsed_ns=elapsed_ns,
                    lifecycle="incomplete",
                    outcome="transport_failure_no_response",
                    failure_class=cast("FailureClass", failure_class),
                    root_exception_class=root_exception_class,
                    body_disposition="no_response",
                    body_object_sha256=None,
                    bodyless_evidence_sha256=bodyless,
                    result_occurrence_sha256s=(),
                    route_landing_sha256s=(),
                    capture_response_receipt_sha256=None,
                    logical_receipt_sha256=None,
                )
                self._observations[attempt.observation_sha256] = observation
                return
            if status_code is None:
                raise ValueError("failed response has no public HTTP status")
            bodyless = _safe_digest(
                {
                    "attempt_sha256": attempt.attempt_sha256,
                    "failure_class": failure_class,
                    "outcome": outcome,
                    "private_receipt_sha256": receipt,
                    "root_exception_class": root_exception_class,
                }
            )
            observation = RequestObservationV2.build(
                attempt=attempt,
                transport=transport,
                started_at=started_at,
                finished_at=finished_at,
                elapsed_ns=elapsed_ns,
                lifecycle="incomplete",
                outcome=outcome,
                failure_class=cast("FailureClass", failure_class),
                root_exception_class=root_exception_class,
                body_disposition="excluded_failure_body",
                body_object_sha256=None,
                bodyless_evidence_sha256=bodyless,
                result_occurrence_sha256s=(),
                route_landing_sha256s=(),
                capture_response_receipt_sha256=None,
                logical_receipt_sha256=None,
            )
            self._observations[attempt.observation_sha256] = observation

        self._guard("response_observation_unavailable", context, record_public)
        return receipt

    def record_static_snapshot_attempt(
        self,
        *,
        context: ParserInputContext,
        endpoint_id: str,
        endpoint_slug: str,
        provider_authority_sha256: str,
        contract_sha256: str,
        captured: CapturedParserInput,
        result_set: ResultSetReceipt,
    ) -> str:
        try:
            receipt = self._delegate.record_static_snapshot_attempt(
                context=context,
                endpoint_id=endpoint_id,
                endpoint_slug=endpoint_slug,
                provider_authority_sha256=provider_authority_sha256,
                contract_sha256=contract_sha256,
                captured=captured,
                result_set=result_set,
            )
        except Exception:
            with self._lock:
                self._timing(context)
            raise
        with self._lock:
            started_at, finished_at, elapsed_ns = self._timing(context)

        def record_public() -> None:
            attempt = self._attempt(
                context=context,
                source_family="static",
                endpoint_id=endpoint_id,
                parameters={},
                provider_authority_sha256=provider_authority_sha256,
                contract_sha256=contract_sha256,
            )
            self._pending[receipt] = PendingRawRequestSuccessV2(
                private_receipt_sha256=receipt,
                attempt=attempt,
                transport=self._transport("static", None, None),
                started_at=started_at,
                finished_at=finished_at,
                elapsed_ns=elapsed_ns,
                outcome="static_snapshot_success",
                body_disposition="declared_bodyless",
                body_object=None,
                results=self._pending_result_rows(
                    source_family="static",
                    endpoint_id=endpoint_id,
                    parser_input=None,
                    provider_authority_sha256=provider_authority_sha256,
                    endpoint_contract_sha256=contract_sha256,
                    safe_parameters_json=attempt.safe_parameters_json,
                    result_sets=(result_set,),
                ),
            )

        self._guard("static_success_authority_unavailable", context, record_public)
        return receipt

    def record_no_response_attempt(
        self,
        *,
        context: ParserInputContext,
        transport_kind: TransportKind,
        source_family: str,
        endpoint_id: str,
        endpoint_slug: str,
        parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        contract_sha256: str,
        outcome: Outcome,
        failure_class: str,
        root_exception_class: str,
    ) -> str:
        try:
            receipt = self._delegate.record_no_response_attempt(
                context=context,
                transport_kind=transport_kind,
                source_family=source_family,
                endpoint_id=endpoint_id,
                endpoint_slug=endpoint_slug,
                parameters=parameters,
                provider_authority_sha256=provider_authority_sha256,
                contract_sha256=contract_sha256,
                outcome=outcome,
                failure_class=failure_class,
                root_exception_class=root_exception_class,
            )
        except Exception:
            with self._lock:
                self._timing(context)
            raise
        with self._lock:
            started_at, finished_at, elapsed_ns = self._timing(context)

        def record_public() -> None:
            attempt = self._attempt(
                context=context,
                source_family=source_family,
                endpoint_id=endpoint_id,
                parameters=parameters,
                provider_authority_sha256=provider_authority_sha256,
                contract_sha256=contract_sha256,
            )
            public_outcome: Outcome = (
                "transport_failure_no_response" if source_family == "static" else outcome
            )
            bodyless_payload = (
                {
                    "attempt_sha256": attempt.attempt_sha256,
                    "failure_class": failure_class,
                    "private_outcome": outcome,
                    "private_receipt_sha256": receipt,
                    "public_outcome": public_outcome,
                    "public_projection": "static_failure_no_public_body_v2",
                    "root_exception_class": root_exception_class,
                    "snapshot_materialized": False,
                }
                if source_family == "static"
                else {
                    "attempt_sha256": attempt.attempt_sha256,
                    "failure_class": failure_class,
                    "outcome": outcome,
                    "private_receipt_sha256": receipt,
                    "root_exception_class": root_exception_class,
                }
            )
            bodyless = _safe_digest(bodyless_payload)
            observation = RequestObservationV2.build(
                attempt=attempt,
                transport=self._transport(source_family, None, None),
                started_at=started_at,
                finished_at=finished_at,
                elapsed_ns=elapsed_ns,
                lifecycle="incomplete",
                outcome=public_outcome,
                failure_class=cast("FailureClass", failure_class),
                root_exception_class=root_exception_class,
                body_disposition="no_response",
                body_object_sha256=None,
                bodyless_evidence_sha256=bodyless,
                result_occurrence_sha256s=(),
                route_landing_sha256s=(),
                capture_response_receipt_sha256=None,
                logical_receipt_sha256=None,
            )
            self._observations[attempt.observation_sha256] = observation

        self._guard("no_response_observation_unavailable", context, record_public)
        return receipt

    def record_logical_call(
        self,
        *,
        context: ParserInputContext,
        logical_endpoint_id: str,
        logical_parameters: Mapping[str, Any],
        provider_authority_sha256: str,
        response_receipt_sha256s: Sequence[str],
        successful_response_ordinals: Sequence[int],
        result_route_ids: Sequence[str],
    ) -> str:
        receipt = self._delegate.record_logical_call(
            context=context,
            logical_endpoint_id=logical_endpoint_id,
            logical_parameters=logical_parameters,
            provider_authority_sha256=provider_authority_sha256,
            response_receipt_sha256s=response_receipt_sha256s,
            successful_response_ordinals=successful_response_ordinals,
            result_route_ids=result_route_ids,
        )
        with self._lock:
            try:
                successful = {
                    response_receipt_sha256s[index] for index in successful_response_ordinals
                }
                routes = tuple(result_route_ids)
                for response_receipt in successful:
                    pending = self._pending.get(response_receipt)
                    if pending is not None:
                        self._pending[response_receipt] = replace(
                            pending,
                            logical_receipt_sha256=receipt,
                            aggregate_route_ids=routes,
                        )
            except Exception as exc:
                self._issue("logical_selection_authority_unavailable", context, exc)
        return receipt

    def mark_downstream_incomplete(
        self,
        *,
        failure_class: str,
        root_exception_class: str,
        receipt_sha256: str | None = None,
    ) -> None:
        """Retain one exact parsed HTTP body after a downstream failure."""

        with self._lock:
            candidates = {
                candidate_receipt: item
                for candidate_receipt, item in self._pending.items()
                if item.body_object is not None
                and item.attempt.observation_sha256 not in self._observations
            }
            if receipt_sha256 is not None:
                pending = candidates.get(receipt_sha256)
                if pending is None:
                    self._issue("downstream_incomplete_receipt_unavailable", None)
                    return
                selected_receipt = receipt_sha256
            elif len(candidates) == 1:
                selected_receipt, pending = next(iter(candidates.items()))
            elif not candidates:
                return
            else:
                self._issue("downstream_incomplete_receipt_ambiguous", None)
                return
            try:
                observation = RequestObservationV2.build(
                    attempt=pending.attempt,
                    transport=pending.transport,
                    started_at=pending.started_at,
                    finished_at=pending.finished_at,
                    elapsed_ns=pending.elapsed_ns,
                    lifecycle="incomplete",
                    outcome="downstream_incomplete",
                    failure_class=cast("FailureClass", failure_class),
                    root_exception_class=root_exception_class,
                    body_disposition="public_parser_input",
                    body_object_sha256=cast(
                        "ParserInputObjectV2", pending.body_object
                    ).object_sha256,
                    bodyless_evidence_sha256=None,
                    result_occurrence_sha256s=(),
                    route_landing_sha256s=(),
                    capture_response_receipt_sha256=pending.private_receipt_sha256,
                    logical_receipt_sha256=None,
                )
            except Exception as exc:
                self._issue("downstream_incomplete_observation_unavailable", None, exc)
                return
            self._observations[pending.attempt.observation_sha256] = observation
            del self._pending[selected_receipt]

    def snapshot(self) -> RawRequestCaptureSnapshotV2:
        with self._lock:
            return RawRequestCaptureSnapshotV2(
                objects=tuple(sorted(self._objects.values(), key=lambda item: item.object_sha256)),
                observations=tuple(
                    sorted(
                        self._observations.values(),
                        key=lambda item: item.attempt.observation_sha256,
                    )
                ),
                pending_successes=tuple(
                    sorted(
                        self._pending.values(),
                        key=lambda item: (
                            item.attempt.retry_ordinal,
                            item.attempt.request_ordinal,
                        ),
                    )
                ),
                issues=tuple(self._issues),
            )


class RawRequestCaptureContract(NbaApiCaptureContract):
    """Capture contract that timestamps allocation immediately before transport."""

    sink: RawRequestCaptureSink

    def begin_request(self) -> ParserInputContext:
        context = super().begin_request()
        self.sink.begin_request(context)
        return context


def wrap_raw_request_capture_contract(
    contract: NbaApiCaptureContract,
    context: RawRequestCaptureContextV2 | None,
) -> RawRequestCaptureContract:
    """Decorate a private capture contract without replacing its receipt ledger."""

    if isinstance(contract.sink, RawRequestCaptureSink):
        raise ValueError("a public raw-request capture contract cannot be rewrapped")
    sink = RawRequestCaptureSink(contract.sink, context)
    return RawRequestCaptureContract(
        sink=sink,
        context=contract.context,
        provider_authority_sha256=contract.provider_authority_sha256,
        endpoint_contract_sha256=contract.endpoint_contract_sha256,
        receipt_ledger=contract.receipt_ledger,
    )
