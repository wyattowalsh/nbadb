"""Atomic DuckDB persistence for public raw-request authority bundles.

The extraction runner captures provisional request evidence and the post-commit
finalizer closes it against staging receipts.  This module owns the next
boundary: immutable, idempotent persistence of the four fixed public raw
tables plus one private bundle journal.  It performs no provider or filesystem
I/O and never records pipeline-journal success itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar, Never, cast

import duckdb
import polars as pl

from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    validate_observation_route_landing,
    validate_parser_input_object,
    validate_raw_request_authority_bundle,
    validate_request_attempt_identity,
    validate_request_observation,
    validate_result_occurrence,
)
from nbadb.core.types import validate_sql_identifier
from nbadb.schemas.raw.nba_api_authority import (
    RawNbaApiObservationRouteLandingSchema,
    RawNbaApiParserInputObjectSchema,
    RawNbaApiRequestObservationSchema,
    RawNbaApiResultOccurrenceSchema,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    import pandera.polars as pa

    from nbadb.orchestrate.extractor_runner import RequestClosureExecutionAuthority
    from nbadb.orchestrate.raw_request_assurance import RawRequestAssuranceAuthorityV2
    from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1
    from nbadb.orchestrate.raw_request_manifest import RawRequestAuthorityManifestV2

__all__ = [
    "RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL",
    "RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL",
    "RAW_REQUEST_AUTHORITY_TABLES",
    "RawRequestAuthorityPersistenceError",
    "RawRequestAuthorityPersistenceReceiptV2",
    "RawRequestClosureCallV2",
    "RawRequestManifestAuthorityV2",
    "RawRequestPersistedAttemptV2",
    "RawRequestAuthorityStore",
    "compile_raw_request_manifest_authority",
    "logical_parameter_digests_by_provider_call",
    "raw_request_closure_authority_sha256",
    "validate_raw_request_manifest_authority",
]

RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL = "_raw_request_authority_bundle_journal"
RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL = "_raw_request_authority_manifest_journal"
RAW_REQUEST_AUTHORITY_TABLES = (
    "raw_nba_api_parser_input_object",
    "raw_nba_api_request_observation",
    "raw_nba_api_result_occurrence",
    "raw_nba_api_observation_route_landing",
)

_WRITE_LOCK = threading.RLock()
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}\Z")
_FORBIDDEN_IDENTITY_RE = re.compile(
    r"(?:authorization|cookie|credential|header|password|proxy|secret|token|vpn|"
    r"(?:^|[._:-])(?:path|host|ip)(?:$|[._:-]))",
    re.IGNORECASE,
)
_MAX_ROUTE_IDS = 4_096
_MAX_ROUTE_ID_BYTES = 1_024
_TERMINAL_OUTCOMES = frozenset({"success_nonempty", "success_empty", "static_snapshot_success"})


class RawRequestAuthorityPersistenceError(ValueError):
    """Public raw authority could not be persisted or read back exactly."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RawRequestAuthorityPersistenceError(
            "raw-request persistence receipt is not canonical JSON"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _fail(message: str) -> Never:
    raise RawRequestAuthorityPersistenceError(message)


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_git_sha(value: object) -> str:
    if type(value) is not str or _GIT_SHA_RE.fullmatch(value) is None:
        _fail("source_sha must be a lowercase 40-character Git SHA")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0 or value > 2**63 - 1:
        _fail(f"{field_name} must be a positive bounded integer")
    return value


def _require_safe_id(value: object, *, field_name: str) -> str:
    if (
        type(value) is not str
        or _SAFE_ID_RE.fullmatch(value) is None
        or _FORBIDDEN_IDENTITY_RE.search(value) is not None
    ):
        _fail(f"{field_name} must be a public-safe path-free identity")
    return value


def _quote_identifier(value: str) -> str:
    validate_sql_identifier(value)
    return f'"{value}"'


def _canonical_inventory(values: Sequence[str]) -> tuple[str, str]:
    ordered = tuple(sorted(values))
    if len(ordered) != len(set(ordered)):
        raise RawRequestAuthorityPersistenceError(
            "raw-request persistence inventory contains duplicate identities"
        )
    encoded = _canonical_bytes(list(ordered)).decode("utf-8")
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_ordered_inventory(values: Sequence[str]) -> tuple[str, str]:
    ordered = tuple(values)
    if len(ordered) != len(set(ordered)):
        raise RawRequestAuthorityPersistenceError(
            "raw-request ordered persistence inventory contains duplicate identities"
        )
    encoded = _canonical_bytes(list(ordered)).decode("utf-8")
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _canonical_row_inventory(
    identities: Sequence[str],
    canonical_rows: Sequence[bytes],
) -> str:
    """Bind exact full canonical row bytes in stable primary-key order."""

    if len(identities) != len(canonical_rows):
        _fail("raw-request row inventory cardinality is invalid")
    pairs = tuple(sorted(zip(identities, canonical_rows, strict=True)))
    if len(pairs) != len({identity for identity, _row in pairs}) or any(
        type(row) is not bytes for _identity, row in pairs
    ):
        _fail("raw-request row inventory is malformed")
    return _sha256(
        [
            {
                "identity": identity,
                "canonical_row_sha256": hashlib.sha256(row).hexdigest(),
            }
            for identity, row in pairs
        ]
    )


def _require_routes(value: object, *, allow_empty: bool) -> tuple[str, ...]:
    if type(value) is not tuple:
        _fail("raw-request route inventory must be an exact tuple")
    routes = value
    if (
        (not allow_empty and not routes)
        or len(routes) > _MAX_ROUTE_IDS
        or routes != tuple(sorted(routes))
        or len(routes) != len(set(routes))
        or any(
            type(item) is not str
            or not item
            or len(item.encode("utf-8")) > _MAX_ROUTE_ID_BYTES
            or _FORBIDDEN_IDENTITY_RE.search(item) is not None
            for item in routes
        )
    ):
        _fail("raw-request route inventory must be bounded, sorted, unique, and public-safe")
    return cast("tuple[str, ...]", routes)


@dataclass(frozen=True, slots=True)
class RawRequestClosureCallV2:
    """One exact logical request in the request-closure denominator."""

    logical_request_sha256: str
    endpoint_name: str
    source_family: str
    endpoint_id: str
    logical_parameters_sha256: str
    provider_parameters_sha256: str | None
    provider_request_sha256: str
    route_ids: tuple[str, ...]
    scope_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "nbadb_raw_request_closure_call_v2"

    def __post_init__(self) -> None:
        _require_safe_id(self.endpoint_name, field_name="endpoint_name")
        _require_safe_id(self.endpoint_id, field_name="endpoint_id")
        if self.source_family not in {"stats", "live", "static"}:
            _fail("source_family must be stats, live, or static")
        for field_name in (
            "logical_parameters_sha256",
            "provider_request_sha256",
            "scope_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if self.provider_parameters_sha256 is not None:
            _require_sha256(
                self.provider_parameters_sha256,
                field_name="provider_parameters_sha256",
            )
        _require_routes(self.route_ids, allow_empty=False)
        _require_sha256(self.logical_request_sha256, field_name="logical_request_sha256")
        if self.logical_request_sha256 != _sha256(self._identity_payload()):
            _fail("logical_request_sha256 does not bind the exact closure call")

    @classmethod
    def build(
        cls,
        *,
        endpoint_name: str,
        source_family: str,
        endpoint_id: str,
        logical_parameters_sha256: str,
        provider_parameters_sha256: str | None,
        provider_request_sha256: str,
        route_ids: tuple[str, ...],
        scope_sha256: str,
    ) -> RawRequestClosureCallV2:
        payload = {
            "endpoint_name": endpoint_name,
            "source_family": source_family,
            "endpoint_id": endpoint_id,
            "logical_parameters_sha256": logical_parameters_sha256,
            "provider_parameters_sha256": provider_parameters_sha256,
            "provider_request_sha256": provider_request_sha256,
            "route_ids": list(route_ids),
            "scope_sha256": scope_sha256,
        }
        return cls(
            logical_request_sha256=_sha256(payload),
            endpoint_name=endpoint_name,
            source_family=source_family,
            endpoint_id=endpoint_id,
            logical_parameters_sha256=logical_parameters_sha256,
            provider_parameters_sha256=provider_parameters_sha256,
            provider_request_sha256=provider_request_sha256,
            route_ids=route_ids,
            scope_sha256=scope_sha256,
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "endpoint_name": self.endpoint_name,
            "source_family": self.source_family,
            "endpoint_id": self.endpoint_id,
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "provider_parameters_sha256": self.provider_parameters_sha256,
            "provider_request_sha256": self.provider_request_sha256,
            "route_ids": list(self.route_ids),
            "scope_sha256": self.scope_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "logical_request_sha256": self.logical_request_sha256,
            **self._identity_payload(),
        }

    def validate_terminal_route_ids(self, route_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Validate fixed planned routes plus at most one typed response route.

        Conditional lossless routes deliberately remain outside the immutable
        pre-provider request-closure inventory.  A terminal response may add
        one only when the current pinned route registry can independently
        reproduce its exact typed admission from this call's fixed routes.
        """

        observed = _require_routes(route_ids, allow_empty=False)
        if observed == self.route_ids:
            return observed
        required = set(self.route_ids)
        observed_set = set(observed)
        conditional_route_ids = tuple(sorted(observed_set - required))
        if (
            self.source_family == "static"
            or not required < observed_set
            or len(observed) != len(self.route_ids) + 1
            or len(conditional_route_ids) != 1
        ):
            _fail("terminal observation routes differ from the exact closure call")

        try:
            from nbadb.contracts.staging_route_contract import (
                admit_known_conditional_staging_route,
                staging_route_contract_bundle,
            )

            route_bundle = staging_route_contract_bundle()
            fixed_routes = tuple(route_bundle.by_route_id[item] for item in self.route_ids)
            if any(
                route.endpoint_name != self.endpoint_name
                or route.source_family != self.source_family
                or route.provider_endpoint_id != self.endpoint_id
                or route.provider_authority_sha256 != route_bundle.provider_authority_sha256
                for route in fixed_routes
            ):
                _fail("closure-call fixed routes differ from pinned provider authority")
            admission = admit_known_conditional_staging_route(
                endpoint_name=self.endpoint_name,
                static_route_ids=self.route_ids,
                conditional_route_ids=conditional_route_ids,
                provider_authority_sha256=route_bundle.provider_authority_sha256,
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise RawRequestAuthorityPersistenceError(
                "terminal observation adds an unproved conditional route"
            ) from exc
        if admission.route_id != conditional_route_ids[0]:
            _fail("terminal observation conditional route differs from exact admission")
        return observed


@dataclass(frozen=True, slots=True)
class RawRequestPersistedAttemptV2:
    """Canonical retry/call projection for one persisted observation."""

    observation_sha256: str
    observation_record_sha256: str
    semantic_request_sha256: str
    logical_invocation_sha256: str
    provider_call_sha256: str
    provider_call_role: str
    provider_call_ordinal: int
    retry_ordinal: int
    request_ordinal: int
    source_family: str
    endpoint_id: str
    provider_request_sha256: str
    logical_parameters_sha256: str
    safe_parameters_sha256: str
    scope_sha256: str
    lifecycle: str
    outcome: str
    route_ids: tuple[str, ...]

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "nbadb_raw_request_persisted_attempt_v2"

    def __post_init__(self) -> None:
        for field_name in (
            "observation_sha256",
            "observation_record_sha256",
            "semantic_request_sha256",
            "logical_invocation_sha256",
            "provider_call_sha256",
            "provider_request_sha256",
            "logical_parameters_sha256",
            "safe_parameters_sha256",
            "scope_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_safe_id(self.provider_call_role, field_name="provider_call_role")
        _require_safe_id(self.endpoint_id, field_name="endpoint_id")
        for field_name in (
            "provider_call_ordinal",
            "retry_ordinal",
            "request_ordinal",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0 or value > 2**63 - 1:
                _fail(f"{field_name} must be a nonnegative bounded integer")
        if self.source_family not in {"stats", "live", "static"}:
            _fail("persisted attempt source_family is invalid")
        if self.lifecycle not in {"incomplete", "selected_terminal"}:
            _fail("persisted attempt must be completed, not merely allocated")
        routes = _require_routes(self.route_ids, allow_empty=True)
        if self.lifecycle == "selected_terminal":
            if self.outcome not in _TERMINAL_OUTCOMES or not routes:
                _fail("selected terminal attempt lacks successful route evidence")
        elif self.outcome in _TERMINAL_OUTCOMES or routes:
            _fail("incomplete attempt cannot claim terminal route evidence")

    @property
    def attempt_receipt_sha256(self) -> str:
        return _sha256(self._semantic_payload())

    def _semantic_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "observation_sha256": self.observation_sha256,
            "observation_record_sha256": self.observation_record_sha256,
            "semantic_request_sha256": self.semantic_request_sha256,
            "logical_invocation_sha256": self.logical_invocation_sha256,
            "provider_call_sha256": self.provider_call_sha256,
            "provider_call_role": self.provider_call_role,
            "provider_call_ordinal": self.provider_call_ordinal,
            "retry_ordinal": self.retry_ordinal,
            "request_ordinal": self.request_ordinal,
            "source_family": self.source_family,
            "endpoint_id": self.endpoint_id,
            "provider_request_sha256": self.provider_request_sha256,
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "safe_parameters_sha256": self.safe_parameters_sha256,
            "scope_sha256": self.scope_sha256,
            "lifecycle": self.lifecycle,
            "outcome": self.outcome,
            "route_ids": list(self.route_ids),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._semantic_payload(), "attempt_receipt_sha256": self.attempt_receipt_sha256}


def logical_parameter_digests_by_provider_call(
    bundle: RawRequestAuthorityBundleV2,
) -> dict[str, str]:
    """Recover call-level logical digests from exact embedded alias authority."""

    parsed = validate_raw_request_authority_bundle(bundle)
    aliased: dict[str, str] = {}
    for observation in parsed.observations:
        binding_json = observation.logical_provider_parameter_binding_json
        if binding_json is None:
            continue
        try:
            from nbadb.contracts.logical_provider_parameter_binding import (
                LogicalProviderParameterBindingV1,
            )

            binding = LogicalProviderParameterBindingV1.from_canonical_bytes(
                binding_json.encode("utf-8", errors="strict")
            )
        except (AttributeError, TypeError, UnicodeEncodeError, ValueError) as exc:
            raise RawRequestAuthorityPersistenceError(
                "raw-request alias authority failed exact logical-digest replay"
            ) from exc
        provider_call_sha256 = observation.attempt.provider_call_sha256
        prior = aliased.setdefault(
            provider_call_sha256,
            binding.logical_parameters_sha256,
        )
        if prior != binding.logical_parameters_sha256:
            _fail("raw-request provider call crosses logical parameter digests")

    logical_by_call: dict[str, str] = {}
    for observation in parsed.observations:
        attempt = observation.attempt
        logical_sha256 = aliased.get(
            attempt.provider_call_sha256,
            attempt.safe_parameters_sha256,
        )
        prior = logical_by_call.setdefault(
            attempt.provider_call_sha256,
            logical_sha256,
        )
        if prior != logical_sha256:
            _fail("raw-request provider call has ambiguous logical parameter authority")
    return logical_by_call


def _attempt_receipts(
    bundle: RawRequestAuthorityBundleV2,
) -> tuple[RawRequestPersistedAttemptV2, ...]:
    logical_by_call = logical_parameter_digests_by_provider_call(bundle)
    routes_by_observation: dict[str, set[str]] = {
        item.attempt.observation_sha256: set() for item in bundle.observations
    }
    for landing in bundle.landings:
        routes_by_observation[landing.observation_sha256].add(landing.route_id)
    result: list[RawRequestPersistedAttemptV2] = []
    for observation in bundle.observations:
        attempt = observation.attempt
        result.append(
            RawRequestPersistedAttemptV2(
                observation_sha256=attempt.observation_sha256,
                observation_record_sha256=observation.observation_record_sha256,
                semantic_request_sha256=attempt.semantic_request_sha256,
                logical_invocation_sha256=attempt.logical_invocation_sha256,
                provider_call_sha256=attempt.provider_call_sha256,
                provider_call_role=attempt.provider_call_role,
                provider_call_ordinal=attempt.provider_call_ordinal,
                retry_ordinal=attempt.retry_ordinal,
                request_ordinal=attempt.request_ordinal,
                source_family=attempt.source_family,
                endpoint_id=attempt.endpoint_id,
                provider_request_sha256=attempt.provider_request_sha256,
                logical_parameters_sha256=logical_by_call[attempt.provider_call_sha256],
                safe_parameters_sha256=attempt.safe_parameters_sha256,
                scope_sha256=attempt.scope_sha256,
                lifecycle=observation.lifecycle,
                outcome=observation.outcome,
                route_ids=tuple(sorted(routes_by_observation[attempt.observation_sha256])),
            )
        )
    return tuple(sorted(result, key=lambda item: item.attempt_receipt_sha256))


@dataclass(frozen=True, slots=True)
class RawRequestAuthorityPersistenceReceiptV2:
    """Exact read-after-commit receipt for one immutable authority bundle."""

    bundle_sha256: str
    object_count: int
    observation_count: int
    occurrence_count: int
    landing_count: int
    object_inventory_sha256: str
    observation_inventory_sha256: str
    occurrence_inventory_sha256: str
    landing_inventory_sha256: str
    object_rows_sha256: str
    observation_rows_sha256: str
    occurrence_rows_sha256: str
    landing_rows_sha256: str
    attempts: tuple[RawRequestPersistedAttemptV2, ...]
    attempt_count: int
    attempt_inventory_sha256: str
    replayed: bool

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "nbadb_raw_request_authority_persistence_receipt_v2"

    def __post_init__(self) -> None:
        for field_name in (
            "bundle_sha256",
            "object_inventory_sha256",
            "observation_inventory_sha256",
            "occurrence_inventory_sha256",
            "landing_inventory_sha256",
            "object_rows_sha256",
            "observation_rows_sha256",
            "occurrence_rows_sha256",
            "landing_rows_sha256",
            "attempt_inventory_sha256",
        ):
            value = getattr(self, field_name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise RawRequestAuthorityPersistenceError(
                    f"{field_name} must be a lowercase SHA-256"
                )
        for field_name in (
            "object_count",
            "observation_count",
            "occurrence_count",
            "landing_count",
            "attempt_count",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0 or value > 2**63 - 1:
                raise RawRequestAuthorityPersistenceError(
                    f"{field_name} must be a nonnegative bounded integer"
                )
        if type(self.replayed) is not bool:
            raise RawRequestAuthorityPersistenceError("replayed must be an exact boolean")
        if type(self.attempts) is not tuple or any(
            type(item) is not RawRequestPersistedAttemptV2 for item in self.attempts
        ):
            _fail("persistence receipt attempts must use exact immutable contracts")
        ordered = tuple(sorted(self.attempts, key=lambda item: item.attempt_receipt_sha256))
        if self.attempts != ordered:
            _fail("persistence receipt attempts must use canonical order")
        attempt_ids = tuple(item.attempt_receipt_sha256 for item in ordered)
        observation_ids = tuple(item.observation_sha256 for item in ordered)
        if len(attempt_ids) != len(set(attempt_ids)) or len(observation_ids) != len(
            set(observation_ids)
        ):
            _fail("persistence receipt attempt inventory contains duplicate identities")
        if self.attempt_count != len(ordered) or self.attempt_count != self.observation_count:
            _fail("persistence receipt attempt count differs from observations")
        if self.attempt_inventory_sha256 != _sha256([item.to_dict() for item in ordered]):
            _fail("persistence receipt attempt inventory digest is invalid")

    def _semantic_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "bundle_sha256": self.bundle_sha256,
            "object_count": self.object_count,
            "observation_count": self.observation_count,
            "occurrence_count": self.occurrence_count,
            "landing_count": self.landing_count,
            "object_inventory_sha256": self.object_inventory_sha256,
            "observation_inventory_sha256": self.observation_inventory_sha256,
            "occurrence_inventory_sha256": self.occurrence_inventory_sha256,
            "landing_inventory_sha256": self.landing_inventory_sha256,
            "object_rows_sha256": self.object_rows_sha256,
            "observation_rows_sha256": self.observation_rows_sha256,
            "occurrence_rows_sha256": self.occurrence_rows_sha256,
            "landing_rows_sha256": self.landing_rows_sha256,
            "attempts": [item.to_dict() for item in self.attempts],
            "attempt_count": self.attempt_count,
            "attempt_inventory_sha256": self.attempt_inventory_sha256,
        }

    @property
    def receipt_sha256(self) -> str:
        """Return the replay-independent persistence identity."""

        return _sha256(self._semantic_payload())

    def to_dict(self) -> dict[str, object]:
        return {
            **self._semantic_payload(),
            "receipt_sha256": self.receipt_sha256,
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class RawRequestManifestAuthorityV2:
    """Exact public-safe authority required to seal runtime generations."""

    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str
    scope_sha256: str
    route_authority_sha256: str
    request_closure_authority_sha256: str
    field_authority_sha256: str
    model_authority_sha256: str
    expected_calls: tuple[RawRequestClosureCallV2, ...]
    compiler_provenance_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "nbadb_raw_request_manifest_authority_v2"

    def __post_init__(self) -> None:
        _require_git_sha(self.source_sha)
        _require_positive_int(self.run_id, field_name="run_id")
        _require_positive_int(self.run_attempt, field_name="run_attempt")
        _require_safe_id(self.chain_id, field_name="chain_id")
        _require_safe_id(self.lane_id, field_name="lane_id")
        for field_name in (
            "scope_sha256",
            "route_authority_sha256",
            "request_closure_authority_sha256",
            "field_authority_sha256",
            "model_authority_sha256",
            "compiler_provenance_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        if type(self.expected_calls) is not tuple or any(
            type(item) is not RawRequestClosureCallV2 for item in self.expected_calls
        ):
            _fail("raw-request manifest authority requires exact expected calls")
        expected = tuple(sorted(self.expected_calls, key=lambda item: item.logical_request_sha256))
        if (
            not expected
            or expected != self.expected_calls
            or len({item.logical_request_sha256 for item in expected}) != len(expected)
            or len({item.provider_request_sha256 for item in expected}) != len(expected)
        ):
            _fail("raw-request expected calls must be nonempty, canonical, and bijective")
        expected_scope = _scope_authority_sha256(expected)
        if self.scope_sha256 != expected_scope:
            _fail("scope_sha256 does not bind the exact per-request scope denominator")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "scope_sha256": self.scope_sha256,
            "route_authority_sha256": self.route_authority_sha256,
            "request_closure_authority_sha256": (self.request_closure_authority_sha256),
            "field_authority_sha256": self.field_authority_sha256,
            "model_authority_sha256": self.model_authority_sha256,
            "expected_calls": [item.to_dict() for item in self.expected_calls],
            "compiler_provenance_sha256": self.compiler_provenance_sha256,
        }


def _scope_authority_sha256(expected_calls: Sequence[RawRequestClosureCallV2]) -> str:
    exact = tuple(expected_calls)
    if len(exact) == 1:
        return exact[0].scope_sha256
    return _sha256(
        {
            "schema_version": 2,
            "kind": "nbadb_raw_request_composite_scope_v2",
            "logical_requests": [
                {
                    "logical_request_sha256": item.logical_request_sha256,
                    "scope_sha256": item.scope_sha256,
                }
                for item in exact
            ],
        }
    )


def _stats_expected_calls(
    authority: RequestClosureExecutionAuthority,
) -> tuple[RawRequestClosureCallV2, ...]:
    from nbadb.orchestrate.extractor_runner import RequestClosureExecutionAuthority

    if type(authority) is not RequestClosureExecutionAuthority:
        _fail("stats request closure authority is not exact")
    routes_by_id = {item.route_id: item for item in authority.route_manifest.routes}
    physical_by_manifest = {
        item.manifest_route_id: item.staging_route_id for item in authority.staging_route_aliases
    }
    result: list[RawRequestClosureCallV2] = []
    for logical_call in authority.logical_calls:
        routes = tuple(routes_by_id[item] for item in logical_call.route_ids)
        physical_route_ids = tuple(
            sorted(physical_by_manifest[item] for item in logical_call.route_ids)
        )
        source_families = {item.source_family for item in routes}
        endpoint_ids = {item.endpoint_id for item in routes}
        if len(source_families) != 1 or len(endpoint_ids) != 1:
            _fail("stats closure call crosses provider endpoint authority")
        result.append(
            RawRequestClosureCallV2.build(
                endpoint_name=logical_call.endpoint_name,
                source_family=next(iter(source_families)),
                endpoint_id=next(iter(endpoint_ids)),
                logical_parameters_sha256=logical_call.logical_parameters_sha256,
                provider_parameters_sha256=logical_call.provider_parameters_sha256,
                provider_request_sha256=logical_call.provider_request_sha256,
                route_ids=physical_route_ids,
                scope_sha256=authority.scope.scope_sha256,
            )
        )
    return tuple(result)


def _static_expected_calls(
    authorities: Sequence[object],
) -> tuple[RawRequestClosureCallV2, ...]:
    from nbadb.orchestrate.request_closure_production import StaticRequestClosureAuthorityV1

    result: list[RawRequestClosureCallV2] = []
    for authority in authorities:
        if type(authority) is not StaticRequestClosureAuthorityV1:
            _fail("static request closure authority is not exact")
        static = authority
        result.append(
            RawRequestClosureCallV2.build(
                endpoint_name=static.endpoint_name,
                source_family="static",
                endpoint_id=static.endpoint_name,
                logical_parameters_sha256=static.logical_parameters_sha256,
                provider_parameters_sha256=static.logical_parameters_sha256,
                provider_request_sha256=static.provider_request_sha256,
                route_ids=static.physical_route_ids,
                scope_sha256=static.scope_sha256,
            )
        )
    return tuple(result)


def raw_request_closure_authority_sha256(
    authority: RequestClosureExecutionAuthority,
) -> str:
    """Bind the complete exact request-closure authority without private state."""

    from nbadb.orchestrate.extractor_runner import RequestClosureExecutionAuthority

    if type(authority) is not RequestClosureExecutionAuthority:
        _fail("raw-request manifest requires an exact request-closure authority")
    return _sha256(
        {
            "schema_version": 1,
            "kind": "nbadb_raw_request_closure_execution_authority",
            "route_manifest_sha256": authority.route_manifest.manifest_sha256,
            "scope_sha256": authority.scope.scope_sha256,
            "staging_route_aliases": [
                {
                    "manifest_route_id": item.manifest_route_id,
                    "staging_route_id": item.staging_route_id,
                }
                for item in authority.staging_route_aliases
            ],
            "logical_calls": [
                {
                    "endpoint_name": item.endpoint_name,
                    "logical_parameters_sha256": item.logical_parameters_sha256,
                    "provider_parameters_sha256": item.provider_parameters_sha256,
                    "provider_request_sha256": item.provider_request_sha256,
                    "route_ids": list(item.route_ids),
                }
                for item in authority.logical_calls
            ],
            "competition_authorities": [
                {
                    "qualified_request": item.qualified_request.to_dict(),
                    "request_binding": item.request_binding.to_dict(),
                }
                for item in authority.competition_authorities
            ],
        }
    )


def _compile_raw_request_manifest_authority_impl(
    execution: RawRequestExecutionIdentityV1,
    request_closure: RequestClosureExecutionAuthority | None,
    *,
    static_authorities: Sequence[object] = (),
    assurance_authority: RawRequestAssuranceAuthorityV2,
    compiler_provenance_sha256: str,
) -> RawRequestManifestAuthorityV2:
    """Compile semantic authority fields after every upstream proof validates."""

    from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
    from nbadb.orchestrate.extractor_runner import RequestClosureExecutionAuthority
    from nbadb.orchestrate.raw_request_assurance import (
        RawRequestAssuranceError,
        validate_raw_request_assurance_authority,
    )
    from nbadb.orchestrate.raw_request_context import RawRequestExecutionIdentityV1

    if type(execution) is not RawRequestExecutionIdentityV1:
        _fail("raw-request manifest requires an exact execution identity")
    try:
        assurance_authority = validate_raw_request_assurance_authority(assurance_authority)
    except RawRequestAssuranceError as exc:
        raise RawRequestAuthorityPersistenceError(
            "raw-request manifest requires independently validated assurance provenance"
        ) from exc
    provider_authority = expected_nba_api_provider_authority()
    if (
        assurance_authority.source_sha != execution.source_sha
        or assurance_authority.provider_authority_sha256 != provider_authority["authority_sha256"]
        or assurance_authority.provider_evidence_sha256
        != provider_authority["provider_evidence_sha256"]
    ):
        _fail("raw-request assurance authority differs from execution or provider authority")
    if (
        request_closure is not None
        and type(request_closure) is not RequestClosureExecutionAuthority
    ):
        _fail("raw-request manifest requires an exact request-closure authority")
    if type(static_authorities) is not tuple:
        _fail("raw-request manifest static authorities must be an exact tuple")
    stats_calls = () if request_closure is None else _stats_expected_calls(request_closure)
    static_calls = _static_expected_calls(static_authorities)
    expected_calls = tuple(
        sorted((*stats_calls, *static_calls), key=lambda item: item.logical_request_sha256)
    )
    if not expected_calls:
        _fail("raw-request manifest requires a nonempty request denominator")
    route_authority_sha256 = _sha256(
        {
            "stats_route_manifest_sha256": (
                None if request_closure is None else request_closure.route_manifest.manifest_sha256
            ),
            "static_route_authorities": [
                {
                    "logical_request_sha256": item.logical_request_sha256,
                    "route_ids": list(item.route_ids),
                }
                for item in static_calls
            ],
        }
    )
    closure_authority_sha256 = _sha256(
        {
            "stats_request_closure_authority_sha256": (
                None
                if request_closure is None
                else raw_request_closure_authority_sha256(request_closure)
            ),
            "static_request_closure_authorities": [
                cast("Any", item).to_dict() for item in static_authorities
            ],
        }
    )
    return RawRequestManifestAuthorityV2(
        source_sha=execution.source_sha,
        run_id=execution.run_id,
        run_attempt=execution.run_attempt,
        chain_id=execution.chain_id,
        lane_id=execution.lane_id,
        scope_sha256=_scope_authority_sha256(expected_calls),
        route_authority_sha256=route_authority_sha256,
        request_closure_authority_sha256=closure_authority_sha256,
        field_authority_sha256=assurance_authority.field_authority_sha256,
        model_authority_sha256=assurance_authority.model_authority_sha256,
        expected_calls=expected_calls,
        compiler_provenance_sha256=compiler_provenance_sha256,
    )


def _build_manifest_compilation_boundary() -> tuple[
    Callable[..., RawRequestManifestAuthorityV2],
    Callable[[object], RawRequestManifestAuthorityV2],
]:
    """Issue tamper-evident runtime capabilities only through exact compilation."""

    signing_key = secrets.token_bytes(32)

    def provenance_sha256(value: RawRequestManifestAuthorityV2) -> str:
        payload = value.to_dict()
        # The provenance field is part of the exact serialized authority but
        # cannot recursively sign itself.  Compile and validate the same
        # canonical payload with that one field replaced by its fixed null pin.
        payload["compiler_provenance_sha256"] = "0" * 64
        return hmac.digest(
            signing_key,
            _canonical_bytes(payload),
            "sha256",
        ).hex()

    def compile_authority(
        execution: RawRequestExecutionIdentityV1,
        request_closure: RequestClosureExecutionAuthority | None,
        *,
        static_authorities: Sequence[object] = (),
        assurance_authority: RawRequestAssuranceAuthorityV2,
    ) -> RawRequestManifestAuthorityV2:
        """Compile the sole manifest authority admitted by one runtime lane."""

        unsigned = _compile_raw_request_manifest_authority_impl(
            execution,
            request_closure,
            static_authorities=static_authorities,
            assurance_authority=assurance_authority,
            compiler_provenance_sha256="0" * 64,
        )
        return replace(
            unsigned,
            compiler_provenance_sha256=provenance_sha256(unsigned),
        )

    def validate(value: object) -> RawRequestManifestAuthorityV2:
        if type(value) is not RawRequestManifestAuthorityV2:
            _fail("raw-request manifest advancement requires an exact V2 authority")
        authority = value
        expected = provenance_sha256(authority)
        if not hmac.compare_digest(authority.compiler_provenance_sha256, expected):
            _fail(
                "raw-request manifest authority lacks current-process exact-compilation provenance"
            )
        return authority

    return compile_authority, validate


compile_raw_request_manifest_authority, validate_raw_request_manifest_authority = (
    _build_manifest_compilation_boundary()
)


@dataclass(frozen=True, slots=True)
class _TableContract:
    table_name: str
    key_column: str
    schema_type: type[pa.DataFrameModel]
    rows: tuple[dict[str, object], ...]


def _polars_schema(schema_type: type[pa.DataFrameModel]) -> dict[str, pl.DataType]:
    schema = schema_type.to_schema()
    result: dict[str, pl.DataType] = {}
    for name, column in schema.columns.items():
        dtype = column.dtype.type
        if dtype in {pl.Boolean, pl.Int64, pl.String, pl.Binary} or isinstance(dtype, pl.Datetime):
            result[name] = dtype
            continue
        raise RawRequestAuthorityPersistenceError(
            f"unsupported public raw dtype for {name}: {dtype!r}"
        )
    return result


def _duckdb_type(dtype: pl.DataType) -> str:
    if dtype == pl.Boolean:
        return "BOOLEAN"
    if dtype == pl.Int64:
        return "BIGINT"
    if dtype == pl.String:
        return "VARCHAR"
    if dtype == pl.Binary:
        return "BLOB"
    if isinstance(dtype, pl.Datetime) and dtype.time_unit == "us" and dtype.time_zone == "UTC":
        return "TIMESTAMP WITH TIME ZONE"
    raise RawRequestAuthorityPersistenceError(f"unsupported public raw dtype: {dtype!r}")


def _frame_for_rows(
    rows: Sequence[Mapping[str, object]],
    schema_type: type[pa.DataFrameModel],
) -> pl.DataFrame:
    schema = _polars_schema(schema_type)
    try:
        frame = pl.DataFrame(
            [dict(row) for row in rows],
            schema=schema,
            orient="row",
            strict=True,
        )
        validated = schema_type.validate(frame)
    except Exception as exc:
        raise RawRequestAuthorityPersistenceError(
            "public raw authority rows failed their fixed table schema"
        ) from exc
    if (
        not isinstance(validated, pl.DataFrame)
        or validated.columns != list(schema)
        or dict(validated.schema) != schema
        or validated.to_dicts() != frame.to_dicts()
    ):
        raise RawRequestAuthorityPersistenceError(
            "public raw schema validation changed the exact authority rows"
        )
    return validated


class RawRequestAuthorityStore:
    """Persist closed public authority bundles on one caller-owned connection."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        if not isinstance(connection, duckdb.DuckDBPyConnection):
            raise TypeError("raw-request authority store requires a DuckDB connection")
        self._conn = connection
        self._poisoned = False

    def _commit_transaction(self) -> None:
        """Commit one active transaction through the fault-injection boundary."""

        self._conn.execute("COMMIT")

    @staticmethod
    def _add_note_preserving(interruption: BaseException, note: str) -> None:
        """Attach one diagnostic without dispatching to a hostile override."""

        with suppress(BaseException):
            BaseException.add_note(interruption, note)

    def _poison_connection(self, interruption: BaseException) -> None:
        """Make an unprovably clean caller connection unusable without masking."""

        self._poisoned = True
        self._add_note_preserving(
            interruption,
            "raw-request connection poisoned after transaction cleanup failure",
        )
        try:
            self._conn.close()
        except BaseException as close_error:
            self._add_note_preserving(
                interruption,
                f"raw-request poisoned connection close failed: {type(close_error).__name__}",
            )

    def _require_usable(self) -> None:
        if self._poisoned:
            _fail("raw-request authority store connection is poisoned")

    def _require_no_caller_transaction(self) -> None:
        """Refuse to present uncommitted caller state as durable readback."""

        try:
            first = self._conn.execute("SELECT current_transaction_id()").fetchone()
            second = self._conn.execute("SELECT current_transaction_id()").fetchone()
        except Exception:
            _fail("raw-request durable readback transaction state is unavailable")
        if (
            first is None
            or second is None
            or len(first) != 1
            or len(second) != 1
            or type(first[0]) is not int
            or type(second[0]) is not int
            or first[0] == second[0]
        ):
            _fail("raw-request durable readback refuses a caller-owned transaction")

    def _rollback_preserving(self, interruption: BaseException) -> bool:
        """Boundedly rollback and report whether a clean state was proven."""

        try:
            self._conn.rollback()
        except BaseException as rollback_error:
            self._add_note_preserving(
                interruption,
                f"raw-request rollback cleanup failed: {type(rollback_error).__name__}",
            )
        else:
            return True
        try:
            self._conn.execute("ROLLBACK")
        except BaseException as sql_rollback_error:
            self._add_note_preserving(
                interruption,
                f"raw-request SQL rollback cleanup failed: {type(sql_rollback_error).__name__}",
            )
            return False
        return True

    def _resolve_interrupted_commit(
        self,
        interruption: BaseException,
        *,
        verify_committed: Callable[[], None],
    ) -> None:
        """Resolve an interrupted commit without changing its outcome.

        The commit fault boundary can raise either before DuckDB executes
        ``COMMIT`` or after it has durably completed.  Recovery must therefore
        never issue another commit.  A successful rollback proves that the
        transaction was still active and is now aborted.  A failed rollback can
        mean that the commit already completed, so a fresh transaction probe
        restores a known-clean connection before exact durable readback.
        """

        if self._rollback_preserving(interruption):
            return

        probe_cleanup_needed = True
        probe_completed = False
        probe_clean = False
        try:
            self._conn.execute("BEGIN TRANSACTION")
            probe_completed = True
        except BaseException as probe_error:
            self._add_note_preserving(
                interruption,
                f"raw-request interrupted-commit state probe failed: {type(probe_error).__name__}",
            )
        finally:
            if probe_cleanup_needed:
                probe_clean = self._rollback_preserving(interruption)
                probe_cleanup_needed = False
                if not probe_clean:
                    self._poison_connection(interruption)

        if not probe_completed or not probe_clean:
            return

        try:
            verify_committed()
        except BaseException as readback_error:
            self._add_note_preserving(
                interruption,
                f"raw-request committed outcome readback failed: {type(readback_error).__name__}",
            )

    @staticmethod
    def _public_table_contracts() -> tuple[_TableContract, ...]:
        return (
            _TableContract(
                table_name=RAW_REQUEST_AUTHORITY_TABLES[0],
                key_column="object_sha256",
                schema_type=RawNbaApiParserInputObjectSchema,
                rows=(),
            ),
            _TableContract(
                table_name=RAW_REQUEST_AUTHORITY_TABLES[1],
                key_column="observation_sha256",
                schema_type=RawNbaApiRequestObservationSchema,
                rows=(),
            ),
            _TableContract(
                table_name=RAW_REQUEST_AUTHORITY_TABLES[2],
                key_column="occurrence_sha256",
                schema_type=RawNbaApiResultOccurrenceSchema,
                rows=(),
            ),
            _TableContract(
                table_name=RAW_REQUEST_AUTHORITY_TABLES[3],
                key_column="landing_sha256",
                schema_type=RawNbaApiObservationRouteLandingSchema,
                rows=(),
            ),
        )

    @classmethod
    def _table_contracts(
        cls,
        bundle: RawRequestAuthorityBundleV2,
    ) -> tuple[_TableContract, ...]:
        rows = (
            tuple(item.to_row() for item in bundle.objects),
            tuple(item.to_row() for item in bundle.observations),
            tuple(item.to_row() for item in bundle.occurrences),
            tuple(item.to_row() for item in bundle.landings),
        )
        return tuple(
            replace(contract, rows=contract_rows)
            for contract, contract_rows in zip(
                cls._public_table_contracts(),
                rows,
                strict=True,
            )
        )

    def _ensure_public_table(self, contract: _TableContract) -> None:
        table_name = _quote_identifier(contract.table_name)
        schema = contract.schema_type.to_schema()
        polars_schema = _polars_schema(contract.schema_type)
        definitions: list[str] = []
        for name, column in schema.columns.items():
            nullable = bool(column.nullable)
            definitions.append(
                f"{_quote_identifier(name)} {_duckdb_type(polars_schema[name])}"
                + ("" if nullable else " NOT NULL")
            )
        definitions.append(f"PRIMARY KEY ({_quote_identifier(contract.key_column)})")
        self._conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({', '.join(definitions)})")

        self._require_public_table(contract)

    def _require_public_table(self, contract: _TableContract) -> None:
        schema = contract.schema_type.to_schema()
        polars_schema = _polars_schema(contract.schema_type)

        expected = []
        for name, column in schema.columns.items():
            expected.append(
                (
                    name,
                    _duckdb_type(polars_schema[name]),
                    not bool(column.nullable) or name == contract.key_column,
                    name == contract.key_column,
                )
            )
        try:
            observed_rows = self._conn.execute(
                f"PRAGMA table_info('{contract.table_name}')"
            ).fetchall()
        except duckdb.Error as exc:
            raise RawRequestAuthorityPersistenceError(
                f"public raw table schema drifted: {contract.table_name}"
            ) from exc
        observed = [
            (str(row[1]), str(row[2]).upper(), bool(row[3]), bool(row[5])) for row in observed_rows
        ]
        if observed != expected:
            raise RawRequestAuthorityPersistenceError(
                f"public raw table schema drifted: {contract.table_name}"
            )

    def _ensure_journal(self) -> None:
        journal = _quote_identifier(RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL)
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {journal} (
                bundle_sha256 VARCHAR PRIMARY KEY,
                object_keys_json VARCHAR NOT NULL,
                observation_keys_json VARCHAR NOT NULL,
                occurrence_keys_json VARCHAR NOT NULL,
                landing_keys_json VARCHAR NOT NULL,
                object_count BIGINT NOT NULL,
                observation_count BIGINT NOT NULL,
                occurrence_count BIGINT NOT NULL,
                landing_count BIGINT NOT NULL,
                object_inventory_sha256 VARCHAR NOT NULL,
                observation_inventory_sha256 VARCHAR NOT NULL,
                occurrence_inventory_sha256 VARCHAR NOT NULL,
                landing_inventory_sha256 VARCHAR NOT NULL,
                object_rows_sha256 VARCHAR NOT NULL,
                observation_rows_sha256 VARCHAR NOT NULL,
                occurrence_rows_sha256 VARCHAR NOT NULL,
                landing_rows_sha256 VARCHAR NOT NULL,
                receipt_sha256 VARCHAR NOT NULL
            )
            """
        )
        self._require_bundle_journal()

    def _require_bundle_journal(self) -> None:
        try:
            observed = self._conn.execute(
                f"PRAGMA table_info('{RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL}')"
            ).fetchall()
        except Exception:
            _fail("raw-request authority bundle journal schema drifted")
        expected = (
            ("bundle_sha256", "VARCHAR", True, True),
            ("object_keys_json", "VARCHAR", True, False),
            ("observation_keys_json", "VARCHAR", True, False),
            ("occurrence_keys_json", "VARCHAR", True, False),
            ("landing_keys_json", "VARCHAR", True, False),
            ("object_count", "BIGINT", True, False),
            ("observation_count", "BIGINT", True, False),
            ("occurrence_count", "BIGINT", True, False),
            ("landing_count", "BIGINT", True, False),
            ("object_inventory_sha256", "VARCHAR", True, False),
            ("observation_inventory_sha256", "VARCHAR", True, False),
            ("occurrence_inventory_sha256", "VARCHAR", True, False),
            ("landing_inventory_sha256", "VARCHAR", True, False),
            ("object_rows_sha256", "VARCHAR", True, False),
            ("observation_rows_sha256", "VARCHAR", True, False),
            ("occurrence_rows_sha256", "VARCHAR", True, False),
            ("landing_rows_sha256", "VARCHAR", True, False),
            ("receipt_sha256", "VARCHAR", True, False),
        )
        observed_contract = tuple(
            (str(row[1]), str(row[2]).upper(), bool(row[3]), bool(row[5])) for row in observed
        )
        if observed_contract != expected:
            raise RawRequestAuthorityPersistenceError(
                "raw-request authority bundle journal schema drifted"
            )

    def _ensure_manifest_journal(self) -> None:
        journal = _quote_identifier(RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL)
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {journal} (
                manifest_sha256 VARCHAR PRIMARY KEY,
                operation_sha256 VARCHAR NOT NULL UNIQUE,
                operation_json VARCHAR NOT NULL,
                source_sha VARCHAR NOT NULL,
                run_id BIGINT NOT NULL,
                run_attempt BIGINT NOT NULL,
                chain_id VARCHAR NOT NULL,
                lane_id VARCHAR NOT NULL,
                scope_sha256 VARCHAR NOT NULL,
                generation BIGINT NOT NULL,
                parent_manifest_sha256 VARCHAR,
                route_authority_sha256 VARCHAR NOT NULL,
                request_closure_authority_sha256 VARCHAR NOT NULL,
                field_authority_sha256 VARCHAR NOT NULL,
                model_authority_sha256 VARCHAR NOT NULL,
                authority_set_sha256 VARCHAR NOT NULL,
                receipt_count BIGINT NOT NULL,
                receipt_inventory_sha256 VARCHAR NOT NULL,
                canonical_json VARCHAR NOT NULL
            )
            """
        )
        observed = self._conn.execute(
            f"PRAGMA table_info('{RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL}')"
        ).fetchall()
        expected = (
            ("manifest_sha256", "VARCHAR", True, True),
            ("operation_sha256", "VARCHAR", True, False),
            ("operation_json", "VARCHAR", True, False),
            ("source_sha", "VARCHAR", True, False),
            ("run_id", "BIGINT", True, False),
            ("run_attempt", "BIGINT", True, False),
            ("chain_id", "VARCHAR", True, False),
            ("lane_id", "VARCHAR", True, False),
            ("scope_sha256", "VARCHAR", True, False),
            ("generation", "BIGINT", True, False),
            ("parent_manifest_sha256", "VARCHAR", False, False),
            ("route_authority_sha256", "VARCHAR", True, False),
            ("request_closure_authority_sha256", "VARCHAR", True, False),
            ("field_authority_sha256", "VARCHAR", True, False),
            ("model_authority_sha256", "VARCHAR", True, False),
            ("authority_set_sha256", "VARCHAR", True, False),
            ("receipt_count", "BIGINT", True, False),
            ("receipt_inventory_sha256", "VARCHAR", True, False),
            ("canonical_json", "VARCHAR", True, False),
        )
        observed_contract = tuple(
            (str(row[1]), str(row[2]).upper(), bool(row[3]), bool(row[5])) for row in observed
        )
        if observed_contract != expected:
            raise RawRequestAuthorityPersistenceError(
                "raw-request authority manifest journal schema drifted"
            )

    @staticmethod
    def _manifest_identity_values(
        authority: RawRequestManifestAuthorityV2,
    ) -> tuple[object, ...]:
        return (
            authority.source_sha,
            authority.run_id,
            authority.run_attempt,
            authority.chain_id,
            authority.lane_id,
            authority.scope_sha256,
            authority.route_authority_sha256,
            authority.request_closure_authority_sha256,
            authority.field_authority_sha256,
            authority.model_authority_sha256,
            authority.expected_calls,
        )

    def _manifest_rows_for_execution(
        self,
        authority: RawRequestManifestAuthorityV2,
    ) -> tuple[tuple[object, ...], ...]:
        rows = self._conn.execute(
            f"""
            SELECT manifest_sha256,
                   operation_sha256,
                   operation_json,
                   source_sha,
                   run_id,
                   run_attempt,
                   chain_id,
                   lane_id,
                   scope_sha256,
                   generation,
                   parent_manifest_sha256,
                   route_authority_sha256,
                   request_closure_authority_sha256,
                   field_authority_sha256,
                   model_authority_sha256,
                   authority_set_sha256,
                   receipt_count,
                   receipt_inventory_sha256,
                   canonical_json
            FROM {_quote_identifier(RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL)}
            WHERE source_sha = ?
              AND run_id = ?
              AND run_attempt = ?
              AND chain_id = ?
              AND lane_id = ?
            ORDER BY generation, manifest_sha256
            """,
            [
                authority.source_sha,
                authority.run_id,
                authority.run_attempt,
                authority.chain_id,
                authority.lane_id,
            ],
        ).fetchall()
        return tuple(tuple(row) for row in rows)

    @staticmethod
    def _manifest_matches_authority(
        manifest: RawRequestAuthorityManifestV2,
        authority: RawRequestManifestAuthorityV2,
    ) -> bool:
        return (
            manifest.source_sha,
            manifest.run_id,
            manifest.run_attempt,
            manifest.chain_id,
            manifest.lane_id,
            manifest.scope_sha256,
            manifest.route_authority_sha256,
            manifest.request_closure_authority_sha256,
            manifest.field_authority_sha256,
            manifest.model_authority_sha256,
            manifest.expected_calls,
        ) == RawRequestAuthorityStore._manifest_identity_values(authority)

    @staticmethod
    def _manifest_operation(
        authority: RawRequestManifestAuthorityV2,
        receipts: tuple[RawRequestAuthorityPersistenceReceiptV2, ...],
        *,
        terminal: bool,
    ) -> tuple[str, str]:
        payload = {
            "schema_version": 2,
            "kind": "nbadb_raw_request_manifest_operation_v2",
            "authority": authority.to_dict(),
            "receipt_sha256s": sorted(item.receipt_sha256 for item in receipts),
            "terminal": terminal,
        }
        canonical_json = _canonical_bytes(payload).decode("utf-8")
        return _sha256(payload), canonical_json

    @staticmethod
    def _parse_manifest_operation(
        operation_sha256: object,
        operation_json: object,
        authority: RawRequestManifestAuthorityV2,
    ) -> tuple[tuple[str, ...], bool]:
        _require_sha256(operation_sha256, field_name="operation_sha256")
        if type(operation_json) is not str:
            _fail("raw-request manifest operation is not exact JSON text")
        try:
            payload = json.loads(operation_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise RawRequestAuthorityPersistenceError(
                "raw-request manifest operation is not JSON"
            ) from exc
        if (
            type(payload) is not dict
            or set(payload)
            != {
                "schema_version",
                "kind",
                "authority",
                "receipt_sha256s",
                "terminal",
            }
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 2
            or type(payload["kind"]) is not str
            or payload["kind"] != "nbadb_raw_request_manifest_operation_v2"
            or type(payload["terminal"]) is not bool
        ):
            _fail("raw-request manifest operation authority is invalid")
        receipt_sha256s = payload["receipt_sha256s"]
        if (
            type(receipt_sha256s) is not list
            or any(
                type(item) is not str or _SHA256_RE.fullmatch(item) is None
                for item in receipt_sha256s
            )
            or receipt_sha256s != sorted(receipt_sha256s)
            or len(set(receipt_sha256s)) != len(receipt_sha256s)
        ):
            _fail("raw-request manifest operation receipt inventory is invalid")
        expected_payload = {
            "schema_version": 2,
            "kind": "nbadb_raw_request_manifest_operation_v2",
            "authority": authority.to_dict(),
            "receipt_sha256s": receipt_sha256s,
            "terminal": payload["terminal"],
        }
        if operation_json != _canonical_bytes(expected_payload).decode(
            "utf-8"
        ) or operation_sha256 != _sha256(expected_payload):
            _fail("raw-request manifest operation digest differs from canonical bytes")
        return tuple(receipt_sha256s), payload["terminal"]

    @staticmethod
    def _decode_inventory(
        encoded: object,
        *,
        count: int,
        digest: str,
        label: str,
        ordered: bool = False,
    ) -> tuple[str, ...]:
        if type(encoded) is not str:
            _fail(f"{label} persisted inventory is not exact JSON text")
        try:
            decoded = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise RawRequestAuthorityPersistenceError(
                f"{label} persisted inventory is not JSON"
            ) from exc
        if not isinstance(decoded, list) or any(
            type(item) is not str or _SHA256_RE.fullmatch(item) is None for item in decoded
        ):
            _fail(f"{label} persisted inventory is invalid")
        inventory = cast("tuple[str, ...]", tuple(decoded))
        expected_json, expected_digest = (
            _canonical_ordered_inventory(inventory) if ordered else _canonical_inventory(inventory)
        )
        if encoded != expected_json or len(inventory) != count or digest != expected_digest:
            _fail(f"{label} persisted inventory differs from its receipt")
        return inventory

    def _verify_persisted_receipt(
        self,
        receipt: RawRequestAuthorityPersistenceReceiptV2,
        authority: RawRequestManifestAuthorityV2,
    ) -> RawRequestAuthorityBundleV2:
        for contract in self._public_table_contracts():
            self._require_public_table(contract)
        row = self._existing_journal_row(receipt.bundle_sha256)
        if row is None or len(row) != 18:
            _fail("raw-request manifest receipt lacks one persisted bundle journal row")
        expected_tail = (
            receipt.object_count,
            receipt.observation_count,
            receipt.occurrence_count,
            receipt.landing_count,
            receipt.object_inventory_sha256,
            receipt.observation_inventory_sha256,
            receipt.occurrence_inventory_sha256,
            receipt.landing_inventory_sha256,
            receipt.object_rows_sha256,
            receipt.observation_rows_sha256,
            receipt.occurrence_rows_sha256,
            receipt.landing_rows_sha256,
            receipt.receipt_sha256,
        )
        if row[0] != receipt.bundle_sha256 or tuple(row[5:]) != expected_tail:
            _fail("raw-request manifest receipt differs from persisted bundle authority")
        object_ids = self._decode_inventory(
            row[1],
            count=receipt.object_count,
            digest=receipt.object_inventory_sha256,
            label="object",
        )
        observation_ids = self._decode_inventory(
            row[2],
            count=receipt.observation_count,
            digest=receipt.observation_inventory_sha256,
            label="observation",
        )
        occurrence_ids = self._decode_inventory(
            row[3],
            count=receipt.occurrence_count,
            digest=receipt.occurrence_inventory_sha256,
            label="occurrence",
        )
        landing_ids = self._decode_inventory(
            row[4],
            count=receipt.landing_count,
            digest=receipt.landing_inventory_sha256,
            label="landing",
            ordered=True,
        )
        if not observation_ids:
            _fail("raw-request manifest refuses an empty observation receipt")

        object_rows = self._load_exact_rows(
            table_name=RAW_REQUEST_AUTHORITY_TABLES[0],
            key_column="object_sha256",
            identities=object_ids,
            schema_type=RawNbaApiParserInputObjectSchema,
            label="object",
        )
        observation_rows = self._load_exact_rows(
            table_name=RAW_REQUEST_AUTHORITY_TABLES[1],
            key_column="observation_sha256",
            identities=observation_ids,
            schema_type=RawNbaApiRequestObservationSchema,
            label="observation",
        )
        occurrence_rows = self._load_exact_rows(
            table_name=RAW_REQUEST_AUTHORITY_TABLES[2],
            key_column="occurrence_sha256",
            identities=occurrence_ids,
            schema_type=RawNbaApiResultOccurrenceSchema,
            label="occurrence",
        )
        landing_rows = self._load_exact_rows(
            table_name=RAW_REQUEST_AUTHORITY_TABLES[3],
            key_column="landing_sha256",
            identities=landing_ids,
            schema_type=RawNbaApiObservationRouteLandingSchema,
            label="landing",
        )
        try:
            objects = tuple(validate_parser_input_object(item) for item in object_rows)
            observations = tuple(self._observation_from_row(item) for item in observation_rows)
            occurrences = tuple(validate_result_occurrence(item) for item in occurrence_rows)
            landings = tuple(self._landing_from_row(item) for item in landing_rows)
            rebuilt = RawRequestAuthorityBundleV2.build(
                objects=objects,
                observations=observations,
                occurrences=occurrences,
                landings=landings,
            )
        except Exception as exc:
            raise RawRequestAuthorityPersistenceError(
                "raw-request manifest receipt rows failed strict reconstruction"
            ) from exc
        expected_execution = (
            authority.source_sha,
            authority.run_id,
            authority.run_attempt,
            authority.chain_id,
            authority.lane_id,
        )
        if any(
            (
                item.attempt.source_sha,
                item.attempt.run_id,
                item.attempt.run_attempt,
                item.attempt.chain_id,
                item.attempt.lane_id,
            )
            != expected_execution
            for item in rebuilt.observations
        ):
            _fail("raw-request manifest receipt has foreign execution authority")
        journal_payload, rebuilt_receipt = self._journal_payload(rebuilt)
        if rebuilt.bundle_sha256 != receipt.bundle_sha256:
            _fail("raw-request manifest receipt bundle differs after reconstruction")
        if (
            rebuilt_receipt.receipt_sha256 != receipt.receipt_sha256
            or rebuilt_receipt._semantic_payload() != receipt._semantic_payload()
            or tuple(journal_payload.values()) != tuple(row)
        ):
            _fail("raw-request manifest receipt differs from exact reconstructed rows")
        return rebuilt

    def verify_persisted_receipt(
        self,
        *,
        expected_bundle_sha256: object,
        expected_receipt_sha256: object,
    ) -> RawRequestAuthorityBundleV2:
        """Read-only reconstruct one exact persisted Raw Authority V2 bundle.

        Both external pins are validated before database access.  The method
        requires the fixed four public schemas and private bundle-journal
        schema, reconstructs every row named by that journal, and independently
        recomputes the bundle and persistence receipt.  It never creates a
        table, begins a transaction, or accepts a caller-owned transaction.
        """

        bundle_pin = _require_sha256(
            expected_bundle_sha256,
            field_name="expected_bundle_sha256",
        )
        receipt_pin = _require_sha256(
            expected_receipt_sha256,
            field_name="expected_receipt_sha256",
        )
        self._require_usable()
        with _WRITE_LOCK:
            self._require_usable()
            self._require_no_caller_transaction()
            try:
                for contract in self._public_table_contracts():
                    self._require_public_table(contract)
                self._require_bundle_journal()
                row = self._existing_journal_row(bundle_pin)
                if row is None or len(row) != 18:
                    _fail("raw-request durable receipt lacks one exact bundle journal row")
                counts = tuple(row[index] for index in range(5, 9))
                if any(
                    type(value) is not int or value < 0 or value > 2**63 - 1 for value in counts
                ):
                    _fail("raw-request durable receipt has invalid persisted row counts")
                digests = tuple(row[index] for index in range(9, 18))
                if any(
                    type(value) is not str or _SHA256_RE.fullmatch(value) is None
                    for value in digests
                ):
                    _fail("raw-request durable receipt has invalid persisted digests")

                object_ids = self._decode_inventory(
                    row[1],
                    count=cast("int", counts[0]),
                    digest=cast("str", row[9]),
                    label="object",
                )
                observation_ids = self._decode_inventory(
                    row[2],
                    count=cast("int", counts[1]),
                    digest=cast("str", row[10]),
                    label="observation",
                )
                occurrence_ids = self._decode_inventory(
                    row[3],
                    count=cast("int", counts[2]),
                    digest=cast("str", row[11]),
                    label="occurrence",
                )
                landing_ids = self._decode_inventory(
                    row[4],
                    count=cast("int", counts[3]),
                    digest=cast("str", row[12]),
                    label="landing",
                    ordered=True,
                )
                if not observation_ids:
                    _fail("raw-request durable receipt refuses an empty observation inventory")

                object_rows = self._load_exact_rows(
                    table_name=RAW_REQUEST_AUTHORITY_TABLES[0],
                    key_column="object_sha256",
                    identities=object_ids,
                    schema_type=RawNbaApiParserInputObjectSchema,
                    label="object",
                )
                observation_rows = self._load_exact_rows(
                    table_name=RAW_REQUEST_AUTHORITY_TABLES[1],
                    key_column="observation_sha256",
                    identities=observation_ids,
                    schema_type=RawNbaApiRequestObservationSchema,
                    label="observation",
                )
                occurrence_rows = self._load_exact_rows(
                    table_name=RAW_REQUEST_AUTHORITY_TABLES[2],
                    key_column="occurrence_sha256",
                    identities=occurrence_ids,
                    schema_type=RawNbaApiResultOccurrenceSchema,
                    label="occurrence",
                )
                landing_rows = self._load_exact_rows(
                    table_name=RAW_REQUEST_AUTHORITY_TABLES[3],
                    key_column="landing_sha256",
                    identities=landing_ids,
                    schema_type=RawNbaApiObservationRouteLandingSchema,
                    label="landing",
                )
                rebuilt = RawRequestAuthorityBundleV2.build(
                    objects=tuple(validate_parser_input_object(item) for item in object_rows),
                    observations=tuple(
                        self._observation_from_row(item) for item in observation_rows
                    ),
                    occurrences=tuple(validate_result_occurrence(item) for item in occurrence_rows),
                    landings=tuple(self._landing_from_row(item) for item in landing_rows),
                )
                journal_payload, receipt = self._journal_payload(rebuilt)
            except RawRequestAuthorityPersistenceError:
                raise
            except Exception:
                _fail("raw-request durable receipt verification failed")
            if (
                rebuilt.bundle_sha256 != bundle_pin
                or receipt.receipt_sha256 != receipt_pin
                or tuple(journal_payload.values()) != tuple(row)
            ):
                _fail("raw-request durable receipt differs from exact reconstructed rows")
            return rebuilt

    def _load_exact_rows(
        self,
        *,
        table_name: str,
        key_column: str,
        identities: tuple[str, ...],
        schema_type: type[pa.DataFrameModel],
        label: str,
    ) -> tuple[dict[str, object], ...]:
        if not identities:
            return ()
        columns = tuple(schema_type.to_schema().columns)
        select_columns = ", ".join(
            (
                f"epoch_us(stored.{_quote_identifier(item)}) AS {_quote_identifier(item)}"
                if (label == "observation" and item in {"started_at", "finished_at"})
                or (label == "landing" and item == "live_snapshot_at")
                else f"stored.{_quote_identifier(item)}"
            )
            for item in columns
        )
        rows = self._conn.execute(
            f"""
            SELECT {select_columns}
            FROM {_quote_identifier(table_name)} AS stored
            INNER JOIN UNNEST(?) WITH ORDINALITY AS expected(key_value, inventory_ordinal)
              ON stored.{_quote_identifier(key_column)} = expected.key_value
            ORDER BY expected.inventory_ordinal
            """,
            [list(identities)],
        ).fetchall()
        if len(rows) != len(identities):
            _fail(f"raw-request manifest receipt is missing persisted {label} inventory")
        materialized = tuple(
            dict(zip(columns, cast("tuple[object, ...]", tuple(row)), strict=True)) for row in rows
        )
        if tuple(cast("str", item[key_column]) for item in materialized) != identities:
            _fail(f"raw-request manifest receipt {label} inventory is not exact")
        return materialized

    @staticmethod
    def _observation_from_row(row: Mapping[str, object]) -> RequestObservationV2:
        materialized = dict(row)
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        for field_name in ("started_at", "finished_at"):
            epoch_us = materialized[field_name]
            if epoch_us is not None:
                if type(epoch_us) is not int:
                    _fail("raw-request observation timestamp is not an exact epoch integer")
                materialized[field_name] = epoch + timedelta(microseconds=epoch_us)
        attempt_fields = tuple(RequestAttemptIdentityV2.model_fields)
        observation_fields = tuple(RequestObservationV2.model_fields)
        attempt = validate_request_attempt_identity(
            {name: materialized[name] for name in attempt_fields}
        )
        transport_kind = materialized["transport_kind"]
        if transport_kind == "static_snapshot":
            transport: dict[str, object] = {"transport_kind": transport_kind}
        else:
            transport = {
                "transport_kind": transport_kind,
                "status_code": materialized["status_code"],
                "effective_status_code": materialized["effective_status_code"],
            }
        payload = {
            name: materialized[name]
            for name in observation_fields
            if name not in {"attempt", "transport"}
        }
        payload["attempt"] = attempt
        payload["transport"] = transport
        return validate_request_observation(payload)

    @staticmethod
    def _landing_from_row(row: Mapping[str, object]) -> ObservationRouteLandingV2:
        materialized = dict(row)
        epoch_us = materialized["live_snapshot_at"]
        if epoch_us is not None:
            if type(epoch_us) is not int:
                _fail("raw-request landing timestamp is not an exact epoch integer")
            materialized["live_snapshot_at"] = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                microseconds=epoch_us
            )
        return validate_observation_route_landing(materialized)

    def _verify_inventory_presence(
        self,
        *,
        table_name: str,
        key_column: str,
        identities: tuple[str, ...],
        label: str,
    ) -> None:
        if not identities:
            return
        view_name = f"_nbadb_expected_raw_manifest_{label}s"
        self._conn.register(view_name, pl.DataFrame({key_column: identities}))
        try:
            observed = self._conn.execute(
                f"""
                SELECT stored.{_quote_identifier(key_column)}
                FROM {_quote_identifier(table_name)} AS stored
                INNER JOIN {_quote_identifier(view_name)} AS expected
                  ON stored.{_quote_identifier(key_column)} =
                     expected.{_quote_identifier(key_column)}
                ORDER BY stored.{_quote_identifier(key_column)}
                """
            ).fetchall()
        finally:
            self._conn.unregister(view_name)
        if tuple(str(item[0]) for item in observed) != identities:
            _fail(f"raw-request manifest receipt is missing persisted {label} inventory")

    def _load_manifest_chain(
        self,
        authority: RawRequestManifestAuthorityV2,
    ) -> tuple[RawRequestAuthorityManifestV2, ...]:
        from nbadb.orchestrate.raw_request_manifest import (
            RawRequestAuthorityManifestV2,
            parse_raw_request_authority_manifest,
            validate_raw_request_authority_manifest_roll_forward,
        )

        rows = self._manifest_rows_for_execution(authority)
        manifests: list[RawRequestAuthorityManifestV2] = []
        operation_sha256s: set[str] = set()
        for expected_generation, row in enumerate(rows):
            if len(row) != 19 or type(row[18]) is not str:
                _fail("raw-request manifest journal row is malformed")
            manifest = parse_raw_request_authority_manifest(row[18].encode("utf-8"))
            projected = (
                manifest.manifest_sha256,
                row[1],
                row[2],
                manifest.source_sha,
                manifest.run_id,
                manifest.run_attempt,
                manifest.chain_id,
                manifest.lane_id,
                manifest.scope_sha256,
                manifest.generation,
                manifest.parent_manifest_sha256,
                manifest.route_authority_sha256,
                manifest.request_closure_authority_sha256,
                manifest.field_authority_sha256,
                manifest.model_authority_sha256,
                manifest.authority_set_sha256,
                manifest.receipt_count,
                manifest.receipt_inventory_sha256,
                manifest.canonical_bytes.decode("utf-8"),
            )
            if tuple(row) != projected:
                _fail("raw-request manifest journal columns differ from canonical bytes")
            if not self._manifest_matches_authority(manifest, authority):
                _fail("raw-request manifest journal contains foreign authority")
            if manifest.generation != expected_generation:
                _fail("raw-request manifest journal generation chain is not contiguous")
            if manifests:
                validate_raw_request_authority_manifest_roll_forward(manifests[-1], manifest)
            operation_receipt_ids, operation_terminal = self._parse_manifest_operation(
                row[1], row[2], authority
            )
            operation_sha256 = cast("str", row[1])
            if operation_sha256 in operation_sha256s:
                _fail("raw-request manifest operation identity is duplicated")
            operation_sha256s.add(operation_sha256)
            receipts_by_sha256 = {item.receipt_sha256: item for item in manifest.receipts}
            if any(item not in receipts_by_sha256 for item in operation_receipt_ids):
                _fail("raw-request manifest operation references an absent receipt")
            operation_receipts = tuple(receipts_by_sha256[item] for item in operation_receipt_ids)
            if manifests:
                parent = manifests[-1]
                parent_ids = {item.receipt_sha256 for item in parent.receipts}
                operation_delta = tuple(
                    item for item in operation_receipts if item.receipt_sha256 not in parent_ids
                )
                expected_manifest = parent.roll_forward(
                    operation_delta,
                    source_sha=authority.source_sha,
                    run_id=authority.run_id,
                    run_attempt=authority.run_attempt,
                    chain_id=authority.chain_id,
                    lane_id=authority.lane_id,
                    scope_sha256=authority.scope_sha256,
                    route_authority_sha256=authority.route_authority_sha256,
                    request_closure_authority_sha256=(authority.request_closure_authority_sha256),
                    field_authority_sha256=authority.field_authority_sha256,
                    model_authority_sha256=authority.model_authority_sha256,
                    terminal=operation_terminal or parent.terminal_sealed,
                )
            else:
                expected_manifest = RawRequestAuthorityManifestV2.seal(
                    source_sha=authority.source_sha,
                    run_id=authority.run_id,
                    run_attempt=authority.run_attempt,
                    chain_id=authority.chain_id,
                    lane_id=authority.lane_id,
                    scope_sha256=authority.scope_sha256,
                    route_authority_sha256=authority.route_authority_sha256,
                    request_closure_authority_sha256=(authority.request_closure_authority_sha256),
                    field_authority_sha256=authority.field_authority_sha256,
                    model_authority_sha256=authority.model_authority_sha256,
                    expected_calls=authority.expected_calls,
                    receipts=operation_receipts,
                    terminal=operation_terminal,
                )
            if expected_manifest != manifest:
                _fail("raw-request manifest operation does not derive its stored generation")
            manifests.append(manifest)
        if manifests:
            for receipt in manifests[-1].receipts:
                self._verify_persisted_receipt(receipt, authority)
        return tuple(manifests)

    def _insert_manifest(
        self,
        manifest: RawRequestAuthorityManifestV2,
        *,
        operation_sha256: str,
        operation_json: str,
    ) -> None:
        payload = (
            manifest.manifest_sha256,
            operation_sha256,
            operation_json,
            manifest.source_sha,
            manifest.run_id,
            manifest.run_attempt,
            manifest.chain_id,
            manifest.lane_id,
            manifest.scope_sha256,
            manifest.generation,
            manifest.parent_manifest_sha256,
            manifest.route_authority_sha256,
            manifest.request_closure_authority_sha256,
            manifest.field_authority_sha256,
            manifest.model_authority_sha256,
            manifest.authority_set_sha256,
            manifest.receipt_count,
            manifest.receipt_inventory_sha256,
            manifest.canonical_bytes.decode("utf-8"),
        )
        self._conn.execute(
            f"""
            INSERT INTO {_quote_identifier(RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL)}
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            list(payload),
        )

    def _manifest_for_operation(
        self,
        *,
        operation_sha256: str,
        operation_json: str,
        chain: tuple[RawRequestAuthorityManifestV2, ...],
    ) -> RawRequestAuthorityManifestV2 | None:
        rows = self._conn.execute(
            f"SELECT manifest_sha256, operation_json "
            f"FROM {_quote_identifier(RAW_REQUEST_AUTHORITY_MANIFEST_JOURNAL)} "
            "WHERE operation_sha256 = ?",
            [operation_sha256],
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            _fail("raw-request manifest operation identity is duplicated")
        row = rows[0]
        if len(row) != 2 or row[1] != operation_json:
            _fail("raw-request manifest operation digest collision or relabel")
        matching = tuple(item for item in chain if item.manifest_sha256 == row[0])
        if len(matching) != 1:
            _fail("raw-request manifest operation does not resolve one stored generation")
        return matching[0]

    def advance_manifest(
        self,
        authority: RawRequestManifestAuthorityV2,
        receipts: Sequence[RawRequestAuthorityPersistenceReceiptV2],
        *,
        terminal: bool = False,
    ) -> RawRequestAuthorityManifestV2:
        """Seal or replay one exact root/copy-plus-delta committed operation.

        Repeating an exact operation returns its already committed generation,
        even after later operations advanced the chain.  It never creates a
        diagnostic successor merely because the caller had not observed the
        prior commit result.
        """

        from nbadb.orchestrate.raw_request_manifest import (
            RawRequestAuthorityManifestError,
            RawRequestAuthorityManifestV2,
        )

        self._require_usable()
        authority = validate_raw_request_manifest_authority(authority)
        if type(receipts) is not tuple or any(
            type(item) is not RawRequestAuthorityPersistenceReceiptV2 for item in receipts
        ):
            _fail("raw-request manifest advancement requires exact receipt tuple")
        exact_receipts = cast("tuple[RawRequestAuthorityPersistenceReceiptV2, ...]", receipts)
        if not exact_receipts and not terminal:
            _fail("raw-request manifest advancement requires a receipt or terminal closeout")
        if len({item.receipt_sha256 for item in exact_receipts}) != len(exact_receipts):
            _fail("raw-request manifest advancement contains duplicate receipts")
        if type(terminal) is not bool:
            _fail("raw-request manifest terminal mode must be an exact boolean")

        with _WRITE_LOCK:
            self._require_usable()
            transaction_cleanup_needed = False
            commit_attempted = False
            try:
                try:
                    transaction_cleanup_needed = True
                    self._conn.execute("BEGIN TRANSACTION")
                    self._ensure_journal()
                    self._ensure_manifest_journal()
                    chain = self._load_manifest_chain(authority)
                    if not chain and not exact_receipts:
                        _fail("raw-request terminal closeout cannot create an empty root manifest")
                    for receipt in exact_receipts:
                        self._verify_persisted_receipt(receipt, authority)
                    operation_sha256, operation_json = self._manifest_operation(
                        authority, exact_receipts, terminal=terminal
                    )
                    committed_operation = self._manifest_for_operation(
                        operation_sha256=operation_sha256,
                        operation_json=operation_json,
                        chain=chain,
                    )

                    if committed_operation is not None:
                        manifest = committed_operation
                    elif chain:
                        parent = chain[-1]
                        parent_ids = {item.receipt_sha256 for item in parent.receipts}
                        delta = tuple(
                            item for item in exact_receipts if item.receipt_sha256 not in parent_ids
                        )
                        manifest = parent.roll_forward(
                            delta,
                            source_sha=authority.source_sha,
                            run_id=authority.run_id,
                            run_attempt=authority.run_attempt,
                            chain_id=authority.chain_id,
                            lane_id=authority.lane_id,
                            scope_sha256=authority.scope_sha256,
                            route_authority_sha256=authority.route_authority_sha256,
                            request_closure_authority_sha256=(
                                authority.request_closure_authority_sha256
                            ),
                            field_authority_sha256=authority.field_authority_sha256,
                            model_authority_sha256=authority.model_authority_sha256,
                            terminal=terminal or parent.terminal_sealed,
                        )
                    else:
                        manifest = RawRequestAuthorityManifestV2.seal(
                            source_sha=authority.source_sha,
                            run_id=authority.run_id,
                            run_attempt=authority.run_attempt,
                            chain_id=authority.chain_id,
                            lane_id=authority.lane_id,
                            scope_sha256=authority.scope_sha256,
                            route_authority_sha256=authority.route_authority_sha256,
                            request_closure_authority_sha256=(
                                authority.request_closure_authority_sha256
                            ),
                            field_authority_sha256=authority.field_authority_sha256,
                            model_authority_sha256=authority.model_authority_sha256,
                            expected_calls=authority.expected_calls,
                            receipts=exact_receipts,
                            terminal=terminal,
                        )
                    if committed_operation is None:
                        self._insert_manifest(
                            manifest,
                            operation_sha256=operation_sha256,
                            operation_json=operation_json,
                        )

                    def verify_committed_manifest() -> None:
                        observed = self._load_manifest_chain(authority)
                        matching = tuple(
                            item
                            for item in observed
                            if item.manifest_sha256 == manifest.manifest_sha256
                        )
                        replayed = self._manifest_for_operation(
                            operation_sha256=operation_sha256,
                            operation_json=operation_json,
                            chain=observed,
                        )
                        if len(matching) != 1 or replayed != manifest:
                            _fail("raw-request manifest journal readback differs")

                    verify_committed_manifest()
                    commit_attempted = True
                    self._commit_transaction()
                    transaction_cleanup_needed = False
                except RawRequestAuthorityPersistenceError:
                    raise
                except RawRequestAuthorityManifestError as exc:
                    raise RawRequestAuthorityPersistenceError(str(exc)) from exc
                except Exception as exc:
                    raise RawRequestAuthorityPersistenceError(
                        "raw-request manifest transaction failed"
                    ) from exc
            except BaseException as interruption:
                if transaction_cleanup_needed:
                    if commit_attempted:
                        self._resolve_interrupted_commit(
                            interruption,
                            verify_committed=verify_committed_manifest,
                        )
                    elif not self._rollback_preserving(interruption):
                        self._poison_connection(interruption)
                raise
        return manifest

    def _insert_frame(self, contract: _TableContract, frame: pl.DataFrame) -> None:
        if frame.is_empty():
            return
        view_name = f"_nbadb_insert_{contract.table_name}"
        self._conn.register(view_name, frame)
        try:
            self._conn.execute(
                f"INSERT OR IGNORE INTO {_quote_identifier(contract.table_name)} "
                f"SELECT * FROM {_quote_identifier(view_name)}"
            )
        finally:
            self._conn.unregister(view_name)

    def _verify_rows(
        self,
        contract: _TableContract,
        frame: pl.DataFrame,
    ) -> None:
        if frame.is_empty():
            return
        view_name = f"_nbadb_expected_{contract.table_name}"
        self._conn.register(view_name, frame)
        try:
            comparisons = " AND ".join(
                f"stored.{_quote_identifier(name)} "
                f"IS NOT DISTINCT FROM expected.{_quote_identifier(name)}"
                for name in frame.columns
            )
            observed_count = self._conn.execute(
                "SELECT COUNT(*) "
                f"FROM {_quote_identifier(contract.table_name)} AS stored "
                f"INNER JOIN {_quote_identifier(view_name)} AS expected "
                f"ON stored.{_quote_identifier(contract.key_column)} = "
                f"expected.{_quote_identifier(contract.key_column)} "
                f"WHERE {comparisons}"
            ).fetchone()
        finally:
            self._conn.unregister(view_name)
        if observed_count is None or observed_count[0] != frame.height:
            raise RawRequestAuthorityPersistenceError(
                f"public raw table readback differs: {contract.table_name}"
            )

    @staticmethod
    def _journal_payload(
        bundle: RawRequestAuthorityBundleV2,
    ) -> tuple[dict[str, object], RawRequestAuthorityPersistenceReceiptV2]:
        object_keys_json, object_inventory_sha256 = _canonical_inventory(
            tuple(item.object_sha256 for item in bundle.objects)
        )
        observation_keys_json, observation_inventory_sha256 = _canonical_inventory(
            tuple(item.attempt.observation_sha256 for item in bundle.observations)
        )
        occurrence_keys_json, occurrence_inventory_sha256 = _canonical_inventory(
            tuple(item.occurrence_sha256 for item in bundle.occurrences)
        )
        landing_keys_json, landing_inventory_sha256 = _canonical_ordered_inventory(
            tuple(item.landing_sha256 for item in bundle.landings)
        )
        object_rows_sha256 = _canonical_row_inventory(
            tuple(item.object_sha256 for item in bundle.objects),
            tuple(item.to_canonical_bytes() for item in bundle.objects),
        )
        observation_rows_sha256 = _canonical_row_inventory(
            tuple(item.attempt.observation_sha256 for item in bundle.observations),
            tuple(item.to_canonical_bytes() for item in bundle.observations),
        )
        occurrence_rows_sha256 = _canonical_row_inventory(
            tuple(item.occurrence_sha256 for item in bundle.occurrences),
            tuple(item.to_canonical_bytes() for item in bundle.occurrences),
        )
        landing_rows_sha256 = _canonical_row_inventory(
            tuple(item.landing_sha256 for item in bundle.landings),
            tuple(item.to_canonical_bytes() for item in bundle.landings),
        )
        attempts = _attempt_receipts(bundle)
        receipt = RawRequestAuthorityPersistenceReceiptV2(
            bundle_sha256=bundle.bundle_sha256,
            object_count=len(bundle.objects),
            observation_count=len(bundle.observations),
            occurrence_count=len(bundle.occurrences),
            landing_count=len(bundle.landings),
            object_inventory_sha256=object_inventory_sha256,
            observation_inventory_sha256=observation_inventory_sha256,
            occurrence_inventory_sha256=occurrence_inventory_sha256,
            landing_inventory_sha256=landing_inventory_sha256,
            object_rows_sha256=object_rows_sha256,
            observation_rows_sha256=observation_rows_sha256,
            occurrence_rows_sha256=occurrence_rows_sha256,
            landing_rows_sha256=landing_rows_sha256,
            attempts=attempts,
            attempt_count=len(attempts),
            attempt_inventory_sha256=_sha256([item.to_dict() for item in attempts]),
            replayed=False,
        )
        payload = {
            "bundle_sha256": bundle.bundle_sha256,
            "object_keys_json": object_keys_json,
            "observation_keys_json": observation_keys_json,
            "occurrence_keys_json": occurrence_keys_json,
            "landing_keys_json": landing_keys_json,
            "object_count": len(bundle.objects),
            "observation_count": len(bundle.observations),
            "occurrence_count": len(bundle.occurrences),
            "landing_count": len(bundle.landings),
            "object_inventory_sha256": object_inventory_sha256,
            "observation_inventory_sha256": observation_inventory_sha256,
            "occurrence_inventory_sha256": occurrence_inventory_sha256,
            "landing_inventory_sha256": landing_inventory_sha256,
            "object_rows_sha256": object_rows_sha256,
            "observation_rows_sha256": observation_rows_sha256,
            "occurrence_rows_sha256": occurrence_rows_sha256,
            "landing_rows_sha256": landing_rows_sha256,
            "receipt_sha256": receipt.receipt_sha256,
        }
        return payload, receipt

    def _existing_journal_row(self, bundle_sha256: str) -> tuple[object, ...] | None:
        return self._conn.execute(
            f"SELECT * FROM {_quote_identifier(RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL)} "
            "WHERE bundle_sha256 = ?",
            [bundle_sha256],
        ).fetchone()

    def _insert_journal_row(self, payload: Mapping[str, object]) -> None:
        columns = tuple(payload)
        placeholders = ", ".join("?" for _ in columns)
        self._conn.execute(
            f"INSERT OR IGNORE INTO {_quote_identifier(RAW_REQUEST_AUTHORITY_BUNDLE_JOURNAL)} "
            f"({', '.join(_quote_identifier(column) for column in columns)}) "
            f"VALUES ({placeholders})",
            [payload[column] for column in columns],
        )

    def persist_bundle(
        self,
        bundle: RawRequestAuthorityBundleV2,
    ) -> RawRequestAuthorityPersistenceReceiptV2:
        """Validate, atomically persist, and read back one authority bundle.

        Replaying the same bundle is a successful no-op only when every public
        row and the private bundle journal remain byte/field identical.  A key
        collision, partial journal, schema drift, or changed row rolls back the
        whole call and raises.
        """

        self._require_usable()
        try:
            parsed = validate_raw_request_authority_bundle(bundle)
        except Exception as exc:
            raise RawRequestAuthorityPersistenceError(
                "raw-request persistence requires a closed validated bundle"
            ) from exc
        if not parsed.observations:
            raise RawRequestAuthorityPersistenceError(
                "raw-request persistence refuses an empty observation bundle"
            )
        contracts = self._table_contracts(parsed)
        frames = tuple(
            _frame_for_rows(contract.rows, contract.schema_type) for contract in contracts
        )
        journal_payload, base_receipt = self._journal_payload(parsed)

        with _WRITE_LOCK:
            self._require_usable()
            transaction_cleanup_needed = False
            commit_attempted = False
            try:
                try:
                    transaction_cleanup_needed = True
                    self._conn.execute("BEGIN TRANSACTION")
                    for contract in contracts:
                        self._ensure_public_table(contract)
                    self._ensure_journal()
                    replayed = self._existing_journal_row(parsed.bundle_sha256) is not None
                    if replayed:
                        for contract, frame in zip(contracts, frames, strict=True):
                            self._verify_rows(contract, frame)
                    for contract, frame in zip(contracts, frames, strict=True):
                        self._insert_frame(contract, frame)
                        self._verify_rows(contract, frame)
                    self._insert_journal_row(journal_payload)
                    observed_journal = self._existing_journal_row(parsed.bundle_sha256)
                    expected_journal = tuple(journal_payload.values())
                    if observed_journal != expected_journal:
                        raise RawRequestAuthorityPersistenceError(
                            "raw-request authority bundle journal readback differs"
                        )

                    def verify_committed_bundle() -> None:
                        for exact_contract, exact_frame in zip(contracts, frames, strict=True):
                            self._verify_rows(exact_contract, exact_frame)
                        committed_journal = self._existing_journal_row(parsed.bundle_sha256)
                        if committed_journal != expected_journal:
                            raise RawRequestAuthorityPersistenceError(
                                "raw-request authority bundle journal readback differs"
                            )

                    commit_attempted = True
                    self._commit_transaction()
                    transaction_cleanup_needed = False
                except RawRequestAuthorityPersistenceError:
                    raise
                except Exception as exc:
                    raise RawRequestAuthorityPersistenceError(
                        "raw-request authority transaction failed"
                    ) from exc
            except BaseException as interruption:
                if transaction_cleanup_needed:
                    if commit_attempted:
                        self._resolve_interrupted_commit(
                            interruption,
                            verify_committed=verify_committed_bundle,
                        )
                    elif not self._rollback_preserving(interruption):
                        self._poison_connection(interruption)
                raise

        return RawRequestAuthorityPersistenceReceiptV2(
            bundle_sha256=base_receipt.bundle_sha256,
            object_count=base_receipt.object_count,
            observation_count=base_receipt.observation_count,
            occurrence_count=base_receipt.occurrence_count,
            landing_count=base_receipt.landing_count,
            object_inventory_sha256=base_receipt.object_inventory_sha256,
            observation_inventory_sha256=base_receipt.observation_inventory_sha256,
            occurrence_inventory_sha256=base_receipt.occurrence_inventory_sha256,
            landing_inventory_sha256=base_receipt.landing_inventory_sha256,
            object_rows_sha256=base_receipt.object_rows_sha256,
            observation_rows_sha256=base_receipt.observation_rows_sha256,
            occurrence_rows_sha256=base_receipt.occurrence_rows_sha256,
            landing_rows_sha256=base_receipt.landing_rows_sha256,
            attempts=base_receipt.attempts,
            attempt_count=base_receipt.attempt_count,
            attempt_inventory_sha256=base_receipt.attempt_inventory_sha256,
            replayed=replayed,
        )
