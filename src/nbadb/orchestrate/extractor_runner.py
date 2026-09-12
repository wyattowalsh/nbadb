from __future__ import annotations

import asyncio
import collections
import hashlib
import inspect
import json
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn, Protocol, cast

from aiolimiter import AsyncLimiter
from loguru import logger

from nbadb.contracts.logical_provider_parameter_binding import (
    compile_logical_provider_parameter_binding as compile_parameter_binding,
)
from nbadb.contracts.logical_provider_parameter_binding import (
    verify_logical_provider_parameter_binding,
)
from nbadb.contracts.raw_request_authority import (
    ParserInputObjectV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    validate_parser_input_object,
    validate_request_attempt_identity,
    validate_request_observation,
)
from nbadb.contracts.raw_transport_contract import (
    source_family_for_transport,
    validate_raw_transport,
)
from nbadb.core.errors import (
    ExtractionError,
    NbaDbError,
    ParserInputCaptureIntegrityError,
    TransientError,
)
from nbadb.core.extraction_failures import (
    SAFE_ROOT_ERROR_NAMES,
    classify_error_name,
    classify_exception,
    root_error_type,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.core.nba_api_request_surface import (
    AuthoritativeRouteManifest,
    NbaApiRequestSurfaceError,
    RequestRouteBinding,
    RequestScopeManifest,
    materialize_provider_request,
    pinned_request_surface_authority,
    require_route_conservation,
)
from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
from nbadb.extract.base import BaseExtractor, is_retryable_error
from nbadb.extract.bronze import (
    STATIC_INPUT_REPRESENTATION,
    CapturedParserInput,
    LogicalCallReceiptBinding,
    RecordedParserInput,
    canonical_parameters_sha256,
    parent_occurrence_states_digest,
)
from nbadb.extract.bronze import (
    ResultSetReceipt as BronzeResultSetReceipt,
)
from nbadb.extract.live_lossless import (
    LIVE_LOSSLESS_STAGING_KEY,
    NbaApiLiveLosslessLanding,
    validate_live_lossless_frame,
)
from nbadb.extract.nba_api_adapter import (
    LOSSLESS_FALLBACK_STAGING_KEY,
    NbaApiCaptureContract,
    NbaApiLosslessFallback,
    NbaApiReceiptSnapshot,
    NbaApiUnknownResponse,
)
from nbadb.extract.raw_request_capture import (
    PendingRawRequestSuccessV2,
    PendingResultOccurrenceV2,
    RawRequestCaptureContextV2,
    RawRequestCaptureIssueV2,
    RawRequestCaptureSnapshotV2,
)
from nbadb.extract.stats_lossless import build_unknown_stats_lossless_fallback
from nbadb.orchestrate.execution_policy import endpoint_family
from nbadb.orchestrate.request_closure_runtime import (
    PersistedStagingReceipt,
    RequestObservation,
)
from nbadb.orchestrate.request_closure_runtime import (
    ResultSetReceipt as ClosureResultSetReceipt,
)
from nbadb.orchestrate.resilience import (
    _AdaptiveThrottle,
    _CircuitBreaker,
    _LatencyTracker,
    _ResponseContractCircuit,
)
from nbadb.orchestrate.staging_map import StagingEntry, get_multi_entries

if TYPE_CHECKING:
    from collections.abc import Coroutine, Iterable, Mapping

    import polars as pl

    from nbadb.core.config import NbaDbSettings
    from nbadb.core.nba_api_competition_identity import CompetitionQualifiedRequest
    from nbadb.core.nba_api_terminal_state import TerminalRequestBinding
    from nbadb.extract.registry import EndpointRegistry
    from nbadb.orchestrate.journal import PipelineJournal
    from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1


type ChunkPersistenceAdmissionsV1 = tuple["W2SourceCallAdmissionV1", ...]
type ChunkPersistenceCallbackV1 = Callable[..., ChunkPersistenceAdmissionsV1 | None]


class _ExtractorLike(Protocol):
    def extract(self, **kwargs: object) -> Coroutine[Any, Any, pl.DataFrame]: ...


class _MultiExtractorLike(Protocol):
    def extract_all(self, **kwargs: object) -> Coroutine[Any, Any, list[pl.DataFrame]]: ...


class _ProgressReporter(Protocol):
    def advance_pattern(self, *, success: bool = True, rows: int = 0) -> None: ...

    def update_circuit_breakers(self, tripped: list[str]) -> None: ...

    def update_rate_info(self, current_rate: float, base_rate: float) -> None: ...

    def record_skip(self) -> None: ...


_VIDEO_LOSSLESS_CANONICAL_STAGING_BY_ENDPOINT = {
    "video_events": "stg_video_events",
    "video_events_asset": "stg_video_events_asset",
}


# ── sync helpers ──────────────────────────────────────────────


def _drive_coroutine[T](coro: Coroutine[Any, Any, T]) -> T:
    """Drive a coroutine that does no real async I/O to completion.

    All nba_api extractors are ``async def`` but perform only synchronous
    HTTP work internally.  This avoids the overhead of creating a fresh
    event loop per call (the old ``asyncio.run()`` pattern).

    Raises ``RuntimeError`` if the coroutine actually yields (i.e. does
    real async I/O), so any future extractor that adds a genuine
    ``await`` will fail loudly rather than silently misbehave.

    IMPORTANT: All BaseExtractor subclasses must perform only synchronous
    I/O inside ``extract()`` / ``extract_all()``.  They are ``async def``
    for interface uniformity but must NOT contain real ``await`` expressions.
    If genuine async I/O is needed in the future, use
    ``asyncio.to_thread`` in the caller instead.
    """
    try:
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    else:
        raise RuntimeError("coroutine yielded unexpectedly; it may perform real async I/O")
    finally:
        coro.close()


def _sync_extract(extractor: object, **kwargs: object) -> pl.DataFrame:
    """Call extractor.extract() synchronously (for asyncio.to_thread)."""
    try:
        return _drive_coroutine(cast("_ExtractorLike", extractor).extract(**kwargs))
    except Exception as exc:
        _raise_extraction_boundary_error(extractor, exc)
        raise AssertionError("unreachable") from exc


def _sync_extract_all(extractor: object, **kwargs: object) -> list[pl.DataFrame]:
    """Call extractor.extract_all() synchronously."""
    try:
        return _drive_coroutine(cast("_MultiExtractorLike", extractor).extract_all(**kwargs))
    except Exception as exc:
        _raise_extraction_boundary_error(extractor, exc)
        raise AssertionError("unreachable") from exc


def _raise_extraction_boundary_error(extractor: object, exc: Exception) -> NoReturn:
    if isinstance(exc, NbaDbError):
        raise exc

    endpoint_name = getattr(extractor, "endpoint_name", type(extractor).__name__)
    if is_retryable_error(exc):
        raise TransientError(
            f"{endpoint_name}: transient extraction failure ({type(exc).__name__})"
        ) from exc

    raise ExtractionError(f"{endpoint_name}: extraction failed ({type(exc).__name__})") from exc


def _record_chunk_completion_heartbeat() -> None:
    heartbeat_path = os.environ.get("NBADB_EXTRACTION_HEARTBEAT_PATH", "").strip()
    if not heartbeat_path:
        return
    try:
        Path(heartbeat_path).touch()
    except OSError as exc:
        logger.warning("failed to update extraction chunk heartbeat: {}", type(exc).__name__)


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ParserInputCaptureIntegrityError(
            "pending request observation is not canonical JSON"
        ) from exc


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ParserInputCaptureIntegrityError(
            f"pending request observation {field_name} is not a canonical SHA-256"
        )
    return value


@dataclass(frozen=True, slots=True)
class _RequestClosureCallAuthority:
    provider_request_sha256: str
    source_family: str
    endpoint_id: str
    route_ids: tuple[str, ...]
    staging_route_aliases: tuple[tuple[str, str], ...]
    provider_semantic_parameters: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True, order=True)
class RequestClosureStagingRouteAlias:
    """Bind one globally unique manifest route to its physical staging route."""

    manifest_route_id: str
    staging_route_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest_route_id, str)
            or not self.manifest_route_id
            or not isinstance(self.staging_route_id, str)
            or not self.staging_route_id
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure staging-route alias identifiers must be nonempty"
            )
        try:
            endpoint_name, staging_key, ordinal_text = self.staging_route_id.rsplit(":", 2)
            ordinal = int(ordinal_text)
        except (TypeError, ValueError) as exc:
            raise ParserInputCaptureIntegrityError(
                "request closure staging-route alias is malformed"
            ) from exc
        if not endpoint_name or not staging_key or ordinal < 0:
            raise ParserInputCaptureIntegrityError(
                "request closure staging-route alias is malformed"
            )


@dataclass(frozen=True, slots=True, order=True)
class RequestClosureLogicalCallBinding:
    """Bind one runner-logical call to one exact materialized provider unit."""

    endpoint_name: str
    logical_parameters_sha256: str
    provider_request_sha256: str
    route_ids: tuple[str, ...]
    provider_parameters_sha256: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.endpoint_name, str) or not self.endpoint_name:
            raise ParserInputCaptureIntegrityError(
                "request closure logical endpoint name must be nonempty"
            )
        _require_sha256(
            self.logical_parameters_sha256,
            field_name="logical parameters SHA-256",
        )
        _require_sha256(
            self.provider_request_sha256,
            field_name="provider request SHA-256",
        )
        if self.provider_parameters_sha256 is not None:
            _require_sha256(
                self.provider_parameters_sha256,
                field_name="provider parameters SHA-256",
            )
        if (
            type(self.route_ids) is not tuple
            or not self.route_ids
            or self.route_ids != tuple(sorted(set(self.route_ids)))
            or any(not isinstance(route_id, str) or not route_id for route_id in self.route_ids)
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure logical-call routes must be sorted, unique, and nonempty"
            )


@dataclass(frozen=True, slots=True)
class RequestClosureCompetitionAuthority:
    """Carry one qualified request and its exact terminal binding together."""

    qualified_request: CompetitionQualifiedRequest
    request_binding: TerminalRequestBinding

    def __post_init__(self) -> None:
        from nbadb.core.nba_api_competition_identity import CompetitionQualifiedRequest
        from nbadb.core.nba_api_terminal_state import TerminalRequestBinding

        if type(self.qualified_request) is not CompetitionQualifiedRequest:
            raise ParserInputCaptureIntegrityError(
                "request closure competition request authority is not exact"
            )
        if type(self.request_binding) is not TerminalRequestBinding:
            raise ParserInputCaptureIntegrityError(
                "request closure terminal request binding is not exact"
            )
        qualified = self.qualified_request
        binding = self.request_binding
        if (
            qualified.request_kind != "provider_request"
            or qualified.provider_request_sha256 != binding.provider_request_sha256
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure competition request and terminal binding disagree"
            )


@dataclass(frozen=True, slots=True)
class RequestClosureExecutionAuthority:
    """Exact route and scope authority for one assurance-enabled runner call.

    The caller owns construction of both manifests.  The runner only verifies
    and consumes them; it never derives a scope digest from local parameters.
    """

    route_manifest: AuthoritativeRouteManifest
    scope: RequestScopeManifest
    staging_route_aliases: tuple[RequestClosureStagingRouteAlias, ...] = ()
    logical_calls: tuple[RequestClosureLogicalCallBinding, ...] = ()
    competition_authorities: tuple[RequestClosureCompetitionAuthority, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.route_manifest, AuthoritativeRouteManifest) or not isinstance(
            self.scope, RequestScopeManifest
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure execution authority has invalid manifests"
            )
        pinned = pinned_request_surface_authority()
        if (
            self.route_manifest.request_surface_sha256 != pinned.surface_sha256
            or self.route_manifest.runtime_contract_payload_sha256
            != pinned.runtime_contract_payload_sha256
            or self.scope.request_surface_sha256 != pinned.surface_sha256
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure execution authority references a foreign pin"
            )
        manifest_route_ids = {route.route_id for route in self.route_manifest.routes}
        if not set(self.scope.seed_route_ids).issubset(manifest_route_ids):
            raise ParserInputCaptureIntegrityError(
                "request closure scope seeds reference routes outside the manifest"
            )
        if not self.staging_route_aliases:
            object.__setattr__(
                self,
                "staging_route_aliases",
                tuple(
                    RequestClosureStagingRouteAlias(route.route_id, route.route_id)
                    for route in self.route_manifest.routes
                ),
            )
        aliases = self.staging_route_aliases
        if (
            type(aliases) is not tuple
            or any(not isinstance(alias, RequestClosureStagingRouteAlias) for alias in aliases)
            or aliases != tuple(sorted(aliases))
            or len({alias.manifest_route_id for alias in aliases}) != len(aliases)
            or {alias.manifest_route_id for alias in aliases} != manifest_route_ids
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure staging-route aliases do not exactly cover the manifest"
            )
        try:
            require_route_conservation(self.route_manifest, self._bindings())
        except NbaApiRequestSurfaceError as exc:
            raise ParserInputCaptureIntegrityError(
                "request closure execution routes are not conserved"
            ) from exc
        bindings = self._bindings()
        if not self.logical_calls:
            physical_by_manifest = {
                alias.manifest_route_id: alias.staging_route_id for alias in aliases
            }
            by_route = {route.route_id: route for route in self.route_manifest.routes}
            derived: list[RequestClosureLogicalCallBinding] = []
            for binding in bindings:
                routes = tuple(by_route[route_id] for route_id in binding.route_ids)
                endpoint_names = {
                    physical_by_manifest[route.route_id].split(":", 1)[0] for route in routes
                }
                logical_parameter_digests = {
                    canonical_parameters_sha256(route.parameter_mapping) for route in routes
                }
                if len(endpoint_names) != 1 or len(logical_parameter_digests) != 1:
                    raise ParserInputCaptureIntegrityError(
                        "request closure cannot infer one logical call from aliased routes"
                    )
                derived.append(
                    RequestClosureLogicalCallBinding(
                        endpoint_name=next(iter(endpoint_names)),
                        logical_parameters_sha256=next(iter(logical_parameter_digests)),
                        provider_request_sha256=binding.provider_request_sha256,
                        route_ids=binding.route_ids,
                    )
                )
            object.__setattr__(self, "logical_calls", tuple(sorted(derived)))
        logical_calls = self.logical_calls
        if (
            type(logical_calls) is not tuple
            or any(not isinstance(item, RequestClosureLogicalCallBinding) for item in logical_calls)
            or logical_calls != tuple(sorted(logical_calls))
            or len({(item.endpoint_name, item.logical_parameters_sha256) for item in logical_calls})
            != len(logical_calls)
            or tuple(sorted(item.provider_request_sha256 for item in logical_calls))
            != tuple(binding.provider_request_sha256 for binding in bindings)
            or {route_id for item in logical_calls for route_id in item.route_ids}
            != manifest_route_ids
            or sum(len(item.route_ids) for item in logical_calls) != len(manifest_route_ids)
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure logical calls do not bijectively cover provider units and routes"
            )
        routes_by_provider = {
            binding.provider_request_sha256: binding.route_ids for binding in bindings
        }
        if any(
            routes_by_provider.get(item.provider_request_sha256) != item.route_ids
            for item in logical_calls
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure logical-call routes differ from provider bindings"
            )
        competition_authorities = self.competition_authorities
        if (
            type(competition_authorities) is not tuple
            or any(
                type(item) is not RequestClosureCompetitionAuthority
                for item in competition_authorities
            )
            or competition_authorities
            != tuple(
                sorted(
                    competition_authorities,
                    key=lambda item: cast("Any", item.request_binding).provider_request_sha256,
                )
            )
            or len(
                {
                    cast("Any", item.request_binding).provider_request_sha256
                    for item in competition_authorities
                }
            )
            != len(competition_authorities)
            or tuple(
                cast("Any", item.request_binding).provider_request_sha256
                for item in competition_authorities
            )
            != tuple(binding.provider_request_sha256 for binding in bindings)
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure competition authorities do not bijectively cover provider units"
            )
        from nbadb.core.nba_api_competition_identity import (
            NbaApiCompetitionIdentityError,
            build_competition_terminal_request_binding,
        )

        for item, provider_binding in zip(
            competition_authorities,
            bindings,
            strict=True,
        ):
            try:
                expected_request_binding = build_competition_terminal_request_binding(
                    cast("Any", item.qualified_request),
                    route_manifest_sha256=self.route_manifest.manifest_sha256,
                    scope_sha256=self.scope.scope_sha256,
                    route_ids=provider_binding.route_ids,
                )
            except NbaApiCompetitionIdentityError as exc:
                raise ParserInputCaptureIntegrityError(
                    "request closure competition-qualified authority did not revalidate"
                ) from exc
            if item.request_binding != expected_request_binding:
                raise ParserInputCaptureIntegrityError(
                    "request closure terminal binding differs from qualified authority"
                )

    def _bindings(self) -> tuple[RequestRouteBinding, ...]:
        pinned = pinned_request_surface_authority()
        routes_by_request: dict[str, list[str]] = {}
        for route in self.route_manifest.routes:
            endpoint = pinned.endpoint(route.source_family, route.endpoint_id)
            request = materialize_provider_request(
                endpoint,
                route.parameter_mapping,
                request_surface_sha256=self.route_manifest.request_surface_sha256,
                runtime_contract_payload_sha256=(
                    self.route_manifest.runtime_contract_payload_sha256
                ),
            )
            routes_by_request.setdefault(request.provider_request_sha256, []).append(route.route_id)
        return tuple(
            RequestRouteBinding(request_sha256, tuple(sorted(route_ids)))
            for request_sha256, route_ids in sorted(routes_by_request.items())
        )

    @property
    def bindings(self) -> tuple[RequestRouteBinding, ...]:
        """Return the independently materialized request-to-route inventory."""

        return self._bindings()

    def request_binding_for(self, provider_request_sha256: str) -> TerminalRequestBinding:
        """Return the unique competition-qualified binding for one provider unit."""

        matches = tuple(
            item.request_binding
            for item in self.competition_authorities
            if cast("Any", item.request_binding).provider_request_sha256 == provider_request_sha256
        )
        if len(matches) != 1:
            raise ParserInputCaptureIntegrityError(
                "request closure provider unit lacks one terminal request binding"
            )
        return matches[0]

    def resolve_call(
        self,
        endpoint_name: str,
        params: dict[str, object],
        required_route_ids: tuple[str, ...],
    ) -> _RequestClosureCallAuthority:
        """Resolve one runner call without inventing endpoint or parameter aliases."""

        if (
            type(required_route_ids) is not tuple
            or not required_route_ids
            or len(required_route_ids) != len(set(required_route_ids))
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure call requires unique nonempty route IDs"
            )
        try:
            logical_parameters_sha256 = canonical_parameters_sha256(params)
        except (TypeError, ValueError) as exc:
            raise ParserInputCaptureIntegrityError(
                "request closure call parameters are not canonical"
            ) from exc
        logical_call = next(
            (
                item
                for item in self.logical_calls
                if item.endpoint_name == endpoint_name
                and item.logical_parameters_sha256 == logical_parameters_sha256
            ),
            None,
        )
        if logical_call is None:
            raise ParserInputCaptureIntegrityError(
                "request closure call parameters differ from its logical authority"
            )
        by_route = {route.route_id: route for route in self.route_manifest.routes}
        physical_by_manifest = {
            alias.manifest_route_id: alias.staging_route_id for alias in self.staging_route_aliases
        }
        selected = tuple(by_route[route_id] for route_id in logical_call.route_ids)
        if any(route.source_family != "stats" for route in selected):
            raise ParserInputCaptureIntegrityError(
                "runner request-closure integration currently accepts stats routes only"
            )
        selected_physical_routes = {physical_by_manifest[route.route_id] for route in selected}
        required_physical_routes = set(required_route_ids)
        additional_routes = selected_physical_routes - required_physical_routes
        if not required_physical_routes <= selected_physical_routes or any(
            route_id.split(":", 2)[1]
            not in {LOSSLESS_FALLBACK_STAGING_KEY, LIVE_LOSSLESS_STAGING_KEY}
            for route_id in additional_routes
        ):
            raise ParserInputCaptureIntegrityError(
                "request closure staging-route aliases differ from the runner call"
            )

        endpoint_ids = {route.endpoint_id for route in selected}
        if len(endpoint_ids) != 1:
            raise ParserInputCaptureIntegrityError(
                "request closure routes do not resolve to one provider request"
            )
        request_key = logical_call.provider_request_sha256
        binding = next(
            (item for item in self._bindings() if item.provider_request_sha256 == request_key),
            None,
        )
        selected_route_ids = tuple(sorted(route.route_id for route in selected))
        if binding is None or binding.route_ids != selected_route_ids:
            raise ParserInputCaptureIntegrityError(
                "request closure routes differ from their materialized binding"
            )
        bound_routes = tuple(by_route[route_id] for route_id in binding.route_ids)
        if {route.source_family for route in bound_routes} != {"stats"} or len(
            {route.endpoint_id for route in bound_routes}
        ) != 1:
            raise ParserInputCaptureIntegrityError(
                "request closure aliases disagree on endpoint or parameters"
            )
        semantic_parameters = bound_routes[0].parameters
        if any(route.parameters != semantic_parameters for route in bound_routes):
            raise ParserInputCaptureIntegrityError(
                "request closure aliases disagree on provider parameters"
            )
        return _RequestClosureCallAuthority(
            provider_request_sha256=request_key,
            source_family="stats",
            endpoint_id=next(iter(endpoint_ids)),
            route_ids=binding.route_ids,
            staging_route_aliases=tuple(
                sorted((route.route_id, physical_by_manifest[route.route_id]) for route in selected)
            ),
            provider_semantic_parameters=cast(
                "tuple[tuple[str, object], ...]",
                semantic_parameters,
            ),
        )

    def resolve_call_if_covered(
        self,
        endpoint_name: str,
        params: dict[str, object],
        required_route_ids: tuple[str, ...],
    ) -> _RequestClosureCallAuthority | None:
        """Resolve an assured call, or return ``None`` for a disjoint typed-gap call.

        Ordinary plan items can contain both closure-backed calls and calls that
        have an explicit fail-closed scope gap. A partial route overlap is never
        a gap: it is an authority mismatch and must still raise.
        """

        physical_route_ids = {alias.staging_route_id for alias in self.staging_route_aliases}
        if set(required_route_ids).isdisjoint(physical_route_ids):
            return None
        return self.resolve_call(endpoint_name, params, required_route_ids)

    def validate_pending(self, pending: PendingRequestObservation) -> None:
        """Rebind compact evidence to this authority before terminal projection."""

        if (
            pending.request_surface_sha256 != self.route_manifest.request_surface_sha256
            or pending.route_manifest_sha256 != self.route_manifest.manifest_sha256
            or pending.scope_sha256 != self.scope.scope_sha256
        ):
            raise ParserInputCaptureIntegrityError(
                "pending request observation references foreign route or scope authority"
            )
        binding = next(
            (
                item
                for item in self._bindings()
                if item.provider_request_sha256 == pending.provider_request_sha256
            ),
            None,
        )
        if binding is None or binding.route_ids != pending.route_ids:
            raise ParserInputCaptureIntegrityError(
                "pending request observation differs from its provider route binding"
            )
        by_route = {route.route_id: route for route in self.route_manifest.routes}
        routes = tuple(by_route[route_id] for route_id in binding.route_ids)
        if {route.source_family for route in routes} != {pending.source_family} or {
            route.endpoint_id for route in routes
        } != {pending.endpoint_id}:
            raise ParserInputCaptureIntegrityError(
                "pending request observation differs from its endpoint authority"
            )
        logical_call = next(
            (
                item
                for item in self.logical_calls
                if item.provider_request_sha256 == pending.provider_request_sha256
            ),
            None,
        )
        if (
            logical_call is None
            or logical_call.logical_parameters_sha256 != pending.logical_parameters_sha256
            or (
                logical_call.provider_parameters_sha256 is not None
                and logical_call.provider_parameters_sha256 != pending.provider_parameters_sha256
            )
        ):
            raise ParserInputCaptureIntegrityError(
                "pending request observation differs from its logical/provider parameters"
            )
        request_binding = cast("Any", self.request_binding_for(pending.provider_request_sha256))
        if (
            request_binding.provider_authority_sha256 != pending.provider_authority_sha256
            or request_binding.source_family != pending.source_family
            or request_binding.endpoint_id != pending.endpoint_id
            or request_binding.route_ids != pending.route_ids
        ):
            raise ParserInputCaptureIntegrityError(
                "pending request observation differs from its terminal request binding"
            )


def _bronze_result_set_payload(receipt: BronzeResultSetReceipt) -> dict[str, object]:
    return {
        "name": receipt.name,
        "provider_index": receipt.provider_index,
        "canonical_index": receipt.canonical_index,
        "headers_sha256": receipt.headers_sha256,
        "row_count": receipt.row_count,
        "json_path": receipt.json_path,
        "container_kind": receipt.container_kind,
        "container_count": receipt.container_count,
        "missing_count": receipt.missing_count,
        "null_count": receipt.null_count,
        "parent_observation_count": receipt.parent_observation_count,
        "parent_occurrence_states_sha256": receipt.parent_occurrence_states_sha256,
        "observed_field_orders_sha256": receipt.observed_field_orders_sha256,
        "normalized_output_sha256": receipt.normalized_output_sha256,
    }


def _pinned_closure_result_sets(
    endpoint_id: str,
    receipts: tuple[BronzeResultSetReceipt, ...],
) -> tuple[ClosureResultSetReceipt, ...]:
    contract = pinned_runtime_contracts().get(endpoint_id)
    expected = () if contract is None else contract.result_sets
    if not expected or len(receipts) != len(expected):
        raise ParserInputCaptureIntegrityError(
            "bronze result sets do not exactly match the pinned result inventory"
        )
    projected: list[ClosureResultSetReceipt] = []
    for receipt, expected_result in zip(receipts, expected, strict=True):
        expected_name = expected_result.result_set_name
        expected_headers_sha256 = _canonical_json_sha256(list(expected_result.expected_columns))
        if (
            expected_name is None
            or receipt.name != expected_name
            or receipt.canonical_index != expected_result.result_set_index
            or receipt.provider_index is None
            or receipt.headers_sha256 != expected_headers_sha256
            or receipt.container_kind != "nba_api_result_set"
            or receipt.container_count != 1
            or receipt.missing_count != 0
            or receipt.null_count != 0
            or receipt.parent_observation_count != 1
            or receipt.parent_occurrence_states_sha256
            != parent_occurrence_states_digest(("present",))
        ):
            raise ParserInputCaptureIntegrityError(
                "bronze result sets are lossless drift rather than pinned-exact output"
            )
        projected.append(
            ClosureResultSetReceipt(
                ordinal=expected_result.result_set_index,
                result_set_name=receipt.name,
                occurrence_state=("present_nonempty" if receipt.row_count > 0 else "present_empty"),
                row_count=receipt.row_count,
                ordered_columns_sha256=receipt.headers_sha256,
                result_set_payload_sha256=receipt.normalized_output_sha256,
            )
        )
    return tuple(projected)


@dataclass(frozen=True, slots=True)
class PendingRequestObservation:
    """Compact bronze-derived success evidence awaiting a staging commit.

    ``lossless_drift`` retains the complete provider receipt inventory, which
    is legitimately empty when an unknown-dynamic response has no legacy
    result envelope. It is intentionally not projectable through the schema-v1
    one-result/one-staging contract. No instance is itself a terminal request
    observation.
    """

    request_surface_sha256: str
    route_manifest_sha256: str
    scope_sha256: str
    provider_request_sha256: str
    source_family: str
    endpoint_id: str
    route_ids: tuple[str, ...]
    attempt_count: int
    retry_ordinal: int
    request_ordinal: int
    http_status: int
    response_body_sha256: str
    response_body_bytes: int
    parser_input_sha256: str
    response_receipt_sha256: str
    logical_call_receipt_sha256: str
    logical_parameters_sha256: str
    provider_parameters_sha256: str
    provider_authority_sha256: str
    endpoint_contract_sha256: str
    result_contract: Literal["pinned_exact", "lossless_drift"]
    bronze_result_sets: tuple[BronzeResultSetReceipt, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "request_surface_sha256",
            "route_manifest_sha256",
            "scope_sha256",
            "provider_request_sha256",
            "response_body_sha256",
            "parser_input_sha256",
            "response_receipt_sha256",
            "logical_call_receipt_sha256",
            "logical_parameters_sha256",
            "provider_parameters_sha256",
            "provider_authority_sha256",
            "endpoint_contract_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if (
            self.source_family != "stats"
            or not isinstance(self.endpoint_id, str)
            or not self.endpoint_id
        ):
            raise ParserInputCaptureIntegrityError(
                "pending request observation must identify one stats endpoint"
            )
        if (
            type(self.route_ids) is not tuple
            or not self.route_ids
            or self.route_ids != tuple(sorted(set(self.route_ids)))
        ):
            raise ParserInputCaptureIntegrityError(
                "pending request observation route IDs must be sorted and unique"
            )
        for field_name in ("attempt_count", "response_body_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ParserInputCaptureIntegrityError(
                    f"pending request observation {field_name} must be positive"
                )
        for field_name in ("retry_ordinal", "request_ordinal"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ParserInputCaptureIntegrityError(
                    f"pending request observation {field_name} must be nonnegative"
                )
        if self.attempt_count != self.retry_ordinal + 1 or self.http_status != 200:
            raise ParserInputCaptureIntegrityError(
                "pending request observation retry or HTTP success authority is invalid"
            )
        if self.result_contract not in {"pinned_exact", "lossless_drift"}:
            raise ParserInputCaptureIntegrityError(
                "pending request observation result contract is invalid"
            )
        if (
            type(self.bronze_result_sets) is not tuple
            or any(
                not isinstance(receipt, BronzeResultSetReceipt)
                for receipt in self.bronze_result_sets
            )
            or (self.result_contract == "pinned_exact" and not self.bronze_result_sets)
        ):
            raise ParserInputCaptureIntegrityError(
                "pending request observation requires exact bronze result receipts"
            )
        if self.result_contract == "pinned_exact":
            _pinned_closure_result_sets(self.endpoint_id, self.bronze_result_sets)

    @property
    def state(self) -> Literal["success_nonempty", "success_empty"]:
        return (
            "success_nonempty"
            if any(receipt.row_count for receipt in self.bronze_result_sets)
            else "success_empty"
        )

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict())

    @property
    def artifact_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    def bind_committed_staging_receipts(
        self,
        authority: RequestClosureExecutionAuthority,
        staging_receipts: tuple[PersistedStagingReceipt, ...],
        *,
        pagination_termination_reason: str | None = None,
    ) -> RequestObservation:
        """Create a terminal observation only after post-commit receipts exist."""

        if not isinstance(authority, RequestClosureExecutionAuthority):
            raise ParserInputCaptureIntegrityError(
                "pending request observation requires its execution authority"
            )
        authority.validate_pending(self)
        if self.result_contract != "pinned_exact":
            raise ParserInputCaptureIntegrityError(
                "lossless drift requires the post-commit many-to-one receipt mapper"
            )
        if type(staging_receipts) is not tuple or any(
            not isinstance(receipt, PersistedStagingReceipt) for receipt in staging_receipts
        ):
            raise ParserInputCaptureIntegrityError(
                "committed staging receipts must be an exact typed tuple"
            )
        return RequestObservation(
            request_surface_sha256=self.request_surface_sha256,
            route_manifest_sha256=self.route_manifest_sha256,
            scope_sha256=self.scope_sha256,
            provider_request_sha256=self.provider_request_sha256,
            source_family=self.source_family,
            endpoint_id=self.endpoint_id,
            route_ids=self.route_ids,
            request_binding=authority.request_binding_for(self.provider_request_sha256),
            state=self.state,
            attempt_count=self.attempt_count,
            http_status=self.http_status,
            response_body_sha256=self.response_body_sha256,
            response_body_bytes=self.response_body_bytes,
            parser_input_sha256=self.parser_input_sha256,
            pagination_termination_reason=pagination_termination_reason,
            result_sets=_pinned_closure_result_sets(
                self.endpoint_id,
                self.bronze_result_sets,
            ),
            staging_receipts=staging_receipts,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "request_surface_sha256": self.request_surface_sha256,
            "route_manifest_sha256": self.route_manifest_sha256,
            "scope_sha256": self.scope_sha256,
            "provider_request_sha256": self.provider_request_sha256,
            "source_family": self.source_family,
            "endpoint_id": self.endpoint_id,
            "route_ids": list(self.route_ids),
            "attempt_count": self.attempt_count,
            "retry_ordinal": self.retry_ordinal,
            "request_ordinal": self.request_ordinal,
            "http_status": self.http_status,
            "response_body_sha256": self.response_body_sha256,
            "response_body_bytes": self.response_body_bytes,
            "parser_input_sha256": self.parser_input_sha256,
            "response_receipt_sha256": self.response_receipt_sha256,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "provider_parameters_sha256": self.provider_parameters_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "result_contract": self.result_contract,
            "bronze_result_sets": [
                _bronze_result_set_payload(receipt) for receipt in self.bronze_result_sets
            ],
        }

    @classmethod
    def from_dict(cls, payload: object) -> PendingRequestObservation:
        expected = {
            "attempt_count",
            "bronze_result_sets",
            "endpoint_contract_sha256",
            "endpoint_id",
            "http_status",
            "logical_call_receipt_sha256",
            "logical_parameters_sha256",
            "parser_input_sha256",
            "provider_authority_sha256",
            "provider_parameters_sha256",
            "provider_request_sha256",
            "request_ordinal",
            "request_surface_sha256",
            "response_body_bytes",
            "response_body_sha256",
            "response_receipt_sha256",
            "result_contract",
            "retry_ordinal",
            "route_ids",
            "route_manifest_sha256",
            "scope_sha256",
            "source_family",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ParserInputCaptureIntegrityError(
                "pending request observation has missing or unexpected fields"
            )
        typed_payload = cast("dict[str, object]", payload)
        route_ids = typed_payload["route_ids"]
        raw_receipts = typed_payload["bronze_result_sets"]
        if not isinstance(route_ids, list) or any(not isinstance(item, str) for item in route_ids):
            raise ParserInputCaptureIntegrityError(
                "pending request observation route IDs are invalid"
            )
        if not isinstance(raw_receipts, list) or any(
            not isinstance(item, dict) for item in raw_receipts
        ):
            raise ParserInputCaptureIntegrityError(
                "pending request observation bronze result receipts are invalid"
            )
        typed_route_ids = cast("list[str]", route_ids)
        typed_receipts = cast("list[dict[str, object]]", raw_receipts)
        receipt_keys = {
            "canonical_index",
            "container_count",
            "container_kind",
            "headers_sha256",
            "json_path",
            "missing_count",
            "name",
            "normalized_output_sha256",
            "null_count",
            "observed_field_orders_sha256",
            "parent_observation_count",
            "parent_occurrence_states_sha256",
            "provider_index",
            "row_count",
        }
        if any(set(item) != receipt_keys for item in typed_receipts):
            raise ParserInputCaptureIntegrityError(
                "pending request observation bronze receipt fields are invalid"
            )
        try:
            receipts = tuple(BronzeResultSetReceipt(**cast("Any", item)) for item in typed_receipts)
            return cls(
                request_surface_sha256=cast("str", typed_payload["request_surface_sha256"]),
                route_manifest_sha256=cast("str", typed_payload["route_manifest_sha256"]),
                scope_sha256=cast("str", typed_payload["scope_sha256"]),
                provider_request_sha256=cast("str", typed_payload["provider_request_sha256"]),
                source_family=cast("str", typed_payload["source_family"]),
                endpoint_id=cast("str", typed_payload["endpoint_id"]),
                route_ids=tuple(typed_route_ids),
                attempt_count=cast("int", typed_payload["attempt_count"]),
                retry_ordinal=cast("int", typed_payload["retry_ordinal"]),
                request_ordinal=cast("int", typed_payload["request_ordinal"]),
                http_status=cast("int", typed_payload["http_status"]),
                response_body_sha256=cast("str", typed_payload["response_body_sha256"]),
                response_body_bytes=cast("int", typed_payload["response_body_bytes"]),
                parser_input_sha256=cast("str", typed_payload["parser_input_sha256"]),
                response_receipt_sha256=cast("str", typed_payload["response_receipt_sha256"]),
                logical_call_receipt_sha256=cast(
                    "str", typed_payload["logical_call_receipt_sha256"]
                ),
                logical_parameters_sha256=cast("str", typed_payload["logical_parameters_sha256"]),
                provider_parameters_sha256=cast("str", typed_payload["provider_parameters_sha256"]),
                provider_authority_sha256=cast("str", typed_payload["provider_authority_sha256"]),
                endpoint_contract_sha256=cast("str", typed_payload["endpoint_contract_sha256"]),
                result_contract=cast(
                    'Literal["pinned_exact", "lossless_drift"]',
                    typed_payload["result_contract"],
                ),
                bronze_result_sets=receipts,
            )
        except (TypeError, ValueError) as exc:
            raise ParserInputCaptureIntegrityError(
                "pending request observation payload is invalid"
            ) from exc

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> PendingRequestObservation:
        if not isinstance(encoded, bytes):
            raise ParserInputCaptureIntegrityError(
                "pending request observation encoding must be bytes"
            )

        def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ParserInputCaptureIntegrityError(
                        f"pending request observation contains duplicate key {key!r}"
                    )
                result[key] = value
            return result

        try:
            decoded = json.loads(
                encoded.decode("utf-8"),
                object_pairs_hook=reject_duplicate_keys,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ParserInputCaptureIntegrityError(
                        f"pending request observation contains non-finite value {value}"
                    )
                ),
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserInputCaptureIntegrityError(
                "pending request observation encoding is invalid"
            ) from exc
        if not isinstance(decoded, dict) or _canonical_json_bytes(decoded) != encoded:
            raise ParserInputCaptureIntegrityError(
                "pending request observation encoding is not canonical"
            )
        return cls.from_dict(decoded)


@dataclass(frozen=True, slots=True)
class _DeferredExtraction:
    endpoint_name: str
    params: dict[str, object]
    wait_seconds: float
    staging_key: str | None = None
    eligible_staging_keys: tuple[str, ...] = ()
    raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None
    retry_ordinal_offset: int = 0

    def __post_init__(self) -> None:
        if (
            (
                self.raw_request_capture_snapshot is not None
                and type(self.raw_request_capture_snapshot) is not RawRequestCaptureSnapshotV2
            )
            or type(self.retry_ordinal_offset) is not int
            or self.retry_ordinal_offset < 0
        ):
            raise ParserInputCaptureIntegrityError(
                "deferred extraction has malformed public raw-request evidence"
            )


@dataclass(frozen=True, slots=True)
class _PendingJournalSuccess:
    endpoint_name: str
    params_json: str
    rows: int
    capture_receipt_snapshot: NbaApiReceiptSnapshot | None = None
    receipt_binding: LogicalCallReceiptBinding | None = None
    pending_request_observations: tuple[PendingRequestObservation, ...] = ()
    raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None
    logical_provider_parameter_binding: LogicalProviderParameterBindingV1 | None = None
    expected_logical_provider_parameter_binding_sha256: str | None = None
    recorded_static_attempts: tuple[RecordedParserInput, ...] = ()
    discard_parser_inputs: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    recorded: bool = False

    @property
    def w2_required(self) -> bool:
        """Whether this success can enter the selected-terminal W2 pipeline."""

        snapshot = self.raw_request_capture_snapshot
        return snapshot is not None and not snapshot.issues

    def __post_init__(self) -> None:
        if (
            self.raw_request_capture_snapshot is not None
            and type(self.raw_request_capture_snapshot) is not RawRequestCaptureSnapshotV2
        ):
            raise ParserInputCaptureIntegrityError(
                "pending journal success has malformed public raw-request evidence"
            )
        snapshot = self.raw_request_capture_snapshot
        if (
            snapshot is not None
            and snapshot.issues
            and (
                len(snapshot.issues) != 1
                or snapshot.issues[0].code != "success_result_authority_pending"
            )
        ):
            raise ParserInputCaptureIntegrityError(
                "pending journal success has unexpected incomplete Raw V2 evidence"
            )
        parameter_binding = self.logical_provider_parameter_binding
        parameter_binding_sha256 = self.expected_logical_provider_parameter_binding_sha256
        if (parameter_binding is None) != (parameter_binding_sha256 is None):
            raise ParserInputCaptureIntegrityError(
                "pending journal success has a one-sided logical/provider parameter binding"
            )
        if parameter_binding is not None:
            try:
                replayed = verify_logical_provider_parameter_binding(
                    parameter_binding,
                    expected_binding_sha256=parameter_binding_sha256,
                )
            except Exception as exc:
                raise ParserInputCaptureIntegrityError(
                    "pending journal success logical/provider parameter binding did not revalidate"
                ) from exc
            if replayed != parameter_binding:
                raise ParserInputCaptureIntegrityError(
                    "pending journal success logical/provider parameter binding changed on replay"
                )
        if type(self.recorded_static_attempts) is not tuple or any(
            type(item) is not RecordedParserInput for item in self.recorded_static_attempts
        ):
            raise ParserInputCaptureIntegrityError(
                "pending journal success has malformed recorded static evidence"
            )


@dataclass(frozen=True, slots=True)
class _AdmittedJournalSuccess:
    """One pending completion paired with its exact W2 admission, when required."""

    pending: _PendingJournalSuccess
    w2_admission: W2SourceCallAdmissionV1 | None

    def __post_init__(self) -> None:
        from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1

        if type(self.pending) is not _PendingJournalSuccess or (
            self.w2_admission is not None and type(self.w2_admission) is not W2SourceCallAdmissionV1
        ):
            raise ParserInputCaptureIntegrityError(
                "journal completion has malformed W2 admission evidence"
            )


@dataclass(frozen=True, slots=True)
class _JournaledExtraction:
    data: pl.DataFrame | list[pl.DataFrame]
    success: _PendingJournalSuccess
    raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None
    lossless_fallbacks: tuple[NbaApiLosslessFallback, ...] = ()
    live_lossless_landings: tuple[NbaApiLiveLosslessLanding, ...] = ()

    def __post_init__(self) -> None:
        if self.raw_request_capture_snapshot is not self.success.raw_request_capture_snapshot:
            raise ParserInputCaptureIntegrityError(
                "journaled extraction changed its public raw-request snapshot"
            )


@dataclass(frozen=True, slots=True)
class _ExtractionTaskResult:
    frames: dict[str, pl.DataFrame]
    pending_success: _PendingJournalSuccess | None = None
    raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None
    source_endpoint_name: str | None = None
    source_params_json: str | None = None
    expected_staging_keys: tuple[str, ...] = ()
    result_route_ids_by_staging_key: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if (
            self.pending_success is not None
            and self.raw_request_capture_snapshot
            is not self.pending_success.raw_request_capture_snapshot
        ):
            raise ParserInputCaptureIntegrityError(
                "extraction task changed its public raw-request snapshot"
            )


@dataclass(frozen=True, slots=True)
class _SkippedTaskResult:
    status: Literal["journal_skip", "retry_skip"]
    endpoint_name: str
    params_json: str


@dataclass(frozen=True, slots=True)
class _FailedExtraction:
    endpoint_name: str
    params_json: str
    error: str
    status: Literal["failure", "deferred_failure", "unexpected"] = "failure"
    failure_class: str = ""
    raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None

    def __post_init__(self) -> None:
        if (
            self.raw_request_capture_snapshot is not None
            and type(self.raw_request_capture_snapshot) is not RawRequestCaptureSnapshotV2
        ):
            raise ParserInputCaptureIntegrityError(
                "failed extraction has malformed public raw-request evidence"
            )
        if not self.failure_class:
            object.__setattr__(self, "failure_class", classify_error_name(self.error))


if TYPE_CHECKING:
    from nbadb.contracts.logical_provider_parameter_binding import (
        LogicalProviderParameterBindingV1,
    )

    type _TaskValue = (
        dict[str, pl.DataFrame]
        | _ExtractionTaskResult
        | _DeferredExtraction
        | _SkippedTaskResult
        | _FailedExtraction
        | None
    )
    type _TaskFactory = Callable[[], Coroutine[Any, Any, _TaskValue]]


@dataclass(frozen=True, slots=True)
class _ChunkTaskBatch:
    tasks: list[_TaskFactory]
    eligible_calls: int = 0
    eligible_calls_by_endpoint: dict[str, int] = field(default_factory=dict)
    support_skip_count: int = 0


@dataclass(frozen=True, slots=True)
class _PreparedChunkPersistence:
    """One-time callback signature analysis reused across every chunk."""

    callback: ChunkPersistenceCallbackV1
    accepted_metadata: tuple[str, ...] | None

    def __call__(
        self,
        frames: dict[str, pl.DataFrame],
        *,
        pattern: str,
        chunk_index: int,
        chunk_params: list[dict],
        entries: list[StagingEntry],
        expected_staging_keys: list[str],
        source_results: list[dict[str, object]],
        failure_raw_request_capture_snapshots: tuple[RawRequestCaptureSnapshotV2, ...],
    ) -> ChunkPersistenceAdmissionsV1 | None:
        metadata = {
            "pattern": pattern,
            "chunk_index": chunk_index,
            "chunk_params": chunk_params,
            "entries": entries,
            "expected_staging_keys": expected_staging_keys,
            "source_results": source_results,
            "failure_raw_request_capture_snapshots": (failure_raw_request_capture_snapshots),
        }
        if self.accepted_metadata is None:
            return self.callback(frames, **metadata)
        if self.accepted_metadata:
            return self.callback(
                frames,
                **{key: metadata[key] for key in self.accepted_metadata},
            )
        return self.callback(frames)


@dataclass(frozen=True, slots=True)
class _BoundedTaskExecution:
    results: list[_TaskValue | BaseException]
    peak_in_flight: int


@dataclass(slots=True)
class PatternExtractionResult:
    frames: dict[str, pl.DataFrame]
    eligible_calls: int = 0
    support_skip_count: int = 0
    journal_skip_count: int = 0
    retry_skip_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    deferred_failure_count: int = 0
    row_count: int = 0
    scheduled_calls: int = 0
    unattempted_eligible_calls: int = 0
    errors: list[str] = field(default_factory=list)
    response_contract_circuit: dict[str, dict[str, int | str | bool]] = field(default_factory=dict)
    pending_request_observations: tuple[PendingRequestObservation, ...] = ()
    raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None

    @property
    def is_complete(self) -> bool:
        if self.failure_count or self.deferred_failure_count:
            return False
        completed = self.success_count + self.journal_skip_count + self.retry_skip_count
        return completed == self.eligible_calls


class _CircuitBreakerTimeoutError(RuntimeError):
    """Raised when an endpoint remains breaker-open past the configured budget."""


class ExtractorRunner:
    """Runs extractors concurrently with semaphore gating and journal
    tracking.

    Supports resume (skips already-extracted via journal), endpoint
    deduplication for ``use_multi`` entries, and chunked processing
    for game-level extractions.
    """

    _LATE_RECOVERY_ENDPOINTS = frozenset({"scoreboard_v2", "scoreboard_v3"})

    def __init__(
        self,
        registry: EndpointRegistry,
        settings: NbaDbSettings,
        journal: PipelineJournal,
        rate_limit: float = 10.0,
        progress: _ProgressReporter | None = None,
        *,
        capture_contract_factory: (
            Callable[[str, dict[str, object]], NbaApiCaptureContract] | None
        ) = None,
        raw_request_capture_context_factory: (
            Callable[[str, dict[str, object]], RawRequestCaptureContextV2] | None
        ) = None,
        call_admission: (Callable[[str, dict[str, object], tuple[str, ...]], None] | None) = None,
        conditional_route_admission: (
            Callable[
                [str, dict[str, object], tuple[str, ...], tuple[str, ...]],
                None,
            ]
            | None
        ) = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._journal = journal
        self._progress = progress
        self._capture_contract_factory = capture_contract_factory
        self._raw_request_capture_context_factory = raw_request_capture_context_factory
        self._call_admission = call_admission
        self._conditional_route_admission = conditional_route_admission
        self._capture_provider_authority_sha256 = (
            expected_nba_api_provider_authority()["authority_sha256"]
            if capture_contract_factory is not None
            else None
        )
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._rate_limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
        self._endpoint_rate_limiters: dict[str, AsyncLimiter] = {}
        self._family_rate_limiters: dict[str, AsyncLimiter] = {}
        self._adaptive = _AdaptiveThrottle(
            base_rate=rate_limit,
            min_rate=getattr(settings, "adaptive_rate_min", 1.0),
            recovery_threshold=getattr(settings, "adaptive_rate_recovery", 50),
        )
        self._family_adaptive: dict[str, _AdaptiveThrottle] = {}
        try:
            self._thread_pool = ThreadPoolExecutor(max_workers=settings.thread_pool_size)
            self._task_window_size = max(1, int(settings.thread_pool_size))
        except (AttributeError, ValueError, TypeError) as exc:
            logger.warning("thread_pool_size misconfigured, falling back to 4: {}", exc)
            self._thread_pool = ThreadPoolExecutor(max_workers=4)
            self._task_window_size = 4
        if raw_request_capture_context_factory is not None and capture_contract_factory is None:
            self._thread_pool.shutdown(wait=False)
            raise ParserInputCaptureIntegrityError(
                "public raw-request capture requires private parser-input capture"
            )
        self._circuit_breaker = _CircuitBreaker(
            threshold=getattr(settings, "circuit_breaker_threshold", 10),
            recovery_seconds=getattr(settings, "circuit_breaker_recovery", 120.0),
        )
        self._latency = _LatencyTracker(
            window_size=getattr(settings, "latency_window_size", 200),
        )
        # Cache for multi-endpoint results: (endpoint, params_json) -> DFs
        self._multi_cache: dict[tuple[str, str], list[pl.DataFrame]] = {}
        # Count of extractions skipped because already done in journal
        self.skipped: int = 0
        # Count only journal-driven skips for the current run.
        self.skipped_due_to_journal: int = 0
        # Count of extraction calls scheduled after runtime eligibility checks.
        self.planned_calls: int = 0
        # Count of extraction calls that failed in the current run after retries.
        self.failed_current_run: int = 0
        # Compact bronze-derived evidence is published only after an optional
        # chunk persistence callback returns successfully.  It is never a
        # terminal request-closure observation by itself.
        self._pending_request_observations: list[PendingRequestObservation] = []
        self._raw_request_capture_snapshots: list[RawRequestCaptureSnapshotV2] = []

    def configure_raw_request_capture_context_factory(
        self,
        factory: Callable[[str, dict[str, object]], RawRequestCaptureContextV2],
    ) -> None:
        """Install one exact public context compiler before any call is planned.

        Request-closure authority is compiled only after the runner exposes its
        registry, so construction-time injection is not always possible.  This
        one-shot boundary retains the same fail-closed invariants without
        allowing mid-run authority replacement.
        """

        if not callable(factory):
            raise TypeError("raw-request capture context factory must be callable")
        if self._capture_contract_factory is None:
            raise ParserInputCaptureIntegrityError(
                "public raw-request capture requires private parser-input capture"
            )
        if self._raw_request_capture_context_factory is not None:
            raise ParserInputCaptureIntegrityError(
                "public raw-request capture context factory is already configured"
            )
        if (
            self.planned_calls
            or self._pending_request_observations
            or self._raw_request_capture_snapshots
        ):
            raise ParserInputCaptureIntegrityError(
                "public raw-request capture context must be configured before planning"
            )
        self._raw_request_capture_context_factory = factory

    def shutdown(self) -> None:
        """Shut down the thread pool to release worker threads."""
        self._thread_pool.shutdown(wait=False)

    def request_closure_pending_snapshot(self) -> tuple[PendingRequestObservation, ...]:
        """Return immutable pending evidence published by completed chunks."""

        return tuple(self._pending_request_observations)

    def raw_request_capture_snapshot(self) -> RawRequestCaptureSnapshotV2 | None:
        """Return every verified public snapshot published by completed calls."""

        return self._merge_raw_request_capture_snapshots(tuple(self._raw_request_capture_snapshots))

    def log_latency_summary(self) -> None:
        """Log the top 5 slowest endpoints by p95 latency."""
        sums = self._latency.all_summaries()
        if not sums:
            return
        sorted_eps = sorted(sums.items(), key=lambda kv: kv[1]["p95"], reverse=True)
        logger.info("Latency Summary (Top 5 slowest endpoints by p95):")
        for ep, s in sorted_eps[:5]:
            logger.info(
                "  {:<25} | p50: {:5.2f}s | p95: {:5.2f}s | p99: {:5.2f}s | count: {}",
                ep,
                s["p50"],
                s["p95"],
                s["p99"],
                int(s["count"]),
            )

    async def __aenter__(self) -> ExtractorRunner:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.shutdown()

    def __del__(self) -> None:
        self._thread_pool.shutdown(wait=False)

    # ── public API ─────────────────────────────────────────────

    async def run_pattern(
        self,
        pattern: str,
        param_sets: list[dict],
        entries: list[StagingEntry],
        on_progress: _ProgressReporter | None = None,
        *,
        skip_items: set[tuple[str, str]] | None = None,
        persist_chunk_results: ChunkPersistenceCallbackV1 | None = None,
        support_date: date | None = None,
        required_route_ids: tuple[str, ...] | None = None,
        snapshot_at: datetime | None = None,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Extract all *entries* across every *param_set*.

        Returns ``{staging_key: concatenated_df}`` for all entries
        that produced data.  Also increments ``self.skipped`` for
        each param set that was already recorded in the journal.
        """
        result = await self.run_pattern_result(
            pattern,
            param_sets,
            entries,
            on_progress=on_progress,
            skip_items=skip_items,
            persist_chunk_results=persist_chunk_results,
            support_date=support_date,
            required_route_ids=required_route_ids,
            snapshot_at=snapshot_at,
            request_closure_authority=request_closure_authority,
        )
        return result.frames

    async def run_pattern_result(
        self,
        pattern: str,
        param_sets: list[dict],
        entries: list[StagingEntry],
        on_progress: _ProgressReporter | None = None,
        *,
        skip_items: set[tuple[str, str]] | None = None,
        persist_chunk_results: ChunkPersistenceCallbackV1 | None = None,
        support_date: date | None = None,
        required_route_ids: tuple[str, ...] | None = None,
        snapshot_at: datetime | None = None,
        retain_frames: bool = True,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
    ) -> PatternExtractionResult:
        """Extract a pattern and return frames plus call-local accounting.

        ``retain_frames=False`` is an explicit streaming-sink contract: every
        successful chunk must be persisted before its journal success is
        recorded, then its frames are released instead of being accumulated
        and concatenated again at the end of the pattern.  The default keeps
        the historical return-value behavior for in-memory consumers.
        """

        effective_support_date = support_date or date.today()
        if not retain_frames and persist_chunk_results is None:
            raise ValueError("retain_frames=False requires persist_chunk_results")
        if snapshot_at is not None and (
            required_route_ids is None
            or not isinstance(snapshot_at, datetime)
            or snapshot_at.tzinfo is None
            or snapshot_at.utcoffset() is None
        ):
            raise ParserInputCaptureIntegrityError(
                "snapshot_at requires an aware exact-plan execution timestamp"
            )
        self._assert_no_derived_fanout(
            param_sets,
            entries,
            required_route_ids,
        )
        if request_closure_authority is not None:
            if not isinstance(request_closure_authority, RequestClosureExecutionAuthority):
                raise ParserInputCaptureIntegrityError(
                    "request closure authority has an invalid type"
                )
            if self._capture_contract_factory is None:
                raise ParserInputCaptureIntegrityError(
                    "request closure authority requires receipt-bound parser-input capture"
                )
        if required_route_ids is not None:
            unsupported_routes = tuple(
                self._result_route_id(entry)
                for entry in entries
                if not self._entry_is_supported(
                    entry,
                    param_sets[0],
                    today=effective_support_date,
                )
            )
            if unsupported_routes:
                raise ParserInputCaptureIntegrityError(
                    "sealed-plan route is filtered by its fixed support date: "
                    + ",".join(unsupported_routes)
                )

        multi_entries, single_entries, multi_by_ep = self._classify_entries(entries)
        if required_route_ids is not None and len(single_entries) + len(multi_by_ep) != 1:
            raise ParserInputCaptureIntegrityError(
                "one sealed dispatch must classify as exactly one logical provider call"
            )
        if request_closure_authority is not None:
            for params in param_sets:
                for entry in single_entries:
                    if self._entry_is_supported(entry, params, today=effective_support_date):
                        request_closure_authority.resolve_call_if_covered(
                            entry.endpoint_name,
                            dict(params),
                            (self._result_route_id(entry),),
                        )
                for endpoint_name, endpoint_entries in multi_by_ep.items():
                    eligible_entries = tuple(
                        entry
                        for entry in endpoint_entries
                        if self._entry_is_supported(entry, params, today=effective_support_date)
                    )
                    if eligible_entries:
                        request_closure_authority.resolve_call_if_covered(
                            endpoint_name,
                            dict(params),
                            tuple(
                                sorted(self._result_route_id(entry) for entry in eligible_entries)
                            ),
                        )
        accum: dict[str, list[pl.DataFrame]] = {e.staging_key: [] for e in entries}
        single_by_key = {
            (entry.endpoint_name, entry.staging_key): entry for entry in single_entries
        }
        pattern_result = PatternExtractionResult(frames={})
        configured_thresholds = getattr(
            self._settings,
            "response_contract_circuit_thresholds",
            {},
        )
        response_contract_circuit = _ResponseContractCircuit(
            configured_thresholds if isinstance(configured_thresholds, dict) else {}
        )
        (
            pattern_result.eligible_calls,
            pattern_result.support_skip_count,
            eligible_calls_by_endpoint,
        ) = self._support_eligible_call_counts(
            single_entries,
            multi_by_ep,
            param_sets,
            today=effective_support_date,
        )
        scheduled_calls_by_endpoint: collections.Counter[str] = collections.Counter()
        prepared_persistence = (
            self._prepare_chunk_persistence(persist_chunk_results)
            if persist_chunk_results is not None
            else None
        )

        chunk_size = self._chunk_size_for_entries(pattern, entries)
        for chunk_index, chunk_start in enumerate(range(0, max(len(param_sets), 1), chunk_size)):
            chunk = param_sets[chunk_start : chunk_start + chunk_size]
            if not chunk:
                break
            chunk_accum: dict[str, list[pl.DataFrame]] = {e.staging_key: [] for e in entries}
            pending_successes: list[_PendingJournalSuccess] = []
            source_results: list[dict[str, object]] = []
            defer_journal_success = (
                persist_chunk_results is not None
                or request_closure_authority is not None
                or self._raw_request_capture_context_factory is not None
            )
            success_count_before = pattern_result.success_count
            failure_count_before = (
                pattern_result.failure_count + pattern_result.deferred_failure_count
            )
            skip_count_before = pattern_result.journal_skip_count + pattern_result.retry_skip_count

            admission_prechecked = self._admit_chunk_calls(
                single_entries,
                multi_by_ep,
                chunk,
                today=effective_support_date,
            )
            already_done = self._prefetch_done(
                single_entries,
                multi_by_ep,
                chunk,
                today=effective_support_date,
            )
            if (
                request_closure_authority is not None
                or self._raw_request_capture_context_factory is not None
            ):
                # A journal root alone cannot reconstruct response/result evidence for
                # this exact manifest. Re-execute until canonical inventory restore is
                # implemented instead of silently accepting an unobserved provider unit.
                already_done = set()
            chunk_batch = self._build_chunk_tasks(
                single_entries,
                multi_by_ep,
                chunk,
                already_done,
                on_progress=on_progress,
                skip_items=skip_items,
                defer_journal_success=defer_journal_success,
                response_contract_circuit=response_contract_circuit,
                today=effective_support_date,
                admission_prechecked=admission_prechecked,
                snapshot_at=snapshot_at,
                request_closure_authority=request_closure_authority,
            )
            pattern_result.scheduled_calls += chunk_batch.eligible_calls
            scheduled_calls_by_endpoint.update(chunk_batch.eligible_calls_by_endpoint)

            task_execution = await self._run_bounded_tasks(chunk_batch.tasks)
            results = task_execution.results
            delayed = [r for r in results if isinstance(r, _DeferredExtraction)]
            immediate = [r for r in results if not isinstance(r, _DeferredExtraction)]
            finalized_capture_results: list[object] = list(immediate)
            chunk_expected_staging_keys = set(self._successful_staging_keys(immediate))
            pending_successes.extend(
                self._collect_results(immediate, chunk_accum, on_progress, pattern_result)
            )
            if persist_chunk_results is not None:
                source_results.extend(
                    self._source_results_for_persistence(
                        immediate,
                        plan_live_snapshot_at=snapshot_at,
                    )
                )
            if delayed:
                replay_results = await self._replay_deferred_chunk(
                    delayed,
                    single_by_key=single_by_key,
                    multi_by_ep=multi_by_ep,
                    on_progress=on_progress,
                    defer_journal_success=defer_journal_success,
                    response_contract_circuit=response_contract_circuit,
                    snapshot_at=snapshot_at,
                    request_closure_authority=request_closure_authority,
                )
                replay_deferred = [r for r in replay_results if isinstance(r, _DeferredExtraction)]
                if replay_deferred:
                    logger.error(
                        "late recovery replay returned deferred extractions unexpectedly: {}",
                        len(replay_deferred),
                    )
                    pattern_result.deferred_failure_count += len(replay_deferred)
                    for item in replay_deferred:
                        pattern_result.errors.append(
                            f"{item.endpoint_name}[{json.dumps(item.params, sort_keys=True)}]: "
                            "deferred recovery did not complete"
                        )
                pending_successes.extend(
                    self._collect_results(
                        [r for r in replay_results if not isinstance(r, _DeferredExtraction)],
                        chunk_accum,
                        on_progress,
                        pattern_result,
                    )
                )
                finalized_capture_results.extend(replay_results)
                chunk_expected_staging_keys.update(
                    self._successful_staging_keys(
                        [r for r in replay_results if not isinstance(r, _DeferredExtraction)]
                    )
                )
                if persist_chunk_results is not None:
                    source_results.extend(
                        self._source_results_for_persistence(
                            [r for r in replay_results if not isinstance(r, _DeferredExtraction)],
                            plan_live_snapshot_at=snapshot_at,
                        )
                    )

            chunk_raw_request_capture_snapshot = self._merge_raw_request_capture_snapshots(
                self._raw_request_capture_snapshots_for_results(finalized_capture_results)
            )
            failure_raw_request_capture_snapshots = (
                self._failure_raw_request_capture_snapshots_for_results(
                    finalized_capture_results,
                    require_snapshot=self._raw_request_capture_context_factory is not None,
                )
            )
            if chunk_raw_request_capture_snapshot is not None:
                if pattern_result.raw_request_capture_snapshot is None:
                    pattern_result.raw_request_capture_snapshot = chunk_raw_request_capture_snapshot
                else:
                    pattern_result.raw_request_capture_snapshot = (
                        self._merge_raw_request_capture_snapshots(
                            (
                                pattern_result.raw_request_capture_snapshot,
                                chunk_raw_request_capture_snapshot,
                            )
                        )
                    )
                self._raw_request_capture_snapshots.append(chunk_raw_request_capture_snapshot)

            chunk_output = self._concat_accum(chunk_accum)
            persistence_result: ChunkPersistenceAdmissionsV1 | None = None
            persistence_invoked = False
            if prepared_persistence is not None and (
                chunk_output or chunk_expected_staging_keys or failure_raw_request_capture_snapshots
            ):
                persistence_result = prepared_persistence(
                    chunk_output,
                    pattern=pattern,
                    chunk_index=chunk_index,
                    chunk_params=chunk,
                    entries=entries,
                    expected_staging_keys=sorted(chunk_expected_staging_keys),
                    source_results=source_results,
                    failure_raw_request_capture_snapshots=(failure_raw_request_capture_snapshots),
                )
                persistence_invoked = True
            admitted_successes = self._bind_chunk_w2_admissions(
                pending_successes,
                persistence_result,
                callback_invoked=persistence_invoked,
                require_w2_operation=(self._raw_request_capture_context_factory is not None),
            )
            self._commit_chunk_journal_successes(
                admitted_successes,
                pattern_result,
                discard_parser_inputs=persistence_invoked,
            )
            if retain_frames:
                for key, df in chunk_output.items():
                    if not df.is_empty():
                        accum.setdefault(key, []).append(df)

            # HR-A-007: free multi-endpoint cache between chunks to
            # prevent unbounded memory growth on large historical runs.
            self._multi_cache.clear()
            _record_chunk_completion_heartbeat()

            chunk_successes = pattern_result.success_count - success_count_before
            chunk_failures = (
                pattern_result.failure_count
                + pattern_result.deferred_failure_count
                - failure_count_before
            )
            chunk_skips = (
                pattern_result.journal_skip_count
                + pattern_result.retry_skip_count
                - skip_count_before
            )
            attempted_calls = max(0, chunk_batch.eligible_calls - chunk_skips)
            if self._should_abort_zero_progress_chunk(
                entries,
                attempted_calls=attempted_calls,
                success_count=chunk_successes,
                failure_count=chunk_failures,
            ):
                marker = (
                    f"zero_progress_chunk_abort:{pattern}:chunk={chunk_index}:"
                    f"attempted={attempted_calls}:skipped={chunk_skips}"
                )
                pattern_result.errors.append(marker)
                logger.error(
                    "aborting endpoint pattern after a fully failed zero-progress chunk: {}",
                    marker,
                )
                break

        pattern_result.frames = self._concat_accum(accum) if retain_frames else {}
        pattern_result.unattempted_eligible_calls = max(
            0,
            pattern_result.eligible_calls - pattern_result.scheduled_calls,
        )
        pattern_result.response_contract_circuit = response_contract_circuit.summary()
        for endpoint, summary in pattern_result.response_contract_circuit.items():
            unattempted_calls = max(
                0,
                eligible_calls_by_endpoint.get(endpoint, 0) - scheduled_calls_by_endpoint[endpoint],
            )
            summary["unattempted_calls"] = unattempted_calls
            summary["preserved_outstanding_calls"] = (
                int(summary["suppressions"]) + unattempted_calls
            )
        if any(
            int(summary["suppressions"]) > 0
            for summary in pattern_result.response_contract_circuit.values()
        ):
            logger.warning(
                "response-contract circuit summary [{}]: {}",
                pattern,
                json.dumps(
                    pattern_result.response_contract_circuit,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        return pattern_result

    # ── run_pattern decomposition ──────────────────────────────

    @staticmethod
    def _classify_entries(
        entries: list[StagingEntry],
    ) -> tuple[list[StagingEntry], list[StagingEntry], dict[str, list[StagingEntry]]]:
        """Split entries into multi vs single and group multi by endpoint."""
        multi_groups = get_multi_entries()
        multi_entries: list[StagingEntry] = []
        single_entries: list[StagingEntry] = []
        for entry in entries:
            if entry.use_multi and entry.endpoint_name in multi_groups:
                multi_entries.append(entry)
            else:
                single_entries.append(entry)

        multi_by_ep: dict[str, list[StagingEntry]] = {}
        for entry in multi_entries:
            multi_by_ep.setdefault(entry.endpoint_name, []).append(entry)

        return multi_entries, single_entries, multi_by_ep

    def _prefetch_done(
        self,
        single_entries: list[StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        chunk: list[dict],
        *,
        today: date,
    ) -> set[tuple[str, str]]:
        """Batch-prefetch already-done items for this chunk (HR-B-008)."""
        batch_items: list[tuple[str, str]] = []
        for entry in single_entries:
            for params in chunk:
                if self._entry_is_supported(entry, params, today=today):
                    batch_items.append((entry.endpoint_name, json.dumps(params, sort_keys=True)))
        for ep_name, ep_entries in multi_by_ep.items():
            for params in chunk:
                if any(
                    self._entry_is_supported(entry, params, today=today) for entry in ep_entries
                ):
                    batch_items.append((ep_name, json.dumps(params, sort_keys=True)))
        if not batch_items:
            return set()
        if self._raw_request_capture_context_factory is not None:
            return self._journal.was_extracted_batch(
                batch_items,
                require_receipt=True,
                require_w2_operation=True,
            )
        if self._capture_contract_factory is None:
            return self._journal.was_extracted_batch(batch_items)
        return self._journal.was_extracted_batch(batch_items, require_receipt=True)

    def _assert_no_derived_fanout(
        self,
        param_sets: list[dict],
        entries: list[StagingEntry],
        required_route_ids: tuple[str, ...] | None,
    ) -> None:
        """Reject extra or unsealed successor provider work before execution."""

        if self._call_admission is not None and required_route_ids is None:
            raise ParserInputCaptureIntegrityError(
                "later-derived or out-of-manifest fan-out: "
                "successor runner requires a sealed dispatch"
            )
        if required_route_ids is None:
            return
        actual_route_ids = tuple(self._result_route_id(entry) for entry in entries)
        if (
            type(required_route_ids) is not tuple
            or not required_route_ids
            or len(required_route_ids) != len(set(required_route_ids))
            or actual_route_ids != required_route_ids
        ):
            raise ParserInputCaptureIntegrityError(
                "sealed-plan routes do not map positionally to runner entries"
            )
        if len(param_sets) != 1:
            raise ParserInputCaptureIntegrityError(
                "later-derived or out-of-manifest fan-out: "
                "one sealed dispatch must contain exactly one provider parameter set"
            )

    def _admit_call(
        self,
        endpoint_name: str,
        params: dict[str, object],
        result_route_ids: tuple[str, ...],
        *,
        admission_prechecked: bool,
    ) -> bool:
        """Admit one logical call before any runner-owned side effect."""

        if self._call_admission is None:
            return False
        if not admission_prechecked:
            self._call_admission(endpoint_name, dict(params), result_route_ids)
        return True

    def _admit_chunk_calls(
        self,
        single_entries: list[StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        chunk: list[dict],
        *,
        today: date,
    ) -> bool:
        """Pre-admit each support-eligible call before journal prefetch."""

        if self._call_admission is None:
            return False
        for entry in single_entries:
            for params in chunk:
                if self._entry_is_supported(entry, params, today=today):
                    self._admit_call(
                        entry.endpoint_name,
                        dict(params),
                        (self._result_route_id(entry),),
                        admission_prechecked=False,
                    )
        for endpoint_name, endpoint_entries in multi_by_ep.items():
            for params in chunk:
                eligible_entries = tuple(
                    entry
                    for entry in endpoint_entries
                    if self._entry_is_supported(entry, params, today=today)
                )
                if eligible_entries:
                    self._admit_call(
                        endpoint_name,
                        dict(params),
                        tuple(sorted(self._result_route_id(entry) for entry in eligible_entries)),
                        admission_prechecked=False,
                    )
        return True

    @classmethod
    def _support_eligible_call_counts(
        cls,
        single_entries: list[StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        param_sets: list[dict],
        *,
        today: date | None = None,
    ) -> tuple[int, int, dict[str, int]]:
        """Count the full support-eligible denominator without scheduling calls."""
        effective_today = today or date.today()
        eligible_calls_by_endpoint: collections.Counter[str] = collections.Counter()
        support_skip_count = 0
        for entry in single_entries:
            for params in param_sets:
                if cls._entry_is_supported(entry, params, today=effective_today):
                    eligible_calls_by_endpoint[entry.endpoint_name] += 1
                else:
                    support_skip_count += 1
        for endpoint_name, endpoint_entries in multi_by_ep.items():
            for params in param_sets:
                if any(
                    cls._entry_is_supported(entry, params, today=effective_today)
                    for entry in endpoint_entries
                ):
                    eligible_calls_by_endpoint[endpoint_name] += 1
                else:
                    support_skip_count += 1
        return (
            sum(eligible_calls_by_endpoint.values()),
            support_skip_count,
            dict(eligible_calls_by_endpoint),
        )

    @staticmethod
    def _season_year(params: dict) -> int | None:
        """Extract the integer season year from param sets.

        Handles formats:
        - ``"2024-25"`` → 2024
        - ``"2024"`` → 2024
        - ``"0024800127"`` → 1948
        - ``"0020000730"`` → 2000

        Returns ``None`` when no season hint can be derived.
        """
        season = params.get("season")
        if season is not None:
            try:
                return int(str(season)[:4])
            except (ValueError, TypeError):
                return None
        game_id = params.get("game_id")
        game_id_str = str(game_id) if game_id is not None else ""
        if len(game_id_str) < 5 or not game_id_str[3:5].isdigit():
            return None
        season_suffix = int(game_id_str[3:5])
        if season_suffix <= 30:
            return 2000 + season_suffix
        return 1900 + season_suffix

    @classmethod
    def _entry_is_supported(
        cls,
        entry: StagingEntry,
        params: dict,
        *,
        today: date,
    ) -> bool:
        if entry.deprecated_after is not None and today > date.fromisoformat(
            entry.deprecated_after
        ):
            return False
        season_year = cls._season_year(params)
        return entry.min_season is None or season_year is None or season_year >= entry.min_season

    def _build_chunk_tasks(
        self,
        single_entries: list[StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        chunk: list[dict],
        already_done: set[tuple[str, str]],
        on_progress: _ProgressReporter | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        defer_journal_success: bool = False,
        response_contract_circuit: _ResponseContractCircuit | None = None,
        *,
        today: date | None = None,
        admission_prechecked: bool = False,
        snapshot_at: datetime | None = None,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
    ) -> _ChunkTaskBatch:
        """Create ordered lazy task factories for all eligible chunk calls."""
        tasks: list[_TaskFactory] = []
        support_skip_count = 0
        eligible_calls = 0
        eligible_calls_by_endpoint: collections.Counter[str] = collections.Counter()
        effective_today = today or date.today()

        for entry in single_entries:
            for params in chunk:
                if not self._entry_is_supported(entry, params, today=effective_today):
                    self.skipped += 1
                    support_skip_count += 1
                    if on_progress is not None:
                        on_progress.advance_pattern(success=True)
                    continue
                self.planned_calls += 1
                eligible_calls += 1
                eligible_calls_by_endpoint[entry.endpoint_name] += 1
                tasks.append(
                    partial(
                        self._extract_single_result,
                        entry,
                        params,
                        already_done=already_done,
                        skip_items=skip_items,
                        on_progress=on_progress,
                        allow_late_recovery=True,
                        defer_journal_success=defer_journal_success,
                        response_contract_circuit=response_contract_circuit,
                        admission_prechecked=admission_prechecked,
                        snapshot_at=(snapshot_at if entry.param_pattern == "live" else None),
                        request_closure_authority=request_closure_authority,
                    )
                )

        for ep_name, ep_entries in multi_by_ep.items():
            for params in chunk:
                # For multi-endpoint groups, keep only entries still eligible
                # under documented upstream support/deprecation windows.
                eligible = [
                    e
                    for e in ep_entries
                    if self._entry_is_supported(e, params, today=effective_today)
                ]
                if not eligible:
                    self.skipped += len(ep_entries)
                    support_skip_count += 1
                    if on_progress is not None:
                        for _ in ep_entries:
                            on_progress.advance_pattern(success=True)
                    continue
                self.planned_calls += 1
                eligible_calls += 1
                eligible_calls_by_endpoint[ep_name] += 1
                tasks.append(
                    partial(
                        self._extract_multi_result,
                        ep_name,
                        eligible,
                        params,
                        already_done=already_done,
                        skip_items=skip_items,
                        on_progress=on_progress,
                        allow_late_recovery=True,
                        defer_journal_success=defer_journal_success,
                        response_contract_circuit=response_contract_circuit,
                        admission_prechecked=admission_prechecked,
                        snapshot_at=(
                            snapshot_at
                            if all(entry.param_pattern == "live" for entry in eligible)
                            else None
                        ),
                        request_closure_authority=request_closure_authority,
                    )
                )

        return _ChunkTaskBatch(
            tasks=tasks,
            eligible_calls=eligible_calls,
            eligible_calls_by_endpoint=dict(eligible_calls_by_endpoint),
            support_skip_count=support_skip_count,
        )

    async def _run_bounded_tasks(
        self,
        task_factories: list[_TaskFactory],
    ) -> _BoundedTaskExecution:
        """Execute lazy call factories with thread-pool-sized backpressure.

        Provider I/O is synchronous and cannot exceed the configured thread
        pool.  Keeping more live asyncio tasks than workers therefore adds
        task/coroutine memory without increasing provider concurrency.  The
        rolling window preserves factory order in the returned result list and
        cancels every live child if its parent is cancelled.
        """

        if not task_factories:
            return _BoundedTaskExecution(results=[], peak_in_flight=0)

        result_count = len(task_factories)
        results: list[_TaskValue | BaseException] = [None] * result_count
        in_flight: dict[asyncio.Task[_TaskValue], int] = {}
        next_index = 0
        peak_in_flight = 0

        def start_next() -> None:
            nonlocal next_index, peak_in_flight
            task = asyncio.create_task(task_factories[next_index]())
            in_flight[task] = next_index
            next_index += 1
            peak_in_flight = max(peak_in_flight, len(in_flight))

        try:
            for _ in range(min(self._task_window_size, result_count)):
                start_next()
            while in_flight:
                done, _pending = await asyncio.wait(
                    in_flight,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in sorted(done, key=in_flight.__getitem__):
                    result_index = in_flight.pop(task)
                    try:
                        results[result_index] = task.result()
                    except BaseException as exc:
                        # Match gather(return_exceptions=True): call-local
                        # failures remain ordered values for accounting.
                        results[result_index] = exc
                while next_index < result_count and len(in_flight) < self._task_window_size:
                    start_next()
        except BaseException:
            for task in in_flight:
                task.cancel()
            await asyncio.gather(*in_flight, return_exceptions=True)
            raise

        return _BoundedTaskExecution(
            results=results,
            peak_in_flight=peak_in_flight,
        )

    async def _replay_deferred_chunk(
        self,
        deferred: list[_DeferredExtraction],
        *,
        single_by_key: dict[tuple[str, str], StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        on_progress: _ProgressReporter | None,
        defer_journal_success: bool = False,
        response_contract_circuit: _ResponseContractCircuit | None = None,
        snapshot_at: datetime | None = None,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
    ) -> list[
        dict[str, pl.DataFrame]
        | _ExtractionTaskResult
        | _SkippedTaskResult
        | _FailedExtraction
        | BaseException
        | _DeferredExtraction
        | None
    ]:
        deduped: dict[tuple[str, str, str | None], _DeferredExtraction] = {}
        for item in deferred:
            params_json = json.dumps(item.params, sort_keys=True)
            key = (item.endpoint_name, params_json, item.staging_key)
            existing = deduped.get(key)
            if existing is None or item.wait_seconds > existing.wait_seconds:
                deduped[key] = item

        replay_items = list(deduped.values())
        wait_seconds = max(item.wait_seconds for item in replay_items)
        logger.warning(
            "replaying {} deferred date extractions after {:.1f}s cooldown",
            len(replay_items),
            wait_seconds,
        )
        await asyncio.sleep(wait_seconds)

        tasks: list[_TaskFactory] = []
        for item in replay_items:
            if item.staging_key is None:
                entries = multi_by_ep.get(item.endpoint_name)
                if not entries:
                    logger.error(
                        "late recovery missing multi entries for endpoint: {}",
                        item.endpoint_name,
                    )
                    continue
                if item.eligible_staging_keys:
                    eligible_keys = set(item.eligible_staging_keys)
                    entries = [entry for entry in entries if entry.staging_key in eligible_keys]
                tasks.append(
                    partial(
                        self._extract_multi_result,
                        item.endpoint_name,
                        entries,
                        item.params,
                        on_progress=on_progress,
                        allow_late_recovery=False,
                        late_recovery_replay=True,
                        defer_journal_success=defer_journal_success,
                        response_contract_circuit=response_contract_circuit,
                        admission_prechecked=self._call_admission is not None,
                        snapshot_at=(
                            snapshot_at
                            if all(entry.param_pattern == "live" for entry in entries)
                            else None
                        ),
                        request_closure_authority=request_closure_authority,
                        prior_raw_request_capture_snapshot=(item.raw_request_capture_snapshot),
                        retry_ordinal_offset=item.retry_ordinal_offset,
                    )
                )
                continue

            entry = single_by_key.get((item.endpoint_name, item.staging_key))
            if entry is None:
                logger.error(
                    "late recovery missing single entry for endpoint {} staging {}",
                    item.endpoint_name,
                    item.staging_key,
                )
                continue
            tasks.append(
                partial(
                    self._extract_single_result,
                    entry,
                    item.params,
                    on_progress=on_progress,
                    allow_late_recovery=False,
                    late_recovery_replay=True,
                    defer_journal_success=defer_journal_success,
                    response_contract_circuit=response_contract_circuit,
                    admission_prechecked=self._call_admission is not None,
                    snapshot_at=(snapshot_at if entry.param_pattern == "live" else None),
                    request_closure_authority=request_closure_authority,
                    prior_raw_request_capture_snapshot=(item.raw_request_capture_snapshot),
                    retry_ordinal_offset=item.retry_ordinal_offset,
                )
            )

        return (await self._run_bounded_tasks(tasks)).results

    @staticmethod
    def _bind_chunk_w2_admissions(
        pending_successes: list[_PendingJournalSuccess],
        callback_result: ChunkPersistenceAdmissionsV1 | None,
        *,
        callback_invoked: bool,
        require_w2_operation: bool,
    ) -> tuple[_AdmittedJournalSuccess, ...]:
        """Replay and positionally bind a chunk's W2 admissions before journaling."""

        from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1

        if type(pending_successes) is not list or any(
            type(item) is not _PendingJournalSuccess for item in pending_successes
        ):
            raise ParserInputCaptureIntegrityError(
                "chunk journal completions have a foreign container or item type"
            )
        required = tuple(item for item in pending_successes if item.w2_required)
        if any(type(item.receipt_binding) is not LogicalCallReceiptBinding for item in required):
            raise ParserInputCaptureIntegrityError(
                "W2-required journal completion lacks an exact logical-call receipt"
            )
        required_roots = tuple(
            cast("LogicalCallReceiptBinding", item.receipt_binding).logical_call_receipt_sha256
            for item in required
        )
        if len(required_roots) != len(set(required_roots)):
            raise ParserInputCaptureIntegrityError(
                "W2-required journal completions repeat one logical-call receipt"
            )

        if callback_result is None:
            if required:
                raise ParserInputCaptureIntegrityError(
                    "W2-required persistence returned no source-call admissions"
                )
            if callback_invoked and require_w2_operation:
                raise ParserInputCaptureIntegrityError(
                    "W2 failure-only persistence must return an exact empty admission tuple"
                )
            return tuple(_AdmittedJournalSuccess(item, None) for item in pending_successes)
        if type(callback_result) is not tuple:
            raise ParserInputCaptureIntegrityError(
                "chunk persistence admissions must be one exact built-in tuple"
            )
        if len(callback_result) != len(required):
            raise ParserInputCaptureIntegrityError(
                "chunk persistence admission count differs from W2-required completions"
            )

        replayed: list[W2SourceCallAdmissionV1] = []
        seen_object_ids: set[int] = set()
        seen_admission_sha256s: set[str] = set()
        seen_logical_roots: set[str] = set()
        for admission in callback_result:
            if type(admission) is not W2SourceCallAdmissionV1:
                raise ParserInputCaptureIntegrityError(
                    "chunk persistence returned a foreign W2 admission"
                )
            if id(admission) in seen_object_ids:
                raise ParserInputCaptureIntegrityError(
                    "chunk persistence aliased one W2 admission object"
                )
            seen_object_ids.add(id(admission))
            try:
                exact = W2SourceCallAdmissionV1.from_canonical_bytes(admission.canonical_bytes())
            except Exception:
                raise ParserInputCaptureIntegrityError(
                    "chunk W2 admission failed exact canonical replay"
                ) from None
            if (
                type(exact) is not W2SourceCallAdmissionV1
                or exact is admission
                or exact != admission
            ):
                raise ParserInputCaptureIntegrityError(
                    "chunk W2 admission changed during exact canonical replay"
                )
            if (
                exact.admission_sha256 in seen_admission_sha256s
                or exact.logical_call_receipt_sha256 in seen_logical_roots
            ):
                raise ParserInputCaptureIntegrityError(
                    "chunk persistence returned duplicate W2 admission authority"
                )
            seen_admission_sha256s.add(exact.admission_sha256)
            seen_logical_roots.add(exact.logical_call_receipt_sha256)
            replayed.append(exact)
        if tuple(item.logical_call_receipt_sha256 for item in replayed) != required_roots:
            raise ParserInputCaptureIntegrityError(
                "chunk W2 admissions differ from ordered pending logical-call receipts"
            )

        admission_by_root = {item.logical_call_receipt_sha256: item for item in replayed}
        return tuple(
            _AdmittedJournalSuccess(
                pending=item,
                w2_admission=(
                    admission_by_root[
                        cast(
                            "LogicalCallReceiptBinding",
                            item.receipt_binding,
                        ).logical_call_receipt_sha256
                    ]
                    if item.w2_required
                    else None
                ),
            )
            for item in pending_successes
        )

    def _commit_chunk_journal_successes(
        self,
        admitted_successes: tuple[_AdmittedJournalSuccess, ...],
        pattern_result: PatternExtractionResult,
        *,
        discard_parser_inputs: bool,
    ) -> None:
        """Commit each admitted call before exposing observations or discarding bytes."""

        if type(admitted_successes) is not tuple or any(
            type(item) is not _AdmittedJournalSuccess for item in admitted_successes
        ):
            raise ParserInputCaptureIntegrityError(
                "admitted journal completions have a foreign container or item type"
            )
        for admitted in admitted_successes:
            success = admitted.pending
            if success.receipt_binding is None:
                self._journal.record_success(
                    success.endpoint_name,
                    success.params_json,
                    success.rows,
                )
            elif success.raw_request_capture_snapshot is None or success.w2_required:
                self._journal.record_success(
                    success.endpoint_name,
                    success.params_json,
                    success.rows,
                    receipt_binding=success.receipt_binding,
                    w2_admission=admitted.w2_admission,
                )
            else:
                self._journal.record_failure(
                    success.endpoint_name,
                    success.params_json,
                    "RawRequestDownstreamIncomplete",
                )
            if success.pending_request_observations:
                pattern_result.pending_request_observations = (
                    *pattern_result.pending_request_observations,
                    *success.pending_request_observations,
                )
                self._pending_request_observations.extend(success.pending_request_observations)
            if discard_parser_inputs and success.discard_parser_inputs is not None:
                success.discard_parser_inputs()

    @staticmethod
    def _prepare_chunk_persistence(
        callback: ChunkPersistenceCallbackV1,
    ) -> _PreparedChunkPersistence:
        """Inspect a persistence callback once for a complete pattern run."""

        signature = inspect.signature(callback)
        parameters = signature.parameters
        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
            return _PreparedChunkPersistence(callback, None)
        metadata_names = (
            "pattern",
            "chunk_index",
            "chunk_params",
            "entries",
            "expected_staging_keys",
            "source_results",
            "failure_raw_request_capture_snapshots",
        )
        accepted_metadata = tuple(
            key
            for key in metadata_names
            if key in parameters
            and parameters[key].kind
            in {
                inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
        )
        return _PreparedChunkPersistence(callback, accepted_metadata)

    @classmethod
    def _persist_chunk_results(
        cls,
        callback: ChunkPersistenceCallbackV1,
        frames: dict[str, pl.DataFrame],
        *,
        pattern: str,
        chunk_index: int,
        chunk_params: list[dict],
        entries: list[StagingEntry],
        expected_staging_keys: list[str],
        source_results: list[dict[str, object]],
        failure_raw_request_capture_snapshots: tuple[RawRequestCaptureSnapshotV2, ...] = (),
    ) -> ChunkPersistenceAdmissionsV1 | None:
        """Compatibility helper for one-off callback invocation."""

        return cls._prepare_chunk_persistence(callback)(
            frames,
            pattern=pattern,
            chunk_index=chunk_index,
            chunk_params=chunk_params,
            entries=entries,
            expected_staging_keys=expected_staging_keys,
            source_results=source_results,
            failure_raw_request_capture_snapshots=(failure_raw_request_capture_snapshots),
        )

    @staticmethod
    def _successful_staging_keys(
        results: list[
            dict[str, pl.DataFrame]
            | _ExtractionTaskResult
            | _SkippedTaskResult
            | _FailedExtraction
            | BaseException
            | None
        ],
    ) -> set[str]:
        keys: set[str] = set()
        for result in results:
            frames: dict[str, pl.DataFrame] | None = None
            if isinstance(result, _ExtractionTaskResult):
                frames = result.frames
            elif isinstance(result, dict):
                frames = result
            if frames is not None:
                keys.update(frames)
        return keys

    @staticmethod
    def _raw_request_capture_snapshots_for_results(
        results: Iterable[object],
    ) -> tuple[RawRequestCaptureSnapshotV2, ...]:
        snapshots: list[RawRequestCaptureSnapshotV2] = []
        for result in results:
            snapshot: RawRequestCaptureSnapshotV2 | None = None
            if isinstance(result, _ExtractionTaskResult):
                snapshot = result.raw_request_capture_snapshot
                if (
                    result.pending_success is not None
                    and snapshot is not result.pending_success.raw_request_capture_snapshot
                ):
                    raise ParserInputCaptureIntegrityError(
                        "extraction result changed its public raw-request snapshot"
                    )
            elif isinstance(result, (_DeferredExtraction, _FailedExtraction)):
                snapshot = result.raw_request_capture_snapshot
            if snapshot is not None:
                snapshots.append(snapshot)
        return tuple(snapshots)

    @staticmethod
    def _failure_raw_request_capture_snapshots_for_results(
        results: Iterable[object],
        *,
        require_snapshot: bool,
    ) -> tuple[RawRequestCaptureSnapshotV2, ...]:
        """Return only terminal failed-call snapshots for durable persistence."""

        snapshots: list[RawRequestCaptureSnapshotV2] = []
        for result in results:
            if not isinstance(result, (_DeferredExtraction, _FailedExtraction)):
                continue
            snapshot = result.raw_request_capture_snapshot
            if snapshot is None:
                if require_snapshot and (
                    not isinstance(result, _FailedExtraction)
                    or result.failure_class != "runner_infrastructure"
                ):
                    raise ParserInputCaptureIntegrityError(
                        "failed public raw-request call lacks an exact capture snapshot"
                    )
                # Context compilation or capture-integrity failures can occur
                # before a provider attempt creates any valid public evidence.
                # The call remains a hard runner-infrastructure failure, but
                # there is no snapshot that can truthfully be materialized.
                continue
            if snapshot.pending_successes:
                raise ParserInputCaptureIntegrityError(
                    "failed public raw-request snapshot contains a pending success"
                )
            snapshots.append(snapshot)
        return tuple(snapshots)

    @staticmethod
    def _recorded_static_attempts_for_snapshot(
        snapshot: RawRequestCaptureSnapshotV2 | None,
        capture_contract: NbaApiCaptureContract | None,
    ) -> tuple[RecordedParserInput, ...]:
        """Reload exact selected static bytes before their private store is discarded."""

        if snapshot is None:
            return ()
        if type(snapshot) is not RawRequestCaptureSnapshotV2:
            raise ParserInputCaptureIntegrityError(
                "recorded static evidence received a foreign capture snapshot"
            )
        selected = tuple(
            item for item in snapshot.pending_successes if item.attempt.source_family == "static"
        )
        if not selected:
            return ()
        if capture_contract is None:
            raise ParserInputCaptureIntegrityError(
                "selected static capture lacks its exact private replay source"
            )
        result: list[RecordedParserInput] = []
        seen_receipts: set[str] = set()
        for pending in selected:
            receipt = pending.private_receipt_sha256
            if receipt in seen_receipts:
                raise ParserInputCaptureIntegrityError(
                    "selected static capture repeats one private receipt"
                )
            try:
                recorded = capture_contract.sink.load_recorded_attempt(receipt)
            except Exception as exc:
                raise ParserInputCaptureIntegrityError(
                    "selected static capture cannot reload its exact packet bytes"
                ) from exc
            attempt = pending.attempt
            expected_result_sets = tuple(item.result_set for item in pending.results)
            expected_private_outcome = (
                "success_nonempty"
                if any(item.row_count for item in expected_result_sets)
                else "success_empty"
            )
            if (
                type(recorded) is not RecordedParserInput
                or type(recorded.captured) is not CapturedParserInput
                or type(recorded.parser_input) is not bytes
                or recorded.receipt_sha256 != receipt
                # The public Raw Authority projection deliberately uses
                # ``static_snapshot``/``static_snapshot_success``.  The exact
                # private Bronze receipt retains the provider transport and
                # row-derived outcome instead; replay must compare each layer
                # to its own contract rather than conflating the two.
                or recorded.transport_kind != "static_provider_snapshot"
                or recorded.source_family != "static"
                or recorded.status_code is not None
                or recorded.outcome != expected_private_outcome
                or recorded.endpoint_id != attempt.endpoint_id
                or recorded.parameters_sha256 != attempt.safe_parameters_sha256
                or recorded.provider_authority_sha256 != attempt.provider_authority_sha256
                or recorded.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
                or recorded.result_sets != expected_result_sets
                or recorded.captured.representation != STATIC_INPUT_REPRESENTATION
                or recorded.captured.response_sha256
                != hashlib.sha256(recorded.parser_input).hexdigest()
                or recorded.captured.uncompressed_bytes != len(recorded.parser_input)
            ):
                raise ParserInputCaptureIntegrityError(
                    "selected static packet differs from its exact capture authority"
                )
            seen_receipts.add(receipt)
            result.append(recorded)
        return tuple(result)

    @staticmethod
    def _source_results_for_persistence(
        results: list[
            dict[str, pl.DataFrame]
            | _ExtractionTaskResult
            | _SkippedTaskResult
            | _FailedExtraction
            | BaseException
            | None
        ],
        *,
        plan_live_snapshot_at: datetime | None = None,
    ) -> list[dict[str, object]]:
        source_results: list[dict[str, object]] = []
        for result in results:
            if not isinstance(result, _ExtractionTaskResult):
                continue
            if result.pending_success is None:
                continue
            if result.source_endpoint_name is None or result.source_params_json is None:
                msg = (
                    "journal-backed extraction result missing source identity for "
                    f"{result.pending_success.endpoint_name}"
                )
                raise RuntimeError(msg)
            if (
                result.raw_request_capture_snapshot
                is not result.pending_success.raw_request_capture_snapshot
            ):
                raise ParserInputCaptureIntegrityError(
                    "source result changed its public raw-request snapshot"
                )
            snapshot = result.raw_request_capture_snapshot
            if snapshot is None:
                exact_plan_live_snapshot_at = None
            elif {item.attempt.source_family for item in snapshot.pending_successes} == {"live"}:
                if (
                    type(plan_live_snapshot_at) is not datetime
                    or plan_live_snapshot_at.tzinfo is None
                    or plan_live_snapshot_at.utcoffset() is None
                ):
                    raise ParserInputCaptureIntegrityError(
                        "live source result lacks its exact sealed-plan snapshot time"
                    )
                exact_plan_live_snapshot_at = plan_live_snapshot_at.astimezone(UTC)
            else:
                if plan_live_snapshot_at is not None:
                    raise ParserInputCaptureIntegrityError(
                        "non-live source result received a live sealed-plan snapshot time"
                    )
                exact_plan_live_snapshot_at = None
            source_result: dict[str, object] = {
                "frames": result.frames,
                "source_endpoint_name": result.source_endpoint_name,
                "source_params_json": result.source_params_json,
                "expected_staging_keys": result.expected_staging_keys,
                "receipt_binding": result.pending_success.receipt_binding,
                "pending_request_observations": (
                    result.pending_success.pending_request_observations
                ),
                "raw_request_capture_snapshot": (result.raw_request_capture_snapshot),
                "recorded_static_attempts": (result.pending_success.recorded_static_attempts),
                "plan_live_snapshot_at": exact_plan_live_snapshot_at,
                "result_route_ids_by_staging_key": (
                    result.result_route_ids_by_staging_key
                    if result.pending_success.receipt_binding is not None
                    else ()
                ),
            }
            parameter_binding = result.pending_success.logical_provider_parameter_binding
            parameter_binding_sha256 = (
                result.pending_success.expected_logical_provider_parameter_binding_sha256
            )
            if parameter_binding is not None:
                assert parameter_binding_sha256 is not None
                source_result["logical_provider_parameter_binding"] = parameter_binding
                source_result["expected_logical_provider_parameter_binding_sha256"] = (
                    parameter_binding_sha256
                )
            source_results.append(source_result)
        return source_results

    @staticmethod
    def _collect_results(
        results: list[
            dict[str, pl.DataFrame]
            | _ExtractionTaskResult
            | _SkippedTaskResult
            | _FailedExtraction
            | BaseException
            | None
        ],
        accum: dict[str, list[pl.DataFrame]],
        on_progress: _ProgressReporter | None,
        pattern_result: PatternExtractionResult | None = None,
    ) -> list[_PendingJournalSuccess]:
        """Merge task results into the accumulator."""
        if pattern_result is None:
            pattern_result = PatternExtractionResult(frames={})
        pending_successes: list[_PendingJournalSuccess] = []
        for result in results:
            if isinstance(result, BaseException):
                # Don't advance progress here — the task either already
                # advanced before raising or was never started.
                logger.error(
                    "extraction task failed: {}",
                    type(result).__name__,
                )
                pattern_result.failure_count += 1
                pattern_result.errors.append(
                    f"task_exception[{classify_exception(result)}:{root_error_type(result)}]"
                )
                continue
            if result is None:
                pattern_result.failure_count += 1
                pattern_result.errors.append("task_returned_none")
                continue
            if isinstance(result, _SkippedTaskResult):
                if result.status == "journal_skip":
                    pattern_result.journal_skip_count += 1
                else:
                    pattern_result.retry_skip_count += 1
                continue
            if isinstance(result, _FailedExtraction):
                if result.status == "deferred_failure":
                    pattern_result.deferred_failure_count += 1
                else:
                    pattern_result.failure_count += 1
                pattern_result.errors.append(
                    f"{result.endpoint_name}[{result.params_json}]: "
                    f"[{result.failure_class}:{result.error}]"
                )
                continue
            if isinstance(result, _ExtractionTaskResult):
                frames = result.frames
                if result.pending_success is not None and not result.pending_success.recorded:
                    pending_successes.append(result.pending_success)
            else:
                frames = result
            if not isinstance(frames, dict):
                # Don't advance progress — unexpected type indicates a
                # programming error, not a countable extraction attempt.
                logger.error(
                    "unexpected extraction task result type: {}",
                    type(frames).__name__,
                )
                pattern_result.failure_count += 1
                pattern_result.errors.append(f"unexpected_result_type:{type(frames).__name__}")
                continue
            # Compute rows for progress reporting
            rows = sum(df.shape[0] for key, df in frames.items() if not df.is_empty())
            pattern_result.success_count += 1
            pattern_result.row_count += rows
            if on_progress is not None:
                on_progress.advance_pattern(success=True, rows=rows)
            for key, df in frames.items():
                if not df.is_empty():
                    accum.setdefault(key, []).append(df)
        return pending_successes

    @staticmethod
    def _concat_accum(accum: dict[str, list[pl.DataFrame]]) -> dict[str, pl.DataFrame]:
        """Concatenate per-staging_key frames into final output."""
        import polars as pl

        output: dict[str, pl.DataFrame] = {}
        for key, frames in accum.items():
            if frames:
                if len(frames) > 1:
                    col_sets = [frozenset(f.columns) for f in frames]
                    if len(set(col_sets)) > 1:
                        all_cols = frozenset().union(*col_sets)
                        common = frozenset.intersection(*col_sets)
                        drift = all_cols - common
                        logger.warning(
                            "{}: schema drift detected across {} frames — divergent columns: {}",
                            key,
                            len(frames),
                            ", ".join(sorted(drift)),
                        )
                output[key] = pl.concat(frames, how="diagonal_relaxed")
                logger.info("{}: {} rows total", key, output[key].shape[0])
            else:
                logger.debug("{}: no data extracted", key)
        return output

    # ── private helpers ────────────────────────────────────────

    def _get_endpoint_rate_limiter(self, endpoint_name: str) -> AsyncLimiter | None:
        endpoint_limits = getattr(self._settings, "endpoint_rate_limits", {})
        if endpoint_name not in endpoint_limits:
            return None
        if endpoint_name not in self._endpoint_rate_limiters:
            self._endpoint_rate_limiters[endpoint_name] = AsyncLimiter(
                max_rate=endpoint_limits[endpoint_name],
                time_period=1.0,
            )
        return self._endpoint_rate_limiters[endpoint_name]

    def _endpoint_family(self, endpoint_name: str, category: str) -> str:
        family_overrides = getattr(self._settings, "endpoint_family_overrides", {})
        if endpoint_name in family_overrides:
            return str(family_overrides[endpoint_name])
        return endpoint_family(endpoint_name, category)

    def _get_family_rate_limiter(self, family: str) -> AsyncLimiter | None:
        family_limits = getattr(self._settings, "family_rate_limits", {})
        if family not in family_limits:
            return None
        if family not in self._family_rate_limiters:
            self._family_rate_limiters[family] = AsyncLimiter(
                max_rate=family_limits[family],
                time_period=1.0,
            )
        return self._family_rate_limiters[family]

    def _get_family_adaptive(self, family: str) -> _AdaptiveThrottle | None:
        family_limits = getattr(self._settings, "family_rate_limits", {})
        if family not in family_limits:
            return None
        if family not in self._family_adaptive:
            self._family_adaptive[family] = _AdaptiveThrottle(
                base_rate=float(family_limits[family]),
                min_rate=getattr(self._settings, "adaptive_rate_min", 1.0),
                recovery_threshold=getattr(self._settings, "adaptive_rate_recovery", 50),
            )
        return self._family_adaptive[family]

    def _get_semaphore(self, endpoint_name: str, category: str) -> asyncio.Semaphore:
        """Lazily create a semaphore for the given endpoint/category lane."""
        endpoint_limits = getattr(self._settings, "endpoint_semaphore_limits", {})
        family_limits = getattr(self._settings, "family_semaphore_limits", {})
        family = self._endpoint_family(endpoint_name, category)
        if endpoint_name in endpoint_limits:
            key = endpoint_name
        elif family in family_limits:
            key = f"family:{family}"
        else:
            key = category
        if key not in self._semaphores:
            if endpoint_name in endpoint_limits:
                limit = endpoint_limits[endpoint_name]
            elif family in family_limits:
                limit = family_limits[family]
            else:
                limit = self._settings.semaphore_tiers.get(
                    category,
                    self._settings.semaphore_tiers.get("default", 10),
                )
            self._semaphores[key] = asyncio.Semaphore(limit)
        return self._semaphores[key]

    def _chunk_size_for_entries(self, pattern: str, entries: list[StagingEntry]) -> int:
        base_chunk_size = (
            self._settings.pbp_chunk_size
            if pattern == "game"
            else self._settings.default_chunk_size
        )
        multipliers = getattr(self._settings, "family_chunk_multipliers", {})
        min_chunk_size = max(1, int(getattr(self._settings, "adaptive_chunk_min_size", 25)))
        max_chunk_size = max(
            min_chunk_size, int(getattr(self._settings, "adaptive_chunk_max_size", base_chunk_size))
        )
        multiplier = 1.0
        for entry in entries:
            family = self._endpoint_family(entry.endpoint_name, entry.param_pattern)
            multiplier = min(multiplier, float(multipliers.get(family, 1.0)))
        chunk_size = max(
            min_chunk_size,
            min(max_chunk_size, max(1, int(base_chunk_size * multiplier))),
        )
        endpoint_limits = getattr(self._settings, "endpoint_chunk_size_limits", {})
        configured_limits = [
            max(1, int(endpoint_limits[entry.endpoint_name]))
            for entry in entries
            if entry.endpoint_name in endpoint_limits
        ]
        if configured_limits:
            chunk_size = min(chunk_size, min(configured_limits))
        return chunk_size

    def _should_abort_zero_progress_chunk(
        self,
        entries: list[StagingEntry],
        *,
        attempted_calls: int,
        success_count: int,
        failure_count: int,
    ) -> bool:
        configured = set(getattr(self._settings, "zero_progress_abort_endpoints", set()))
        endpoints = {entry.endpoint_name for entry in entries}
        return bool(
            attempted_calls > 0
            and endpoints
            and endpoints.issubset(configured)
            and success_count == 0
            and failure_count >= attempted_calls
        )

    def _capture_contract_for_call(
        self,
        endpoint_name: str,
        params: dict[str, object] | None,
    ) -> NbaApiCaptureContract | None:
        """Create one explicit capture authority for a logical extractor call."""

        if self._capture_contract_factory is None:
            return None
        contract = self._capture_contract_factory(endpoint_name, dict(params or {}))
        if not isinstance(contract, NbaApiCaptureContract):
            raise ParserInputCaptureIntegrityError(
                "capture factory did not return an NBA API capture contract"
            )
        if contract.context.retry_ordinal != 0 or contract.context.request_ordinal != 0:
            raise ParserInputCaptureIntegrityError(
                "logical capture context must begin at retry and request ordinal zero"
            )
        if contract.provider_authority_sha256 != self._capture_provider_authority_sha256:
            raise ParserInputCaptureIntegrityError(
                "logical capture contract differs from pinned provider authority"
            )
        return contract

    def _raw_request_capture_context_for_call(
        self,
        endpoint_name: str,
        params: dict[str, object] | None,
    ) -> RawRequestCaptureContextV2 | None:
        """Create and revalidate one exact public authority for a logical call."""

        if self._raw_request_capture_context_factory is None:
            return None
        try:
            context = self._raw_request_capture_context_factory(
                endpoint_name,
                dict(params or {}),
            )
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "public raw-request context factory failed"
            ) from exc
        if type(context) is not RawRequestCaptureContextV2:
            raise ParserInputCaptureIntegrityError(
                "public raw-request context factory did not return an exact context"
            )
        if context.provider_authority_sha256 != self._capture_provider_authority_sha256:
            raise ParserInputCaptureIntegrityError(
                "public raw-request context differs from pinned provider authority"
            )
        return context

    @staticmethod
    def _validate_raw_request_capture_snapshot_shape(
        snapshot: RawRequestCaptureSnapshotV2,
    ) -> None:
        if type(snapshot) is not RawRequestCaptureSnapshotV2:
            raise ParserInputCaptureIntegrityError(
                "public raw-request snapshot is not the exact V2 DTO"
            )
        fields: tuple[tuple[object, type[object], str], ...] = (
            (snapshot.objects, ParserInputObjectV2, "parser-input object"),
            (snapshot.observations, RequestObservationV2, "request observation"),
            (snapshot.pending_successes, PendingRawRequestSuccessV2, "pending success"),
            (snapshot.issues, RawRequestCaptureIssueV2, "capture issue"),
        )
        for values, item_type, label in fields:
            if type(values) is not tuple or any(type(item) is not item_type for item in values):
                raise ParserInputCaptureIntegrityError(
                    f"public raw-request snapshot has invalid {label} rows"
                )

        object_by_sha: dict[str, ParserInputObjectV2] = {}
        for item in snapshot.objects:
            try:
                validate_parser_input_object(item)
            except (TypeError, ValueError):
                raise ParserInputCaptureIntegrityError(
                    "public raw-request snapshot contains an invalid parser-input object"
                ) from None
            if item.object_sha256 in object_by_sha:
                raise ParserInputCaptureIntegrityError(
                    "public raw-request snapshot repeats a parser-input object"
                )
            object_by_sha[item.object_sha256] = item

        observation_ids: set[str] = set()
        referenced_objects: set[str] = set()
        for observation in snapshot.observations:
            try:
                validate_request_observation(observation)
            except (TypeError, ValueError):
                raise ParserInputCaptureIntegrityError(
                    "public raw-request snapshot contains an invalid request observation"
                ) from None
            if observation.lifecycle not in {"allocated", "incomplete"}:
                raise ParserInputCaptureIntegrityError(
                    "runner capture cannot self-seal a terminal request observation"
                )
            observation_id = observation.attempt.observation_sha256
            if observation_id in observation_ids:
                raise ParserInputCaptureIntegrityError(
                    "public raw-request snapshot repeats an observation"
                )
            observation_ids.add(observation_id)
            if observation.body_object_sha256 is not None:
                referenced_objects.add(observation.body_object_sha256)

        private_receipts: set[str] = set()
        pending_attempt_ids: set[str] = set()
        for pending in snapshot.pending_successes:
            try:
                attempt = validate_request_attempt_identity(pending.attempt)
                transport = validate_raw_transport(pending.transport)
            except (TypeError, ValueError):
                raise ParserInputCaptureIntegrityError(
                    "pending raw-request success contains invalid attempt authority"
                ) from None
            if (
                type(pending.private_receipt_sha256) is not str
                or len(pending.private_receipt_sha256) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in pending.private_receipt_sha256
                )
                or pending.private_receipt_sha256 in private_receipts
                or pending.attempt.observation_sha256 in pending_attempt_ids
            ):
                raise ParserInputCaptureIntegrityError(
                    "public raw-request snapshot has duplicate or invalid pending authority"
                )
            private_receipts.add(pending.private_receipt_sha256)
            pending_attempt_ids.add(attempt.observation_sha256)
            if attempt.observation_sha256 in observation_ids:
                raise ParserInputCaptureIntegrityError(
                    "public raw-request attempt is both pending and observed"
                )
            if (
                type(pending.started_at) is not datetime
                or pending.started_at.tzinfo is None
                or pending.started_at.utcoffset() != UTC.utcoffset(pending.started_at)
                or type(pending.finished_at) is not datetime
                or pending.finished_at.tzinfo is None
                or pending.finished_at.utcoffset() != UTC.utcoffset(pending.finished_at)
                or pending.finished_at < pending.started_at
                or type(pending.elapsed_ns) is not int
                or not 0 <= pending.elapsed_ns <= 2**63 - 1
                or pending.outcome
                not in {"success_nonempty", "success_empty", "static_snapshot_success"}
                or type(pending.body_disposition) is not str
                or (
                    pending.logical_receipt_sha256 is not None
                    and (
                        type(pending.logical_receipt_sha256) is not str
                        or len(pending.logical_receipt_sha256) != 64
                        or any(
                            character not in "0123456789abcdef"
                            for character in pending.logical_receipt_sha256
                        )
                    )
                )
            ):
                raise ParserInputCaptureIntegrityError(
                    "pending raw-request success has malformed timing or selection authority"
                )
            if source_family_for_transport(transport) != attempt.source_family:
                raise ParserInputCaptureIntegrityError(
                    "pending raw-request transport differs from its attempt source"
                )
            if attempt.source_family == "static":
                if (
                    transport.transport_kind != "static_snapshot"
                    or pending.outcome != "static_snapshot_success"
                    or pending.body_disposition != "declared_bodyless"
                    or pending.body_object is not None
                ):
                    raise ParserInputCaptureIntegrityError(
                        "pending static success has malformed body or transport authority"
                    )
            else:
                if transport.transport_kind == "static_snapshot":
                    raise ParserInputCaptureIntegrityError(
                        "pending HTTP success has malformed body or transport authority"
                    )
                if (
                    transport.status_code is None
                    or transport.effective_status_code is None
                    or not 200 <= transport.status_code <= 299
                    or not 200 <= transport.effective_status_code <= 299
                    or pending.outcome not in {"success_nonempty", "success_empty"}
                    or pending.body_disposition != "public_parser_input"
                    or type(pending.body_object) is not ParserInputObjectV2
                ):
                    raise ParserInputCaptureIntegrityError(
                        "pending HTTP success has malformed body or transport authority"
                    )
            if pending.body_object is not None:
                try:
                    validate_parser_input_object(pending.body_object)
                except (TypeError, ValueError):
                    raise ParserInputCaptureIntegrityError(
                        "pending raw-request body is not exact public parser input"
                    ) from None
                referenced_objects.add(pending.body_object.object_sha256)
                if object_by_sha.get(pending.body_object.object_sha256) != pending.body_object:
                    raise ParserInputCaptureIntegrityError(
                        "pending raw-request body differs from its object inventory"
                    )
            if (
                type(pending.results) is not tuple
                or any(type(item) is not PendingResultOccurrenceV2 for item in pending.results)
                or type(pending.aggregate_route_ids) is not tuple
                or len(pending.aggregate_route_ids) != len(set(pending.aggregate_route_ids))
            ):
                raise ParserInputCaptureIntegrityError(
                    "pending raw-request result authority is malformed"
                )
            if any(
                type(route_id) is not str
                or not route_id
                or len(route_id) > 600
                or not route_id.isascii()
                or any(ord(character) < 0x20 or ord(character) == 0x7F for character in route_id)
                for route_id in pending.aggregate_route_ids
            ):
                raise ParserInputCaptureIntegrityError(
                    "pending raw-request aggregate route authority is malformed"
                )
            duplicate_name_ordinals: collections.Counter[str] = collections.Counter()
            for result in pending.results:
                if (
                    type(result.result_set) is not BronzeResultSetReceipt
                    or type(result.duplicate_name_ordinal) is not int
                    or result.duplicate_name_ordinal < 0
                    or type(result.ordered_headers) is not tuple
                    or any(type(header) is not str for header in result.ordered_headers)
                ):
                    raise ParserInputCaptureIntegrityError(
                        "pending raw-request result occurrence is malformed"
                    )
                receipt = result.result_set
                try:
                    revalidated_receipt = BronzeResultSetReceipt(
                        name=receipt.name,
                        provider_index=receipt.provider_index,
                        canonical_index=receipt.canonical_index,
                        headers_sha256=receipt.headers_sha256,
                        row_count=receipt.row_count,
                        json_path=receipt.json_path,
                        container_kind=receipt.container_kind,
                        container_count=receipt.container_count,
                        missing_count=receipt.missing_count,
                        null_count=receipt.null_count,
                        parent_observation_count=receipt.parent_observation_count,
                        parent_occurrence_states_sha256=(receipt.parent_occurrence_states_sha256),
                        observed_field_orders_sha256=receipt.observed_field_orders_sha256,
                        normalized_output_sha256=receipt.normalized_output_sha256,
                    )
                except (TypeError, ValueError):
                    raise ParserInputCaptureIntegrityError(
                        "pending raw-request result receipt is invalid"
                    ) from None
                if revalidated_receipt != receipt:
                    raise ParserInputCaptureIntegrityError(
                        "pending raw-request result receipt is not exact"
                    )
                expected_duplicate_ordinal = duplicate_name_ordinals[receipt.name]
                duplicate_name_ordinals[receipt.name] += 1
                if result.duplicate_name_ordinal != expected_duplicate_ordinal:
                    raise ParserInputCaptureIntegrityError(
                        "pending raw-request duplicate-name ordinals are not contiguous"
                    )

        if referenced_objects != set(object_by_sha):
            raise ParserInputCaptureIntegrityError(
                "public raw-request object inventory is not exactly referenced"
            )
        for issue in snapshot.issues:
            if (
                type(issue.code) is not str
                or not issue.code
                or len(issue.code) > 200
                or not issue.code.isascii()
                or any(not (character.isalnum() or character in "_.:-") for character in issue.code)
                or (
                    issue.retry_ordinal is not None
                    and (type(issue.retry_ordinal) is not int or issue.retry_ordinal < 0)
                )
                or (
                    issue.request_ordinal is not None
                    and (type(issue.request_ordinal) is not int or issue.request_ordinal < 0)
                )
                or (
                    issue.root_exception_class is not None
                    and (
                        type(issue.root_exception_class) is not str
                        or issue.root_exception_class not in SAFE_ROOT_ERROR_NAMES
                    )
                )
            ):
                raise ParserInputCaptureIntegrityError(
                    "public raw-request capture issue is malformed"
                )

    @staticmethod
    def _attempt_matches_raw_request_context(
        attempt: RequestAttemptIdentityV2,
        context: RawRequestCaptureContextV2,
        *,
        retry_ordinal: int,
    ) -> bool:
        if type(attempt) is not RequestAttemptIdentityV2:
            return False
        try:
            call = context.call_for(attempt.request_ordinal)
        except (TypeError, ValueError):
            return False
        return (
            attempt.retry_ordinal == retry_ordinal
            and attempt.provider_authority_sha256 == context.provider_authority_sha256
            and attempt.source_sha == context.source_sha
            and attempt.run_id == context.run_id
            and attempt.run_attempt == context.run_attempt
            and attempt.chain_id == context.chain_id
            and attempt.lane_id == context.lane_id
            and attempt.semantic_request_sha256 == call.semantic_request_sha256
            and attempt.logical_invocation_sha256 == call.logical_invocation_sha256
            and attempt.provider_call_role == call.provider_call_role
            and attempt.provider_call_ordinal == call.provider_call_ordinal
            and attempt.source_family == call.source_family
            and attempt.endpoint_id == call.endpoint_id
            and attempt.provider_request_sha256 == call.provider_request_sha256
            and attempt.endpoint_contract_sha256 == call.endpoint_contract_sha256
            and attempt.competition_id == call.competition_id
            and attempt.competition_identity_sha256 == call.competition_identity_sha256
            and attempt.scope_sha256 == call.scope_sha256
            and attempt.pagination_sha256 == call.pagination_sha256
            and attempt.page_ordinal == call.page_ordinal
        )

    @classmethod
    def _verified_raw_request_capture_snapshot(
        cls,
        extractor: object,
        context: RawRequestCaptureContextV2,
        *,
        retry_ordinal: int,
    ) -> RawRequestCaptureSnapshotV2:
        snapshot_getter = getattr(extractor, "raw_request_capture_snapshot", None)
        if not callable(snapshot_getter):
            raise ParserInputCaptureIntegrityError(
                "public-capture extractor cannot return its raw-request snapshot"
            )
        snapshot = snapshot_getter()
        if type(snapshot) is not RawRequestCaptureSnapshotV2:
            raise ParserInputCaptureIntegrityError(
                "public-capture extractor returned a malformed raw-request snapshot"
            )
        cls._validate_raw_request_capture_snapshot_shape(snapshot)
        attempts = (
            *(observation.attempt for observation in snapshot.observations),
            *(pending.attempt for pending in snapshot.pending_successes),
        )
        if any(
            not cls._attempt_matches_raw_request_context(
                attempt,
                context,
                retry_ordinal=retry_ordinal,
            )
            for attempt in attempts
        ):
            raise ParserInputCaptureIntegrityError(
                "public raw-request snapshot crosses logical capture contexts"
            )
        for issue in snapshot.issues:
            if issue.retry_ordinal not in {None, retry_ordinal} or (
                issue.request_ordinal is not None
                and issue.request_ordinal >= len(context.provider_calls)
            ):
                raise ParserInputCaptureIntegrityError(
                    "public raw-request capture issue crosses logical capture contexts"
                )
        return snapshot

    @staticmethod
    def _has_only_expected_lossless_pending_result_issue(
        snapshot: RawRequestCaptureSnapshotV2,
        fallbacks: tuple[NbaApiLosslessFallback, ...],
        *,
        retry_ordinal: int,
    ) -> bool:
        """Allow one receipt-bound unknown result to reach committed staging.

        The public capture sidecar records ``success_result_authority_pending``
        when a successful dynamic response has no named result occurrence.  An
        exact lossless fallback is the only case where that issue can be
        resolved after the response is committed: staging must preserve the
        body first, then request-closure finalization classifies the missing
        many-result-to-one identity.  Every other issue remains a pre-commit
        integrity failure.
        """

        if len(fallbacks) != 1 or len(snapshot.pending_successes) != 1 or len(snapshot.issues) != 1:
            return False
        fallback = fallbacks[0]
        pending = snapshot.pending_successes[0]
        issue = snapshot.issues[0]
        return (
            not pending.results
            and fallback.response_receipt_sha256 == pending.private_receipt_sha256
            and issue.code == "success_result_authority_pending"
            and issue.retry_ordinal == retry_ordinal
            and issue.request_ordinal == pending.attempt.request_ordinal
            and issue.root_exception_class is None
        )

    @classmethod
    def _merge_raw_request_capture_snapshots(
        cls,
        snapshots: tuple[RawRequestCaptureSnapshotV2, ...],
    ) -> RawRequestCaptureSnapshotV2 | None:
        if not snapshots:
            return None
        objects: dict[str, ParserInputObjectV2] = {}
        observations: dict[str, RequestObservationV2] = {}
        pending: dict[str, PendingRawRequestSuccessV2] = {}
        attempt_ids: set[str] = set()
        issues: list[RawRequestCaptureIssueV2] = []
        for snapshot in snapshots:
            if type(snapshot) is not RawRequestCaptureSnapshotV2:
                raise ParserInputCaptureIntegrityError(
                    "cannot merge a malformed public raw-request snapshot"
                )
            cls._validate_raw_request_capture_snapshot_shape(snapshot)
            for item in snapshot.objects:
                existing = objects.get(item.object_sha256)
                if existing is not None and existing != item:
                    raise ParserInputCaptureIntegrityError(
                        "public raw-request object digest collision"
                    )
                objects[item.object_sha256] = item
            for observation in snapshot.observations:
                observation_id = observation.attempt.observation_sha256
                if observation_id in attempt_ids:
                    raise ParserInputCaptureIntegrityError(
                        "public raw-request snapshots repeat an attempt"
                    )
                attempt_ids.add(observation_id)
                observations[observation_id] = observation
            for item in snapshot.pending_successes:
                observation_id = item.attempt.observation_sha256
                if observation_id in attempt_ids or item.private_receipt_sha256 in pending:
                    raise ParserInputCaptureIntegrityError(
                        "public raw-request snapshots repeat pending authority"
                    )
                attempt_ids.add(observation_id)
                pending[item.private_receipt_sha256] = item
            issues.extend(snapshot.issues)
        merged = RawRequestCaptureSnapshotV2(
            objects=tuple(sorted(objects.values(), key=lambda item: item.object_sha256)),
            observations=tuple(
                sorted(
                    observations.values(),
                    key=lambda item: item.attempt.observation_sha256,
                )
            ),
            pending_successes=tuple(
                sorted(
                    pending.values(),
                    key=lambda item: (
                        item.attempt.semantic_request_sha256,
                        item.attempt.retry_ordinal,
                        item.attempt.request_ordinal,
                        item.private_receipt_sha256,
                    ),
                )
            ),
            issues=tuple(issues),
        )
        cls._validate_raw_request_capture_snapshot_shape(merged)
        return merged

    @staticmethod
    def _result_route_id(entry: StagingEntry) -> str:
        return f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"

    @staticmethod
    def _lossless_result_route_id(
        endpoint_name: str,
        fallback: NbaApiLosslessFallback,
    ) -> str:
        return f"{endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:{fallback.result_route_index}"

    @staticmethod
    def _live_lossless_result_route_id(
        endpoint_name: str,
        landing: NbaApiLiveLosslessLanding,
    ) -> str:
        return f"{endpoint_name}:{LIVE_LOSSLESS_STAGING_KEY}:{landing.expected_result_set_count}"

    @staticmethod
    def _lossless_fallbacks_for_attempt(
        extractor: object,
    ) -> tuple[NbaApiLosslessFallback, ...]:
        snapshot_getter = getattr(extractor, "lossless_fallback_snapshot", None)
        if not callable(snapshot_getter):
            return ()
        fallbacks = snapshot_getter()
        if type(fallbacks) is not tuple or any(
            not isinstance(fallback, NbaApiLosslessFallback) for fallback in fallbacks
        ):
            raise ParserInputCaptureIntegrityError(
                "extractor returned an invalid lossless-fallback snapshot"
            )
        return fallbacks

    @staticmethod
    def _unknown_response_fallbacks_for_attempt(
        extractor: object,
        contract: NbaApiCaptureContract | None,
        *,
        retry_ordinal: int,
    ) -> tuple[NbaApiLosslessFallback, ...]:
        """Project captured Video* unknown responses under exact bronze authority."""

        snapshot_getter = getattr(extractor, "unknown_response_snapshot", None)
        if not callable(snapshot_getter):
            return ()
        observations = snapshot_getter()
        if type(observations) is not tuple or any(
            not isinstance(observation, NbaApiUnknownResponse) for observation in observations
        ):
            raise ParserInputCaptureIntegrityError(
                "extractor returned an invalid unknown-response snapshot"
            )
        if not observations or contract is None:
            # The conditional public table is receipt-authoritative. Direct
            # standalone extraction retains the typed observation in the
            # extractor but cannot materialize an unbound public route.
            return ()
        if len(observations) != 1:
            raise ParserInputCaptureIntegrityError(
                "one video request produced multiple unknown-response observations"
            )
        observation = observations[0]
        receipt = observation.response_receipt_sha256
        if receipt is None:
            raise ParserInputCaptureIntegrityError(
                "captured unknown response omitted its response receipt"
            )
        try:
            recorded = contract.sink.load_recorded_attempt(receipt)
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "unknown response receipt cannot be independently reloaded"
            ) from exc
        if (
            not isinstance(recorded, RecordedParserInput)
            or recorded.receipt_sha256 != receipt
            or recorded.transport_kind != "http_response"
            or recorded.source_family != "stats"
            or recorded.status_code != 200
            or recorded.endpoint_id != observation.endpoint_id
            or recorded.endpoint_slug != observation.endpoint_slug
            or recorded.provider_authority_sha256 != observation.provider_authority_sha256
            or recorded.endpoint_contract_sha256 != observation.endpoint_contract_sha256
            or recorded.parameters_sha256 != observation.parameters_sha256
            or recorded.captured.response_sha256 != observation.parser_input_sha256
            or recorded.result_sets != observation.result_set_receipts
            or recorded.outcome != observation.outcome
        ):
            raise ParserInputCaptureIntegrityError(
                "unknown response observation differs from its exact capture receipt"
            )
        try:
            fallback = build_unknown_stats_lossless_fallback(
                observation,
                expected_response_receipt_sha256=recorded.receipt_sha256,
                expected_parameters_sha256=recorded.parameters_sha256,
                expected_parser_input_sha256=recorded.captured.response_sha256,
            )
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "unknown response failed its conditional lossless projection"
            ) from exc
        return () if fallback is None else (fallback,)

    @staticmethod
    def _live_lossless_landings_for_attempt(
        extractor: object,
    ) -> tuple[NbaApiLiveLosslessLanding, ...]:
        snapshot_getter = getattr(extractor, "live_lossless_landing_snapshot", None)
        if not callable(snapshot_getter):
            return ()
        landings = snapshot_getter()
        if type(landings) is not tuple or any(
            not isinstance(landing, NbaApiLiveLosslessLanding) for landing in landings
        ):
            raise ParserInputCaptureIntegrityError(
                "extractor returned an invalid live-lossless landing snapshot"
            )
        return landings

    @staticmethod
    def _verify_lossless_fallback_receipts(
        fallbacks: tuple[NbaApiLosslessFallback, ...],
        snapshot: NbaApiReceiptSnapshot | None,
        *,
        retry_ordinal: int,
    ) -> None:
        if not fallbacks:
            return
        if snapshot is None:
            if any(fallback.response_receipt_sha256 is not None for fallback in fallbacks):
                raise ParserInputCaptureIntegrityError(
                    "uncaptured logical call returned a receipt-bound lossless fallback"
                )
            return

        successful_receipts = {
            entry.receipt_sha256
            for entry in snapshot.entries
            if entry.successful and entry.context.retry_ordinal == retry_ordinal
        }
        fallback_receipts = tuple(fallback.response_receipt_sha256 for fallback in fallbacks)
        if any(
            receipt is None or receipt not in successful_receipts for receipt in fallback_receipts
        ) or len(set(fallback_receipts)) != len(fallback_receipts):
            raise ParserInputCaptureIntegrityError(
                "lossless fallback is not bound to one exact successful response receipt"
            )

    @staticmethod
    def _verified_live_lossless_landings(
        landings: tuple[NbaApiLiveLosslessLanding, ...],
        snapshot: NbaApiReceiptSnapshot | None,
        *,
        retry_ordinal: int,
        expected_snapshot_at: datetime | None = None,
    ) -> tuple[NbaApiLiveLosslessLanding, ...]:
        """Return only captured landings bound to the current successful retry."""

        if not landings:
            return ()
        if expected_snapshot_at is not None and (
            expected_snapshot_at.tzinfo is None or expected_snapshot_at.utcoffset() is None
        ):
            raise ParserInputCaptureIntegrityError(
                "live-lossless expected snapshot must be timezone-aware"
            )
        normalized_snapshot_at = (
            expected_snapshot_at.astimezone(UTC) if expected_snapshot_at is not None else None
        )
        for landing in landings:
            if normalized_snapshot_at is not None and landing.snapshot_at != normalized_snapshot_at:
                raise ParserInputCaptureIntegrityError(
                    "live-lossless landing differs from the exact execution snapshot"
                )
            try:
                validate_live_lossless_frame(
                    landing.frame,
                    expected_response_receipt_sha256=landing.response_receipt_sha256,
                    expected_result_set_count=landing.expected_result_set_count,
                    expected_snapshot_at=landing.snapshot_at,
                    expected_endpoint_id=landing.endpoint_id,
                    expected_endpoint_slug=landing.endpoint_slug,
                    expected_anomaly_codes=landing.reason_codes,
                )
            except Exception as exc:
                raise ParserInputCaptureIntegrityError(
                    "live-lossless landing failed its fixed node contract"
                ) from exc
        if snapshot is None:
            if any(landing.response_receipt_sha256 is not None for landing in landings):
                raise ParserInputCaptureIntegrityError(
                    "uncaptured logical call returned a receipt-bound live-lossless landing"
                )
            # The public conditional table is receipt-authoritative. Standalone
            # live extraction retains its normal wide output but does not land
            # an unbound node tree.
            return ()
        successful_receipts = {
            entry.receipt_sha256
            for entry in snapshot.entries
            if entry.successful and entry.context.retry_ordinal == retry_ordinal
        }
        landing_receipts = tuple(landing.response_receipt_sha256 for landing in landings)
        if any(
            receipt is None or receipt not in successful_receipts for receipt in landing_receipts
        ) or len(set(landing_receipts)) != len(landing_receipts):
            raise ParserInputCaptureIntegrityError(
                "live-lossless landing is not bound to one exact successful response receipt"
            )
        return landings

    def _admit_conditional_result_routes(
        self,
        endpoint_name: str,
        params: dict[str, object],
        static_route_ids: tuple[str, ...],
        conditional_route_ids: tuple[str, ...],
    ) -> None:
        """Validate response-conditional routes without weakening pre-call admission.

        Static routes are still admitted before provider access. A successor
        authority must explicitly supply the separate conditional hook before
        an observed drift route can be finalized into the logical receipt.
        """

        if not conditional_route_ids:
            return
        canonical_conditionals = tuple(sorted(set(conditional_route_ids)))
        if len(canonical_conditionals) != len(conditional_route_ids) or set(
            canonical_conditionals
        ) & set(static_route_ids):
            raise ParserInputCaptureIntegrityError(
                "conditional landing produced duplicate or colliding result routes"
            )
        if self._call_admission is not None and self._conditional_route_admission is None:
            raise ParserInputCaptureIntegrityError(
                "successor dispatch has no conditional staging-route authority"
            )
        if self._conditional_route_admission is not None:
            self._conditional_route_admission(
                endpoint_name,
                dict(params),
                tuple(static_route_ids),
                canonical_conditionals,
            )

    @classmethod
    def _merge_lossless_fallbacks(
        cls,
        endpoint_name: str,
        fallbacks: tuple[NbaApiLosslessFallback, ...],
    ) -> tuple[pl.DataFrame, str] | None:
        if not fallbacks:
            return None
        route_ids = {
            cls._lossless_result_route_id(endpoint_name, fallback) for fallback in fallbacks
        }
        if len(route_ids) != 1:
            raise ParserInputCaptureIntegrityError(
                "one logical call produced incompatible lossless result routes"
            )
        import polars as pl

        frames = [fallback.frame for fallback in fallbacks]
        frame = frames[0] if len(frames) == 1 else pl.concat(frames, how="vertical")
        return frame, next(iter(route_ids))

    @staticmethod
    def _canonical_video_lossless_projection(
        endpoint_name: str,
        *,
        static_route_ids: tuple[str, ...],
        fallbacks: tuple[NbaApiLosslessFallback, ...],
        fallback_projection: tuple[pl.DataFrame, str] | None,
        pending_success: _PendingJournalSuccess | None,
    ) -> tuple[str, pl.DataFrame] | None:
        """Bind exact VideoEvents drift cells to its canonical endpoint staging key."""

        staging_key = _VIDEO_LOSSLESS_CANONICAL_STAGING_BY_ENDPOINT.get(endpoint_name)
        if staging_key is None or fallback_projection is None:
            return None
        static_route_id = f"{endpoint_name}:{staging_key}:0"
        fallback_frame, fallback_route_id = fallback_projection
        receipt_binding = pending_success.receipt_binding if pending_success is not None else None
        expected_route_ids = tuple(sorted((static_route_id, fallback_route_id)))
        if (
            static_route_ids != (static_route_id,)
            or not fallbacks
            or any(fallback.response_receipt_sha256 is None for fallback in fallbacks)
            or receipt_binding is None
            or receipt_binding.endpoint_name != endpoint_name
            or receipt_binding.result_route_ids != expected_route_ids
        ):
            raise ParserInputCaptureIntegrityError(
                "video lossless canonical projection lacks exact receipt and route authority"
            )
        return staging_key, fallback_frame

    @classmethod
    def _merge_live_lossless_landings(
        cls,
        endpoint_name: str,
        landings: tuple[NbaApiLiveLosslessLanding, ...],
    ) -> tuple[pl.DataFrame, str] | None:
        if not landings:
            return None
        route_ids = {
            cls._live_lossless_result_route_id(endpoint_name, landing) for landing in landings
        }
        if len(route_ids) != 1:
            raise ParserInputCaptureIntegrityError(
                "one logical call produced incompatible live-lossless routes"
            )
        import polars as pl

        frames = [landing.frame for landing in landings]
        frame = frames[0] if len(frames) == 1 else pl.concat(frames, how="vertical")
        return frame, next(iter(route_ids))

    @classmethod
    def _verify_live_lossless_request_scope(
        cls,
        *,
        endpoint_name: str,
        landings: tuple[NbaApiLiveLosslessLanding, ...],
        static_route_ids: tuple[str, ...],
        provider_authority_sha256: str,
        logical_params: dict[str, object],
    ) -> None:
        if not landings:
            return
        import polars as pl

        from nbadb.contracts.staging_route_contract import (
            admit_conditional_live_lossless_route,
        )

        route_ids = tuple(
            sorted(
                {cls._live_lossless_result_route_id(endpoint_name, landing) for landing in landings}
            )
        )
        try:
            admission = admit_conditional_live_lossless_route(
                endpoint_name=endpoint_name,
                static_route_ids=static_route_ids,
                conditional_route_ids=route_ids,
                provider_authority_sha256=provider_authority_sha256,
            )
            provider_request_scopes = {
                request_parameters_json
                for landing in landings
                for request_parameters_json in landing.frame.get_column(
                    "request_parameters_json"
                ).unique()
                if isinstance(request_parameters_json, str)
            }
            if len(provider_request_scopes) != 1 or {
                admission.logical_parameters_sha256(scope) for scope in provider_request_scopes
            } != {canonical_parameters_sha256(logical_params)}:
                raise ValueError("live-lossless request scope differs")
        except (ValueError, pl.exceptions.ColumnNotFoundError) as exc:
            raise ParserInputCaptureIntegrityError(
                "live-lossless landing differs from its logical request scope"
            ) from exc

    @staticmethod
    def _finalize_logical_call_receipt(
        contract: NbaApiCaptureContract,
        snapshot: NbaApiReceiptSnapshot,
        *,
        endpoint_name: str,
        params: dict[str, object],
        result_route_ids: tuple[str, ...],
    ) -> LogicalCallReceiptBinding:
        canonical_routes = tuple(sorted(set(result_route_ids)))
        if not canonical_routes or len(canonical_routes) != len(result_route_ids):
            raise ParserInputCaptureIntegrityError(
                "capture-enabled logical call requires unique result routes"
            )
        receipt_sha256 = contract.sink.record_logical_call(
            context=contract.context,
            logical_endpoint_id=endpoint_name,
            logical_parameters=params,
            provider_authority_sha256=contract.provider_authority_sha256,
            response_receipt_sha256s=snapshot.receipt_sha256s,
            successful_response_ordinals=snapshot.successful_response_ordinals,
            result_route_ids=canonical_routes,
        )
        try:
            return LogicalCallReceiptBinding(
                logical_call_receipt_sha256=receipt_sha256,
                endpoint_name=endpoint_name,
                logical_parameters_sha256=canonical_parameters_sha256(params),
                provider_authority_sha256=contract.provider_authority_sha256,
                result_route_ids=canonical_routes,
            )
        except (TypeError, ValueError) as exc:
            raise ParserInputCaptureIntegrityError(
                "logical-call receipt binding is invalid"
            ) from exc

    @staticmethod
    def _capture_context_matches(
        contract: NbaApiCaptureContract,
        snapshot: NbaApiReceiptSnapshot,
    ) -> bool:
        expected = contract.context
        scope_fields = (
            "attempt_id",
            "workflow_run_id",
            "workflow_run_attempt",
            "chain_id",
            "lane_id",
            "semantic_source_sha",
        )
        return all(
            all(
                getattr(entry.context, field_name) == getattr(expected, field_name)
                for field_name in scope_fields
            )
            for entry in snapshot.entries
        )

    @classmethod
    def _verified_success_capture_snapshot(
        cls,
        extractor: object,
        contract: NbaApiCaptureContract,
        *,
        retry_ordinal: int,
    ) -> NbaApiReceiptSnapshot:
        """Seal and verify the receipt evidence for one successful logical call."""

        snapshot_getter = getattr(extractor, "capture_receipt_snapshot", None)
        if not callable(snapshot_getter):
            raise ParserInputCaptureIntegrityError(
                "capture-enabled extractor cannot return its receipt snapshot"
            )
        extractor_snapshot = snapshot_getter()
        contract_snapshot = contract.receipt_snapshot()
        if (
            not isinstance(extractor_snapshot, NbaApiReceiptSnapshot)
            or extractor_snapshot is not contract_snapshot
        ):
            raise ParserInputCaptureIntegrityError(
                "extractor receipt snapshot differs from its logical capture contract"
            )
        if not cls._capture_context_matches(contract, contract_snapshot):
            raise ParserInputCaptureIntegrityError(
                "extractor receipt snapshot crosses logical capture contexts"
            )
        if not any(
            entry.successful and entry.context.retry_ordinal == retry_ordinal
            for entry in contract_snapshot.entries
        ):
            raise ParserInputCaptureIntegrityError(
                "successful extractor attempt has no matching successful response receipt"
            )
        if any(entry.context.retry_ordinal > retry_ordinal for entry in contract_snapshot.entries):
            raise ParserInputCaptureIntegrityError(
                "extractor receipt snapshot contains a future retry ordinal"
            )
        return contract_snapshot

    @staticmethod
    def _pending_request_observations_for_success(
        *,
        contract: NbaApiCaptureContract,
        snapshot: NbaApiReceiptSnapshot,
        execution_authority: RequestClosureExecutionAuthority,
        call_authority: _RequestClosureCallAuthority,
        receipt_binding: LogicalCallReceiptBinding,
        logical_params: dict[str, object],
        retry_ordinal: int,
        lossless_fallbacks: tuple[NbaApiLosslessFallback, ...],
    ) -> tuple[PendingRequestObservation, ...]:
        """Project the exact successful retry without retaining response bytes."""

        successful_entries = tuple(
            entry
            for entry in snapshot.entries
            if entry.successful and entry.context.retry_ordinal == retry_ordinal
        )
        if len(successful_entries) != 1:
            raise ParserInputCaptureIntegrityError(
                "one assured stats request requires one successful response receipt"
            )
        receipt_routes = set(receipt_binding.result_route_ids)
        authority_routes = {
            staging_route_id
            for _manifest_route_id, staging_route_id in call_authority.staging_route_aliases
        }
        if (not lossless_fallbacks and receipt_routes != authority_routes) or (
            lossless_fallbacks and not authority_routes <= receipt_routes
        ):
            raise ParserInputCaptureIntegrityError(
                "logical-call routes differ from the request-closure binding"
            )
        logical_parameters_sha256 = canonical_parameters_sha256(logical_params)
        if (
            receipt_binding.logical_parameters_sha256 != logical_parameters_sha256
            or receipt_binding.provider_authority_sha256 != contract.provider_authority_sha256
        ):
            raise ParserInputCaptureIntegrityError(
                "logical-call receipt differs from its assured request"
            )

        entry = successful_entries[0]
        try:
            recorded = contract.sink.load_recorded_attempt(entry.receipt_sha256)
        except Exception as exc:
            raise ParserInputCaptureIntegrityError(
                "successful bronze response receipt cannot be reloaded"
            ) from exc
        if not isinstance(recorded, RecordedParserInput):
            raise ParserInputCaptureIntegrityError(
                "successful bronze response receipt has an invalid type"
            )
        if (
            recorded.receipt_sha256 != entry.receipt_sha256
            or recorded.transport_kind != "http_response"
            or recorded.source_family != "stats"
            or recorded.endpoint_id != call_authority.endpoint_id
            or recorded.provider_authority_sha256 != receipt_binding.provider_authority_sha256
            or recorded.status_code != 200
            or recorded.outcome not in {"success_nonempty", "success_empty"}
        ):
            raise ParserInputCaptureIntegrityError(
                "successful bronze response differs from its exact request authority"
            )
        if recorded.result_sets:
            expected_outcome = (
                "success_nonempty"
                if any(receipt.row_count for receipt in recorded.result_sets)
                else "success_empty"
            )
        else:
            unknown_response_states = {
                state
                for fallback in lossless_fallbacks
                for state in fallback.frame.get_column("response_state").unique()
                if isinstance(state, str)
            }
            if len(lossless_fallbacks) != 1 or len(unknown_response_states) != 1:
                raise ParserInputCaptureIntegrityError(
                    "successful bronze response omitted its declared result receipts"
                )
            (unknown_response_state,) = unknown_response_states
            expected_outcome = (
                "success_empty"
                if unknown_response_state == "legacy_present_empty"
                else "success_nonempty"
            )
        if recorded.outcome != expected_outcome:
            raise ParserInputCaptureIntegrityError(
                "successful bronze response outcome contradicts its result sets"
            )

        result_contract: Literal["pinned_exact", "lossless_drift"]
        if lossless_fallbacks:
            result_contract = "lossless_drift"
        else:
            _pinned_closure_result_sets(recorded.endpoint_id, recorded.result_sets)
            result_contract = "pinned_exact"

        return (
            PendingRequestObservation(
                request_surface_sha256=(execution_authority.route_manifest.request_surface_sha256),
                route_manifest_sha256=execution_authority.route_manifest.manifest_sha256,
                scope_sha256=execution_authority.scope.scope_sha256,
                provider_request_sha256=call_authority.provider_request_sha256,
                source_family=recorded.source_family,
                endpoint_id=recorded.endpoint_id,
                route_ids=call_authority.route_ids,
                attempt_count=retry_ordinal + 1,
                retry_ordinal=retry_ordinal,
                request_ordinal=entry.context.request_ordinal,
                http_status=recorded.status_code,
                response_body_sha256=recorded.captured.response_sha256,
                response_body_bytes=recorded.captured.uncompressed_bytes,
                parser_input_sha256=recorded.captured.object_sha256,
                response_receipt_sha256=recorded.receipt_sha256,
                logical_call_receipt_sha256=(receipt_binding.logical_call_receipt_sha256),
                logical_parameters_sha256=logical_parameters_sha256,
                provider_parameters_sha256=canonical_parameters_sha256(
                    dict(call_authority.provider_semantic_parameters)
                ),
                provider_authority_sha256=recorded.provider_authority_sha256,
                endpoint_contract_sha256=recorded.endpoint_contract_sha256,
                result_contract=result_contract,
                bronze_result_sets=recorded.result_sets,
            ),
        )

    @classmethod
    def _seal_terminal_failure_capture(
        cls,
        contract: NbaApiCaptureContract,
    ) -> ParserInputCaptureIntegrityError | None:
        """Seal failed-call evidence, returning an integrity failure when incomplete."""

        try:
            snapshot = contract.receipt_snapshot()
        except ParserInputCaptureIntegrityError as exc:
            return exc
        if not cls._capture_context_matches(contract, snapshot):
            return ParserInputCaptureIntegrityError(
                "failed extractor receipt snapshot crosses logical capture contexts"
            )
        return None

    def _prepare_extractor(
        self,
        extractor: object,
        capture_contract: NbaApiCaptureContract | None = None,
        logical_params: Mapping[str, object] | None = None,
        raw_request_capture_context: RawRequestCaptureContextV2 | None = None,
    ) -> None:
        """Prepare an extractor instance before extraction."""
        attempt_starter = getattr(extractor, "begin_extraction_attempt", None)
        if callable(attempt_starter):
            attempt_starter()
        request_params_setter = getattr(extractor, "set_logical_request_params", None)
        if callable(request_params_setter):
            request_params_setter(dict(logical_params or {}))
        if raw_request_capture_context is not None:
            raw_context_setter = getattr(
                extractor,
                "set_raw_request_capture_context",
                None,
            )
            if not callable(raw_context_setter):
                raise ParserInputCaptureIntegrityError(
                    "public-capture extractor cannot accept a raw-request context"
                )
            raw_context_setter(raw_request_capture_context)
        if capture_contract is not None:
            capture_setter = getattr(extractor, "set_capture_contract", None)
            if not callable(capture_setter):
                raise ParserInputCaptureIntegrityError(
                    "capture-enabled extractor cannot accept a capture contract"
                )
            capture_setter(capture_contract)
        if not isinstance(extractor, BaseExtractor):
            return
        endpoint_timeouts = getattr(self._settings, "endpoint_request_timeouts", {})
        timeout = endpoint_timeouts.get(extractor.endpoint_name)
        if timeout is not None:
            extractor._request_timeout_override = timeout

    async def _wait_for_circuit_breaker(self, endpoint_name: str, params_json: str) -> None:
        max_wait = max(float(getattr(self._settings, "circuit_breaker_max_wait", 600.0)), 0.0)
        deadline = time.monotonic() + max_wait
        while self._circuit_breaker.is_open(endpoint_name):
            wait_seconds = max(self._circuit_breaker.retry_after(endpoint_name), 1.0)
            if max_wait > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.error(
                        "circuit breaker wait budget exhausted: {} [{}] ({:.1f}s)",
                        endpoint_name,
                        params_json,
                        max_wait,
                    )
                    raise _CircuitBreakerTimeoutError(endpoint_name)
                wait_seconds = min(wait_seconds, remaining)
            logger.debug(
                "circuit breaker OPEN, delaying: {} [{}] ({:.1f}s)",
                endpoint_name,
                params_json,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

    # Exception types that warrant a retry (transient network / rate-limit errors)
    _RETRYABLE_ERRORS: tuple[type[Exception], ...] = ()

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Return True if the exception is transient and worth retrying."""
        return is_retryable_error(exc)

    def _should_delay_replay(
        self,
        endpoint_name: str,
        params: dict[str, object] | None,
        exc: Exception | None,
        *,
        allow_late_recovery: bool,
    ) -> bool:
        if not allow_late_recovery or exc is None or not self._is_retryable(exc):
            return False
        if endpoint_name not in self._LATE_RECOVERY_ENDPOINTS:
            return False
        if params is None:
            return False
        return "game_date" in params

    def _late_recovery_wait_seconds(self, endpoint_name: str) -> float:
        backoff_wait = 0.0
        if self._settings.extract_retry_base_delay > 0:
            backoff_wait = self._settings.extract_retry_base_delay * (
                2 ** max(self._settings.extract_max_retries, 0)
            )
        return max(self._circuit_breaker.retry_after(endpoint_name), backoff_wait, 1.0)

    def _record_runtime_failure(
        self,
        endpoint_name: str,
        family: str,
        duration: float,
        *,
        isolated_scope: str,
    ) -> None:
        self._journal.record_metric(endpoint_name, duration, 0, errors=1)
        self._circuit_breaker.record_failure(endpoint_name)
        tripped = self._circuit_breaker.tripped_endpoints()
        if tripped and self._progress is not None:
            self._progress.update_circuit_breakers(tripped)
        self._latency.record(endpoint_name, duration)
        if isolated_scope == "global":
            new_rate = self._adaptive.record_failure()
            if new_rate is not None:
                self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
                logger.warning("adaptive rate: backing off to {:.1f} req/s", new_rate)
                if self._progress is not None:
                    self._progress.update_rate_info(
                        self._adaptive.current_rate,
                        self._adaptive._base_rate,
                    )
        elif isolated_scope == "family":
            adaptive = self._get_family_adaptive(family)
            if adaptive is not None:
                new_rate = adaptive.record_failure()
                if new_rate is not None:
                    self._family_rate_limiters[family] = AsyncLimiter(
                        max_rate=new_rate, time_period=1.0
                    )
                    logger.warning(
                        "family adaptive rate [{}]: backing off to {:.1f} req/s", family, new_rate
                    )

    async def _run_with_journal(
        self,
        endpoint_name: str,
        params_json: str,
        *,
        params: dict[str, object] | None,
        fn: Callable,
        result_route_ids: tuple[str, ...] = (),
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
        defer_journal_success: bool = False,
        return_failures: bool = False,
        response_contract_circuit: _ResponseContractCircuit | None = None,
        admission_prechecked: bool = False,
        snapshot_at: datetime | None = None,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
        prior_raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None,
        retry_ordinal_offset: int = 0,
    ) -> (
        pl.DataFrame
        | list[pl.DataFrame]
        | _JournaledExtraction
        | _DeferredExtraction
        | _FailedExtraction
        | None
    ):
        """Execute an extraction call with full journal tracking and retries.

        *fn* is a one-arg async-compatible callable ``fn(extractor)``
        that performs the actual extraction (params captured via
        closure). Returns ``None`` on terminal failure and a deferred
        replay sentinel when a retryable date extraction should cool
        down before one final in-run replay.
        """
        logical_params = dict(params or {})
        if type(retry_ordinal_offset) is not int or retry_ordinal_offset < 0:
            raise ParserInputCaptureIntegrityError(
                "raw-request retry ordinal offset must be a nonnegative integer"
            )
        request_closure_call_authority = (
            request_closure_authority.resolve_call_if_covered(
                endpoint_name,
                logical_params,
                result_route_ids,
            )
            if request_closure_authority is not None
            else None
        )
        self._admit_call(
            endpoint_name,
            logical_params,
            result_route_ids,
            admission_prechecked=admission_prechecked,
        )
        try:
            extractor_cls = self._registry.get(endpoint_name)
        except KeyError:
            logger.warning("no extractor for endpoint: {}", endpoint_name)
            if return_failures:
                return _FailedExtraction(endpoint_name, params_json, "MissingExtractor")
            return None

        endpoint_retry_budgets = getattr(self._settings, "endpoint_retry_budgets", {})
        max_retries = max(
            0,
            int(
                endpoint_retry_budgets.get(
                    endpoint_name,
                    self._settings.extract_max_retries,
                )
            ),
        )
        base_delay = self._settings.extract_retry_base_delay
        last_exc: Exception | None = None
        family = self._endpoint_family(endpoint_name, getattr(extractor_cls, "category", "default"))

        if self._raw_request_capture_context_factory is not None:
            self._journal.record_start(
                endpoint_name,
                params_json,
                require_receipt=True,
                require_w2_operation=True,
            )
        elif self._capture_contract_factory is None:
            self._journal.record_start(endpoint_name, params_json)
        else:
            self._journal.record_start(endpoint_name, params_json, require_receipt=True)
        t0 = time.perf_counter()
        isolated_scope = "global"
        suppressed_error: str | None = None
        logical_capture_contract: NbaApiCaptureContract | None = None
        raw_request_capture_context: RawRequestCaptureContextV2 | None = None
        logical_parameter_binding: LogicalProviderParameterBindingV1 | None = None
        expected_logical_parameter_binding_sha256: str | None = None
        capture_initialization_failed = False
        attempt_count = 0
        raw_request_capture_snapshots: list[RawRequestCaptureSnapshotV2] = []
        try:
            logical_capture_contract = self._capture_contract_for_call(endpoint_name, params)
            raw_request_capture_context = self._raw_request_capture_context_for_call(
                endpoint_name,
                params,
            )
            if prior_raw_request_capture_snapshot is not None:
                if raw_request_capture_context is None or retry_ordinal_offset == 0:
                    raise ParserInputCaptureIntegrityError(
                        "prior raw-request evidence lacks a replay context"
                    )
                self._validate_raw_request_capture_snapshot_shape(
                    prior_raw_request_capture_snapshot
                )
                prior_attempts = (
                    *(item.attempt for item in prior_raw_request_capture_snapshot.observations),
                    *(
                        item.attempt
                        for item in prior_raw_request_capture_snapshot.pending_successes
                    ),
                )
                if any(
                    attempt.retry_ordinal >= retry_ordinal_offset
                    or not self._attempt_matches_raw_request_context(
                        attempt,
                        raw_request_capture_context,
                        retry_ordinal=attempt.retry_ordinal,
                    )
                    for attempt in prior_attempts
                ):
                    raise ParserInputCaptureIntegrityError(
                        "prior raw-request evidence crosses replay contexts"
                    )
                raw_request_capture_snapshots.append(prior_raw_request_capture_snapshot)
        except Exception as exc:
            last_exc = exc
            capture_initialization_failed = True

        if not capture_initialization_failed:
            for attempt in range(max_retries + 1):
                attempt_count += 1
                retry_ordinal = retry_ordinal_offset + attempt
                extractor = extractor_cls()
                capture_receipt_snapshot: NbaApiReceiptSnapshot | None = None
                receipt_binding: LogicalCallReceiptBinding | None = None
                pending_request_observations: tuple[PendingRequestObservation, ...] = ()
                parser_input_discard: Callable[[], None] | None = None
                lossless_fallbacks: tuple[NbaApiLosslessFallback, ...] = ()
                live_lossless_landings: tuple[NbaApiLiveLosslessLanding, ...] = ()
                attempt_raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None

                def capture_attempt_snapshot(
                    current_extractor: object,
                    current_retry_ordinal: int,
                ) -> RawRequestCaptureSnapshotV2 | None:
                    nonlocal attempt_raw_request_capture_snapshot
                    if raw_request_capture_context is None:
                        return None
                    if attempt_raw_request_capture_snapshot is None:
                        attempt_raw_request_capture_snapshot = (
                            self._verified_raw_request_capture_snapshot(
                                current_extractor,
                                raw_request_capture_context,
                                retry_ordinal=current_retry_ordinal,
                            )
                        )
                        raw_request_capture_snapshots.append(attempt_raw_request_capture_snapshot)
                    return attempt_raw_request_capture_snapshot

                try:
                    attempt_capture_contract = (
                        logical_capture_contract.for_retry(retry_ordinal)
                        if logical_capture_contract is not None
                        else None
                    )
                    self._prepare_extractor(
                        extractor,
                        attempt_capture_contract,
                        logical_params,
                        raw_request_capture_context,
                    )
                    family = self._endpoint_family(endpoint_name, extractor.category)
                    sem = self._get_semaphore(endpoint_name, extractor.category)
                    endpoint_limiter = self._get_endpoint_rate_limiter(endpoint_name)
                    family_limiter = self._get_family_rate_limiter(family)
                    if endpoint_limiter is not None:
                        rate_limiter = endpoint_limiter
                        isolated_scope = "endpoint"
                    elif family_limiter is not None:
                        rate_limiter = family_limiter
                        isolated_scope = "family"
                    else:
                        rate_limiter = self._rate_limiter
                        isolated_scope = "global"

                    await self._wait_for_circuit_breaker(endpoint_name, params_json)
                    async with sem:
                        blocked_signature = (
                            response_contract_circuit.blocked_signature(endpoint_name)
                            if response_contract_circuit is not None
                            else None
                        )
                        if blocked_signature is not None:
                            assert response_contract_circuit is not None
                            response_contract_circuit.record_suppression(endpoint_name)
                            suppressed_error = f"ResponseContractCircuitOpen:{blocked_signature}"
                            capture_attempt_snapshot(extractor, retry_ordinal)
                            break
                        async with rate_limiter:
                            if response_contract_circuit is not None:
                                response_contract_circuit.record_upstream_attempt(endpoint_name)
                            result = await fn(extractor)
                        lossless_fallbacks = self._lossless_fallbacks_for_attempt(extractor)
                        unknown_response_fallbacks = self._unknown_response_fallbacks_for_attempt(
                            extractor,
                            logical_capture_contract,
                            retry_ordinal=retry_ordinal,
                        )
                        if lossless_fallbacks and unknown_response_fallbacks:
                            raise ParserInputCaptureIntegrityError(
                                "one stats response mixed declared and unknown lossless routes"
                            )
                        lossless_fallbacks = (
                            *lossless_fallbacks,
                            *unknown_response_fallbacks,
                        )
                        observed_live_landings = self._live_lossless_landings_for_attempt(extractor)
                        stats_conditional_route_ids = tuple(
                            self._lossless_result_route_id(endpoint_name, fallback)
                            for fallback in lossless_fallbacks
                        )
                        if logical_capture_contract is not None:
                            capture_receipt_snapshot = self._verified_success_capture_snapshot(
                                extractor,
                                logical_capture_contract,
                                retry_ordinal=retry_ordinal,
                            )
                        self._verify_lossless_fallback_receipts(
                            lossless_fallbacks,
                            capture_receipt_snapshot,
                            retry_ordinal=retry_ordinal,
                        )
                        live_lossless_landings = self._verified_live_lossless_landings(
                            observed_live_landings,
                            capture_receipt_snapshot,
                            retry_ordinal=retry_ordinal,
                            expected_snapshot_at=snapshot_at,
                        )
                        if live_lossless_landings:
                            if logical_capture_contract is None:
                                raise ParserInputCaptureIntegrityError(
                                    "live-lossless landing lacks capture authority"
                                )
                            self._verify_live_lossless_request_scope(
                                endpoint_name=endpoint_name,
                                landings=live_lossless_landings,
                                static_route_ids=result_route_ids,
                                provider_authority_sha256=(
                                    logical_capture_contract.provider_authority_sha256
                                ),
                                logical_params=logical_params,
                            )
                        live_conditional_route_ids = tuple(
                            sorted(
                                {
                                    self._live_lossless_result_route_id(
                                        endpoint_name,
                                        landing,
                                    )
                                    for landing in live_lossless_landings
                                }
                            )
                        )
                        if lossless_fallbacks and live_lossless_landings:
                            raise ParserInputCaptureIntegrityError(
                                "one logical call cannot mix stats and live conditional routes"
                            )
                        conditional_route_ids = (
                            *stats_conditional_route_ids,
                            *live_conditional_route_ids,
                        )
                        self._admit_conditional_result_routes(
                            endpoint_name,
                            dict(params or {}),
                            result_route_ids,
                            conditional_route_ids,
                        )
                        if logical_capture_contract is not None:
                            if (
                                capture_receipt_snapshot is None
                            ):  # pragma: no cover - narrowed above
                                raise ParserInputCaptureIntegrityError(
                                    "capture-enabled success omitted its receipt snapshot"
                                )
                            receipt_binding = self._finalize_logical_call_receipt(
                                logical_capture_contract,
                                capture_receipt_snapshot,
                                endpoint_name=endpoint_name,
                                params=dict(params or {}),
                                result_route_ids=(*result_route_ids, *conditional_route_ids),
                            )
                            if (
                                raw_request_capture_context is not None
                                and request_closure_call_authority is not None
                            ):
                                compiled_parameter_binding = compile_parameter_binding(
                                    raw_request_context=raw_request_capture_context,
                                    logical_endpoint_name=endpoint_name,
                                    logical_parameters=logical_params,
                                    result_route_ids=receipt_binding.result_route_ids,
                                    provider_semantic_parameters=(
                                        dict(
                                            request_closure_call_authority.provider_semantic_parameters
                                        ),
                                    ),
                                )
                                if (
                                    compiled_parameter_binding.logical_parameters_sha256
                                    != compiled_parameter_binding.provider_entries[
                                        0
                                    ].safe_parameters_sha256
                                ):
                                    logical_parameter_binding = (
                                        verify_logical_provider_parameter_binding(
                                            compiled_parameter_binding,
                                            expected_binding_sha256=(
                                                compiled_parameter_binding.binding_sha256
                                            ),
                                        )
                                    )
                                    expected_logical_parameter_binding_sha256 = (
                                        logical_parameter_binding.binding_sha256
                                    )
                            if (
                                request_closure_authority is not None
                                and request_closure_call_authority is not None
                            ):
                                pending_request_observations = (
                                    self._pending_request_observations_for_success(
                                        contract=logical_capture_contract,
                                        snapshot=capture_receipt_snapshot,
                                        execution_authority=request_closure_authority,
                                        call_authority=request_closure_call_authority,
                                        receipt_binding=receipt_binding,
                                        logical_params=logical_params,
                                        retry_ordinal=retry_ordinal,
                                        lossless_fallbacks=lossless_fallbacks,
                                    )
                                )
                            discard_parser_inputs = getattr(
                                logical_capture_contract.sink,
                                "discard_parser_inputs",
                                None,
                            )
                            if callable(discard_parser_inputs):
                                parser_input_discard = cast(
                                    "Callable[[], None]",
                                    partial(
                                        discard_parser_inputs,
                                        capture_receipt_snapshot.receipt_sha256s,
                                    ),
                                )
                        public_snapshot = capture_attempt_snapshot(
                            extractor,
                            retry_ordinal,
                        )
                        if public_snapshot is not None:
                            assert raw_request_capture_context is not None
                            if (
                                not public_snapshot.pending_successes
                                or (
                                    public_snapshot.issues
                                    and not self._has_only_expected_lossless_pending_result_issue(
                                        public_snapshot,
                                        lossless_fallbacks,
                                        retry_ordinal=retry_ordinal,
                                    )
                                )
                                or {
                                    item.attempt.request_ordinal
                                    for item in (
                                        *public_snapshot.observations,
                                        *public_snapshot.pending_successes,
                                    )
                                }
                                != set(range(len(raw_request_capture_context.provider_calls)))
                            ):
                                raise ParserInputCaptureIntegrityError(
                                    "successful extraction lacks complete public raw-request "
                                    "evidence"
                                )
                except Exception as exc:
                    try:
                        capture_attempt_snapshot(extractor, retry_ordinal)
                    except Exception as capture_exc:
                        last_exc = capture_exc
                        break
                    last_exc = exc
                    if attempt < max_retries and self._is_retryable(exc):
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            "extract retry {}/{}: {} [{}] -> {} (backoff {:.1f}s)",
                            attempt + 1,
                            max_retries,
                            endpoint_name,
                            params_json,
                            type(exc).__name__,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    # Non-retryable or retries exhausted
                    break
                else:
                    # Success
                    duration = time.perf_counter() - t0
                    if isinstance(result, list):
                        rows = sum(df.shape[0] for df in result if not df.is_empty())
                    else:
                        rows = result.shape[0] if not result.is_empty() else 0
                    rows += sum(fallback.frame.height for fallback in lossless_fallbacks)
                    rows += sum(landing.frame.height for landing in live_lossless_landings)
                    merged_raw_request_capture_snapshot = self._merge_raw_request_capture_snapshots(
                        tuple(raw_request_capture_snapshots)
                    )
                    recorded_static_attempts = self._recorded_static_attempts_for_snapshot(
                        merged_raw_request_capture_snapshot,
                        logical_capture_contract,
                    )
                    pending_success = _PendingJournalSuccess(
                        endpoint_name=endpoint_name,
                        params_json=params_json,
                        rows=rows,
                        capture_receipt_snapshot=capture_receipt_snapshot,
                        receipt_binding=receipt_binding,
                        pending_request_observations=pending_request_observations,
                        raw_request_capture_snapshot=merged_raw_request_capture_snapshot,
                        logical_provider_parameter_binding=logical_parameter_binding,
                        expected_logical_provider_parameter_binding_sha256=(
                            expected_logical_parameter_binding_sha256
                        ),
                        recorded_static_attempts=recorded_static_attempts,
                        discard_parser_inputs=parser_input_discard,
                        recorded=not defer_journal_success,
                    )
                    if not defer_journal_success:
                        if receipt_binding is None:
                            self._journal.record_success(endpoint_name, params_json, rows)
                        else:
                            self._journal.record_success(
                                endpoint_name,
                                params_json,
                                rows,
                                receipt_binding=receipt_binding,
                            )
                        if parser_input_discard is not None:
                            parser_input_discard()
                    self._journal.record_metric(endpoint_name, duration, rows)
                    self._circuit_breaker.record_success(endpoint_name)
                    if response_contract_circuit is not None:
                        response_contract_circuit.record_success(endpoint_name)
                    self._latency.record(endpoint_name, duration)
                    if isolated_scope == "global":
                        new_rate = self._adaptive.record_success()
                        if new_rate is not None:
                            self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
                            logger.info("adaptive rate: recovering to {:.1f} req/s", new_rate)
                            if self._progress is not None:
                                self._progress.update_rate_info(
                                    self._adaptive.current_rate,
                                    self._adaptive._base_rate,
                                )
                    elif isolated_scope == "family":
                        adaptive = self._get_family_adaptive(family)
                        if adaptive is not None:
                            new_rate = adaptive.record_success()
                            if new_rate is not None:
                                self._family_rate_limiters[family] = AsyncLimiter(
                                    max_rate=new_rate,
                                    time_period=1.0,
                                )
                                logger.info(
                                    "family adaptive rate [{}]: recovering to {:.1f} req/s",
                                    family,
                                    new_rate,
                                )
                    if retry_ordinal > 0:
                        logger.info(
                            "extract succeeded on retry {}: {} [{}]",
                            retry_ordinal,
                            endpoint_name,
                            params_json,
                        )
                    if (
                        defer_journal_success
                        or lossless_fallbacks
                        or live_lossless_landings
                        or pending_success.raw_request_capture_snapshot is not None
                    ):
                        return _JournaledExtraction(
                            data=result,
                            success=pending_success,
                            raw_request_capture_snapshot=(
                                pending_success.raw_request_capture_snapshot
                            ),
                            lossless_fallbacks=lossless_fallbacks,
                            live_lossless_landings=live_lossless_landings,
                        )
                    return result

        combined_raw_request_capture_snapshot = self._merge_raw_request_capture_snapshots(
            tuple(raw_request_capture_snapshots)
        )
        if suppressed_error is not None:
            self.failed_current_run += 1
            self._journal.record_failure(endpoint_name, params_json, suppressed_error)
            logger.debug(
                "response-contract circuit suppressed queued call: {} [{}] -> {}",
                endpoint_name,
                params_json,
                suppressed_error,
            )
            if return_failures:
                return _FailedExtraction(
                    endpoint_name,
                    params_json,
                    suppressed_error,
                    failure_class="response_contract",
                    raw_request_capture_snapshot=(combined_raw_request_capture_snapshot),
                )
            return None

        # All retries exhausted
        if logical_capture_contract is not None:
            capture_integrity_error = self._seal_terminal_failure_capture(logical_capture_contract)
            if capture_integrity_error is not None:
                last_exc = capture_integrity_error
        duration = time.perf_counter() - t0
        exc_name = root_error_type(last_exc) if last_exc else "Unknown"
        if self._should_delay_replay(
            endpoint_name,
            params,
            last_exc,
            allow_late_recovery=allow_late_recovery,
        ):
            self._record_runtime_failure(
                endpoint_name,
                family,
                duration,
                isolated_scope=isolated_scope,
            )
            wait_seconds = self._late_recovery_wait_seconds(endpoint_name)
            logger.warning(
                "deferring retryable date extraction for late replay: {} [{}] -> {} ({:.1f}s)",
                endpoint_name,
                params_json,
                exc_name,
                wait_seconds,
            )
            return _DeferredExtraction(
                endpoint_name=endpoint_name,
                params=dict(params or {}),
                wait_seconds=wait_seconds,
                raw_request_capture_snapshot=combined_raw_request_capture_snapshot,
                retry_ordinal_offset=retry_ordinal_offset + attempt_count,
            )

        failure_class = classify_exception(last_exc) if last_exc is not None else "application"
        if response_contract_circuit is not None and failure_class == "response_contract":
            response_contract_circuit.record_failure(endpoint_name, exc_name)
        self.failed_current_run += 1
        self._journal.record_failure(endpoint_name, params_json, exc_name)
        if failure_class == "runner_infrastructure":
            self._journal.record_metric(endpoint_name, duration, 0, errors=1)
        elif not late_recovery_replay:
            self._record_runtime_failure(
                endpoint_name,
                family,
                duration,
                isolated_scope=isolated_scope,
            )
        logger.error(
            "extract failed after {} attempts: {} [{}] -> {}",
            attempt_count,
            endpoint_name,
            params_json,
            exc_name,
        )
        if return_failures:
            return _FailedExtraction(
                endpoint_name,
                params_json,
                exc_name,
                status="deferred_failure" if late_recovery_replay else "failure",
                failure_class=failure_class,
                raw_request_capture_snapshot=combined_raw_request_capture_snapshot,
            )
        return None

    async def _extract_single(
        self,
        entry: StagingEntry,
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: _ProgressReporter | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
        defer_journal_success: bool = False,
        response_contract_circuit: _ResponseContractCircuit | None = None,
        admission_prechecked: bool = False,
        snapshot_at: datetime | None = None,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
        prior_raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None,
        retry_ordinal_offset: int = 0,
    ) -> dict[str, pl.DataFrame] | _ExtractionTaskResult | _DeferredExtraction | None:
        result = await self._extract_single_result(
            entry,
            params,
            already_done=already_done,
            skip_items=skip_items,
            on_progress=on_progress,
            allow_late_recovery=allow_late_recovery,
            late_recovery_replay=late_recovery_replay,
            defer_journal_success=defer_journal_success,
            response_contract_circuit=response_contract_circuit,
            admission_prechecked=admission_prechecked,
            snapshot_at=snapshot_at,
            request_closure_authority=request_closure_authority,
            prior_raw_request_capture_snapshot=prior_raw_request_capture_snapshot,
            retry_ordinal_offset=retry_ordinal_offset,
        )
        if isinstance(result, (_ExtractionTaskResult, _DeferredExtraction)):
            return result
        if isinstance(result, dict):
            return result
        return None

    async def _extract_single_result(
        self,
        entry: StagingEntry,
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: _ProgressReporter | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
        defer_journal_success: bool = False,
        response_contract_circuit: _ResponseContractCircuit | None = None,
        admission_prechecked: bool = False,
        snapshot_at: datetime | None = None,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
        prior_raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None,
        retry_ordinal_offset: int = 0,
    ) -> (
        dict[str, pl.DataFrame]
        | _ExtractionTaskResult
        | _DeferredExtraction
        | _SkippedTaskResult
        | _FailedExtraction
        | None
    ):
        """Extract a single (non-multi) entry for one param set."""
        params_json = json.dumps(params, sort_keys=True)
        call_prechecked = self._admit_call(
            entry.endpoint_name,
            dict(params),
            (self._result_route_id(entry),),
            admission_prechecked=admission_prechecked,
        )

        # Resume: skip if already extracted (use pre-fetched set when available)
        journal_done = (
            (entry.endpoint_name, params_json) in already_done
            if already_done is not None
            else (
                self._journal.was_extracted(
                    entry.endpoint_name,
                    params_json,
                    require_receipt=True,
                    require_w2_operation=True,
                )
                if self._raw_request_capture_context_factory is not None
                else (
                    self._journal.was_extracted(entry.endpoint_name, params_json)
                    if self._capture_contract_factory is None
                    else self._journal.was_extracted(
                        entry.endpoint_name,
                        params_json,
                        require_receipt=True,
                    )
                )
            )
        )
        retry_skip = (
            (entry.endpoint_name, params_json) in skip_items if skip_items is not None else False
        )
        if journal_done or retry_skip:
            self.skipped += 1
            if journal_done:
                self.skipped_due_to_journal += 1
            if on_progress is not None:
                on_progress.record_skip()
            logger.debug(
                "skip ({}): {} [{}]",
                "already done" if journal_done else "already attempted this run",
                entry.endpoint_name,
                params_json,
            )
            return _SkippedTaskResult(
                "journal_skip" if journal_done else "retry_skip",
                entry.endpoint_name,
                params_json,
            )

        pool = self._thread_pool

        async def _do(ext: object) -> pl.DataFrame:
            loop = asyncio.get_running_loop()
            transport_params = dict(params)
            if snapshot_at is not None:
                transport_params["snapshot_at"] = snapshot_at
            return await loop.run_in_executor(
                pool,
                lambda: _sync_extract(ext, **transport_params),
            )

        df = await self._run_with_journal(
            entry.endpoint_name,
            params_json,
            params=params,
            result_route_ids=(self._result_route_id(entry),),
            fn=_do,
            allow_late_recovery=allow_late_recovery,
            late_recovery_replay=late_recovery_replay,
            defer_journal_success=defer_journal_success,
            return_failures=True,
            response_contract_circuit=response_contract_circuit,
            admission_prechecked=call_prechecked,
            snapshot_at=snapshot_at,
            request_closure_authority=request_closure_authority,
            prior_raw_request_capture_snapshot=prior_raw_request_capture_snapshot,
            retry_ordinal_offset=retry_ordinal_offset,
        )
        if df is None:
            return _FailedExtraction(entry.endpoint_name, params_json, "UnknownFailure")
        if isinstance(df, _FailedExtraction):
            return df
        if isinstance(df, _DeferredExtraction):
            return _DeferredExtraction(
                endpoint_name=df.endpoint_name,
                params=df.params,
                wait_seconds=df.wait_seconds,
                staging_key=entry.staging_key,
                eligible_staging_keys=(entry.staging_key,),
                raw_request_capture_snapshot=df.raw_request_capture_snapshot,
                retry_ordinal_offset=df.retry_ordinal_offset,
            )
        pending_success: _PendingJournalSuccess | None = None
        raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None
        lossless_fallbacks: tuple[NbaApiLosslessFallback, ...] = ()
        live_lossless_landings: tuple[NbaApiLiveLosslessLanding, ...] = ()
        if isinstance(df, _JournaledExtraction):
            pending_success = df.success
            raw_request_capture_snapshot = df.raw_request_capture_snapshot
            lossless_fallbacks = df.lossless_fallbacks
            live_lossless_landings = df.live_lossless_landings
            df = df.data
        if isinstance(df, list):
            logger.error("unexpected list result for single extraction: {}", entry.endpoint_name)
            return _FailedExtraction(
                entry.endpoint_name,
                params_json,
                "UnexpectedListResult",
                status="unexpected",
                raw_request_capture_snapshot=raw_request_capture_snapshot,
            )
        frames = {entry.staging_key: df}
        fallback_projection = self._merge_lossless_fallbacks(
            entry.endpoint_name,
            lossless_fallbacks,
        )
        if fallback_projection is not None:
            fallback_frame, _fallback_route = fallback_projection
            frames[LOSSLESS_FALLBACK_STAGING_KEY] = fallback_frame
        canonical_video_projection = self._canonical_video_lossless_projection(
            entry.endpoint_name,
            static_route_ids=(self._result_route_id(entry),),
            fallbacks=lossless_fallbacks,
            fallback_projection=fallback_projection,
            pending_success=pending_success,
        )
        if canonical_video_projection is not None:
            canonical_staging_key, canonical_frame = canonical_video_projection
            frames[canonical_staging_key] = canonical_frame
        live_projection = self._merge_live_lossless_landings(
            entry.endpoint_name,
            live_lossless_landings,
        )
        if live_projection is not None:
            frames[LIVE_LOSSLESS_STAGING_KEY] = live_projection[0]
        if pending_success is not None:
            route_mapping_items = [(entry.staging_key, self._result_route_id(entry))]
            if fallback_projection is not None:
                route_mapping_items.append((LOSSLESS_FALLBACK_STAGING_KEY, fallback_projection[1]))
            if live_projection is not None:
                route_mapping_items.append((LIVE_LOSSLESS_STAGING_KEY, live_projection[1]))
            route_mapping = (
                tuple(sorted(route_mapping_items))
                if pending_success.receipt_binding is not None
                else ()
            )
            return _ExtractionTaskResult(
                frames=frames,
                pending_success=pending_success,
                raw_request_capture_snapshot=raw_request_capture_snapshot,
                source_endpoint_name=entry.endpoint_name,
                source_params_json=params_json,
                expected_staging_keys=tuple(frames),
                result_route_ids_by_staging_key=route_mapping,
            )
        return frames

    async def _extract_multi(
        self,
        endpoint_name: str,
        entries: list[StagingEntry],
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: _ProgressReporter | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
        defer_journal_success: bool = False,
        response_contract_circuit: _ResponseContractCircuit | None = None,
        admission_prechecked: bool = False,
        snapshot_at: datetime | None = None,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
        prior_raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None,
        retry_ordinal_offset: int = 0,
    ) -> dict[str, pl.DataFrame] | _ExtractionTaskResult | _DeferredExtraction | None:
        result = await self._extract_multi_result(
            endpoint_name,
            entries,
            params,
            already_done=already_done,
            skip_items=skip_items,
            on_progress=on_progress,
            allow_late_recovery=allow_late_recovery,
            late_recovery_replay=late_recovery_replay,
            defer_journal_success=defer_journal_success,
            response_contract_circuit=response_contract_circuit,
            admission_prechecked=admission_prechecked,
            snapshot_at=snapshot_at,
            request_closure_authority=request_closure_authority,
            prior_raw_request_capture_snapshot=prior_raw_request_capture_snapshot,
            retry_ordinal_offset=retry_ordinal_offset,
        )
        if isinstance(result, (_ExtractionTaskResult, _DeferredExtraction)):
            return result
        if isinstance(result, dict):
            return result
        return None

    async def _extract_multi_result(
        self,
        endpoint_name: str,
        entries: list[StagingEntry],
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: _ProgressReporter | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
        defer_journal_success: bool = False,
        response_contract_circuit: _ResponseContractCircuit | None = None,
        admission_prechecked: bool = False,
        snapshot_at: datetime | None = None,
        request_closure_authority: RequestClosureExecutionAuthority | None = None,
        prior_raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None,
        retry_ordinal_offset: int = 0,
    ) -> (
        dict[str, pl.DataFrame]
        | _ExtractionTaskResult
        | _DeferredExtraction
        | _SkippedTaskResult
        | _FailedExtraction
        | None
    ):
        """Extract a multi-result endpoint once and fan out by
        ``result_set_index``.

        Uses a cache so the same (endpoint, params) is only called
        once even if multiple staging entries reference it.
        """
        import polars as pl

        params_json = json.dumps(params, sort_keys=True)
        cache_key = (endpoint_name, params_json)
        result_route_ids = tuple(sorted(self._result_route_id(entry) for entry in entries))
        call_prechecked = self._admit_call(
            endpoint_name,
            dict(params),
            result_route_ids,
            admission_prechecked=admission_prechecked,
        )

        # Single check: all entries share the same endpoint call
        # (use pre-fetched set when available)
        journal_done = (
            (endpoint_name, params_json) in already_done
            if already_done is not None
            else (
                self._journal.was_extracted(
                    endpoint_name,
                    params_json,
                    require_receipt=True,
                    require_w2_operation=True,
                )
                if self._raw_request_capture_context_factory is not None
                else (
                    self._journal.was_extracted(endpoint_name, params_json)
                    if self._capture_contract_factory is None
                    else self._journal.was_extracted(
                        endpoint_name,
                        params_json,
                        require_receipt=True,
                    )
                )
            )
        )
        retry_skip = (endpoint_name, params_json) in skip_items if skip_items is not None else False
        if journal_done or retry_skip:
            self.skipped += 1
            if journal_done:
                self.skipped_due_to_journal += 1
            if on_progress is not None:
                on_progress.record_skip()
            logger.debug(
                "skip ({}): {} [{}]",
                "already done" if journal_done else "already attempted this run",
                endpoint_name,
                params_json,
            )
            return _SkippedTaskResult(
                "journal_skip" if journal_done else "retry_skip",
                endpoint_name,
                params_json,
            )

        # Receipt-bound calls are never served from the legacy frame-only
        # cache: each logical invocation must own its exact response receipt.
        # An uncaptured fallback also bypasses the cache so its observation is
        # not silently discarded on a later call.
        cache_allowed = self._capture_contract_factory is None
        pending_success: _PendingJournalSuccess | None = None
        raw_request_capture_snapshot: RawRequestCaptureSnapshotV2 | None = None
        lossless_fallbacks: tuple[NbaApiLosslessFallback, ...] = ()
        live_lossless_landings: tuple[NbaApiLiveLosslessLanding, ...] = ()
        if not cache_allowed or cache_key not in self._multi_cache:
            pool = self._thread_pool

            async def _do(ext: object) -> list[pl.DataFrame]:
                loop = asyncio.get_running_loop()
                transport_params = dict(params)
                if snapshot_at is not None:
                    transport_params["snapshot_at"] = snapshot_at
                return await loop.run_in_executor(
                    pool,
                    lambda: _sync_extract_all(ext, **transport_params),
                )

            all_dfs = await self._run_with_journal(
                endpoint_name,
                params_json,
                params=params,
                result_route_ids=result_route_ids,
                fn=_do,
                allow_late_recovery=allow_late_recovery,
                late_recovery_replay=late_recovery_replay,
                defer_journal_success=defer_journal_success,
                return_failures=True,
                response_contract_circuit=response_contract_circuit,
                admission_prechecked=call_prechecked,
                snapshot_at=snapshot_at,
                request_closure_authority=request_closure_authority,
                prior_raw_request_capture_snapshot=prior_raw_request_capture_snapshot,
                retry_ordinal_offset=retry_ordinal_offset,
            )
            if all_dfs is None:
                return _FailedExtraction(endpoint_name, params_json, "UnknownFailure")
            if isinstance(all_dfs, _FailedExtraction):
                return all_dfs
            if isinstance(all_dfs, _DeferredExtraction):
                return _DeferredExtraction(
                    endpoint_name=all_dfs.endpoint_name,
                    params=all_dfs.params,
                    wait_seconds=all_dfs.wait_seconds,
                    eligible_staging_keys=tuple(entry.staging_key for entry in entries),
                    raw_request_capture_snapshot=(all_dfs.raw_request_capture_snapshot),
                    retry_ordinal_offset=all_dfs.retry_ordinal_offset,
                )
            if isinstance(all_dfs, _JournaledExtraction):
                pending_success = all_dfs.success
                raw_request_capture_snapshot = all_dfs.raw_request_capture_snapshot
                lossless_fallbacks = all_dfs.lossless_fallbacks
                live_lossless_landings = all_dfs.live_lossless_landings
                all_dfs = all_dfs.data
            if not isinstance(all_dfs, list):
                logger.error("unexpected non-list result for multi extraction: {}", endpoint_name)
                return _FailedExtraction(
                    endpoint_name,
                    params_json,
                    "UnexpectedNonListResult",
                    status="unexpected",
                    raw_request_capture_snapshot=raw_request_capture_snapshot,
                )
            validated_dfs: list[pl.DataFrame] = []
            for df in all_dfs:
                if not isinstance(df, pl.DataFrame):
                    logger.error(
                        "unexpected element type for multi extraction {}: {}",
                        endpoint_name,
                        type(df).__name__,
                    )
                    return _FailedExtraction(
                        endpoint_name,
                        params_json,
                        f"UnexpectedElementType:{type(df).__name__}",
                        status="unexpected",
                        raw_request_capture_snapshot=raw_request_capture_snapshot,
                    )
                validated_dfs.append(df)
            all_dfs = validated_dfs
            if cache_allowed and not lossless_fallbacks and not live_lossless_landings:
                self._multi_cache[cache_key] = validated_dfs
        else:
            all_dfs = self._multi_cache[cache_key]

        # Fan out results by result_set_index
        output: dict[str, pl.DataFrame] = {}
        for entry in entries:
            idx = entry.result_set_index
            if idx < len(all_dfs):
                output[entry.staging_key] = all_dfs[idx]
            elif entry.allow_missing_result_set or lossless_fallbacks or live_lossless_landings:
                logger.debug(
                    "{}: result_set_index {} retained by lossless/optional route (got {} sets)",
                    entry.staging_key,
                    idx,
                    len(all_dfs),
                )
                output[entry.staging_key] = pl.DataFrame()
            else:
                error = f"MissingRequiredResultSet:{entry.staging_key}:{idx}"
                logger.warning(
                    "{}: result_set_index {} out of range (got {} sets)",
                    entry.staging_key,
                    idx,
                    len(all_dfs),
                )
                self._journal.record_failure(endpoint_name, params_json, error)
                return _FailedExtraction(
                    endpoint_name,
                    params_json,
                    error,
                    status="unexpected",
                    raw_request_capture_snapshot=raw_request_capture_snapshot,
                )

        fallback_projection = self._merge_lossless_fallbacks(
            endpoint_name,
            lossless_fallbacks,
        )
        if fallback_projection is not None:
            output[LOSSLESS_FALLBACK_STAGING_KEY] = fallback_projection[0]
        canonical_video_projection = self._canonical_video_lossless_projection(
            endpoint_name,
            static_route_ids=tuple(self._result_route_id(entry) for entry in entries),
            fallbacks=lossless_fallbacks,
            fallback_projection=fallback_projection,
            pending_success=pending_success,
        )
        if canonical_video_projection is not None:
            canonical_staging_key, canonical_frame = canonical_video_projection
            output[canonical_staging_key] = canonical_frame
        live_projection = self._merge_live_lossless_landings(
            endpoint_name,
            live_lossless_landings,
        )
        if live_projection is not None:
            output[LIVE_LOSSLESS_STAGING_KEY] = live_projection[0]

        if pending_success is not None:
            route_mapping_items = [
                (entry.staging_key, self._result_route_id(entry)) for entry in entries
            ]
            if fallback_projection is not None:
                route_mapping_items.append((LOSSLESS_FALLBACK_STAGING_KEY, fallback_projection[1]))
            if live_projection is not None:
                route_mapping_items.append((LIVE_LOSSLESS_STAGING_KEY, live_projection[1]))
            route_mapping = (
                tuple(sorted(route_mapping_items))
                if pending_success.receipt_binding is not None
                else ()
            )
            return _ExtractionTaskResult(
                frames=output,
                pending_success=pending_success,
                raw_request_capture_snapshot=raw_request_capture_snapshot,
                source_endpoint_name=endpoint_name,
                source_params_json=params_json,
                expected_staging_keys=tuple(output),
                result_route_ids_by_staging_key=route_mapping,
            )
        return output
