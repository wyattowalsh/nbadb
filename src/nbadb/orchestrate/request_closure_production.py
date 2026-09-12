"""Public receipt-only request-closure wiring for ordinary pipeline runs.

Raw parser input is retained only in bounded process memory long enough to
derive the public-safe response/result receipts consumed by the post-commit
staging join.  It is never written to the checkout or public data directory.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from nbadb.contracts.raw_request_authority import canonical_semantic_parameters
from nbadb.core.errors import ExtractionError, ParserInputCaptureIntegrityError
from nbadb.core.nba_api_competition_identity import (
    CompetitionQualifiedRequest,
    NbaApiCompetitionIdentityError,
    bind_explicit_competition_request,
    bind_static_competition_source,
    build_competition_terminal_request_binding,
    compile_competition_identity_requirements,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_request_surface import (
    CanonicalProviderRequest,
    RequestScopeDimension,
    RequestScopeManifest,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_runtime_contract import (
    owned_contract_sha256,
    pinned_runtime_contracts,
    pinned_static_dataset_contract,
)
from nbadb.extract.base import BaseExtractor, _forward_explicit_provider_parameters
from nbadb.extract.bronze import (
    DEFAULT_CODEC,
    PARSER_INPUT_REPRESENTATION,
    STATIC_INPUT_REPRESENTATION,
    CapturedParserInput,
    ParserInputContext,
    RecordedParserInput,
    ResultSetReceipt,
    canonical_parameters_sha256,
)
from nbadb.extract.nba_api_adapter import NbaApiCaptureContract, _stats_request_contract
from nbadb.orchestrate.extractor_runner import (
    RequestClosureCompetitionAuthority,
    RequestClosureExecutionAuthority,
    RequestClosureLogicalCallBinding,
    RequestClosureStagingRouteAlias,
)
from nbadb.orchestrate.request_closure_runtime import (
    RouteRequestSpecInput,
    build_authoritative_route_manifest,
)
from nbadb.orchestrate.request_closure_staging import RequestClosureScopeGap

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from nbadb.extract.bronze import Outcome, TransportKind
    from nbadb.extract.registry import EndpointRegistry
    from nbadb.orchestrate.planning import ExtractionPlanItem
    from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
    from nbadb.orchestrate.staging_map import StagingEntry

_SUCCESS_OUTCOMES = frozenset({"success_nonempty", "success_empty"})
_MAX_RESPONSE_BYTES = 128 * 1024 * 1024
_MAX_OUTSTANDING_BYTES = 512 * 1024 * 1024
_STATIC_SCOPE_DOMAIN = "nbadb.raw-request.static-scope.v1"
_STATIC_AUTHORITY_DOMAIN = "nbadb.raw-request.static-closure-authority.v1"


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    payload = value if isinstance(value, bytes) else _canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def _blob_relative_path(object_sha256: str) -> str:
    return f"blobs/sha256/{object_sha256[:2]}/{object_sha256}.payload.gz"


@dataclass(frozen=True, slots=True)
class _AttemptMetadata:
    context: ParserInputContext
    transport_kind: str
    source_family: str
    endpoint_id: str
    endpoint_slug: str
    parameters_sha256: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    status_code: int | None
    outcome: str
    result_sets: tuple[ResultSetReceipt, ...]
    captured: CapturedParserInput | None


class ReceiptOnlyParserInputSink:
    """Thread-safe bounded memory sink that exposes no durable raw body."""

    def __init__(
        self,
        *,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        max_outstanding_bytes: int = _MAX_OUTSTANDING_BYTES,
    ) -> None:
        if (
            type(max_response_bytes) is not int
            or max_response_bytes <= 0
            or type(max_outstanding_bytes) is not int
            or max_outstanding_bytes < max_response_bytes
        ):
            raise ValueError("receipt-only parser-input limits are invalid")
        self._max_response_bytes = max_response_bytes
        self._max_outstanding_bytes = max_outstanding_bytes
        self._lock = threading.RLock()
        self._payloads: dict[str, bytes] = {}
        self._attempts: dict[str, _AttemptMetadata] = {}
        self._logical_selections: dict[
            str,
            tuple[str, tuple[str, ...], tuple[str, ...]],
        ] = {}
        self._discarded_attempts: set[str] = set()
        self._outstanding_bytes = 0

    @property
    def outstanding_parser_input_bytes(self) -> int:
        with self._lock:
            return self._outstanding_bytes

    def _store_raw(self, raw: bytes, *, representation: str) -> CapturedParserInput:
        if len(raw) > self._max_response_bytes:
            raise ParserInputCaptureIntegrityError(
                "receipt-only parser input exceeds the per-response bound"
            )
        response_sha256 = hashlib.sha256(raw).hexdigest()
        object_sha256 = hashlib.sha256(representation.encode("ascii") + b"\0" + raw).hexdigest()
        stored = gzip.compress(raw, compresslevel=6, mtime=0)
        captured = CapturedParserInput(
            representation=representation,
            response_sha256=response_sha256,
            object_sha256=object_sha256,
            uncompressed_bytes=len(raw),
            stored_sha256=hashlib.sha256(stored).hexdigest(),
            stored_bytes=len(stored),
            codec=DEFAULT_CODEC,
            relative_path=_blob_relative_path(object_sha256),
        )
        with self._lock:
            prior = self._payloads.get(object_sha256)
            if prior is not None and prior != raw:
                raise ParserInputCaptureIntegrityError(
                    "receipt-only parser-input identity collision"
                )
            if prior is None:
                if self._outstanding_bytes + len(raw) > self._max_outstanding_bytes:
                    raise ParserInputCaptureIntegrityError(
                        "receipt-only parser-input outstanding-byte bound exceeded"
                    )
                self._payloads[object_sha256] = raw
                self._outstanding_bytes += len(raw)
        return captured

    def store_parser_input(
        self,
        payload: str,
        *,
        representation: str,
    ) -> CapturedParserInput:
        if representation != PARSER_INPUT_REPRESENTATION:
            raise ValueError("HTTP parser input uses the decoded-response representation")
        if not isinstance(payload, str):
            raise TypeError("HTTP parser input must be decoded text")
        return self._store_raw(
            payload.encode("utf-8", errors="strict"),
            representation=representation,
        )

    def store_static_records(self, records: object) -> CapturedParserInput:
        return self._store_raw(
            _canonical_json_bytes(records),
            representation=STATIC_INPUT_REPRESENTATION,
        )

    def _verify_captured(self, captured: CapturedParserInput) -> bytes:
        if not isinstance(captured, CapturedParserInput):
            raise ParserInputCaptureIntegrityError("receipt-only capture identity is invalid")
        raw = self._payloads.get(captured.object_sha256)
        if (
            raw is None
            or len(raw) != captured.uncompressed_bytes
            or hashlib.sha256(raw).hexdigest() != captured.response_sha256
            or hashlib.sha256(captured.representation.encode("ascii") + b"\0" + raw).hexdigest()
            != captured.object_sha256
        ):
            raise ParserInputCaptureIntegrityError(
                "receipt-only parser input differs from its captured identity"
            )
        return raw

    def _record_attempt(
        self,
        metadata: _AttemptMetadata,
        *,
        failure_class: str | None,
        root_exception_class: str | None,
        effective_status_code: int | None,
    ) -> str:
        payload = {
            "context": asdict(metadata.context),
            "transport_kind": metadata.transport_kind,
            "source_family": metadata.source_family,
            "endpoint_id": metadata.endpoint_id,
            "endpoint_slug": metadata.endpoint_slug,
            "parameters_sha256": metadata.parameters_sha256,
            "provider_authority_sha256": metadata.provider_authority_sha256,
            "endpoint_contract_sha256": metadata.endpoint_contract_sha256,
            "status_code": metadata.status_code,
            "effective_status_code": effective_status_code,
            "outcome": metadata.outcome,
            "failure_class": failure_class,
            "root_exception_class": root_exception_class,
            "captured": asdict(metadata.captured) if metadata.captured is not None else None,
            "result_sets": [asdict(item) for item in metadata.result_sets],
        }
        receipt_sha256 = _sha256(payload)
        prior = self._attempts.get(receipt_sha256)
        if prior is not None and prior != metadata:
            raise ParserInputCaptureIntegrityError("receipt-only attempt identity collision")
        self._attempts[receipt_sha256] = metadata
        return receipt_sha256

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
        with self._lock:
            self._verify_captured(captured)
            typed_results = tuple(result_sets)
            if any(not isinstance(item, ResultSetReceipt) for item in typed_results):
                raise ParserInputCaptureIntegrityError(
                    "receipt-only result-set inventory is invalid"
                )
            metadata = _AttemptMetadata(
                context=context,
                transport_kind=transport_kind,
                source_family=source_family,
                endpoint_id=endpoint_id,
                endpoint_slug=endpoint_slug,
                parameters_sha256=canonical_parameters_sha256(parameters),
                provider_authority_sha256=provider_authority_sha256,
                endpoint_contract_sha256=contract_sha256,
                status_code=status_code,
                outcome=outcome,
                result_sets=typed_results,
                captured=captured,
            )
            return self._record_attempt(
                metadata,
                failure_class=failure_class,
                root_exception_class=root_exception_class,
                effective_status_code=effective_status_code,
            )

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
        outcome: Outcome = "success_nonempty" if result_set.row_count else "success_empty"
        return self.record_response_attempt(
            context=context,
            transport_kind="static_provider_snapshot",
            source_family="static",
            endpoint_id=endpoint_id,
            endpoint_slug=endpoint_slug,
            parameters={},
            provider_authority_sha256=provider_authority_sha256,
            contract_sha256=contract_sha256,
            status_code=None,
            captured=captured,
            outcome=outcome,
            failure_class=None,
            root_exception_class=None,
            result_sets=(result_set,),
        )

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
        with self._lock:
            return self._record_attempt(
                _AttemptMetadata(
                    context=context,
                    transport_kind=transport_kind,
                    source_family=source_family,
                    endpoint_id=endpoint_id,
                    endpoint_slug=endpoint_slug,
                    parameters_sha256=canonical_parameters_sha256(parameters),
                    provider_authority_sha256=provider_authority_sha256,
                    endpoint_contract_sha256=contract_sha256,
                    status_code=None,
                    outcome=outcome,
                    result_sets=(),
                    captured=None,
                ),
                failure_class=failure_class,
                root_exception_class=root_exception_class,
                effective_status_code=None,
            )

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
        with self._lock:
            receipts = tuple(response_receipt_sha256s)
            ordinals = tuple(successful_response_ordinals)
            routes = tuple(sorted(result_route_ids))
            if (
                not receipts
                or len(receipts) != len(set(receipts))
                or not routes
                or routes != tuple(sorted(set(routes)))
            ):
                raise ParserInputCaptureIntegrityError(
                    "receipt-only logical call inventory is invalid"
                )
            try:
                attempts = tuple(self._attempts[item] for item in receipts)
            except KeyError as exc:
                raise ParserInputCaptureIntegrityError(
                    "receipt-only logical call references an unknown attempt"
                ) from exc
            expected_ordinals = tuple(
                index
                for index, attempt in enumerate(attempts)
                if attempt.outcome in _SUCCESS_OUTCOMES
            )
            if ordinals != expected_ordinals or not ordinals:
                raise ParserInputCaptureIntegrityError(
                    "receipt-only logical-call success ordinals are invalid"
                )
            if any(
                attempt.context.attempt_id != context.attempt_id
                or attempt.provider_authority_sha256 != provider_authority_sha256
                for attempt in attempts
            ):
                raise ParserInputCaptureIntegrityError(
                    "receipt-only logical call crosses attempt/provider authority"
                )
            logical_receipt_sha256 = _sha256(
                {
                    "context": asdict(context),
                    "logical_endpoint_id": logical_endpoint_id,
                    "logical_parameters_sha256": canonical_parameters_sha256(logical_parameters),
                    "provider_authority_sha256": provider_authority_sha256,
                    "response_receipt_sha256s": list(receipts),
                    "successful_response_ordinals": list(ordinals),
                    "result_route_ids": list(routes),
                }
            )
            selected_receipts = tuple(receipts[index] for index in ordinals)
            selection = (
                logical_receipt_sha256,
                routes,
                selected_receipts,
            )
            for selected_receipt in selected_receipts:
                prior = self._logical_selections.get(selected_receipt)
                if prior is not None and prior != selection:
                    raise ParserInputCaptureIntegrityError(
                        "receipt-only response changed logical selection"
                    )
                self._logical_selections[selected_receipt] = selection
            return logical_receipt_sha256

    def exact_logical_selection(
        self,
        response_receipt_sha256s: Sequence[str],
    ) -> tuple[str, tuple[str, ...]]:
        """Read back the exact logical selection for public-sidecar binding."""

        receipts = tuple(response_receipt_sha256s)
        if not receipts or len(receipts) != len(set(receipts)):
            raise ParserInputCaptureIntegrityError(
                "receipt-only logical selection inventory is invalid"
            )
        with self._lock:
            try:
                selections = tuple(self._logical_selections[item] for item in receipts)
            except KeyError as exc:
                raise ParserInputCaptureIntegrityError(
                    "receipt-only response lacks its logical selection"
                ) from exc
            if len(set(selections)) != 1:
                raise ParserInputCaptureIntegrityError(
                    "receipt-only responses cross logical selections"
                )
            logical_receipt_sha256, routes, selected_receipts = selections[0]
            if set(selected_receipts) != set(receipts):
                raise ParserInputCaptureIntegrityError(
                    "receipt-only logical selection has a foreign response inventory"
                )
            return logical_receipt_sha256, routes

    def load_recorded_attempt(self, receipt_sha256: str) -> RecordedParserInput:
        with self._lock:
            try:
                attempt = self._attempts[receipt_sha256]
            except KeyError as exc:
                raise ExtractionError("receipt-only attempt is unavailable") from exc
            if attempt.captured is None or receipt_sha256 in self._discarded_attempts:
                raise ExtractionError("receipt-only attempt has no retained parser input")
            raw = self._verify_captured(attempt.captured)
            return RecordedParserInput(
                receipt_sha256=receipt_sha256,
                transport_kind=cast("TransportKind", attempt.transport_kind),
                source_family=attempt.source_family,
                endpoint_id=attempt.endpoint_id,
                endpoint_slug=attempt.endpoint_slug,
                parameters_sha256=attempt.parameters_sha256,
                provider_authority_sha256=attempt.provider_authority_sha256,
                endpoint_contract_sha256=attempt.endpoint_contract_sha256,
                status_code=attempt.status_code,
                outcome=cast("Outcome", attempt.outcome),
                result_sets=attempt.result_sets,
                captured=attempt.captured,
                parser_input=raw,
            )

    def replay_parser_input(self, receipt_sha256: str) -> bytes:
        return self.load_recorded_attempt(receipt_sha256).parser_input

    def discard_parser_inputs(self, receipt_sha256s: Sequence[str]) -> None:
        """Irreversibly discard raw bodies after public-safe projection."""

        with self._lock:
            for receipt_sha256 in tuple(receipt_sha256s):
                if receipt_sha256 not in self._attempts:
                    raise ParserInputCaptureIntegrityError(
                        "receipt-only discard references an unknown attempt"
                    )
                self._discarded_attempts.add(receipt_sha256)
            retained_objects = {
                attempt.captured.object_sha256
                for digest, attempt in self._attempts.items()
                if digest not in self._discarded_attempts and attempt.captured is not None
            }
            for object_sha256 in tuple(self._payloads):
                if object_sha256 not in retained_objects:
                    self._outstanding_bytes -= len(self._payloads.pop(object_sha256))


class ReceiptOnlyCaptureFactory:
    """Issue isolated public receipt-only capture contracts for runner calls."""

    def __init__(
        self,
        sink: ReceiptOnlyParserInputSink | None = None,
        *,
        execution_identity: RawRequestExecutionIdentityV1 | None = None,
    ) -> None:
        if execution_identity is not None:
            from nbadb.orchestrate.raw_request_context import (
                RawRequestExecutionIdentityV1,
            )

            if type(execution_identity) is not RawRequestExecutionIdentityV1:
                raise TypeError("receipt-only capture execution identity must be exact")
        self.sink = sink or ReceiptOnlyParserInputSink()
        self._execution_identity = execution_identity
        self._provider_authority_sha256 = expected_nba_api_provider_authority()["authority_sha256"]
        self._lock = threading.Lock()
        self._ordinal = 0

    def contract_for(
        self,
        endpoint_name: str,
        params: Mapping[str, Any],
    ) -> NbaApiCaptureContract:
        parameter_digest = canonical_parameters_sha256(params)
        with self._lock:
            ordinal = self._ordinal
            self._ordinal += 1
        endpoint_digest = hashlib.sha256(endpoint_name.encode("utf-8")).hexdigest()
        execution = self._execution_identity
        context = ParserInputContext(
            attempt_id=(f"receipt-{ordinal:016x}-{endpoint_digest[:12]}-{parameter_digest[:16]}"),
            workflow_run_id=None if execution is None else execution.run_id,
            workflow_run_attempt=None if execution is None else execution.run_attempt,
            chain_id=None if execution is None else execution.chain_id,
            lane_id=None if execution is None else execution.lane_id,
            semantic_source_sha=None if execution is None else execution.source_sha,
        )
        return NbaApiCaptureContract(
            sink=self.sink,
            context=context,
            provider_authority_sha256=self._provider_authority_sha256,
            endpoint_contract_sha256="0" * 64,
        )


class _ProviderBoundaryProbe(BaseException):
    def __init__(
        self,
        endpoint_cls: type,
        constructor_parameters: dict[str, object],
        runtime_parameters: dict[str, object],
    ) -> None:
        self.endpoint_cls = endpoint_cls
        self.constructor_parameters = constructor_parameters
        self.runtime_parameters = runtime_parameters


@dataclass(frozen=True, slots=True)
class _LogicalCandidate:
    endpoint_name: str
    logical_parameters_sha256: str
    provider_endpoint_id: str
    provider_parameters: tuple[tuple[str, object], ...]
    provider_parameters_sha256: str
    provider_request_sha256: str
    physical_route_ids: tuple[str, ...]
    qualified_request: CompetitionQualifiedRequest


@dataclass(frozen=True, slots=True)
class ProductionRequestClosureBuild:
    """Exact pre-dispatch authority plus explicitly unproved scope surfaces."""

    authority: RequestClosureExecutionAuthority | None
    scope_gaps: tuple[RequestClosureScopeGap, ...]
    support_date: date
    static_authorities: tuple[StaticRequestClosureAuthorityV1, ...] = ()

    def __post_init__(self) -> None:
        authorities = self.static_authorities
        if (
            type(authorities) is not tuple
            or any(type(item) is not StaticRequestClosureAuthorityV1 for item in authorities)
            or authorities != tuple(sorted(authorities, key=lambda item: item.endpoint_name))
            or len({item.endpoint_name for item in authorities}) != len(authorities)
        ):
            raise ParserInputCaptureIntegrityError(
                "ordinary request closure static authorities are invalid"
            )


@dataclass(frozen=True, slots=True)
class StaticRequestClosureAuthorityV1:
    """Exact bodyless request authority for one pinned static dataset call.

    Static datasets are deliberately outside ``RequestClosureExecutionAuthority``:
    they have no HTTP provider request and their competition identity is rooted in
    the pinned getter/source/data chain rather than a response receipt.  This
    authority carries that distinction without weakening the HTTP closure model.
    """

    endpoint_name: str
    logical_parameters_sha256: str
    provider_request_sha256: str
    physical_route_ids: tuple[str, ...]
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    competition_id: str
    competition_identity_sha256: str
    competition_scope_sha256: str
    competition_requirement_sha256: str
    role_binding_sha256: str
    source_evidence_sha256: str
    scope_sha256: str
    static_authority_sha256: str
    qualified_request: CompetitionQualifiedRequest = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _revalidate_static_request_closure_authority(self)

    def to_dict(self) -> dict[str, object]:
        _revalidate_static_request_closure_authority(self)
        return _static_request_closure_payload(self)


def _static_scope_payload(
    *,
    endpoint_name: str,
    provider_request_sha256: str,
    physical_route_ids: tuple[str, ...],
    provider_authority_sha256: str,
    endpoint_contract_sha256: str,
    qualified_request: CompetitionQualifiedRequest,
) -> dict[str, object]:
    surface = pinned_request_surface_authority()
    return {
        "domain_separator": _STATIC_SCOPE_DOMAIN,
        "request_surface_sha256": surface.surface_sha256,
        "runtime_contract_payload_sha256": surface.runtime_contract_payload_sha256,
        "endpoint_name": endpoint_name,
        "provider_request_sha256": provider_request_sha256,
        "physical_route_ids": list(physical_route_ids),
        "provider_authority_sha256": provider_authority_sha256,
        "endpoint_contract_sha256": endpoint_contract_sha256,
        "competition_scope_sha256": qualified_request.competition_scope_sha256,
        "competition_identity_sha256": qualified_request.source_request_sha256,
        "source_evidence_sha256": qualified_request.source_evidence_sha256,
    }


def _static_request_closure_body(
    *,
    endpoint_name: str,
    logical_parameters_sha256: str,
    provider_request_sha256: str,
    physical_route_ids: tuple[str, ...],
    provider_authority_sha256: str,
    endpoint_contract_sha256: str,
    competition_id: str,
    scope_sha256: str,
    qualified_request: CompetitionQualifiedRequest,
) -> dict[str, object]:
    return {
        "domain_separator": _STATIC_AUTHORITY_DOMAIN,
        "schema_version": 1,
        "endpoint_name": endpoint_name,
        "logical_parameters_sha256": logical_parameters_sha256,
        "provider_request_sha256": provider_request_sha256,
        "physical_route_ids": list(physical_route_ids),
        "provider_authority_sha256": provider_authority_sha256,
        "endpoint_contract_sha256": endpoint_contract_sha256,
        "competition_id": competition_id,
        "competition_identity_sha256": qualified_request.source_request_sha256,
        "competition_scope_sha256": qualified_request.competition_scope_sha256,
        "competition_requirement_sha256": qualified_request.requirement_sha256,
        "role_binding_sha256": qualified_request.role_binding_sha256,
        "source_evidence_sha256": qualified_request.source_evidence_sha256,
        "scope_sha256": scope_sha256,
        "qualified_request": qualified_request.to_dict(),
    }


def _static_request_closure_payload(
    authority: StaticRequestClosureAuthorityV1,
) -> dict[str, object]:
    return {
        **_static_request_closure_body(
            endpoint_name=authority.endpoint_name,
            logical_parameters_sha256=authority.logical_parameters_sha256,
            provider_request_sha256=authority.provider_request_sha256,
            physical_route_ids=authority.physical_route_ids,
            provider_authority_sha256=authority.provider_authority_sha256,
            endpoint_contract_sha256=authority.endpoint_contract_sha256,
            competition_id=authority.competition_id,
            scope_sha256=authority.scope_sha256,
            qualified_request=authority.qualified_request,
        ),
        "static_authority_sha256": authority.static_authority_sha256,
    }


def _revalidate_static_request_closure_authority(
    authority: StaticRequestClosureAuthorityV1,
) -> None:
    try:
        if type(authority.qualified_request) is not CompetitionQualifiedRequest:
            raise ValueError("static competition authority is not exact")
        if (
            type(authority.endpoint_name) is not str
            or not authority.endpoint_name
            or type(authority.physical_route_ids) is not tuple
            or not authority.physical_route_ids
            or authority.physical_route_ids != tuple(sorted(set(authority.physical_route_ids)))
        ):
            raise ValueError("static endpoint or route identity is invalid")

        contract = pinned_static_dataset_contract(authority.endpoint_name)
        if (
            contract.source_family != "static"
            or contract.model_disposition != "defined_and_implemented"
            or contract.implementation_status != "complete"
            or owned_contract_sha256(contract) != authority.endpoint_contract_sha256
        ):
            raise ValueError("static endpoint contract is not exact and complete")

        surface = pinned_request_surface_authority()
        datasets = tuple(
            item for item in surface.static_datasets if item.dataset_id == authority.endpoint_name
        )
        if len(datasets) != 1:
            raise ValueError("static dataset is absent from the pinned request surface")
        dataset = datasets[0]
        if (
            dataset.module_name != contract.provider_module
            or dataset.source_symbol != contract.source_symbol
            or dataset.row_count != contract.row_count
            or dataset.row_width != len(contract.raw_fields)
            or dataset.embedded_body_sha256 != contract.source_rows_sha256
            or dataset.runtime_source_rows_sha256 != contract.source_rows_sha256
        ):
            raise ValueError("static dataset surface differs from its runtime contract")

        from nbadb.contracts.staging_route_contract import staging_route_contract_bundle

        bundle = staging_route_contract_bundle()
        expected_provider = expected_nba_api_provider_authority()["authority_sha256"]
        if (
            type(expected_provider) is not str
            or authority.provider_authority_sha256 != expected_provider
            or authority.provider_authority_sha256 != bundle.provider_authority_sha256
        ):
            raise ValueError("static provider authority differs from the pinned provider")
        expected_route_ids = tuple(
            sorted(
                route.route_id
                for route in bundle.routes
                if route.source_family == "static"
                and route.endpoint_name == authority.endpoint_name
            )
        )
        if authority.physical_route_ids != expected_route_ids:
            raise ValueError("static routes do not exactly cover the pinned dataset")
        routes = tuple(bundle.by_route_id[route_id] for route_id in expected_route_ids)
        expected_result_name = f"{contract.source_symbol}_shape_1"
        if any(
            route.provider_endpoint_id != authority.endpoint_name
            or route.endpoint_contract_sha256 != authority.endpoint_contract_sha256
            or route.provider_authority_sha256 != authority.provider_authority_sha256
            or route.canonical_result_set_ordinal != 0
            or route.provider_result_set_name != expected_result_name
            or tuple(route.provider_columns) != tuple(field.name for field in contract.raw_fields)
            for route in routes
        ):
            raise ValueError("static staging routes differ from their pinned dataset")

        _safe_json, logical_parameters_sha256, provider_request_sha256 = (
            canonical_semantic_parameters("static", authority.endpoint_name, {})
        )
        if (
            authority.logical_parameters_sha256 != logical_parameters_sha256
            or authority.provider_request_sha256 != provider_request_sha256
        ):
            raise ValueError("static parameterless request identity drifted")

        requirements = tuple(
            requirement
            for requirement in compile_competition_identity_requirements()
            if requirement.source_family == "static"
            and requirement.provider_endpoint_id == authority.endpoint_name
            and requirement.repo_endpoint_name == authority.endpoint_name
            and requirement.executable
            and requirement.role_binding.binding_strategy == "fixed_static_root"
        )
        if len(requirements) != 1:
            raise ValueError("static dataset lacks one fixed competition root")
        requirement = requirements[0]
        expected_qualified = bind_static_competition_source(requirement)
        if authority.qualified_request.to_dict() != expected_qualified.to_dict():
            raise ValueError("static competition root differs from the pinned fixed root")
        if (
            authority.competition_id != requirement.league_id
            or authority.competition_identity_sha256 != expected_qualified.source_request_sha256
            or authority.competition_scope_sha256 != expected_qualified.competition_scope_sha256
            or authority.competition_requirement_sha256 != expected_qualified.requirement_sha256
            or authority.role_binding_sha256 != expected_qualified.role_binding_sha256
            or authority.source_evidence_sha256 != expected_qualified.source_evidence_sha256
        ):
            raise ValueError("static competition projection differs from its fixed root")

        expected_scope = _sha256(
            _static_scope_payload(
                endpoint_name=authority.endpoint_name,
                provider_request_sha256=authority.provider_request_sha256,
                physical_route_ids=authority.physical_route_ids,
                provider_authority_sha256=authority.provider_authority_sha256,
                endpoint_contract_sha256=authority.endpoint_contract_sha256,
                qualified_request=expected_qualified,
            )
        )
        expected_body = _static_request_closure_body(
            endpoint_name=authority.endpoint_name,
            logical_parameters_sha256=authority.logical_parameters_sha256,
            provider_request_sha256=authority.provider_request_sha256,
            physical_route_ids=authority.physical_route_ids,
            provider_authority_sha256=authority.provider_authority_sha256,
            endpoint_contract_sha256=authority.endpoint_contract_sha256,
            competition_id=authority.competition_id,
            scope_sha256=expected_scope,
            qualified_request=expected_qualified,
        )
        if authority.scope_sha256 != expected_scope or authority.static_authority_sha256 != _sha256(
            expected_body
        ):
            raise ValueError("static closure or scope digest is invalid")
    except (KeyError, TypeError, ValueError, NbaApiCompetitionIdentityError) as exc:
        raise ParserInputCaptureIntegrityError(
            "static request-closure authority failed exact revalidation"
        ) from exc


def _build_static_request_closure_authority(
    *,
    registry: EndpointRegistry,
    endpoint_name: str,
    logical_params: dict[str, object],
    physical_route_ids: tuple[str, ...],
) -> StaticRequestClosureAuthorityV1:
    if logical_params or type(logical_params) is not dict:
        raise ParserInputCaptureIntegrityError(
            "static request closure requires an exact parameterless call"
        )
    try:
        extractor_cls = registry.get(endpoint_name)
    except KeyError as exc:
        raise ParserInputCaptureIntegrityError(
            "static request closure lacks its registered extractor"
        ) from exc
    if (
        not isinstance(extractor_cls, type)
        or not issubclass(extractor_cls, BaseExtractor)
        or extractor_cls.endpoint_name != endpoint_name
        or extractor_cls.category != "static"
    ):
        raise ParserInputCaptureIntegrityError(
            "static request closure extractor identity is invalid"
        )

    from nbadb.contracts.staging_route_contract import staging_route_contract_bundle

    bundle = staging_route_contract_bundle()
    try:
        routes = tuple(bundle.by_route_id[route_id] for route_id in physical_route_ids)
        contract = pinned_static_dataset_contract(endpoint_name)
    except (KeyError, ValueError) as exc:
        raise ParserInputCaptureIntegrityError(
            "static request closure lacks pinned route or dataset authority"
        ) from exc
    if (
        not routes
        or any(route.source_family != "static" for route in routes)
        or {route.endpoint_name for route in routes} != {endpoint_name}
        or {route.provider_endpoint_id for route in routes} != {endpoint_name}
        or len({route.endpoint_contract_sha256 for route in routes}) != 1
        or next(iter({route.endpoint_contract_sha256 for route in routes}))
        != owned_contract_sha256(contract)
    ):
        raise ParserInputCaptureIntegrityError(
            "static request closure routes cross pinned dataset authority"
        )

    requirements = tuple(
        requirement
        for requirement in compile_competition_identity_requirements()
        if requirement.source_family == "static"
        and requirement.provider_endpoint_id == endpoint_name
        and requirement.repo_endpoint_name == endpoint_name
        and requirement.executable
        and requirement.role_binding.binding_strategy == "fixed_static_root"
    )
    if len(requirements) != 1:
        raise ParserInputCaptureIntegrityError(
            "static request closure lacks one fixed competition root"
        )
    try:
        qualified = bind_static_competition_source(requirements[0])
        _safe_json, logical_parameters_sha256, provider_request_sha256 = (
            canonical_semantic_parameters("static", endpoint_name, {})
        )
    except (NbaApiCompetitionIdentityError, TypeError, ValueError) as exc:
        raise ParserInputCaptureIntegrityError(
            "static request closure could not reproduce its fixed authority"
        ) from exc
    provider_authority_sha256 = bundle.provider_authority_sha256
    endpoint_contract_sha256 = owned_contract_sha256(contract)
    scope_sha256 = _sha256(
        _static_scope_payload(
            endpoint_name=endpoint_name,
            provider_request_sha256=provider_request_sha256,
            physical_route_ids=physical_route_ids,
            provider_authority_sha256=provider_authority_sha256,
            endpoint_contract_sha256=endpoint_contract_sha256,
            qualified_request=qualified,
        )
    )
    body = _static_request_closure_body(
        endpoint_name=endpoint_name,
        logical_parameters_sha256=logical_parameters_sha256,
        provider_request_sha256=provider_request_sha256,
        physical_route_ids=physical_route_ids,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256,
        competition_id=requirements[0].league_id,
        scope_sha256=scope_sha256,
        qualified_request=qualified,
    )
    return StaticRequestClosureAuthorityV1(
        endpoint_name=endpoint_name,
        logical_parameters_sha256=logical_parameters_sha256,
        provider_request_sha256=provider_request_sha256,
        physical_route_ids=physical_route_ids,
        provider_authority_sha256=provider_authority_sha256,
        endpoint_contract_sha256=endpoint_contract_sha256,
        competition_id=requirements[0].league_id,
        competition_identity_sha256=qualified.source_request_sha256,
        competition_scope_sha256=qualified.competition_scope_sha256,
        competition_requirement_sha256=qualified.requirement_sha256,
        role_binding_sha256=qualified.role_binding_sha256,
        source_evidence_sha256=qualified.source_evidence_sha256,
        scope_sha256=scope_sha256,
        static_authority_sha256=_sha256(body),
        qualified_request=qualified,
    )


def _entry_is_supported(entry: StagingEntry, params: Mapping[str, object], today: date) -> bool:
    if entry.deprecated_after is not None and today > date.fromisoformat(entry.deprecated_after):
        return False
    season = params.get("season")
    season_year: int | None = None
    if season is not None:
        try:
            season_year = int(str(season)[:4])
        except (TypeError, ValueError):
            season_year = None
    elif (game_id := params.get("game_id")) is not None:
        game_id_text = str(game_id)
        if len(game_id_text) >= 5 and game_id_text[3:5].isdigit():
            suffix = int(game_id_text[3:5])
            season_year = 2000 + suffix if suffix <= 30 else 1900 + suffix
    return entry.min_season is None or season_year is None or season_year >= entry.min_season


def _probe_provider_call(
    registry: EndpointRegistry,
    *,
    endpoint_name: str,
    params: dict[str, object],
    use_multi: bool,
) -> tuple[type, dict[str, object], dict[str, object]]:
    extractor_cls = registry.get(endpoint_name)
    extractor = extractor_cls()
    if not isinstance(extractor, BaseExtractor):
        raise ParserInputCaptureIntegrityError(
            "ordinary request closure requires BaseExtractor provider boundaries"
        )
    extractor.begin_extraction_attempt()
    extractor.set_logical_request_params(params)

    def capture(endpoint_cls: type, **kwargs: Any) -> NoReturn:
        forwarded = _forward_explicit_provider_parameters(
            endpoint_cls,
            dict(kwargs),
            params,
        )
        extractor._inject_timeout(forwarded)
        _slug, runtime_parameters, _proxy, _headers, _timeout = _stats_request_contract(
            endpoint_cls,
            forwarded,
        )
        parameter_names = {
            parameter.name
            for parameter in pinned_request_surface_authority()
            .endpoint("stats", endpoint_cls.__name__)
            .parameters
        }
        constructor_parameters = {
            name: value for name, value in forwarded.items() if name in parameter_names
        }
        raise _ProviderBoundaryProbe(
            endpoint_cls,
            constructor_parameters,
            runtime_parameters,
        )

    probe_extractor = cast("Any", extractor)
    probe_extractor._call_nba_api = capture
    probe_extractor._fetch_nba_api_payload = capture
    coroutine = probe_extractor.extract_all(**params) if use_multi else extractor.extract(**params)
    try:
        coroutine.send(None)
    except _ProviderBoundaryProbe as probe:
        return (
            probe.endpoint_cls,
            probe.constructor_parameters,
            probe.runtime_parameters,
        )
    except StopIteration as exc:
        raise ParserInputCaptureIntegrityError(
            "extractor completed without reaching its owned provider boundary"
        ) from exc
    finally:
        coroutine.close()
    raise ParserInputCaptureIntegrityError("extractor provider probe yielded unexpectedly")


def _competition_qualified_request(
    *,
    endpoint_name: str,
    provider_request: CanonicalProviderRequest,
    supplied: Mapping[str, CompetitionQualifiedRequest] | None,
) -> CompetitionQualifiedRequest | None:
    """Resolve one exact competition authority without inventing dynamic roots."""

    requirements = tuple(
        requirement
        for requirement in compile_competition_identity_requirements()
        if requirement.source_family == provider_request.source_family
        and requirement.provider_endpoint_id == provider_request.endpoint_id
        and requirement.repo_endpoint_name == endpoint_name
    )
    explicit: list[CompetitionQualifiedRequest] = []
    for requirement in requirements:
        if requirement.role_binding.binding_strategy != "explicit_applicability_cell":
            continue
        try:
            explicit.append(bind_explicit_competition_request(requirement, provider_request))
        except NbaApiCompetitionIdentityError:
            continue
    if len(explicit) == 1:
        return explicit[0]
    if explicit:
        return None

    if supplied is None:
        return None
    qualified = supplied.get(provider_request.provider_request_sha256)
    if type(qualified) is not CompetitionQualifiedRequest:
        return None
    dynamic_requirement_ids = {
        requirement.requirement_sha256
        for requirement in requirements
        if requirement.role_binding.binding_strategy == "receipt_bound_dynamic_root"
    }
    try:
        qualified.to_dict()
    except NbaApiCompetitionIdentityError:
        return None
    if (
        qualified.request_kind != "provider_request"
        or qualified.provider_request_sha256 != provider_request.provider_request_sha256
        or qualified.requirement_sha256 not in dynamic_requirement_ids
    ):
        return None
    return qualified


class _GapAccumulator:
    def __init__(self) -> None:
        self._routes: dict[str, set[str]] = defaultdict(set)
        self._endpoints: dict[str, set[str]] = defaultdict(set)
        self._calls: dict[str, int] = defaultdict(int)

    def add(
        self,
        reason_code: str,
        *,
        endpoint_names: Sequence[str],
        route_ids: Sequence[str],
        call_count: int,
    ) -> None:
        self._routes[reason_code].update(route_ids)
        self._endpoints[reason_code].update(endpoint_names)
        self._calls[reason_code] += call_count

    def build(self, *, run_mode: str) -> tuple[RequestClosureScopeGap, ...]:
        gaps: list[RequestClosureScopeGap] = []
        for reason_code in sorted(self._routes):
            route_ids = tuple(sorted(self._routes[reason_code]))
            endpoint_names = tuple(sorted(self._endpoints[reason_code]))
            call_count = self._calls[reason_code]
            evidence_sha256 = _sha256(
                {
                    "run_mode": run_mode,
                    "reason_code": reason_code,
                    "route_ids": list(route_ids),
                    "endpoint_names": list(endpoint_names),
                    "call_count": call_count,
                }
            )
            gaps.append(
                RequestClosureScopeGap(
                    reason_code=cast("Any", reason_code),
                    endpoint_names=endpoint_names,
                    physical_route_ids=route_ids,
                    logical_call_count=call_count,
                    scope_evidence_sha256=evidence_sha256,
                )
            )
        return tuple(sorted(gaps, key=lambda item: item.reason_code))


def build_ordinary_request_closure_authority(
    plan: Sequence[ExtractionPlanItem],
    *,
    registry: EndpointRegistry,
    run_mode: Literal["init", "daily", "monthly", "backfill"],
    support_date: date,
    discovery_seed_requested: bool,
    recurring_live_requested: bool,
    competition_request_authorities: Mapping[str, CompetitionQualifiedRequest] | None = None,
) -> ProductionRequestClosureBuild:
    """Build exact provider authority from the same ordinary execution plan."""

    from nbadb.contracts.staging_route_contract import staging_route_contract_bundle

    bundle = staging_route_contract_bundle()
    pinned = pinned_request_surface_authority()
    pinned_results = pinned_runtime_contracts()
    gaps = _GapAccumulator()
    raw_candidates: list[_LogicalCandidate] = []
    raw_static_authorities: list[StaticRequestClosureAuthorityV1] = []

    if discovery_seed_requested:
        gaps.add(
            "discovery_receipt_not_bound",
            endpoint_names=("league_game_log",),
            route_ids=("league_game_log:stg_league_game_log:0",),
            call_count=1,
        )
    if recurring_live_requested:
        gaps.add(
            "live_many_result_to_one_unproven",
            endpoint_names=("live_snapshot",),
            route_ids=("live_snapshot:stg_nba_api_live_lossless_nodes:0",),
            call_count=1,
        )

    for item in plan:
        entries = tuple(item.entries)
        if item.cume_dependency is not None:
            dependent_entries = item.cume_dependency.dependent_entries
            gaps.add(
                "dependent_scope_unmaterialized",
                endpoint_names=tuple(entry.endpoint_name for entry in dependent_entries),
                route_ids=tuple(
                    f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
                    for entry in dependent_entries
                ),
                call_count=len(item.params) * len(dependent_entries),
            )
        multi_by_endpoint: dict[str, list[StagingEntry]] = defaultdict(list)
        singles: list[StagingEntry] = []
        for entry in entries:
            if entry.use_multi:
                multi_by_endpoint[entry.endpoint_name].append(entry)
            else:
                singles.append(entry)
        call_shapes: list[tuple[str, tuple[StagingEntry, ...], bool, dict[str, object]]] = []
        for params in item.params:
            logical_params = dict(params)
            for entry in singles:
                if _entry_is_supported(entry, logical_params, support_date):
                    call_shapes.append((entry.endpoint_name, (entry,), False, logical_params))
            for endpoint_name, endpoint_entries in multi_by_endpoint.items():
                eligible = tuple(
                    entry
                    for entry in endpoint_entries
                    if _entry_is_supported(entry, logical_params, support_date)
                )
                if eligible:
                    call_shapes.append((endpoint_name, eligible, True, logical_params))

        for endpoint_name, call_entries, use_multi, logical_params in call_shapes:
            physical_route_ids = tuple(
                sorted(
                    f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
                    for entry in call_entries
                )
            )
            route_contracts = tuple(bundle.by_route_id[route_id] for route_id in physical_route_ids)
            source_families = {route.source_family for route in route_contracts}
            if source_families == {"static"}:
                try:
                    if use_multi:
                        raise ParserInputCaptureIntegrityError(
                            "static request closure cannot use multi-result execution"
                        )
                    raw_static_authorities.append(
                        _build_static_request_closure_authority(
                            registry=registry,
                            endpoint_name=endpoint_name,
                            logical_params=logical_params,
                            physical_route_ids=physical_route_ids,
                        )
                    )
                except (TypeError, ValueError, ParserInputCaptureIntegrityError):
                    gaps.add(
                        "static_receipt_not_bound",
                        endpoint_names=(endpoint_name,),
                        route_ids=physical_route_ids,
                        call_count=1,
                    )
                continue
            if source_families != {"stats"}:
                gaps.add(
                    "live_many_result_to_one_unproven",
                    endpoint_names=(endpoint_name,),
                    route_ids=physical_route_ids,
                    call_count=1,
                )
                continue
            provider_endpoint_ids = {route.provider_endpoint_id for route in route_contracts}
            if len(provider_endpoint_ids) != 1:
                gaps.add(
                    "provider_boundary_unproven",
                    endpoint_names=(endpoint_name,),
                    route_ids=physical_route_ids,
                    call_count=1,
                )
                continue
            provider_endpoint_id = next(iter(provider_endpoint_ids))
            endpoint_surface = pinned.endpoint("stats", provider_endpoint_id)
            if any(
                parameter.semantic_role == "pagination_cursor"
                for parameter in endpoint_surface.parameters
            ):
                gaps.add(
                    "pagination_scope_unproven",
                    endpoint_names=(endpoint_name,),
                    route_ids=physical_route_ids,
                    call_count=1,
                )
                continue
            expected_contract = pinned_results.get(provider_endpoint_id)
            expected_ordinals = (
                set()
                if expected_contract is None
                else {result.result_set_index for result in expected_contract.result_sets}
            )
            persisted_ordinals = {route.canonical_result_set_ordinal for route in route_contracts}
            if (
                expected_contract is None
                or any(result.result_set_name is None for result in expected_contract.result_sets)
                or persisted_ordinals != expected_ordinals
            ):
                gaps.add(
                    "result_set_persistence_not_exhaustive",
                    endpoint_names=(endpoint_name,),
                    route_ids=physical_route_ids,
                    call_count=1,
                )
                continue
            try:
                endpoint_cls, constructor_params, runtime_params = _probe_provider_call(
                    registry,
                    endpoint_name=endpoint_name,
                    params=logical_params,
                    use_multi=use_multi,
                )
                if endpoint_cls.__name__ != provider_endpoint_id:
                    raise ParserInputCaptureIntegrityError(
                        "provider probe differs from the staging route contract"
                    )
                request = materialize_provider_request(
                    endpoint_surface,
                    constructor_params,
                    request_surface_sha256=pinned.surface_sha256,
                    runtime_contract_payload_sha256=pinned.runtime_contract_payload_sha256,
                )
                _slug, expected_runtime_params, _proxy, _headers, _timeout = (
                    _stats_request_contract(
                        endpoint_cls,
                        dict(request.materialized_parameters),
                    )
                )
                if runtime_params != expected_runtime_params:
                    raise ParserInputCaptureIntegrityError(
                        "provider probe serialization differs from pinned materialization"
                    )
            except (KeyError, TypeError, ValueError, ParserInputCaptureIntegrityError):
                gaps.add(
                    "provider_boundary_unproven",
                    endpoint_names=(endpoint_name,),
                    route_ids=physical_route_ids,
                    call_count=1,
                )
                continue
            qualified_request = _competition_qualified_request(
                endpoint_name=endpoint_name,
                provider_request=request,
                supplied=competition_request_authorities,
            )
            if qualified_request is None:
                gaps.add(
                    "provider_boundary_unproven",
                    endpoint_names=(endpoint_name,),
                    route_ids=physical_route_ids,
                    call_count=1,
                )
                continue
            raw_candidates.append(
                _LogicalCandidate(
                    endpoint_name=endpoint_name,
                    logical_parameters_sha256=canonical_parameters_sha256(logical_params),
                    provider_endpoint_id=provider_endpoint_id,
                    provider_parameters=tuple(sorted(request.materialized_parameters)),
                    provider_parameters_sha256=canonical_parameters_sha256(
                        dict(request.materialized_parameters)
                    ),
                    provider_request_sha256=request.provider_request_sha256,
                    physical_route_ids=physical_route_ids,
                    qualified_request=qualified_request,
                )
            )

    candidates_by_logical: dict[tuple[str, str], list[_LogicalCandidate]] = defaultdict(list)
    for candidate in raw_candidates:
        candidates_by_logical[
            (candidate.endpoint_name, candidate.logical_parameters_sha256)
        ].append(candidate)
    logical_unique: list[_LogicalCandidate] = []
    for logical_key, candidates in candidates_by_logical.items():
        if len(candidates) != 1:
            gaps.add(
                "logical_call_identity_collision_unproven",
                endpoint_names=(logical_key[0],),
                route_ids=tuple(
                    route_id
                    for candidate in candidates
                    for route_id in candidate.physical_route_ids
                ),
                call_count=len(candidates),
            )
        else:
            logical_unique.append(candidates[0])

    candidates_by_provider: dict[str, list[_LogicalCandidate]] = defaultdict(list)
    for candidate in logical_unique:
        candidates_by_provider[candidate.provider_request_sha256].append(candidate)
    included: list[_LogicalCandidate] = []
    for candidates in candidates_by_provider.values():
        if len(candidates) != 1:
            gaps.add(
                "provider_request_many_call_alias_unproven",
                endpoint_names=tuple(candidate.endpoint_name for candidate in candidates),
                route_ids=tuple(
                    route_id
                    for candidate in candidates
                    for route_id in candidate.physical_route_ids
                ),
                call_count=len(candidates),
            )
        else:
            included.append(candidates[0])

    static_by_endpoint: dict[str, list[StaticRequestClosureAuthorityV1]] = defaultdict(list)
    for static_authority in raw_static_authorities:
        static_by_endpoint[static_authority.endpoint_name].append(static_authority)
    included_static: list[StaticRequestClosureAuthorityV1] = []
    for endpoint_name, static_authorities in static_by_endpoint.items():
        if len(static_authorities) != 1:
            gaps.add(
                "logical_call_identity_collision_unproven",
                endpoint_names=(endpoint_name,),
                route_ids=tuple(
                    route_id
                    for static_authority in static_authorities
                    for route_id in static_authority.physical_route_ids
                ),
                call_count=len(static_authorities),
            )
        else:
            included_static.append(static_authorities[0])
    included_static.sort(key=lambda item: item.endpoint_name)

    scope_gaps = gaps.build(run_mode=run_mode)
    if not included:
        return ProductionRequestClosureBuild(
            None,
            scope_gaps,
            support_date,
            tuple(included_static),
        )

    route_inputs: list[RouteRequestSpecInput] = []
    aliases: list[RequestClosureStagingRouteAlias] = []
    logical_calls: list[RequestClosureLogicalCallBinding] = []
    for candidate in included:
        manifest_route_ids: list[str] = []
        for physical_route_id in candidate.physical_route_ids:
            manifest_route_id = f"{physical_route_id}:request:{candidate.provider_request_sha256}"
            manifest_route_ids.append(manifest_route_id)
            route_inputs.append(
                RouteRequestSpecInput(
                    route_id=manifest_route_id,
                    source_family="stats",
                    endpoint_id=candidate.provider_endpoint_id,
                    parameters=cast(
                        "tuple[tuple[str, Any], ...]",
                        candidate.provider_parameters,
                    ),
                )
            )
            aliases.append(RequestClosureStagingRouteAlias(manifest_route_id, physical_route_id))
        logical_calls.append(
            RequestClosureLogicalCallBinding(
                endpoint_name=candidate.endpoint_name,
                logical_parameters_sha256=candidate.logical_parameters_sha256,
                provider_request_sha256=candidate.provider_request_sha256,
                route_ids=tuple(sorted(manifest_route_ids)),
                provider_parameters_sha256=candidate.provider_parameters_sha256,
            )
        )

    manifest = build_authoritative_route_manifest(
        tuple(sorted(route_inputs, key=lambda item: item.route_id))
    )
    values_by_dimension: dict[tuple[str, str, str], set[object]] = defaultdict(set)
    for route in manifest.routes:
        endpoint = pinned.endpoint(route.source_family, route.endpoint_id)
        values = route.parameter_mapping
        for parameter in endpoint.parameters:
            value = values[parameter.name]
            for dependency_id in parameter.dependencies:
                values_by_dimension[(dependency_id, endpoint.endpoint_id, parameter.name)].add(
                    value
                )
            neutral_evidence = next(
                (
                    evidence
                    for evidence in parameter.evidence
                    if evidence.evidence_kind == "neutral_value"
                ),
                None,
            )
            if (
                parameter.semantic_role == "neutral_filter"
                and neutral_evidence is not None
                and value != neutral_evidence.neutral_value
            ):
                values_by_dimension[
                    ("explicit_scope_manifest", endpoint.endpoint_id, parameter.name)
                ].add(value)

    dimensions: list[RequestScopeDimension] = []
    for (dependency_id, endpoint_id, parameter_name), raw_values in values_by_dimension.items():
        by_bytes = {_canonical_json_bytes(value): value for value in raw_values}
        values = tuple(by_bytes[key] for key in sorted(by_bytes))
        source_authority_sha256 = _sha256(
            {
                "run_mode": run_mode,
                "route_manifest_sha256": manifest.manifest_sha256,
                "dependency_id": dependency_id,
                "endpoint_id": endpoint_id,
                "parameter_name": parameter_name,
                "values": list(values),
            }
        )
        dimensions.append(
            RequestScopeDimension(
                dependency_id=dependency_id,
                source_kind="ordinary_request_scope_v1",
                source_authority_sha256=source_authority_sha256,
                values=cast("tuple[Any, ...]", values),
                endpoint_id=endpoint_id,
                parameter_name=parameter_name,
            )
        )
    dimensions.sort(key=lambda item: item.dimension_sha256)
    scope = RequestScopeManifest(
        request_surface_sha256=pinned.surface_sha256,
        scope_id=f"ordinary_{run_mode}_request_scope_v1",
        seed_route_ids=tuple(route.route_id for route in manifest.routes),
        dimensions=tuple(dimensions),
    )
    routes_by_provider = {
        logical_call.provider_request_sha256: logical_call.route_ids
        for logical_call in logical_calls
    }
    competition_authorities = tuple(
        sorted(
            (
                RequestClosureCompetitionAuthority(
                    qualified_request=candidate.qualified_request,
                    request_binding=build_competition_terminal_request_binding(
                        candidate.qualified_request,
                        route_manifest_sha256=manifest.manifest_sha256,
                        scope_sha256=scope.scope_sha256,
                        route_ids=routes_by_provider[candidate.provider_request_sha256],
                    ),
                )
                for candidate in included
            ),
            key=lambda item: item.request_binding.provider_request_sha256,
        )
    )
    authority = RequestClosureExecutionAuthority(
        route_manifest=manifest,
        scope=scope,
        staging_route_aliases=tuple(sorted(aliases)),
        logical_calls=tuple(sorted(logical_calls)),
        competition_authorities=competition_authorities,
    )
    return ProductionRequestClosureBuild(
        authority,
        scope_gaps,
        support_date,
        tuple(included_static),
    )


__all__ = [
    "ProductionRequestClosureBuild",
    "ReceiptOnlyCaptureFactory",
    "ReceiptOnlyParserInputSink",
    "StaticRequestClosureAuthorityV1",
    "build_ordinary_request_closure_authority",
]
