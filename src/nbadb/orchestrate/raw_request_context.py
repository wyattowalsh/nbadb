"""Compile exact public raw-request capture contexts for ordinary provider calls.

The capture boundary deliberately accepts fully compiled identities instead of
deriving them from transport state.  This module is the narrow join from the
existing request-closure authority and trusted Actions execution provenance to
that boundary.  Ordinary stats calls retain their terminal request binding;
the four bodyless static datasets use their distinct pinned fixed-root authority.
Live, pagination expansion, and one-logical-to-many-provider-call execution
remain fail-closed until their own exact authorities are available.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.core.nba_api_competition_identity import (
    compile_competition_identity_requirements,
)
from nbadb.extract.bronze import canonical_parameters_sha256
from nbadb.extract.raw_request_capture import (
    RawProviderCallContextV2,
    RawRequestCaptureContextV2,
)
from nbadb.orchestrate.extractor_runner import RequestClosureExecutionAuthority
from nbadb.orchestrate.request_closure_production import (
    StaticRequestClosureAuthorityV1,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

__all__ = [
    "RawRequestContextCompilationError",
    "RawRequestExecutionIdentityV1",
    "build_ordinary_raw_request_context_factory",
    "build_ordinary_stats_raw_request_context_factory",
    "compile_ordinary_stats_raw_request_context",
    "compile_static_raw_request_context",
]

_SEMANTIC_REQUEST_DOMAIN = "nbadb.raw-request.semantic-request.v1"
_LOGICAL_INVOCATION_DOMAIN = "nbadb.raw-request.logical-invocation.v1"
_PAGINATION_DOMAIN = "nbadb.raw-request.pagination.v1"
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}\Z")
_FORBIDDEN_IDENTITY_RE = re.compile(
    r"(?:authorization|cookie|credential|header|password|proxy|secret|token|vpn|"
    r"(?:^|[._:-])(?:path|host|ip)(?:$|[._:-]))",
    re.IGNORECASE,
)


class RawRequestContextCompilationError(ParserInputCaptureIntegrityError):
    """Raised when execution and request authorities cannot be joined exactly."""


def _fail(message: str) -> Never:
    raise RawRequestContextCompilationError(message)


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
        raise RawRequestContextCompilationError(
            "raw-request context identity is not canonical JSON"
        ) from exc


def _domain_sha256(domain: str, payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        _canonical_json_bytes({"domain_separator": domain, **payload})
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class RawRequestExecutionIdentityV1:
    """Trusted, public-safe Actions identity for one runner lane."""

    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str

    def __post_init__(self) -> None:
        if type(self.source_sha) is not str or _GIT_SHA_RE.fullmatch(self.source_sha) is None:
            _fail("raw-request execution source SHA is invalid")
        for field_name in ("run_id", "run_attempt"):
            value = getattr(self, field_name)
            if type(value) is not int or value <= 0 or value > 2**63 - 1:
                _fail(f"raw-request execution {field_name} is invalid")
        for field_name in ("chain_id", "lane_id"):
            value = getattr(self, field_name)
            if (
                type(value) is not str
                or _SAFE_ID_RE.fullmatch(value) is None
                or _FORBIDDEN_IDENTITY_RE.search(value) is not None
            ):
                _fail(f"raw-request execution {field_name} is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "run_attempt": self.run_attempt,
            "run_id": self.run_id,
            "source_sha": self.source_sha,
        }


def _matching_logical_call(
    authority: RequestClosureExecutionAuthority,
    endpoint_name: str,
    params: Mapping[str, object],
) -> Any:
    if type(authority) is not RequestClosureExecutionAuthority:
        _fail("raw-request context requires an exact request-closure authority")
    if type(endpoint_name) is not str or not endpoint_name:
        _fail("raw-request context endpoint name is invalid")
    if type(params) is not dict:
        _fail("raw-request context parameters must be an exact dictionary")
    try:
        logical_parameters_sha256 = canonical_parameters_sha256(params)
    except (TypeError, ValueError) as exc:
        raise RawRequestContextCompilationError(
            "raw-request context parameters are not canonical"
        ) from exc
    matches = tuple(
        item
        for item in authority.logical_calls
        if item.endpoint_name == endpoint_name
        and item.logical_parameters_sha256 == logical_parameters_sha256
    )
    if len(matches) != 1:
        _fail("raw-request context has no unique logical-call authority")
    return matches[0]


def _endpoint_contract_sha256(
    authority: RequestClosureExecutionAuthority,
    logical_call: Any,
) -> str:
    physical_by_manifest = {
        alias.manifest_route_id: alias.staging_route_id for alias in authority.staging_route_aliases
    }
    try:
        physical_route_ids = tuple(
            physical_by_manifest[route_id] for route_id in logical_call.route_ids
        )
    except KeyError as exc:
        raise RawRequestContextCompilationError(
            "raw-request context route alias authority is incomplete"
        ) from exc
    bundle = staging_route_contract_bundle()
    routes = tuple(bundle.by_route_id.get(route_id) for route_id in physical_route_ids)
    if any(route is None for route in routes):
        _fail("raw-request context currently requires fixed staging routes")
    typed_routes = tuple(route for route in routes if route is not None)
    endpoint_names = {route.endpoint_name for route in typed_routes}
    source_families = {route.source_family for route in typed_routes}
    endpoint_ids = {route.provider_endpoint_id for route in typed_routes}
    endpoint_contracts = {route.endpoint_contract_sha256 for route in typed_routes}
    provider_authorities = {route.provider_authority_sha256 for route in typed_routes}
    if (
        endpoint_names != {logical_call.endpoint_name}
        or source_families != {"stats"}
        or len(endpoint_ids) != 1
        or len(endpoint_contracts) != 1
        or provider_authorities != {bundle.provider_authority_sha256}
    ):
        _fail("raw-request context staging routes cross endpoint authority")
    return next(iter(endpoint_contracts))


def _competition_identity(
    authority: RequestClosureExecutionAuthority,
    provider_request_sha256: str,
) -> tuple[str, str, Any]:
    matches = tuple(
        item
        for item in authority.competition_authorities
        if item.request_binding.provider_request_sha256 == provider_request_sha256
    )
    if len(matches) != 1:
        _fail("raw-request context lacks one competition-qualified authority")
    competition = matches[0]
    request_binding = authority.request_binding_for(provider_request_sha256)
    if competition.request_binding != request_binding:
        _fail("raw-request competition and terminal request bindings differ")
    requirements = tuple(
        item
        for item in compile_competition_identity_requirements()
        if item.requirement_sha256 == request_binding.competition_requirement_sha256
    )
    if len(requirements) != 1:
        _fail("raw-request competition requirement is not uniquely pinned")
    requirement = requirements[0]
    if (
        requirement.competition_scope_sha256 != request_binding.competition_scope_sha256
        or requirement.role_binding.role_binding_sha256 != request_binding.role_binding_sha256
        or competition.qualified_request.source_request_sha256
        != request_binding.source_request_sha256
    ):
        _fail("raw-request competition identity differs from terminal authority")
    return (
        requirement.league_id,
        competition.qualified_request.source_request_sha256,
        request_binding,
    )


def _pagination_identity(
    authority: RequestClosureExecutionAuthority,
    logical_call: Any,
) -> tuple[str | None, int | None]:
    routes_by_id = {route.route_id: route for route in authority.route_manifest.routes}
    try:
        routes = tuple(routes_by_id[route_id] for route_id in logical_call.route_ids)
    except KeyError as exc:
        raise RawRequestContextCompilationError(
            "raw-request context manifest route authority is incomplete"
        ) from exc
    pagination = {(route.pagination_series_id, route.pagination_ordinal) for route in routes}
    if pagination == {(None, None)}:
        return None, None
    if len(pagination) != 1:
        _fail("raw-request logical call spans pagination identities")
    series_id, page_ordinal = next(iter(pagination))
    if series_id is None or page_ordinal is None:
        _fail("raw-request pagination identity is incomplete")
    return (
        _domain_sha256(
            _PAGINATION_DOMAIN,
            {
                "pagination_series_id": series_id,
                "provider_request_sha256": logical_call.provider_request_sha256,
                "route_manifest_sha256": authority.route_manifest.manifest_sha256,
            },
        ),
        page_ordinal,
    )


def compile_ordinary_stats_raw_request_context(
    authority: RequestClosureExecutionAuthority,
    execution: RawRequestExecutionIdentityV1,
    endpoint_name: str,
    params: dict[str, object],
) -> RawRequestCaptureContextV2:
    """Compile one exact single-provider-call stats capture context.

    The semantic request is stable across execution attempts for the same
    frozen request authority.  The logical invocation additionally binds the
    exact source/run/attempt/chain/lane identity, while retry ordinals remain
    owned by the runner and therefore do not alter either digest.
    """

    if type(execution) is not RawRequestExecutionIdentityV1:
        _fail("raw-request context requires an exact execution identity")
    logical_call = _matching_logical_call(authority, endpoint_name, params)
    endpoint_contract_sha256 = _endpoint_contract_sha256(authority, logical_call)
    competition_id, competition_identity_sha256, request_binding = _competition_identity(
        authority,
        logical_call.provider_request_sha256,
    )
    if (
        request_binding.source_family != "stats"
        or request_binding.provider_authority_sha256
        != staging_route_contract_bundle().provider_authority_sha256
    ):
        _fail("raw-request context currently accepts stats provider authority only")
    pagination_sha256, page_ordinal = _pagination_identity(authority, logical_call)
    semantic_request_sha256 = _domain_sha256(
        _SEMANTIC_REQUEST_DOMAIN,
        {
            "competition_identity_sha256": competition_identity_sha256,
            "endpoint_name": logical_call.endpoint_name,
            "logical_parameters_sha256": logical_call.logical_parameters_sha256,
            "provider_request_sha256": logical_call.provider_request_sha256,
            "route_ids": list(logical_call.route_ids),
            "scope_sha256": authority.scope.scope_sha256,
        },
    )
    provider_call_payload: dict[str, object] = {
        "endpoint_id": request_binding.endpoint_id,
        "pagination_sha256": pagination_sha256,
        "page_ordinal": page_ordinal,
        "provider_call_ordinal": 0,
        "provider_call_role": "primary",
        "provider_request_sha256": logical_call.provider_request_sha256,
        "request_ordinal": 0,
    }
    logical_invocation_sha256 = _domain_sha256(
        _LOGICAL_INVOCATION_DOMAIN,
        {
            "execution": execution.to_dict(),
            "provider_calls": [provider_call_payload],
            "semantic_request_sha256": semantic_request_sha256,
        },
    )
    try:
        return RawRequestCaptureContextV2(
            provider_authority_sha256=request_binding.provider_authority_sha256,
            source_sha=execution.source_sha,
            run_id=execution.run_id,
            run_attempt=execution.run_attempt,
            chain_id=execution.chain_id,
            lane_id=execution.lane_id,
            provider_calls=(
                RawProviderCallContextV2(
                    request_ordinal=0,
                    semantic_request_sha256=semantic_request_sha256,
                    logical_invocation_sha256=logical_invocation_sha256,
                    provider_call_role="primary",
                    provider_call_ordinal=0,
                    source_family="stats",
                    endpoint_id=request_binding.endpoint_id,
                    provider_request_sha256=logical_call.provider_request_sha256,
                    endpoint_contract_sha256=endpoint_contract_sha256,
                    competition_id=competition_id,
                    competition_identity_sha256=competition_identity_sha256,
                    scope_sha256=authority.scope.scope_sha256,
                    pagination_sha256=pagination_sha256,
                    page_ordinal=page_ordinal,
                ),
            ),
        )
    except (TypeError, ValueError) as exc:
        raise RawRequestContextCompilationError(
            "compiled raw-request context failed strict validation"
        ) from exc


def compile_static_raw_request_context(
    authority: StaticRequestClosureAuthorityV1,
    execution: RawRequestExecutionIdentityV1,
    endpoint_name: str,
    params: dict[str, object],
) -> RawRequestCaptureContextV2:
    """Compile one exact parameterless static snapshot capture context."""

    if type(authority) is not StaticRequestClosureAuthorityV1:
        _fail("static raw-request context requires an exact static authority")
    if type(execution) is not RawRequestExecutionIdentityV1:
        _fail("raw-request context requires an exact execution identity")
    if type(endpoint_name) is not str or endpoint_name != authority.endpoint_name:
        _fail("static raw-request endpoint differs from its closure authority")
    if type(params) is not dict or params:
        _fail("static raw-request context requires exact empty parameters")
    try:
        authority.to_dict()
    except (TypeError, ValueError, ParserInputCaptureIntegrityError) as exc:
        raise RawRequestContextCompilationError(
            "static raw-request authority failed exact revalidation"
        ) from exc
    semantic_request_sha256 = _domain_sha256(
        _SEMANTIC_REQUEST_DOMAIN,
        {
            "competition_identity_sha256": authority.competition_identity_sha256,
            "endpoint_name": authority.endpoint_name,
            "logical_parameters_sha256": authority.logical_parameters_sha256,
            "provider_request_sha256": authority.provider_request_sha256,
            "route_ids": list(authority.physical_route_ids),
            "scope_sha256": authority.scope_sha256,
            "static_authority_sha256": authority.static_authority_sha256,
        },
    )
    provider_call_payload: dict[str, object] = {
        "endpoint_id": authority.endpoint_name,
        "pagination_sha256": None,
        "page_ordinal": None,
        "provider_call_ordinal": 0,
        "provider_call_role": "static_snapshot",
        "provider_request_sha256": authority.provider_request_sha256,
        "request_ordinal": 0,
    }
    logical_invocation_sha256 = _domain_sha256(
        _LOGICAL_INVOCATION_DOMAIN,
        {
            "execution": execution.to_dict(),
            "provider_calls": [provider_call_payload],
            "semantic_request_sha256": semantic_request_sha256,
        },
    )
    try:
        return RawRequestCaptureContextV2(
            provider_authority_sha256=authority.provider_authority_sha256,
            source_sha=execution.source_sha,
            run_id=execution.run_id,
            run_attempt=execution.run_attempt,
            chain_id=execution.chain_id,
            lane_id=execution.lane_id,
            provider_calls=(
                RawProviderCallContextV2(
                    request_ordinal=0,
                    semantic_request_sha256=semantic_request_sha256,
                    logical_invocation_sha256=logical_invocation_sha256,
                    provider_call_role="static_snapshot",
                    provider_call_ordinal=0,
                    source_family="static",
                    endpoint_id=authority.endpoint_name,
                    provider_request_sha256=authority.provider_request_sha256,
                    endpoint_contract_sha256=authority.endpoint_contract_sha256,
                    competition_id=authority.competition_id,
                    competition_identity_sha256=authority.competition_identity_sha256,
                    scope_sha256=authority.scope_sha256,
                    pagination_sha256=None,
                    page_ordinal=None,
                ),
            ),
        )
    except (TypeError, ValueError) as exc:
        raise RawRequestContextCompilationError(
            "compiled static raw-request context failed strict validation"
        ) from exc


def build_ordinary_stats_raw_request_context_factory(
    authority: RequestClosureExecutionAuthority,
    execution: RawRequestExecutionIdentityV1,
) -> Callable[[str, dict[str, object]], RawRequestCaptureContextV2]:
    """Bind immutable authority and execution identity for ``ExtractorRunner``."""

    if type(authority) is not RequestClosureExecutionAuthority:
        _fail("raw-request context factory requires an exact closure authority")
    if type(execution) is not RawRequestExecutionIdentityV1:
        _fail("raw-request context factory requires an exact execution identity")

    def factory(
        endpoint_name: str,
        params: dict[str, object],
    ) -> RawRequestCaptureContextV2:
        return compile_ordinary_stats_raw_request_context(
            authority,
            execution,
            endpoint_name,
            params,
        )

    return factory


def build_ordinary_raw_request_context_factory(
    authority: RequestClosureExecutionAuthority | None,
    static_authorities: tuple[StaticRequestClosureAuthorityV1, ...],
    execution: RawRequestExecutionIdentityV1,
) -> Callable[[str, dict[str, object]], RawRequestCaptureContextV2]:
    """Bind the exact ordinary stats/static authority without activating it."""

    if authority is not None and type(authority) is not RequestClosureExecutionAuthority:
        _fail("raw-request context factory requires an exact closure authority")
    if type(execution) is not RawRequestExecutionIdentityV1:
        _fail("raw-request context factory requires an exact execution identity")
    if (
        type(static_authorities) is not tuple
        or any(type(item) is not StaticRequestClosureAuthorityV1 for item in static_authorities)
        or static_authorities
        != tuple(sorted(static_authorities, key=lambda item: item.endpoint_name))
        or len({item.endpoint_name for item in static_authorities}) != len(static_authorities)
    ):
        _fail("raw-request context factory static authorities are invalid")
    if authority is None and not static_authorities:
        _fail("raw-request context factory has no exact provider authority")
    try:
        for static_authority in static_authorities:
            static_authority.to_dict()
    except (TypeError, ValueError, ParserInputCaptureIntegrityError) as exc:
        raise RawRequestContextCompilationError(
            "raw-request context factory static authority did not revalidate"
        ) from exc
    static_by_endpoint = {item.endpoint_name: item for item in static_authorities}

    def factory(
        endpoint_name: str,
        params: dict[str, object],
    ) -> RawRequestCaptureContextV2:
        static_authority = static_by_endpoint.get(endpoint_name)
        if static_authority is not None:
            return compile_static_raw_request_context(
                static_authority,
                execution,
                endpoint_name,
                params,
            )
        if authority is None:
            _fail("raw-request context has no authority for this logical call")
        return compile_ordinary_stats_raw_request_context(
            authority,
            execution,
            endpoint_name,
            params,
        )

    return factory
