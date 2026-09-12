"""Pure checkpoint authority for persisted public raw-request receipts.

The DuckDB store returns one read-after-commit receipt per closed public raw
bundle.  This module seals those exact receipts into a path-free lane manifest
and provides the copy-plus-delta verifier used by later checkpoint integration.
It performs no filesystem, provider, workflow, or network I/O.

``replayed`` is operation diagnostics on the store receipt, not raw authority.
Every manifest normalizes receipts to the replay-independent projection before
computing cumulative, delta, or manifest digests.  A replay therefore cannot
replace, duplicate, or relabel an already committed authority receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import ClassVar, Never, Self, cast

from nbadb.orchestrate.raw_request_store import (
    RawRequestAuthorityPersistenceError,
    RawRequestAuthorityPersistenceReceiptV2,
    RawRequestClosureCallV2,
    RawRequestPersistedAttemptV2,
)

__all__ = [
    "RAW_REQUEST_AUTHORITY_MANIFEST_KIND",
    "RAW_REQUEST_AUTHORITY_MANIFEST_SCHEMA_VERSION",
    "RawRequestAuthorityManifestError",
    "RawRequestAuthorityManifestV2",
    "merge_raw_request_authority_manifest",
    "parse_raw_request_authority_manifest",
    "recompute_raw_request_authority_manifest",
    "validate_raw_request_authority_manifest",
    "validate_raw_request_authority_manifest_roll_forward",
]

RAW_REQUEST_AUTHORITY_MANIFEST_SCHEMA_VERSION = 2
RAW_REQUEST_AUTHORITY_MANIFEST_KIND = "nbadb_raw_request_authority_manifest_v2"
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_MAX_RECEIPTS = 1_000_000
_MAX_COUNTER = 2**63 - 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}\Z")
_FORBIDDEN_IDENTITY_RE = re.compile(
    r"(?:authorization|cookie|credential|header|password|proxy|secret|token|vpn|"
    r"(?:^|[._:-])(?:path|host|ip)(?:$|[._:-]))",
    re.IGNORECASE,
)


class RawRequestAuthorityManifestError(ValueError):
    """A public raw-request manifest is malformed or fails conservation."""


def _fail(message: str) -> Never:
    raise RawRequestAuthorityManifestError(message)


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
        raise RawRequestAuthorityManifestError(
            "raw-request authority manifest is not canonical JSON"
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_git_sha(value: object) -> str:
    if type(value) is not str or _GIT_SHA_RE.fullmatch(value) is None:
        _fail("source_sha must be a lowercase 40-character Git SHA")
    return value


def _require_safe_id(value: object, *, field_name: str) -> str:
    if (
        type(value) is not str
        or _SAFE_ID_RE.fullmatch(value) is None
        or _FORBIDDEN_IDENTITY_RE.search(value) is not None
    ):
        _fail(f"{field_name} must be a public-safe path-free identity")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0 or value > _MAX_COUNTER:
        _fail(f"{field_name} must be a positive bounded integer")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0 or value > _MAX_COUNTER:
        _fail(f"{field_name} must be a nonnegative bounded integer")
    return value


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    observed = frozenset(payload)
    if observed == expected:
        return
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if extra:
        details.append("unexpected=" + ",".join(extra))
    _fail(f"{label} fields are invalid: {'; '.join(details)}")


def _reject_known_secrets(raw: bytes, *, known_secrets: Sequence[str | bytes]) -> None:
    for secret in known_secrets:
        if not isinstance(secret, str | bytes):
            _fail("known_secrets must contain only strings or bytes")
        encoded = secret.encode("utf-8") if isinstance(secret, str) else secret
        if encoded and encoded in raw:
            _fail("raw-request authority manifest contains caller-known secret bytes")


def _strict_receipt(
    value: object,
    *,
    label: str,
) -> RawRequestAuthorityPersistenceReceiptV2:
    if type(value) is not RawRequestAuthorityPersistenceReceiptV2:
        _fail(f"{label} must contain exact persistence receipts")
    receipt = value
    try:
        rebuilt = RawRequestAuthorityPersistenceReceiptV2(
            bundle_sha256=receipt.bundle_sha256,
            object_count=receipt.object_count,
            observation_count=receipt.observation_count,
            occurrence_count=receipt.occurrence_count,
            landing_count=receipt.landing_count,
            object_inventory_sha256=receipt.object_inventory_sha256,
            observation_inventory_sha256=receipt.observation_inventory_sha256,
            occurrence_inventory_sha256=receipt.occurrence_inventory_sha256,
            landing_inventory_sha256=receipt.landing_inventory_sha256,
            object_rows_sha256=receipt.object_rows_sha256,
            observation_rows_sha256=receipt.observation_rows_sha256,
            occurrence_rows_sha256=receipt.occurrence_rows_sha256,
            landing_rows_sha256=receipt.landing_rows_sha256,
            attempts=tuple(_strict_attempt(item, label=label) for item in receipt.attempts),
            attempt_count=receipt.attempt_count,
            attempt_inventory_sha256=receipt.attempt_inventory_sha256,
            replayed=receipt.replayed,
        )
    except (AttributeError, TypeError, RawRequestAuthorityPersistenceError) as exc:
        raise RawRequestAuthorityManifestError(
            f"{label} persistence receipt failed strict reconstruction"
        ) from exc
    if rebuilt.to_dict() != receipt.to_dict():
        _fail(f"{label} persistence receipt changed during reconstruction")
    return rebuilt


def _replay_independent_receipt(
    value: object,
    *,
    label: str,
) -> RawRequestAuthorityPersistenceReceiptV2:
    """Return the sole receipt projection admitted into manifest authority."""

    receipt = _strict_receipt(value, label=label)
    return receipt if not receipt.replayed else replace(receipt, replayed=False)


def _strict_expected_call(value: object, *, label: str) -> RawRequestClosureCallV2:
    if type(value) is not RawRequestClosureCallV2:
        _fail(f"{label} must contain exact closure-call contracts")
    item = value
    try:
        rebuilt = RawRequestClosureCallV2(
            logical_request_sha256=item.logical_request_sha256,
            endpoint_name=item.endpoint_name,
            source_family=item.source_family,
            endpoint_id=item.endpoint_id,
            logical_parameters_sha256=item.logical_parameters_sha256,
            provider_parameters_sha256=item.provider_parameters_sha256,
            provider_request_sha256=item.provider_request_sha256,
            route_ids=item.route_ids,
            scope_sha256=item.scope_sha256,
        )
    except (AttributeError, TypeError, RawRequestAuthorityPersistenceError) as exc:
        raise RawRequestAuthorityManifestError(
            f"{label} closure call failed strict reconstruction"
        ) from exc
    if rebuilt.to_dict() != item.to_dict():
        _fail(f"{label} closure call changed during reconstruction")
    return rebuilt


def _strict_attempt(value: object, *, label: str) -> RawRequestPersistedAttemptV2:
    if type(value) is not RawRequestPersistedAttemptV2:
        _fail(f"{label} must contain exact persisted-attempt contracts")
    item = value
    try:
        rebuilt = RawRequestPersistedAttemptV2(
            observation_sha256=item.observation_sha256,
            observation_record_sha256=item.observation_record_sha256,
            semantic_request_sha256=item.semantic_request_sha256,
            logical_invocation_sha256=item.logical_invocation_sha256,
            provider_call_sha256=item.provider_call_sha256,
            provider_call_role=item.provider_call_role,
            provider_call_ordinal=item.provider_call_ordinal,
            retry_ordinal=item.retry_ordinal,
            request_ordinal=item.request_ordinal,
            source_family=item.source_family,
            endpoint_id=item.endpoint_id,
            provider_request_sha256=item.provider_request_sha256,
            logical_parameters_sha256=item.logical_parameters_sha256,
            safe_parameters_sha256=item.safe_parameters_sha256,
            scope_sha256=item.scope_sha256,
            lifecycle=item.lifecycle,
            outcome=item.outcome,
            route_ids=item.route_ids,
        )
    except (AttributeError, TypeError, RawRequestAuthorityPersistenceError) as exc:
        raise RawRequestAuthorityManifestError(
            f"{label} persisted attempt failed strict reconstruction"
        ) from exc
    if rebuilt.to_dict() != item.to_dict():
        _fail(f"{label} persisted attempt changed during reconstruction")
    return rebuilt


@dataclass(frozen=True, slots=True)
class _ReceiptAggregate:
    receipt_count: int
    object_reference_count: int
    observation_reference_count: int
    occurrence_reference_count: int
    landing_reference_count: int
    receipt_inventory_sha256: str
    bundle_inventory_sha256: str
    object_inventory_sha256: str
    observation_inventory_sha256: str
    occurrence_inventory_sha256: str
    landing_inventory_sha256: str
    object_rows_sha256: str
    observation_rows_sha256: str
    occurrence_rows_sha256: str
    landing_rows_sha256: str


@dataclass(frozen=True, slots=True)
class _DenominatorState:
    expected_request_sha256s: tuple[str, ...]
    completed_request_sha256s: tuple[str, ...]
    unresolved_request_sha256s: tuple[str, ...]
    expected_request_inventory_sha256: str
    completed_request_inventory_sha256: str
    unresolved_request_inventory_sha256: str
    coverage_complete: bool


def _denominator_state(
    expected_calls: Sequence[RawRequestClosureCallV2],
    receipts: Sequence[RawRequestAuthorityPersistenceReceiptV2],
) -> _DenominatorState:
    expected = tuple(_strict_expected_call(item, label="expected calls") for item in expected_calls)
    if not expected:
        _fail("raw-request manifest requires a nonempty closure denominator")
    if expected != tuple(sorted(expected, key=lambda item: item.logical_request_sha256)):
        _fail("expected calls must use canonical logical-request order")
    logical_ids = tuple(item.logical_request_sha256 for item in expected)
    provider_ids = tuple(item.provider_request_sha256 for item in expected)
    if len(logical_ids) != len(set(logical_ids)) or len(provider_ids) != len(set(provider_ids)):
        _fail("expected calls must bijectively identify logical and provider requests")
    expected_by_provider = {item.provider_request_sha256: item for item in expected}

    attempts: list[RawRequestPersistedAttemptV2] = []
    for receipt in receipts:
        attempts.extend(
            _strict_attempt(item, label="manifest receipt attempts") for item in receipt.attempts
        )
    attempt_ids = [item.attempt_receipt_sha256 for item in attempts]
    observation_ids = [item.observation_sha256 for item in attempts]
    if len(attempt_ids) != len(set(attempt_ids)) or len(observation_ids) != len(
        set(observation_ids)
    ):
        _fail("cumulative receipt attempts contain duplicate identities")

    by_provider: defaultdict[str, list[RawRequestPersistedAttemptV2]] = defaultdict(list)
    for attempt in attempts:
        call = expected_by_provider.get(attempt.provider_request_sha256)
        if call is None:
            _fail("persisted observation is outside the exact closure denominator")
        if call.provider_parameters_sha256 is None:
            _fail("exact closure call lacks provider parameter authority")
        expected_logical_parameters_sha256 = (
            call.logical_parameters_sha256
            if attempt.lifecycle == "selected_terminal"
            else call.provider_parameters_sha256
        )
        if (
            attempt.source_family != call.source_family
            or attempt.endpoint_id != call.endpoint_id
            or attempt.logical_parameters_sha256 != expected_logical_parameters_sha256
            or attempt.safe_parameters_sha256 != call.provider_parameters_sha256
            or attempt.scope_sha256 != call.scope_sha256
        ):
            _fail("persisted observation differs from its exact closure call")
        expected_role = "static_snapshot" if call.source_family == "static" else "primary"
        if (
            attempt.provider_call_role != expected_role
            or attempt.provider_call_ordinal != 0
            or attempt.request_ordinal != 0
        ):
            _fail("persisted observation adds an unplanned provider-call shape")
        if attempt.lifecycle == "selected_terminal":
            try:
                call.validate_terminal_route_ids(attempt.route_ids)
            except RawRequestAuthorityPersistenceError as exc:
                raise RawRequestAuthorityManifestError(str(exc)) from exc
        elif attempt.route_ids:
            _fail("incomplete observation cannot carry terminal route coverage")
        by_provider[attempt.provider_request_sha256].append(attempt)

    completed: list[str] = []
    for call in expected:
        call_attempts = by_provider.get(call.provider_request_sha256, [])
        if not call_attempts:
            continue
        semantic_contexts = {
            (item.semantic_request_sha256, item.logical_invocation_sha256) for item in call_attempts
        }
        if len(semantic_contexts) != 1:
            _fail("persisted retries cross logical request identity")
        coordinates = [(item.retry_ordinal, item.request_ordinal) for item in call_attempts]
        if len(coordinates) != len(set(coordinates)):
            _fail("cumulative retries repeat a retry/request coordinate")
        retry_ordinals = sorted(item.retry_ordinal for item in call_attempts)
        if retry_ordinals != list(range(len(retry_ordinals))):
            _fail("cumulative retries do not preserve the exact retry prefix")
        if len({item.provider_call_sha256 for item in call_attempts}) != 1:
            _fail("persisted observations add an unplanned provider-call identity")
        by_retry: defaultdict[int, set[int]] = defaultdict(set)
        request_to_call: dict[int, str] = {}
        call_to_request: dict[str, int] = {}
        call_shapes: dict[str, tuple[str, int]] = {}
        selected_by_call: defaultdict[str, list[RawRequestPersistedAttemptV2]] = defaultdict(list)
        for attempt in call_attempts:
            by_retry[attempt.retry_ordinal].add(attempt.request_ordinal)
            prior_call = request_to_call.setdefault(
                attempt.request_ordinal,
                attempt.provider_call_sha256,
            )
            prior_request = call_to_request.setdefault(
                attempt.provider_call_sha256,
                attempt.request_ordinal,
            )
            shape = (attempt.provider_call_role, attempt.provider_call_ordinal)
            prior_shape = call_shapes.setdefault(attempt.provider_call_sha256, shape)
            if (
                prior_call != attempt.provider_call_sha256
                or prior_request != attempt.request_ordinal
                or prior_shape != shape
            ):
                _fail("persisted retries reorder or reshape provider-call identity")
            if attempt.lifecycle == "selected_terminal":
                selected_by_call[attempt.provider_call_sha256].append(attempt)
        if any(sorted(values) != list(range(len(values))) for values in by_retry.values()):
            _fail("persisted request coordinates are not contiguous within a retry")
        if any(len(items) > 1 for items in selected_by_call.values()):
            _fail("provider call has more than one terminal selection")
        for provider_call_sha256, selected in selected_by_call.items():
            terminal = selected[0]
            if any(
                item.provider_call_sha256 == provider_call_sha256
                and item.retry_ordinal > terminal.retry_ordinal
                for item in call_attempts
            ):
                _fail("provider call has an attempt after its terminal selection")
        if set(selected_by_call) == set(call_to_request):
            selected_requests = sorted(
                item.request_ordinal for items in selected_by_call.values() for item in items
            )
            selected_call_ordinals = sorted(
                item.provider_call_ordinal for items in selected_by_call.values() for item in items
            )
            if selected_requests != list(
                range(len(selected_requests))
            ) or selected_call_ordinals != list(range(len(selected_call_ordinals))):
                _fail("terminal provider-call inventory is not contiguous")
            completed.append(call.logical_request_sha256)

    completed_ids = tuple(sorted(completed))
    unresolved_ids = tuple(sorted(set(logical_ids) - set(completed_ids)))
    expected_ids = tuple(sorted(logical_ids))
    return _DenominatorState(
        expected_request_sha256s=expected_ids,
        completed_request_sha256s=completed_ids,
        unresolved_request_sha256s=unresolved_ids,
        expected_request_inventory_sha256=_sha256(list(expected_ids)),
        completed_request_inventory_sha256=_sha256(list(completed_ids)),
        unresolved_request_inventory_sha256=_sha256(list(unresolved_ids)),
        coverage_complete=not unresolved_ids,
    )


def _bounded_sum(values: Sequence[int], *, field_name: str) -> int:
    total = sum(values)
    if total > _MAX_COUNTER:
        _fail(f"{field_name} exceeds the bounded counter range")
    return total


def _receipt_aggregate(
    receipts: Sequence[RawRequestAuthorityPersistenceReceiptV2],
) -> _ReceiptAggregate:
    exact = tuple(_replay_independent_receipt(item, label="receipt inventory") for item in receipts)
    if len(exact) > _MAX_RECEIPTS:
        _fail("receipt inventory exceeds the bounded manifest limit")
    receipt_ids = tuple(item.receipt_sha256 for item in exact)
    bundle_ids = tuple(item.bundle_sha256 for item in exact)
    if len(receipt_ids) != len(set(receipt_ids)):
        _fail("receipt inventory contains duplicate receipt identities")
    if len(bundle_ids) != len(set(bundle_ids)):
        _fail("receipt inventory contains duplicate bundle identities")
    return _ReceiptAggregate(
        receipt_count=len(exact),
        object_reference_count=_bounded_sum(
            tuple(item.object_count for item in exact),
            field_name="object_reference_count",
        ),
        observation_reference_count=_bounded_sum(
            tuple(item.observation_count for item in exact),
            field_name="observation_reference_count",
        ),
        occurrence_reference_count=_bounded_sum(
            tuple(item.occurrence_count for item in exact),
            field_name="occurrence_reference_count",
        ),
        landing_reference_count=_bounded_sum(
            tuple(item.landing_count for item in exact),
            field_name="landing_reference_count",
        ),
        receipt_inventory_sha256=_sha256([item.to_dict() for item in exact]),
        bundle_inventory_sha256=_sha256(list(bundle_ids)),
        object_inventory_sha256=_sha256(
            [
                {
                    "receipt_sha256": item.receipt_sha256,
                    "inventory_sha256": item.object_inventory_sha256,
                }
                for item in exact
            ]
        ),
        observation_inventory_sha256=_sha256(
            [
                {
                    "receipt_sha256": item.receipt_sha256,
                    "inventory_sha256": item.observation_inventory_sha256,
                }
                for item in exact
            ]
        ),
        occurrence_inventory_sha256=_sha256(
            [
                {
                    "receipt_sha256": item.receipt_sha256,
                    "inventory_sha256": item.occurrence_inventory_sha256,
                }
                for item in exact
            ]
        ),
        landing_inventory_sha256=_sha256(
            [
                {
                    "receipt_sha256": item.receipt_sha256,
                    "inventory_sha256": item.landing_inventory_sha256,
                }
                for item in exact
            ]
        ),
        object_rows_sha256=_sha256(
            [
                {"receipt_sha256": item.receipt_sha256, "rows_sha256": item.object_rows_sha256}
                for item in exact
            ]
        ),
        observation_rows_sha256=_sha256(
            [
                {
                    "receipt_sha256": item.receipt_sha256,
                    "rows_sha256": item.observation_rows_sha256,
                }
                for item in exact
            ]
        ),
        occurrence_rows_sha256=_sha256(
            [
                {
                    "receipt_sha256": item.receipt_sha256,
                    "rows_sha256": item.occurrence_rows_sha256,
                }
                for item in exact
            ]
        ),
        landing_rows_sha256=_sha256(
            [
                {"receipt_sha256": item.receipt_sha256, "rows_sha256": item.landing_rows_sha256}
                for item in exact
            ]
        ),
    )


_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "source_sha",
        "run_id",
        "run_attempt",
        "chain_id",
        "lane_id",
        "scope_sha256",
        "generation",
        "parent_manifest_sha256",
        "route_authority_sha256",
        "request_closure_authority_sha256",
        "field_authority_sha256",
        "model_authority_sha256",
        "authority_set_sha256",
        "expected_calls",
        "expected_request_sha256s",
        "completed_request_sha256s",
        "unresolved_request_sha256s",
        "expected_request_count",
        "completed_request_count",
        "unresolved_request_count",
        "expected_request_inventory_sha256",
        "completed_request_inventory_sha256",
        "unresolved_request_inventory_sha256",
        "coverage_complete",
        "terminal_sealed",
        "is_complete",
        "receipts",
        "delta_receipt_sha256s",
        "receipt_count",
        "object_reference_count",
        "observation_reference_count",
        "occurrence_reference_count",
        "landing_reference_count",
        "receipt_inventory_sha256",
        "bundle_inventory_sha256",
        "object_inventory_sha256",
        "observation_inventory_sha256",
        "occurrence_inventory_sha256",
        "landing_inventory_sha256",
        "object_rows_sha256",
        "observation_rows_sha256",
        "occurrence_rows_sha256",
        "landing_rows_sha256",
        "delta_receipt_count",
        "delta_object_reference_count",
        "delta_observation_reference_count",
        "delta_occurrence_reference_count",
        "delta_landing_reference_count",
        "delta_object_inventory_sha256",
        "delta_observation_inventory_sha256",
        "delta_occurrence_inventory_sha256",
        "delta_landing_inventory_sha256",
        "delta_object_rows_sha256",
        "delta_observation_rows_sha256",
        "delta_occurrence_rows_sha256",
        "delta_landing_rows_sha256",
        "delta_receipt_inventory_sha256",
        "manifest_sha256",
    }
)

_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "bundle_sha256",
        "object_count",
        "observation_count",
        "occurrence_count",
        "landing_count",
        "object_inventory_sha256",
        "observation_inventory_sha256",
        "occurrence_inventory_sha256",
        "landing_inventory_sha256",
        "object_rows_sha256",
        "observation_rows_sha256",
        "occurrence_rows_sha256",
        "landing_rows_sha256",
        "attempts",
        "attempt_count",
        "attempt_inventory_sha256",
        "receipt_sha256",
        "replayed",
    }
)

_EXPECTED_CALL_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "logical_request_sha256",
        "endpoint_name",
        "source_family",
        "endpoint_id",
        "logical_parameters_sha256",
        "provider_parameters_sha256",
        "provider_request_sha256",
        "route_ids",
        "scope_sha256",
    }
)

_ATTEMPT_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "observation_sha256",
        "observation_record_sha256",
        "semantic_request_sha256",
        "logical_invocation_sha256",
        "provider_call_sha256",
        "provider_call_role",
        "provider_call_ordinal",
        "retry_ordinal",
        "request_ordinal",
        "source_family",
        "endpoint_id",
        "provider_request_sha256",
        "logical_parameters_sha256",
        "safe_parameters_sha256",
        "scope_sha256",
        "lifecycle",
        "outcome",
        "route_ids",
        "attempt_receipt_sha256",
    }
)


@dataclass(frozen=True, slots=True)
class RawRequestAuthorityManifestV2:
    """Canonical cumulative public raw authority for one exact lane scope."""

    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str
    scope_sha256: str
    generation: int
    parent_manifest_sha256: str | None
    route_authority_sha256: str
    request_closure_authority_sha256: str
    field_authority_sha256: str
    model_authority_sha256: str
    authority_set_sha256: str
    expected_calls: tuple[RawRequestClosureCallV2, ...]
    expected_request_sha256s: tuple[str, ...]
    completed_request_sha256s: tuple[str, ...]
    unresolved_request_sha256s: tuple[str, ...]
    expected_request_count: int
    completed_request_count: int
    unresolved_request_count: int
    expected_request_inventory_sha256: str
    completed_request_inventory_sha256: str
    unresolved_request_inventory_sha256: str
    coverage_complete: bool
    terminal_sealed: bool
    is_complete: bool
    receipts: tuple[RawRequestAuthorityPersistenceReceiptV2, ...]
    delta_receipt_sha256s: tuple[str, ...]
    receipt_count: int
    object_reference_count: int
    observation_reference_count: int
    occurrence_reference_count: int
    landing_reference_count: int
    receipt_inventory_sha256: str
    bundle_inventory_sha256: str
    object_inventory_sha256: str
    observation_inventory_sha256: str
    occurrence_inventory_sha256: str
    landing_inventory_sha256: str
    object_rows_sha256: str
    observation_rows_sha256: str
    occurrence_rows_sha256: str
    landing_rows_sha256: str
    delta_receipt_count: int
    delta_object_reference_count: int
    delta_observation_reference_count: int
    delta_occurrence_reference_count: int
    delta_landing_reference_count: int
    delta_object_inventory_sha256: str
    delta_observation_inventory_sha256: str
    delta_occurrence_inventory_sha256: str
    delta_landing_inventory_sha256: str
    delta_object_rows_sha256: str
    delta_observation_rows_sha256: str
    delta_occurrence_rows_sha256: str
    delta_landing_rows_sha256: str
    delta_receipt_inventory_sha256: str

    schema_version: ClassVar[int] = RAW_REQUEST_AUTHORITY_MANIFEST_SCHEMA_VERSION
    kind: ClassVar[str] = RAW_REQUEST_AUTHORITY_MANIFEST_KIND

    def __post_init__(self) -> None:
        _require_git_sha(self.source_sha)
        _require_positive_int(self.run_id, field_name="run_id")
        _require_positive_int(self.run_attempt, field_name="run_attempt")
        _require_safe_id(self.chain_id, field_name="chain_id")
        _require_safe_id(self.lane_id, field_name="lane_id")
        _require_sha256(self.scope_sha256, field_name="scope_sha256")
        _require_nonnegative_int(self.generation, field_name="generation")
        if self.generation == 0:
            if self.parent_manifest_sha256 is not None:
                _fail("generation zero must not reference a parent manifest")
        elif self.parent_manifest_sha256 is None:
            _fail("a non-root generation must reference its exact parent manifest")
        else:
            _require_sha256(
                self.parent_manifest_sha256,
                field_name="parent_manifest_sha256",
            )

        authorities = {
            "route_authority_sha256": _require_sha256(
                self.route_authority_sha256,
                field_name="route_authority_sha256",
            ),
            "request_closure_authority_sha256": _require_sha256(
                self.request_closure_authority_sha256,
                field_name="request_closure_authority_sha256",
            ),
            "field_authority_sha256": _require_sha256(
                self.field_authority_sha256,
                field_name="field_authority_sha256",
            ),
            "model_authority_sha256": _require_sha256(
                self.model_authority_sha256,
                field_name="model_authority_sha256",
            ),
        }
        _require_sha256(self.authority_set_sha256, field_name="authority_set_sha256")
        if self.authority_set_sha256 != _sha256(authorities):
            _fail("authority_set_sha256 does not bind the four authority digests")

        if type(self.expected_calls) is not tuple:
            _fail("expected_calls must be an immutable tuple")
        expected_calls = tuple(
            _strict_expected_call(item, label="manifest expected calls")
            for item in self.expected_calls
        )
        if expected_calls != tuple(
            sorted(expected_calls, key=lambda item: item.logical_request_sha256)
        ):
            _fail("expected_calls must use canonical logical-request order")

        if type(self.receipts) is not tuple:
            _fail("receipts must be an immutable tuple")
        supplied_receipts = tuple(
            _strict_receipt(item, label="manifest receipts") for item in self.receipts
        )
        exact_receipts = tuple(
            _replay_independent_receipt(item, label="manifest receipts")
            for item in supplied_receipts
        )
        if supplied_receipts != exact_receipts:
            _fail("manifest receipts must use the replay-independent authority projection")
        canonical_receipts = tuple(sorted(exact_receipts, key=lambda item: item.receipt_sha256))
        if exact_receipts != canonical_receipts:
            _fail("receipts must use canonical receipt-identity order")
        aggregate = _receipt_aggregate(exact_receipts)
        denominator = _denominator_state(expected_calls, exact_receipts)

        inventory_fields = {
            "expected_request_sha256s": denominator.expected_request_sha256s,
            "completed_request_sha256s": denominator.completed_request_sha256s,
            "unresolved_request_sha256s": denominator.unresolved_request_sha256s,
        }
        for field_name, expected_inventory in inventory_fields.items():
            observed_inventory = getattr(self, field_name)
            if type(observed_inventory) is not tuple or observed_inventory != expected_inventory:
                _fail(f"{field_name} differs from the exact closure denominator")
        request_counts = {
            "expected_request_count": len(denominator.expected_request_sha256s),
            "completed_request_count": len(denominator.completed_request_sha256s),
            "unresolved_request_count": len(denominator.unresolved_request_sha256s),
        }
        for field_name, expected_count in request_counts.items():
            if (
                _require_nonnegative_int(getattr(self, field_name), field_name=field_name)
                != expected_count
            ):
                _fail(f"{field_name} differs from the exact closure denominator")
        request_digests = {
            "expected_request_inventory_sha256": (denominator.expected_request_inventory_sha256),
            "completed_request_inventory_sha256": (denominator.completed_request_inventory_sha256),
            "unresolved_request_inventory_sha256": (
                denominator.unresolved_request_inventory_sha256
            ),
        }
        for field_name, expected_digest in request_digests.items():
            if _require_sha256(getattr(self, field_name), field_name=field_name) != expected_digest:
                _fail(f"{field_name} differs from the exact closure denominator")
        for field_name in ("coverage_complete", "terminal_sealed", "is_complete"):
            if type(getattr(self, field_name)) is not bool:
                _fail(f"{field_name} must be an exact boolean")
        if self.coverage_complete is not denominator.coverage_complete:
            _fail("coverage_complete differs from the exact unresolved inventory")
        if self.terminal_sealed and not self.coverage_complete:
            _fail("terminal sealing rejects unresolved closure calls")
        if self.is_complete is not (self.coverage_complete and self.terminal_sealed):
            _fail("is_complete requires exact coverage and explicit terminal sealing")

        if type(self.delta_receipt_sha256s) is not tuple:
            _fail("delta_receipt_sha256s must be an immutable tuple")
        delta_ids = tuple(
            _require_sha256(item, field_name="delta_receipt_sha256s")
            for item in self.delta_receipt_sha256s
        )
        if delta_ids != tuple(sorted(delta_ids)):
            _fail("delta_receipt_sha256s must use canonical sorted order")
        if len(delta_ids) != len(set(delta_ids)):
            _fail("delta_receipt_sha256s contains duplicates")
        receipt_by_id = {item.receipt_sha256: item for item in exact_receipts}
        if not set(delta_ids).issubset(receipt_by_id):
            _fail("delta receipt inventory references a missing cumulative receipt")
        delta_receipts = tuple(receipt_by_id[item] for item in delta_ids)
        delta = _receipt_aggregate(delta_receipts)
        if self.generation == 0 and delta_ids != tuple(receipt_by_id):
            _fail("root generation delta must equal its complete receipt inventory")

        expected_counts = {
            "receipt_count": aggregate.receipt_count,
            "object_reference_count": aggregate.object_reference_count,
            "observation_reference_count": aggregate.observation_reference_count,
            "occurrence_reference_count": aggregate.occurrence_reference_count,
            "landing_reference_count": aggregate.landing_reference_count,
            "delta_receipt_count": delta.receipt_count,
            "delta_object_reference_count": delta.object_reference_count,
            "delta_observation_reference_count": delta.observation_reference_count,
            "delta_occurrence_reference_count": delta.occurrence_reference_count,
            "delta_landing_reference_count": delta.landing_reference_count,
        }
        for field_name, expected in expected_counts.items():
            observed = _require_nonnegative_int(getattr(self, field_name), field_name=field_name)
            if observed != expected:
                _fail(f"{field_name} differs from the exact receipt inventory")

        expected_digests = {
            "receipt_inventory_sha256": aggregate.receipt_inventory_sha256,
            "bundle_inventory_sha256": aggregate.bundle_inventory_sha256,
            "object_inventory_sha256": aggregate.object_inventory_sha256,
            "observation_inventory_sha256": aggregate.observation_inventory_sha256,
            "occurrence_inventory_sha256": aggregate.occurrence_inventory_sha256,
            "landing_inventory_sha256": aggregate.landing_inventory_sha256,
            "object_rows_sha256": aggregate.object_rows_sha256,
            "observation_rows_sha256": aggregate.observation_rows_sha256,
            "occurrence_rows_sha256": aggregate.occurrence_rows_sha256,
            "landing_rows_sha256": aggregate.landing_rows_sha256,
            "delta_object_inventory_sha256": delta.object_inventory_sha256,
            "delta_observation_inventory_sha256": delta.observation_inventory_sha256,
            "delta_occurrence_inventory_sha256": delta.occurrence_inventory_sha256,
            "delta_landing_inventory_sha256": delta.landing_inventory_sha256,
            "delta_object_rows_sha256": delta.object_rows_sha256,
            "delta_observation_rows_sha256": delta.observation_rows_sha256,
            "delta_occurrence_rows_sha256": delta.occurrence_rows_sha256,
            "delta_landing_rows_sha256": delta.landing_rows_sha256,
            "delta_receipt_inventory_sha256": delta.receipt_inventory_sha256,
        }
        for field_name, expected in expected_digests.items():
            observed = _require_sha256(getattr(self, field_name), field_name=field_name)
            if observed != expected:
                _fail(f"{field_name} differs from the exact receipt inventory")
        if len(_canonical_bytes(self.to_dict())) > _MAX_MANIFEST_BYTES:
            _fail("raw-request authority manifest exceeds the canonical byte limit")

    @classmethod
    def seal(
        cls,
        *,
        source_sha: str,
        run_id: int,
        run_attempt: int,
        chain_id: str,
        lane_id: str,
        scope_sha256: str,
        route_authority_sha256: str,
        request_closure_authority_sha256: str,
        field_authority_sha256: str,
        model_authority_sha256: str,
        expected_calls: Sequence[RawRequestClosureCallV2],
        receipts: Sequence[RawRequestAuthorityPersistenceReceiptV2],
        terminal: bool = False,
        known_secrets: Sequence[str | bytes] = (),
    ) -> RawRequestAuthorityManifestV2:
        """Seal a root generation from exact persistence receipts."""

        if not receipts:
            _fail("root generation requires at least one persisted request receipt")

        return cls._from_parts(
            source_sha=source_sha,
            run_id=run_id,
            run_attempt=run_attempt,
            chain_id=chain_id,
            lane_id=lane_id,
            scope_sha256=scope_sha256,
            generation=0,
            parent_manifest_sha256=None,
            route_authority_sha256=route_authority_sha256,
            request_closure_authority_sha256=request_closure_authority_sha256,
            field_authority_sha256=field_authority_sha256,
            model_authority_sha256=model_authority_sha256,
            expected_calls=expected_calls,
            receipts=receipts,
            delta_receipt_sha256s=tuple(item.receipt_sha256 for item in receipts),
            terminal_sealed=terminal,
            known_secrets=known_secrets,
        )

    @classmethod
    def _from_parts(
        cls,
        *,
        source_sha: str,
        run_id: int,
        run_attempt: int,
        chain_id: str,
        lane_id: str,
        scope_sha256: str,
        generation: int,
        parent_manifest_sha256: str | None,
        route_authority_sha256: str,
        request_closure_authority_sha256: str,
        field_authority_sha256: str,
        model_authority_sha256: str,
        expected_calls: Sequence[RawRequestClosureCallV2],
        receipts: Sequence[RawRequestAuthorityPersistenceReceiptV2],
        delta_receipt_sha256s: Sequence[str],
        terminal_sealed: bool,
        known_secrets: Sequence[str | bytes] = (),
    ) -> Self:
        exact = tuple(
            _replay_independent_receipt(item, label="manifest input") for item in receipts
        )
        ordered = tuple(sorted(exact, key=lambda item: item.receipt_sha256))
        exact_expected = tuple(
            sorted(
                (_strict_expected_call(item, label="manifest input") for item in expected_calls),
                key=lambda item: item.logical_request_sha256,
            )
        )
        delta_ids = tuple(sorted(delta_receipt_sha256s))
        aggregate = _receipt_aggregate(ordered)
        by_id = {item.receipt_sha256: item for item in ordered}
        if not set(delta_ids).issubset(by_id):
            _fail("delta receipt input references a missing cumulative receipt")
        delta = _receipt_aggregate(tuple(by_id[item] for item in delta_ids))
        denominator = _denominator_state(exact_expected, ordered)
        authorities = {
            "route_authority_sha256": route_authority_sha256,
            "request_closure_authority_sha256": request_closure_authority_sha256,
            "field_authority_sha256": field_authority_sha256,
            "model_authority_sha256": model_authority_sha256,
        }
        manifest = cls(
            source_sha=source_sha,
            run_id=run_id,
            run_attempt=run_attempt,
            chain_id=chain_id,
            lane_id=lane_id,
            scope_sha256=scope_sha256,
            generation=generation,
            parent_manifest_sha256=parent_manifest_sha256,
            route_authority_sha256=route_authority_sha256,
            request_closure_authority_sha256=request_closure_authority_sha256,
            field_authority_sha256=field_authority_sha256,
            model_authority_sha256=model_authority_sha256,
            authority_set_sha256=_sha256(authorities),
            expected_calls=exact_expected,
            expected_request_sha256s=denominator.expected_request_sha256s,
            completed_request_sha256s=denominator.completed_request_sha256s,
            unresolved_request_sha256s=denominator.unresolved_request_sha256s,
            expected_request_count=len(denominator.expected_request_sha256s),
            completed_request_count=len(denominator.completed_request_sha256s),
            unresolved_request_count=len(denominator.unresolved_request_sha256s),
            expected_request_inventory_sha256=(denominator.expected_request_inventory_sha256),
            completed_request_inventory_sha256=(denominator.completed_request_inventory_sha256),
            unresolved_request_inventory_sha256=(denominator.unresolved_request_inventory_sha256),
            coverage_complete=denominator.coverage_complete,
            terminal_sealed=terminal_sealed,
            is_complete=denominator.coverage_complete and terminal_sealed,
            receipts=ordered,
            delta_receipt_sha256s=delta_ids,
            receipt_count=aggregate.receipt_count,
            object_reference_count=aggregate.object_reference_count,
            observation_reference_count=aggregate.observation_reference_count,
            occurrence_reference_count=aggregate.occurrence_reference_count,
            landing_reference_count=aggregate.landing_reference_count,
            receipt_inventory_sha256=aggregate.receipt_inventory_sha256,
            bundle_inventory_sha256=aggregate.bundle_inventory_sha256,
            object_inventory_sha256=aggregate.object_inventory_sha256,
            observation_inventory_sha256=aggregate.observation_inventory_sha256,
            occurrence_inventory_sha256=aggregate.occurrence_inventory_sha256,
            landing_inventory_sha256=aggregate.landing_inventory_sha256,
            object_rows_sha256=aggregate.object_rows_sha256,
            observation_rows_sha256=aggregate.observation_rows_sha256,
            occurrence_rows_sha256=aggregate.occurrence_rows_sha256,
            landing_rows_sha256=aggregate.landing_rows_sha256,
            delta_receipt_count=delta.receipt_count,
            delta_object_reference_count=delta.object_reference_count,
            delta_observation_reference_count=delta.observation_reference_count,
            delta_occurrence_reference_count=delta.occurrence_reference_count,
            delta_landing_reference_count=delta.landing_reference_count,
            delta_object_inventory_sha256=delta.object_inventory_sha256,
            delta_observation_inventory_sha256=delta.observation_inventory_sha256,
            delta_occurrence_inventory_sha256=delta.occurrence_inventory_sha256,
            delta_landing_inventory_sha256=delta.landing_inventory_sha256,
            delta_object_rows_sha256=delta.object_rows_sha256,
            delta_observation_rows_sha256=delta.observation_rows_sha256,
            delta_occurrence_rows_sha256=delta.occurrence_rows_sha256,
            delta_landing_rows_sha256=delta.landing_rows_sha256,
            delta_receipt_inventory_sha256=delta.receipt_inventory_sha256,
        )
        _reject_known_secrets(manifest.canonical_bytes, known_secrets=known_secrets)
        return manifest

    def _semantic_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "scope_sha256": self.scope_sha256,
            "generation": self.generation,
            "parent_manifest_sha256": self.parent_manifest_sha256,
            "route_authority_sha256": self.route_authority_sha256,
            "request_closure_authority_sha256": self.request_closure_authority_sha256,
            "field_authority_sha256": self.field_authority_sha256,
            "model_authority_sha256": self.model_authority_sha256,
            "authority_set_sha256": self.authority_set_sha256,
            "expected_calls": [item.to_dict() for item in self.expected_calls],
            "expected_request_sha256s": list(self.expected_request_sha256s),
            "completed_request_sha256s": list(self.completed_request_sha256s),
            "unresolved_request_sha256s": list(self.unresolved_request_sha256s),
            "expected_request_count": self.expected_request_count,
            "completed_request_count": self.completed_request_count,
            "unresolved_request_count": self.unresolved_request_count,
            "expected_request_inventory_sha256": self.expected_request_inventory_sha256,
            "completed_request_inventory_sha256": self.completed_request_inventory_sha256,
            "unresolved_request_inventory_sha256": self.unresolved_request_inventory_sha256,
            "coverage_complete": self.coverage_complete,
            "terminal_sealed": self.terminal_sealed,
            "is_complete": self.is_complete,
            "receipts": [item.to_dict() for item in self.receipts],
            "delta_receipt_sha256s": list(self.delta_receipt_sha256s),
            "receipt_count": self.receipt_count,
            "object_reference_count": self.object_reference_count,
            "observation_reference_count": self.observation_reference_count,
            "occurrence_reference_count": self.occurrence_reference_count,
            "landing_reference_count": self.landing_reference_count,
            "receipt_inventory_sha256": self.receipt_inventory_sha256,
            "bundle_inventory_sha256": self.bundle_inventory_sha256,
            "object_inventory_sha256": self.object_inventory_sha256,
            "observation_inventory_sha256": self.observation_inventory_sha256,
            "occurrence_inventory_sha256": self.occurrence_inventory_sha256,
            "landing_inventory_sha256": self.landing_inventory_sha256,
            "object_rows_sha256": self.object_rows_sha256,
            "observation_rows_sha256": self.observation_rows_sha256,
            "occurrence_rows_sha256": self.occurrence_rows_sha256,
            "landing_rows_sha256": self.landing_rows_sha256,
            "delta_receipt_count": self.delta_receipt_count,
            "delta_object_reference_count": self.delta_object_reference_count,
            "delta_observation_reference_count": self.delta_observation_reference_count,
            "delta_occurrence_reference_count": self.delta_occurrence_reference_count,
            "delta_landing_reference_count": self.delta_landing_reference_count,
            "delta_object_inventory_sha256": self.delta_object_inventory_sha256,
            "delta_observation_inventory_sha256": self.delta_observation_inventory_sha256,
            "delta_occurrence_inventory_sha256": self.delta_occurrence_inventory_sha256,
            "delta_landing_inventory_sha256": self.delta_landing_inventory_sha256,
            "delta_object_rows_sha256": self.delta_object_rows_sha256,
            "delta_observation_rows_sha256": self.delta_observation_rows_sha256,
            "delta_occurrence_rows_sha256": self.delta_occurrence_rows_sha256,
            "delta_landing_rows_sha256": self.delta_landing_rows_sha256,
            "delta_receipt_inventory_sha256": self.delta_receipt_inventory_sha256,
        }

    @property
    def manifest_sha256(self) -> str:
        """Return the semantic digest, excluding only the digest field itself."""

        return _sha256(self._semantic_payload())

    def to_dict(self) -> dict[str, object]:
        return {**self._semantic_payload(), "manifest_sha256": self.manifest_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        """Return the sole accepted byte representation of the manifest."""

        return _canonical_bytes(self.to_dict())

    def roll_forward(
        self,
        delta_receipts: Sequence[RawRequestAuthorityPersistenceReceiptV2],
        *,
        source_sha: str | None = None,
        run_id: int | None = None,
        run_attempt: int | None = None,
        chain_id: str | None = None,
        lane_id: str | None = None,
        scope_sha256: str | None = None,
        route_authority_sha256: str | None = None,
        request_closure_authority_sha256: str | None = None,
        field_authority_sha256: str | None = None,
        model_authority_sha256: str | None = None,
        terminal: bool | None = None,
        known_secrets: Sequence[str | bytes] = (),
    ) -> RawRequestAuthorityManifestV2:
        """Create and independently verify one immutable copy-plus-delta child."""

        return merge_raw_request_authority_manifest(
            self,
            delta_receipts,
            source_sha=self.source_sha if source_sha is None else source_sha,
            run_id=self.run_id if run_id is None else run_id,
            run_attempt=self.run_attempt if run_attempt is None else run_attempt,
            chain_id=self.chain_id if chain_id is None else chain_id,
            lane_id=self.lane_id if lane_id is None else lane_id,
            scope_sha256=self.scope_sha256 if scope_sha256 is None else scope_sha256,
            route_authority_sha256=(
                self.route_authority_sha256
                if route_authority_sha256 is None
                else route_authority_sha256
            ),
            request_closure_authority_sha256=(
                self.request_closure_authority_sha256
                if request_closure_authority_sha256 is None
                else request_closure_authority_sha256
            ),
            field_authority_sha256=(
                self.field_authority_sha256
                if field_authority_sha256 is None
                else field_authority_sha256
            ),
            model_authority_sha256=(
                self.model_authority_sha256
                if model_authority_sha256 is None
                else model_authority_sha256
            ),
            terminal=self.terminal_sealed if terminal is None else terminal,
            known_secrets=known_secrets,
        )


def validate_raw_request_authority_manifest(
    value: object,
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> RawRequestAuthorityManifestV2:
    """Strictly reconstruct a manifest and recompute every derived field."""

    if type(value) is not RawRequestAuthorityManifestV2:
        _fail("raw-request authority manifest has no exact contract type")
    manifest = value
    recomputed = recompute_raw_request_authority_manifest(manifest)
    if recomputed.to_dict() != manifest.to_dict():
        _fail("raw-request authority manifest changed during recomputation")
    _reject_known_secrets(recomputed.canonical_bytes, known_secrets=known_secrets)
    return recomputed


def recompute_raw_request_authority_manifest(
    value: RawRequestAuthorityManifestV2,
) -> RawRequestAuthorityManifestV2:
    """Independently rebuild one manifest solely from its declared authorities."""

    if type(value) is not RawRequestAuthorityManifestV2:
        _fail("raw-request authority manifest has no exact contract type")
    return RawRequestAuthorityManifestV2._from_parts(
        source_sha=value.source_sha,
        run_id=value.run_id,
        run_attempt=value.run_attempt,
        chain_id=value.chain_id,
        lane_id=value.lane_id,
        scope_sha256=value.scope_sha256,
        generation=value.generation,
        parent_manifest_sha256=value.parent_manifest_sha256,
        route_authority_sha256=value.route_authority_sha256,
        request_closure_authority_sha256=value.request_closure_authority_sha256,
        field_authority_sha256=value.field_authority_sha256,
        model_authority_sha256=value.model_authority_sha256,
        expected_calls=value.expected_calls,
        receipts=value.receipts,
        delta_receipt_sha256s=value.delta_receipt_sha256s,
        terminal_sealed=value.terminal_sealed,
    )


def merge_raw_request_authority_manifest(
    parent: RawRequestAuthorityManifestV2,
    delta_receipts: Sequence[RawRequestAuthorityPersistenceReceiptV2],
    *,
    source_sha: str,
    run_id: int,
    run_attempt: int,
    chain_id: str,
    lane_id: str,
    scope_sha256: str,
    route_authority_sha256: str,
    request_closure_authority_sha256: str,
    field_authority_sha256: str,
    model_authority_sha256: str,
    terminal: bool,
    known_secrets: Sequence[str | bytes] = (),
) -> RawRequestAuthorityManifestV2:
    """Copy a parent receipt inventory and add one exact, disjoint delta."""

    validated_parent = validate_raw_request_authority_manifest(
        parent,
        known_secrets=known_secrets,
    )
    exact_delta = tuple(
        _replay_independent_receipt(item, label="copy-plus-delta input") for item in delta_receipts
    )
    _receipt_aggregate(exact_delta)
    if validated_parent.terminal_sealed and exact_delta:
        _fail("terminal manifest cannot accept a new receipt delta")
    parent_ids = {item.receipt_sha256 for item in validated_parent.receipts}
    parent_bundles = {item.bundle_sha256 for item in validated_parent.receipts}
    if any(item.receipt_sha256 in parent_ids for item in exact_delta):
        _fail("copy-plus-delta input repeats a parent receipt identity")
    if any(item.bundle_sha256 in parent_bundles for item in exact_delta):
        _fail("copy-plus-delta input repeats a parent bundle identity")
    child = RawRequestAuthorityManifestV2._from_parts(
        source_sha=source_sha,
        run_id=run_id,
        run_attempt=run_attempt,
        chain_id=chain_id,
        lane_id=lane_id,
        scope_sha256=scope_sha256,
        generation=validated_parent.generation + 1,
        parent_manifest_sha256=validated_parent.manifest_sha256,
        route_authority_sha256=route_authority_sha256,
        request_closure_authority_sha256=request_closure_authority_sha256,
        field_authority_sha256=field_authority_sha256,
        model_authority_sha256=model_authority_sha256,
        expected_calls=validated_parent.expected_calls,
        receipts=(*validated_parent.receipts, *exact_delta),
        delta_receipt_sha256s=tuple(item.receipt_sha256 for item in exact_delta),
        terminal_sealed=terminal or validated_parent.terminal_sealed,
        known_secrets=known_secrets,
    )
    validate_raw_request_authority_manifest_roll_forward(validated_parent, child)
    return child


def validate_raw_request_authority_manifest_roll_forward(
    parent: RawRequestAuthorityManifestV2,
    child: RawRequestAuthorityManifestV2,
) -> RawRequestAuthorityManifestV2:
    """Prove exact conservation and disjoint delta across two generations."""

    old = validate_raw_request_authority_manifest(parent)
    new = validate_raw_request_authority_manifest(child)
    identity_fields = (
        "source_sha",
        "run_id",
        "run_attempt",
        "chain_id",
        "lane_id",
        "scope_sha256",
        "route_authority_sha256",
        "request_closure_authority_sha256",
        "field_authority_sha256",
        "model_authority_sha256",
        "authority_set_sha256",
        "expected_calls",
        "expected_request_sha256s",
        "expected_request_inventory_sha256",
    )
    drifted = tuple(
        field_name
        for field_name in identity_fields
        if getattr(old, field_name) != getattr(new, field_name)
    )
    if drifted:
        _fail("copy-plus-delta child has foreign lineage or authority: " + ",".join(drifted))
    if new.generation != old.generation + 1 or new.parent_manifest_sha256 != old.manifest_sha256:
        _fail("copy-plus-delta generation or parent digest is invalid")
    if old.terminal_sealed and (
        not new.terminal_sealed or not new.is_complete or not new.coverage_complete
    ):
        _fail("copy-plus-delta child downgraded terminal completeness")

    old_by_id = {item.receipt_sha256: item for item in old.receipts}
    new_by_id = {item.receipt_sha256: item for item in new.receipts}
    if not set(old_by_id).issubset(new_by_id):
        _fail("copy-plus-delta child removed a parent receipt")
    if any(new_by_id[key].to_dict() != receipt.to_dict() for key, receipt in old_by_id.items()):
        _fail("copy-plus-delta child changed a parent receipt row")
    added = tuple(sorted(set(new_by_id) - set(old_by_id)))
    if old.terminal_sealed and added:
        _fail("copy-plus-delta child added receipts after terminal sealing")
    if new.delta_receipt_sha256s != added:
        _fail("copy-plus-delta child delta differs from the exact added inventory")
    return new


def _decode_object(raw: bytes) -> Mapping[str, object]:
    if not isinstance(raw, bytes):
        _fail("raw-request authority manifest parser requires exact bytes")
    if not raw or len(raw) > _MAX_MANIFEST_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        _fail("raw-request authority manifest byte envelope is invalid")

    def reject_constant(value: str) -> Never:
        _fail(f"non-finite JSON constant is forbidden: {value}")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                _fail(f"raw-request authority manifest repeats JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RawRequestAuthorityManifestError(
            "raw-request authority manifest is not strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        _fail("raw-request authority manifest root must be a JSON object")
    return cast("Mapping[str, object]", value)


def _parse_expected_call(value: object, *, index: int) -> RawRequestClosureCallV2:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        _fail(f"expected_calls[{index}] must be a JSON object")
    payload = cast("Mapping[str, object]", value)
    _require_exact_keys(
        payload,
        expected=_EXPECTED_CALL_FIELDS,
        label=f"expected_calls[{index}]",
    )
    raw_routes = payload["route_ids"]
    if not isinstance(raw_routes, list) or any(type(item) is not str for item in raw_routes):
        _fail(f"expected_calls[{index}] routes are invalid")
    try:
        call = RawRequestClosureCallV2(
            logical_request_sha256=cast("str", payload["logical_request_sha256"]),
            endpoint_name=cast("str", payload["endpoint_name"]),
            source_family=cast("str", payload["source_family"]),
            endpoint_id=cast("str", payload["endpoint_id"]),
            logical_parameters_sha256=cast("str", payload["logical_parameters_sha256"]),
            provider_parameters_sha256=cast("str | None", payload["provider_parameters_sha256"]),
            provider_request_sha256=cast("str", payload["provider_request_sha256"]),
            route_ids=cast("tuple[str, ...]", tuple(raw_routes)),
            scope_sha256=cast("str", payload["scope_sha256"]),
        )
    except (TypeError, RawRequestAuthorityPersistenceError) as exc:
        raise RawRequestAuthorityManifestError(
            f"expected_calls[{index}] closure call is invalid"
        ) from exc
    if (
        payload["schema_version"] != RawRequestClosureCallV2.schema_version
        or payload["kind"] != RawRequestClosureCallV2.kind
    ):
        _fail(f"expected_calls[{index}] schema is invalid")
    return call


def _parse_attempt(
    value: object,
    *,
    receipt_index: int,
    index: int,
) -> RawRequestPersistedAttemptV2:
    label = f"receipts[{receipt_index}].attempts[{index}]"
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        _fail(f"{label} must be a JSON object")
    payload = cast("Mapping[str, object]", value)
    _require_exact_keys(payload, expected=_ATTEMPT_FIELDS, label=label)
    raw_routes = payload["route_ids"]
    if not isinstance(raw_routes, list) or any(type(item) is not str for item in raw_routes):
        _fail(f"{label} routes are invalid")
    try:
        attempt = RawRequestPersistedAttemptV2(
            observation_sha256=cast("str", payload["observation_sha256"]),
            observation_record_sha256=cast("str", payload["observation_record_sha256"]),
            semantic_request_sha256=cast("str", payload["semantic_request_sha256"]),
            logical_invocation_sha256=cast("str", payload["logical_invocation_sha256"]),
            provider_call_sha256=cast("str", payload["provider_call_sha256"]),
            provider_call_role=cast("str", payload["provider_call_role"]),
            provider_call_ordinal=cast("int", payload["provider_call_ordinal"]),
            retry_ordinal=cast("int", payload["retry_ordinal"]),
            request_ordinal=cast("int", payload["request_ordinal"]),
            source_family=cast("str", payload["source_family"]),
            endpoint_id=cast("str", payload["endpoint_id"]),
            provider_request_sha256=cast("str", payload["provider_request_sha256"]),
            logical_parameters_sha256=cast("str", payload["logical_parameters_sha256"]),
            safe_parameters_sha256=cast("str", payload["safe_parameters_sha256"]),
            scope_sha256=cast("str", payload["scope_sha256"]),
            lifecycle=cast("str", payload["lifecycle"]),
            outcome=cast("str", payload["outcome"]),
            route_ids=cast("tuple[str, ...]", tuple(raw_routes)),
        )
    except (TypeError, RawRequestAuthorityPersistenceError) as exc:
        raise RawRequestAuthorityManifestError(f"{label} is invalid") from exc
    if (
        payload["schema_version"] != RawRequestPersistedAttemptV2.schema_version
        or payload["kind"] != RawRequestPersistedAttemptV2.kind
        or payload["attempt_receipt_sha256"] != attempt.attempt_receipt_sha256
    ):
        _fail(f"{label} schema or digest is invalid")
    return attempt


def _parse_receipt(value: object, *, index: int) -> RawRequestAuthorityPersistenceReceiptV2:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        _fail(f"receipts[{index}] must be a JSON object")
    payload = cast("Mapping[str, object]", value)
    _require_exact_keys(payload, expected=_RECEIPT_FIELDS, label=f"receipts[{index}]")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != RawRequestAuthorityPersistenceReceiptV2.schema_version
        or payload["kind"] != RawRequestAuthorityPersistenceReceiptV2.kind
    ):
        _fail(f"receipts[{index}] schema is invalid")
    raw_attempts = payload["attempts"]
    if not isinstance(raw_attempts, list):
        _fail(f"receipts[{index}] attempts must be a JSON list")
    attempts = tuple(
        _parse_attempt(item, receipt_index=index, index=attempt_index)
        for attempt_index, item in enumerate(raw_attempts)
    )
    try:
        receipt = RawRequestAuthorityPersistenceReceiptV2(
            bundle_sha256=cast("str", payload["bundle_sha256"]),
            object_count=cast("int", payload["object_count"]),
            observation_count=cast("int", payload["observation_count"]),
            occurrence_count=cast("int", payload["occurrence_count"]),
            landing_count=cast("int", payload["landing_count"]),
            object_inventory_sha256=cast("str", payload["object_inventory_sha256"]),
            observation_inventory_sha256=cast("str", payload["observation_inventory_sha256"]),
            occurrence_inventory_sha256=cast("str", payload["occurrence_inventory_sha256"]),
            landing_inventory_sha256=cast("str", payload["landing_inventory_sha256"]),
            object_rows_sha256=cast("str", payload["object_rows_sha256"]),
            observation_rows_sha256=cast("str", payload["observation_rows_sha256"]),
            occurrence_rows_sha256=cast("str", payload["occurrence_rows_sha256"]),
            landing_rows_sha256=cast("str", payload["landing_rows_sha256"]),
            attempts=attempts,
            attempt_count=cast("int", payload["attempt_count"]),
            attempt_inventory_sha256=cast("str", payload["attempt_inventory_sha256"]),
            replayed=cast("bool", payload["replayed"]),
        )
    except (TypeError, RawRequestAuthorityPersistenceError) as exc:
        raise RawRequestAuthorityManifestError(
            f"receipts[{index}] persistence receipt is invalid"
        ) from exc
    if payload["receipt_sha256"] != receipt.receipt_sha256:
        _fail(f"receipts[{index}] receipt digest is invalid")
    return receipt


def parse_raw_request_authority_manifest(
    raw: bytes,
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> RawRequestAuthorityManifestV2:
    """Parse only exact canonical bytes and independently recompute authority."""

    _reject_known_secrets(raw, known_secrets=known_secrets)
    payload = _decode_object(raw)
    _require_exact_keys(payload, expected=_MANIFEST_FIELDS, label="manifest")
    if (
        type(payload["schema_version"]) is not int
        or payload["schema_version"] != RAW_REQUEST_AUTHORITY_MANIFEST_SCHEMA_VERSION
        or payload["kind"] != RAW_REQUEST_AUTHORITY_MANIFEST_KIND
    ):
        _fail("raw-request authority manifest schema is invalid")
    raw_receipts = payload["receipts"]
    raw_delta = payload["delta_receipt_sha256s"]
    raw_expected_calls = payload["expected_calls"]
    raw_expected_ids = payload["expected_request_sha256s"]
    raw_completed_ids = payload["completed_request_sha256s"]
    raw_unresolved_ids = payload["unresolved_request_sha256s"]
    if (
        not isinstance(raw_receipts, list)
        or not isinstance(raw_delta, list)
        or not isinstance(raw_expected_calls, list)
        or not isinstance(raw_expected_ids, list)
        or not isinstance(raw_completed_ids, list)
        or not isinstance(raw_unresolved_ids, list)
    ):
        _fail("manifest receipt inventories must be JSON lists")
    expected_calls = tuple(
        _parse_expected_call(item, index=index) for index, item in enumerate(raw_expected_calls)
    )
    request_inventories = (raw_expected_ids, raw_completed_ids, raw_unresolved_ids)
    if any(any(type(item) is not str for item in inventory) for inventory in request_inventories):
        _fail("manifest request inventories contain non-string identities")
    receipts = tuple(_parse_receipt(item, index=index) for index, item in enumerate(raw_receipts))
    delta_ids = tuple(
        _require_sha256(item, field_name="delta_receipt_sha256s") for item in raw_delta
    )
    manifest = RawRequestAuthorityManifestV2(
        source_sha=cast("str", payload["source_sha"]),
        run_id=cast("int", payload["run_id"]),
        run_attempt=cast("int", payload["run_attempt"]),
        chain_id=cast("str", payload["chain_id"]),
        lane_id=cast("str", payload["lane_id"]),
        scope_sha256=cast("str", payload["scope_sha256"]),
        generation=cast("int", payload["generation"]),
        parent_manifest_sha256=cast("str | None", payload["parent_manifest_sha256"]),
        route_authority_sha256=cast("str", payload["route_authority_sha256"]),
        request_closure_authority_sha256=cast("str", payload["request_closure_authority_sha256"]),
        field_authority_sha256=cast("str", payload["field_authority_sha256"]),
        model_authority_sha256=cast("str", payload["model_authority_sha256"]),
        authority_set_sha256=cast("str", payload["authority_set_sha256"]),
        expected_calls=expected_calls,
        expected_request_sha256s=cast("tuple[str, ...]", tuple(raw_expected_ids)),
        completed_request_sha256s=cast("tuple[str, ...]", tuple(raw_completed_ids)),
        unresolved_request_sha256s=cast("tuple[str, ...]", tuple(raw_unresolved_ids)),
        expected_request_count=cast("int", payload["expected_request_count"]),
        completed_request_count=cast("int", payload["completed_request_count"]),
        unresolved_request_count=cast("int", payload["unresolved_request_count"]),
        expected_request_inventory_sha256=cast("str", payload["expected_request_inventory_sha256"]),
        completed_request_inventory_sha256=cast(
            "str", payload["completed_request_inventory_sha256"]
        ),
        unresolved_request_inventory_sha256=cast(
            "str", payload["unresolved_request_inventory_sha256"]
        ),
        coverage_complete=cast("bool", payload["coverage_complete"]),
        terminal_sealed=cast("bool", payload["terminal_sealed"]),
        is_complete=cast("bool", payload["is_complete"]),
        receipts=receipts,
        delta_receipt_sha256s=delta_ids,
        receipt_count=cast("int", payload["receipt_count"]),
        object_reference_count=cast("int", payload["object_reference_count"]),
        observation_reference_count=cast("int", payload["observation_reference_count"]),
        occurrence_reference_count=cast("int", payload["occurrence_reference_count"]),
        landing_reference_count=cast("int", payload["landing_reference_count"]),
        receipt_inventory_sha256=cast("str", payload["receipt_inventory_sha256"]),
        bundle_inventory_sha256=cast("str", payload["bundle_inventory_sha256"]),
        object_inventory_sha256=cast("str", payload["object_inventory_sha256"]),
        observation_inventory_sha256=cast("str", payload["observation_inventory_sha256"]),
        occurrence_inventory_sha256=cast("str", payload["occurrence_inventory_sha256"]),
        landing_inventory_sha256=cast("str", payload["landing_inventory_sha256"]),
        object_rows_sha256=cast("str", payload["object_rows_sha256"]),
        observation_rows_sha256=cast("str", payload["observation_rows_sha256"]),
        occurrence_rows_sha256=cast("str", payload["occurrence_rows_sha256"]),
        landing_rows_sha256=cast("str", payload["landing_rows_sha256"]),
        delta_receipt_count=cast("int", payload["delta_receipt_count"]),
        delta_object_reference_count=cast("int", payload["delta_object_reference_count"]),
        delta_observation_reference_count=cast("int", payload["delta_observation_reference_count"]),
        delta_occurrence_reference_count=cast("int", payload["delta_occurrence_reference_count"]),
        delta_landing_reference_count=cast("int", payload["delta_landing_reference_count"]),
        delta_object_inventory_sha256=cast("str", payload["delta_object_inventory_sha256"]),
        delta_observation_inventory_sha256=cast(
            "str", payload["delta_observation_inventory_sha256"]
        ),
        delta_occurrence_inventory_sha256=cast("str", payload["delta_occurrence_inventory_sha256"]),
        delta_landing_inventory_sha256=cast("str", payload["delta_landing_inventory_sha256"]),
        delta_object_rows_sha256=cast("str", payload["delta_object_rows_sha256"]),
        delta_observation_rows_sha256=cast("str", payload["delta_observation_rows_sha256"]),
        delta_occurrence_rows_sha256=cast("str", payload["delta_occurrence_rows_sha256"]),
        delta_landing_rows_sha256=cast("str", payload["delta_landing_rows_sha256"]),
        delta_receipt_inventory_sha256=cast("str", payload["delta_receipt_inventory_sha256"]),
    )
    if payload["manifest_sha256"] != manifest.manifest_sha256:
        _fail("raw-request authority manifest digest is invalid")
    if raw != manifest.canonical_bytes:
        _fail("raw-request authority manifest bytes are not canonical")
    return validate_raw_request_authority_manifest(manifest, known_secrets=known_secrets)
