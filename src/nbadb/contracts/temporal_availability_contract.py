"""Immutable temporal evidence contracts for every extraction route.

This compiler deliberately separates planning policy from provider evidence.
The repository's historical support rules remain bounded ``contract_blocked``
evidence; they are never promoted to a general availability claim.  Likewise,
the conventional 1946 planning floor is recorded as an unverified fallback,
not as proof that an endpoint is supported from 1946.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from functools import lru_cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from nbadb.contracts.staging_route_contract import (
    EXPECTED_STAGING_ROUTE_COUNT,
    StagingRouteContract,
    staging_route_contract_bundle,
)
from nbadb.orchestrate.extraction_contract import (
    FULL_EXTRACTION_CONTRACT_ALIASES,
    FULL_EXTRACTION_SUPPORT_RULES,
    EndpointSupportRule,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

TemporalState = Literal["contract_blocked"]
PlannerStartBasis = Literal["declared_provider_floor", "fallback_attempt_unverified"]
EvidenceDisposition = Literal["legacy_bounded_rule_not_availability"]
ProbeBindingState = Literal[
    "season_scope",
    "runtime_scope",
    "observed_entity_binding_required",
    "verified_workload_binding_required",
]

EXPECTED_ROUTE_SCOPE_COUNT = EXPECTED_STAGING_ROUTE_COUNT
EXPECTED_LEGACY_RULE_COUNT = 149
FALLBACK_PLANNER_START_SEASON = 1946
MAX_TEMPORAL_PROBE_POINTS_PER_SCOPE = 20
ALLOWED_TEMPORAL_OBSERVATION_STATES = (
    "observed_nonempty",
    "observed_valid_empty",
    "upstream_unavailable",
    "contract_blocked",
    "inconclusive_transient",
)

_SHA256_LENGTH = 64
_TERMINAL_TEMPORAL_AVAILABILITY_STATES = frozenset(
    {
        "nonexistent",
        "nonapplicable",
        "result_missing",
        "field_missing",
        "null",
        "present_empty",
        "populated",
    }
)


class TemporalAvailabilityLedgerError(ValueError):
    """Raised when final temporal evidence is incomplete or inconsistently bound."""


class TemporalEvidenceStateV1(StrEnum):
    """Closed input vocabulary for one exact denominator-unit observation."""

    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    NONAPPLICABLE = "nonapplicable"
    RESULT_MISSING = "result_missing"
    FIELD_MISSING = "field_missing"
    NULL = "null"
    PRESENT_EMPTY = "present_empty"
    POPULATED = "populated"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"


class TemporalAvailabilityStateV1(StrEnum):
    """Availability ledger state after evidence-basis validation."""

    NONEXISTENT = "nonexistent"
    NONAPPLICABLE = "nonapplicable"
    RESULT_MISSING = "result_missing"
    FIELD_MISSING = "field_missing"
    NULL = "null"
    PRESENT_EMPTY = "present_empty"
    POPULATED = "populated"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"


class TemporalEvidenceBasisV1(StrEnum):
    """Closed authority basis; transport symptoms are never unavailability proof."""

    EXACT_OBSERVATION_RECEIPT = "exact_observation_receipt"
    EXACT_NONAPPLICABILITY_AUTHORITY = "exact_nonapplicability_authority"
    EXACT_UPSTREAM_UNAVAILABLE_AUTHORITY = "exact_upstream_unavailable_authority"
    NO_EVIDENCE = "no_evidence"
    HTTP_404 = "http_404"
    HTTP_429 = "http_429"
    HTTP_5XX = "http_5xx"
    TIMEOUT = "timeout"
    MALFORMED_RESPONSE = "malformed_response"


_EVIDENCE_STATE_BY_BASIS: Mapping[TemporalEvidenceBasisV1, frozenset[TemporalEvidenceStateV1]] = (
    MappingProxyType(
        {
            TemporalEvidenceBasisV1.EXACT_OBSERVATION_RECEIPT: frozenset(
                {
                    TemporalEvidenceStateV1.RESULT_MISSING,
                    TemporalEvidenceStateV1.FIELD_MISSING,
                    TemporalEvidenceStateV1.NULL,
                    TemporalEvidenceStateV1.PRESENT_EMPTY,
                    TemporalEvidenceStateV1.POPULATED,
                }
            ),
            TemporalEvidenceBasisV1.EXACT_NONAPPLICABILITY_AUTHORITY: frozenset(
                {TemporalEvidenceStateV1.NONAPPLICABLE}
            ),
            TemporalEvidenceBasisV1.EXACT_UPSTREAM_UNAVAILABLE_AUTHORITY: frozenset(
                {TemporalEvidenceStateV1.UPSTREAM_UNAVAILABLE}
            ),
            TemporalEvidenceBasisV1.NO_EVIDENCE: frozenset(
                {TemporalEvidenceStateV1.EVIDENCE_INSUFFICIENT}
            ),
            TemporalEvidenceBasisV1.HTTP_404: frozenset(
                {TemporalEvidenceStateV1.EVIDENCE_INSUFFICIENT}
            ),
            TemporalEvidenceBasisV1.HTTP_429: frozenset(
                {TemporalEvidenceStateV1.EVIDENCE_INSUFFICIENT}
            ),
            TemporalEvidenceBasisV1.HTTP_5XX: frozenset(
                {TemporalEvidenceStateV1.EVIDENCE_INSUFFICIENT}
            ),
            TemporalEvidenceBasisV1.TIMEOUT: frozenset(
                {TemporalEvidenceStateV1.EVIDENCE_INSUFFICIENT}
            ),
            TemporalEvidenceBasisV1.MALFORMED_RESPONSE: frozenset(
                {TemporalEvidenceStateV1.EVIDENCE_INSUFFICIENT}
            ),
        }
    )
)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if (
        type(value) is not str
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TemporalAvailabilityLedgerError(f"{field_name} must be an exact lowercase SHA-256")
    return value


def _require_text(value: object, *, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 1_024
        or any(ord(character) < 0x20 for character in value)
    ):
        raise TemporalAvailabilityLedgerError(
            f"{field_name} must be exact bounded non-control text"
        )
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise TemporalAvailabilityLedgerError(f"{field_name} must be a nonnegative integer")
    return value


@dataclass(frozen=True, slots=True)
class TemporalAuthorityBindingsV1:
    """Exact upstream, denominator, and committed-checkpoint trust bindings."""

    authority_generation_sha256: str
    request_universe_generation_sha256: str
    request_universe_terminal_receipt_sha256: str
    request_universe_independent_proof_sha256: str
    checkpoint_transaction_sha256: str
    checkpoint_database_sha256: str
    checkpoint_w2_authority_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "authority_generation_sha256",
            "request_universe_generation_sha256",
            "request_universe_terminal_receipt_sha256",
            "request_universe_independent_proof_sha256",
            "checkpoint_transaction_sha256",
            "checkpoint_database_sha256",
            "checkpoint_w2_authority_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)

    @property
    def identity_sha256(self) -> str:
        return _canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "authority_generation_sha256": self.authority_generation_sha256,
            "request_universe_generation_sha256": self.request_universe_generation_sha256,
            "request_universe_terminal_receipt_sha256": (
                self.request_universe_terminal_receipt_sha256
            ),
            "request_universe_independent_proof_sha256": (
                self.request_universe_independent_proof_sha256
            ),
            "checkpoint_transaction_sha256": self.checkpoint_transaction_sha256,
            "checkpoint_database_sha256": self.checkpoint_database_sha256,
            "checkpoint_w2_authority_sha256": self.checkpoint_w2_authority_sha256,
        }


@dataclass(frozen=True, slots=True)
class TemporalAvailabilityUnitV1:
    """One exact field/route/request/competition/season-type denominator interval."""

    unit_id: str
    authority: TemporalAuthorityBindingsV1
    route_id: str
    provider_endpoint_id: str
    provider_result_set_name: str | None
    provider_result_set_ordinal: int | None
    request_scope_sha256: str
    competition_identity_sha256: str
    season_type_identity_sha256: str
    season_type: str
    field_occurrence_id: str
    provider_field: str
    field_occurrence_ordinal: int
    season_start: int
    season_end: int

    def __post_init__(self) -> None:
        if type(self.authority) is not TemporalAuthorityBindingsV1:
            raise TemporalAvailabilityLedgerError(
                "temporal unit authority must use the exact binding DTO"
            )
        for field_name in (
            "route_id",
            "provider_endpoint_id",
            "season_type",
            "field_occurrence_id",
            "provider_field",
        ):
            _require_text(getattr(self, field_name), field_name=field_name)
        if self.provider_result_set_name is None:
            if self.provider_result_set_ordinal is not None:
                raise TemporalAvailabilityLedgerError(
                    "result-set name and ordinal must both be absent or present"
                )
        else:
            _require_text(
                self.provider_result_set_name,
                field_name="provider_result_set_name",
            )
            _require_nonnegative_int(
                self.provider_result_set_ordinal,
                field_name="provider_result_set_ordinal",
            )
        for field_name in (
            "request_scope_sha256",
            "competition_identity_sha256",
            "season_type_identity_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_nonnegative_int(
            self.field_occurrence_ordinal,
            field_name="field_occurrence_ordinal",
        )
        if type(self.season_start) is not int or self.season_start < 1946:
            raise TemporalAvailabilityLedgerError(
                "season_start must be an integer at or after 1946"
            )
        if type(self.season_end) is not int or self.season_end < self.season_start:
            raise TemporalAvailabilityLedgerError(
                "season_end must be an integer at or after season_start"
            )
        expected = f"temporal-unit-v1:{_canonical_sha256(self._identity_payload())}"
        if self.unit_id != expected:
            raise TemporalAvailabilityLedgerError(
                "temporal unit ID differs from its exact authority and scope identity"
            )

    @classmethod
    def build(
        cls,
        *,
        authority: TemporalAuthorityBindingsV1,
        route_id: str,
        provider_endpoint_id: str,
        provider_result_set_name: str | None,
        provider_result_set_ordinal: int | None,
        request_scope_sha256: str,
        competition_identity_sha256: str,
        season_type_identity_sha256: str,
        season_type: str,
        field_occurrence_id: str,
        provider_field: str,
        field_occurrence_ordinal: int,
        season_start: int,
        season_end: int,
    ) -> TemporalAvailabilityUnitV1:
        values: dict[str, object] = {
            "authority": authority,
            "route_id": route_id,
            "provider_endpoint_id": provider_endpoint_id,
            "provider_result_set_name": provider_result_set_name,
            "provider_result_set_ordinal": provider_result_set_ordinal,
            "request_scope_sha256": request_scope_sha256,
            "competition_identity_sha256": competition_identity_sha256,
            "season_type_identity_sha256": season_type_identity_sha256,
            "season_type": season_type,
            "field_occurrence_id": field_occurrence_id,
            "provider_field": provider_field,
            "field_occurrence_ordinal": field_occurrence_ordinal,
            "season_start": season_start,
            "season_end": season_end,
        }
        identity = {
            "schema_version": 1,
            "kind": "temporal_availability_unit_v1",
            "authority": authority.to_dict(),
            "route_id": route_id,
            "provider_endpoint_id": provider_endpoint_id,
            "provider_result_set_name": provider_result_set_name,
            "provider_result_set_ordinal": provider_result_set_ordinal,
            "request_scope_sha256": request_scope_sha256,
            "competition_identity_sha256": competition_identity_sha256,
            "season_type_identity_sha256": season_type_identity_sha256,
            "season_type": season_type,
            "field_occurrence_id": field_occurrence_id,
            "provider_field": provider_field,
            "field_occurrence_ordinal": field_occurrence_ordinal,
            "season_start": season_start,
            "season_end": season_end,
        }
        return cls(
            unit_id=f"temporal-unit-v1:{_canonical_sha256(identity)}",
            **values,
        )

    def _identity_payload_unchecked(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "temporal_availability_unit_v1",
            "authority": self.authority.to_dict(),
            "route_id": self.route_id,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_result_set_name": self.provider_result_set_name,
            "provider_result_set_ordinal": self.provider_result_set_ordinal,
            "request_scope_sha256": self.request_scope_sha256,
            "competition_identity_sha256": self.competition_identity_sha256,
            "season_type_identity_sha256": self.season_type_identity_sha256,
            "season_type": self.season_type,
            "field_occurrence_id": self.field_occurrence_id,
            "provider_field": self.provider_field,
            "field_occurrence_ordinal": self.field_occurrence_ordinal,
            "season_start": self.season_start,
            "season_end": self.season_end,
        }

    def _identity_payload(self) -> dict[str, object]:
        return self._identity_payload_unchecked()

    def group_identity_payload(self) -> dict[str, object]:
        payload = self._identity_payload()
        payload.pop("season_start")
        payload.pop("season_end")
        return payload

    @property
    def group_identity_sha256(self) -> str:
        return _canonical_sha256(self.group_identity_payload())

    def to_dict(self) -> dict[str, object]:
        return {"unit_id": self.unit_id, **self._identity_payload()}


@dataclass(frozen=True, slots=True)
class TemporalRevalidationPolicyV1:
    """Deterministic staleness policy applied to every terminal evidence row."""

    policy_id: str
    as_of_date: date
    current_window_start_season: int
    historical_max_age_days: int
    current_max_age_days: int
    unavailable_max_age_days: int

    def __post_init__(self) -> None:
        _require_text(self.policy_id, field_name="policy_id")
        if type(self.as_of_date) is not date:
            raise TemporalAvailabilityLedgerError("as_of_date must be an exact date")
        if (
            type(self.current_window_start_season) is not int
            or self.current_window_start_season < 1946
        ):
            raise TemporalAvailabilityLedgerError(
                "current_window_start_season must be at or after 1946"
            )
        for field_name in (
            "historical_max_age_days",
            "current_max_age_days",
            "unavailable_max_age_days",
        ):
            _require_nonnegative_int(getattr(self, field_name), field_name=field_name)

    @property
    def digest(self) -> str:
        return _canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "temporal_revalidation_policy_v1",
            "policy_id": self.policy_id,
            "as_of_date": self.as_of_date.isoformat(),
            "current_window_start_season": self.current_window_start_season,
            "historical_max_age_days": self.historical_max_age_days,
            "current_max_age_days": self.current_max_age_days,
            "unavailable_max_age_days": self.unavailable_max_age_days,
        }


def _upstream_unavailable_identity(
    *,
    unit: TemporalAvailabilityUnitV1,
    evidence_authority_sha256: str,
) -> str:
    return _canonical_sha256(
        {
            "schema_version": 1,
            "kind": "exact_upstream_unavailable_identity_v1",
            "unit": unit.to_dict(),
            "evidence_authority_sha256": evidence_authority_sha256,
            "classification": "upstream_unavailable",
        }
    )


@dataclass(frozen=True, slots=True)
class TemporalAvailabilityEvidenceV1:
    """One exact observation or explicitly nonauthoritative failed attempt."""

    evidence_id: str
    unit: TemporalAvailabilityUnitV1
    state: TemporalEvidenceStateV1
    basis: TemporalEvidenceBasisV1
    observed_on: date | None
    evidence_authority_sha256: str | None
    upstream_unavailable_identity_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.unit) is not TemporalAvailabilityUnitV1:
            raise TemporalAvailabilityLedgerError(
                "temporal evidence must embed an exact denominator unit"
            )
        if type(self.state) is not TemporalEvidenceStateV1:
            raise TemporalAvailabilityLedgerError(
                "temporal evidence state must use the exact closed enum"
            )
        if type(self.basis) is not TemporalEvidenceBasisV1:
            raise TemporalAvailabilityLedgerError(
                "temporal evidence basis must use the exact closed enum"
            )
        if self.state not in _EVIDENCE_STATE_BY_BASIS[self.basis]:
            raise TemporalAvailabilityLedgerError(
                "temporal evidence state is incompatible with its authority basis"
            )
        if self.basis is TemporalEvidenceBasisV1.NO_EVIDENCE:
            if (
                self.observed_on is not None
                or self.evidence_authority_sha256 is not None
                or self.upstream_unavailable_identity_sha256 is not None
            ):
                raise TemporalAvailabilityLedgerError(
                    "no-evidence rows cannot carry fabricated receipt identity"
                )
        else:
            if type(self.observed_on) is not date:
                raise TemporalAvailabilityLedgerError(
                    "observed evidence must carry an exact observation date"
                )
            _require_sha256(
                self.evidence_authority_sha256,
                field_name="evidence_authority_sha256",
            )
        if self.basis is TemporalEvidenceBasisV1.EXACT_UPSTREAM_UNAVAILABLE_AUTHORITY:
            assert self.evidence_authority_sha256 is not None
            expected_unavailable = _upstream_unavailable_identity(
                unit=self.unit,
                evidence_authority_sha256=self.evidence_authority_sha256,
            )
            if self.upstream_unavailable_identity_sha256 != expected_unavailable:
                raise TemporalAvailabilityLedgerError(
                    "upstream-unavailable evidence lacks its exact evidence identity"
                )
        elif self.upstream_unavailable_identity_sha256 is not None:
            raise TemporalAvailabilityLedgerError(
                "only exact upstream-unavailable evidence may carry that identity"
            )
        expected_id = f"temporal-evidence-v1:{_canonical_sha256(self._identity_payload())}"
        if self.evidence_id != expected_id:
            raise TemporalAvailabilityLedgerError(
                "temporal evidence ID differs from its exact unit and receipt identity"
            )

    @classmethod
    def build(
        cls,
        *,
        unit: TemporalAvailabilityUnitV1,
        state: TemporalEvidenceStateV1,
        basis: TemporalEvidenceBasisV1,
        observed_on: date | None,
        evidence_authority_sha256: str | None,
    ) -> TemporalAvailabilityEvidenceV1:
        unavailable_identity = None
        if basis is TemporalEvidenceBasisV1.EXACT_UPSTREAM_UNAVAILABLE_AUTHORITY:
            if evidence_authority_sha256 is None:
                raise TemporalAvailabilityLedgerError(
                    "upstream-unavailable evidence requires receipt authority"
                )
            unavailable_identity = _upstream_unavailable_identity(
                unit=unit,
                evidence_authority_sha256=evidence_authority_sha256,
            )
        payload = {
            "schema_version": 1,
            "kind": "temporal_availability_evidence_v1",
            "unit": unit.to_dict(),
            "state": state.value,
            "basis": basis.value,
            "observed_on": observed_on.isoformat() if observed_on is not None else None,
            "evidence_authority_sha256": evidence_authority_sha256,
            "upstream_unavailable_identity_sha256": unavailable_identity,
        }
        return cls(
            evidence_id=f"temporal-evidence-v1:{_canonical_sha256(payload)}",
            unit=unit,
            state=state,
            basis=basis,
            observed_on=observed_on,
            evidence_authority_sha256=evidence_authority_sha256,
            upstream_unavailable_identity_sha256=unavailable_identity,
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "temporal_availability_evidence_v1",
            "unit": self.unit.to_dict(),
            "state": self.state.value,
            "basis": self.basis.value,
            "observed_on": (self.observed_on.isoformat() if self.observed_on is not None else None),
            "evidence_authority_sha256": self.evidence_authority_sha256,
            "upstream_unavailable_identity_sha256": (self.upstream_unavailable_identity_sha256),
        }

    def to_dict(self) -> dict[str, object]:
        return {"evidence_id": self.evidence_id, **self._identity_payload()}


@dataclass(frozen=True, slots=True)
class TemporalAvailabilityIntervalV1:
    """One denominator interval with a lossless final evidence disposition."""

    unit_id: str
    group_identity_sha256: str
    season_start: int
    season_end: int
    state: TemporalAvailabilityStateV1
    evidence_id: str | None
    evidence_basis: TemporalEvidenceBasisV1
    observed_on: date | None
    revalidation_required: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "group_identity_sha256": self.group_identity_sha256,
            "season_start": self.season_start,
            "season_end": self.season_end,
            "state": self.state.value,
            "evidence_id": self.evidence_id,
            "evidence_basis": self.evidence_basis.value,
            "observed_on": (self.observed_on.isoformat() if self.observed_on is not None else None),
            "revalidation_required": self.revalidation_required,
        }


@dataclass(frozen=True, slots=True)
class TemporalAvailabilityGapV1:
    """One explicit uncovered internal period; gaps are never silently bridged."""

    group_identity_sha256: str
    previous_unit_id: str
    next_unit_id: str
    season_start: int
    season_end: int

    def to_dict(self) -> dict[str, object]:
        return {
            "group_identity_sha256": self.group_identity_sha256,
            "previous_unit_id": self.previous_unit_id,
            "next_unit_id": self.next_unit_id,
            "season_start": self.season_start,
            "season_end": self.season_end,
        }


@dataclass(frozen=True, slots=True)
class TemporalAvailabilityEvidenceLedgerV1:
    """Final exact-denominator temporal ledger; green is entirely evidence-derived."""

    authority: TemporalAuthorityBindingsV1
    revalidation_policy: TemporalRevalidationPolicyV1
    required_units: tuple[TemporalAvailabilityUnitV1, ...]
    evidence: tuple[TemporalAvailabilityEvidenceV1, ...]
    intervals: tuple[TemporalAvailabilityIntervalV1, ...]
    internal_gaps: tuple[TemporalAvailabilityGapV1, ...]
    blocker_counts: tuple[tuple[str, int], ...]
    digest: str
    _by_unit_id: Mapping[str, TemporalAvailabilityIntervalV1]

    @property
    def by_unit_id(self) -> Mapping[str, TemporalAvailabilityIntervalV1]:
        return self._by_unit_id

    @property
    def model_green(self) -> bool:
        return (
            not self.blocker_counts
            and not self.internal_gaps
            and len(self.intervals) == len(self.required_units)
            and all(
                interval.state.value in _TERMINAL_TEMPORAL_AVAILABILITY_STATES
                and not interval.revalidation_required
                for interval in self.intervals
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "temporal_availability_evidence_ledger_v1",
            "authority": self.authority.to_dict(),
            "revalidation_policy": self.revalidation_policy.to_dict(),
            "required_units": [unit.to_dict() for unit in self.required_units],
            "evidence": [item.to_dict() for item in self.evidence],
            "intervals": [item.to_dict() for item in self.intervals],
            "internal_gaps": [item.to_dict() for item in self.internal_gaps],
            "blocker_counts": dict(self.blocker_counts),
            "digest": self.digest,
            "model_green": self.model_green,
        }


def _availability_state(
    evidence_state: TemporalEvidenceStateV1,
) -> TemporalAvailabilityStateV1:
    if evidence_state is TemporalEvidenceStateV1.UPSTREAM_UNAVAILABLE:
        return TemporalAvailabilityStateV1.NONEXISTENT
    return TemporalAvailabilityStateV1(evidence_state.value)


def _evidence_requires_revalidation(
    *,
    unit: TemporalAvailabilityUnitV1,
    evidence: TemporalAvailabilityEvidenceV1 | None,
    policy: TemporalRevalidationPolicyV1,
) -> bool:
    if evidence is None or evidence.state is TemporalEvidenceStateV1.EVIDENCE_INSUFFICIENT:
        return True
    assert evidence.observed_on is not None
    age_days = (policy.as_of_date - evidence.observed_on).days
    if age_days < 0:
        raise TemporalAvailabilityLedgerError(
            "temporal evidence observation date is after the policy as-of date"
        )
    if evidence.state is TemporalEvidenceStateV1.UPSTREAM_UNAVAILABLE:
        maximum_age = policy.unavailable_max_age_days
    elif unit.season_end >= policy.current_window_start_season:
        maximum_age = policy.current_max_age_days
    else:
        maximum_age = policy.historical_max_age_days
    return age_days > maximum_age


def _unit_sort_key(unit: TemporalAvailabilityUnitV1) -> tuple[object, ...]:
    return (
        unit.group_identity_sha256,
        unit.season_start,
        unit.season_end,
        unit.unit_id,
    )


def _validate_units_and_find_gaps(
    units: Sequence[TemporalAvailabilityUnitV1],
    *,
    authority: TemporalAuthorityBindingsV1,
) -> tuple[TemporalAvailabilityGapV1, ...]:
    if not units:
        raise TemporalAvailabilityLedgerError("temporal availability denominator cannot be empty")
    unit_ids: set[str] = set()
    grouped: dict[str, list[TemporalAvailabilityUnitV1]] = defaultdict(list)
    for unit in units:
        if type(unit) is not TemporalAvailabilityUnitV1:
            raise TemporalAvailabilityLedgerError(
                "temporal denominator contains a non-exact unit DTO"
            )
        if unit.authority != authority:
            raise TemporalAvailabilityLedgerError(
                "temporal denominator contains a foreign authority generation"
            )
        if unit.unit_id in unit_ids:
            raise TemporalAvailabilityLedgerError("temporal denominator contains a duplicate unit")
        unit_ids.add(unit.unit_id)
        grouped[unit.group_identity_sha256].append(unit)

    gaps: list[TemporalAvailabilityGapV1] = []
    for group_identity, values in sorted(grouped.items()):
        ordered = sorted(values, key=_unit_sort_key)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.season_start <= previous.season_end:
                raise TemporalAvailabilityLedgerError(
                    "temporal denominator intervals overlap within one exact field scope"
                )
            if current.season_start > previous.season_end + 1:
                gaps.append(
                    TemporalAvailabilityGapV1(
                        group_identity_sha256=group_identity,
                        previous_unit_id=previous.unit_id,
                        next_unit_id=current.unit_id,
                        season_start=previous.season_end + 1,
                        season_end=current.season_start - 1,
                    )
                )
    return tuple(gaps)


def _temporal_ledger_digest_payload(
    *,
    authority: TemporalAuthorityBindingsV1,
    revalidation_policy: TemporalRevalidationPolicyV1,
    required_units: Sequence[TemporalAvailabilityUnitV1],
    evidence: Sequence[TemporalAvailabilityEvidenceV1],
    intervals: Sequence[TemporalAvailabilityIntervalV1],
    internal_gaps: Sequence[TemporalAvailabilityGapV1],
    blocker_counts: Sequence[tuple[str, int]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "temporal_availability_evidence_ledger_v1",
        "authority": authority.to_dict(),
        "revalidation_policy": revalidation_policy.to_dict(),
        "required_units": [unit.to_dict() for unit in required_units],
        "evidence": [item.to_dict() for item in evidence],
        "intervals": [item.to_dict() for item in intervals],
        "internal_gaps": [item.to_dict() for item in internal_gaps],
        "blocker_counts": dict(blocker_counts),
    }


def _compile_temporal_availability_evidence_ledger_v1(
    *,
    authority: TemporalAuthorityBindingsV1,
    required_units: Sequence[TemporalAvailabilityUnitV1],
    evidence: Sequence[TemporalAvailabilityEvidenceV1],
    revalidation_policy: TemporalRevalidationPolicyV1,
) -> TemporalAvailabilityEvidenceLedgerV1:
    if type(authority) is not TemporalAuthorityBindingsV1:
        raise TemporalAvailabilityLedgerError(
            "temporal ledger authority must use the exact binding DTO"
        )
    if type(revalidation_policy) is not TemporalRevalidationPolicyV1:
        raise TemporalAvailabilityLedgerError(
            "temporal ledger revalidation policy must use the exact DTO"
        )
    ordered_units = tuple(sorted(required_units, key=_unit_sort_key))
    internal_gaps = _validate_units_and_find_gaps(ordered_units, authority=authority)
    unit_by_id = {unit.unit_id: unit for unit in ordered_units}

    evidence_by_unit: dict[str, TemporalAvailabilityEvidenceV1] = {}
    for item in evidence:
        if type(item) is not TemporalAvailabilityEvidenceV1:
            raise TemporalAvailabilityLedgerError(
                "temporal ledger contains a non-exact evidence DTO"
            )
        expected_unit = unit_by_id.get(item.unit.unit_id)
        if expected_unit is None:
            raise TemporalAvailabilityLedgerError(
                "temporal ledger contains extra or foreign evidence"
            )
        if item.unit != expected_unit or item.unit.authority != authority:
            raise TemporalAvailabilityLedgerError(
                "temporal ledger evidence has an ambiguous or foreign identity"
            )
        if item.unit.unit_id in evidence_by_unit:
            raise TemporalAvailabilityLedgerError(
                "temporal ledger contains duplicate evidence for one required unit"
            )
        evidence_by_unit[item.unit.unit_id] = item

    ordered_evidence = tuple(
        evidence_by_unit[unit.unit_id] for unit in ordered_units if unit.unit_id in evidence_by_unit
    )
    blockers: Counter[str] = Counter()
    if internal_gaps:
        blockers["denominator_internal_gap"] = len(internal_gaps)
    intervals: list[TemporalAvailabilityIntervalV1] = []
    for unit in ordered_units:
        item = evidence_by_unit.get(unit.unit_id)
        if item is None:
            blockers["required_unit_evidence_missing"] += 1
            blockers["evidence_insufficient"] += 1
            basis = TemporalEvidenceBasisV1.NO_EVIDENCE
            state = TemporalAvailabilityStateV1.EVIDENCE_INSUFFICIENT
            observed_on = None
            evidence_id = None
        else:
            basis = item.basis
            state = _availability_state(item.state)
            observed_on = item.observed_on
            evidence_id = item.evidence_id
            if state is TemporalAvailabilityStateV1.EVIDENCE_INSUFFICIENT:
                blockers["evidence_insufficient"] += 1
                blockers[f"nonauthoritative_{basis.value}"] += 1
        revalidation_required = _evidence_requires_revalidation(
            unit=unit,
            evidence=item,
            policy=revalidation_policy,
        )
        if revalidation_required:
            blockers["revalidation_required"] += 1
        intervals.append(
            TemporalAvailabilityIntervalV1(
                unit_id=unit.unit_id,
                group_identity_sha256=unit.group_identity_sha256,
                season_start=unit.season_start,
                season_end=unit.season_end,
                state=state,
                evidence_id=evidence_id,
                evidence_basis=basis,
                observed_on=observed_on,
                revalidation_required=revalidation_required,
            )
        )

    blocker_counts = tuple(sorted(blockers.items()))
    interval_tuple = tuple(intervals)
    payload = _temporal_ledger_digest_payload(
        authority=authority,
        revalidation_policy=revalidation_policy,
        required_units=ordered_units,
        evidence=ordered_evidence,
        intervals=interval_tuple,
        internal_gaps=internal_gaps,
        blocker_counts=blocker_counts,
    )
    return TemporalAvailabilityEvidenceLedgerV1(
        authority=authority,
        revalidation_policy=revalidation_policy,
        required_units=ordered_units,
        evidence=ordered_evidence,
        intervals=interval_tuple,
        internal_gaps=internal_gaps,
        blocker_counts=blocker_counts,
        digest=_canonical_sha256(payload),
        _by_unit_id=MappingProxyType({interval.unit_id: interval for interval in interval_tuple}),
    )


def compile_temporal_availability_evidence_ledger_v1(
    *,
    authority: TemporalAuthorityBindingsV1,
    required_units: Sequence[TemporalAvailabilityUnitV1],
    evidence: Sequence[TemporalAvailabilityEvidenceV1] = (),
    revalidation_policy: TemporalRevalidationPolicyV1,
) -> TemporalAvailabilityEvidenceLedgerV1:
    """Compile a final evidence ledger without issuing or inferring provider calls.

    Missing observations remain explicit red ``evidence_insufficient`` rows.
    Extra, duplicate, foreign, overlapping, or semantically ambiguous input is
    rejected instead of being normalized into an availability claim.
    """

    ledger = _compile_temporal_availability_evidence_ledger_v1(
        authority=authority,
        required_units=required_units,
        evidence=evidence,
        revalidation_policy=revalidation_policy,
    )
    validate_temporal_availability_evidence_ledger_v1(ledger)
    return ledger


def validate_temporal_availability_evidence_ledger_v1(
    ledger: TemporalAvailabilityEvidenceLedgerV1,
) -> None:
    """Recompile the exact ledger and reject digest, index, or summary drift."""

    if type(ledger) is not TemporalAvailabilityEvidenceLedgerV1:
        raise TemporalAvailabilityLedgerError("temporal availability ledger must use the exact DTO")
    expected = _compile_temporal_availability_evidence_ledger_v1(
        authority=ledger.authority,
        required_units=ledger.required_units,
        evidence=ledger.evidence,
        revalidation_policy=ledger.revalidation_policy,
    )
    if ledger != expected:
        raise TemporalAvailabilityLedgerError(
            "temporal availability ledger differs from its exact evidence compilation"
        )


@dataclass(frozen=True, slots=True)
class TemporalEvidenceInterval:
    """One bounded legacy evidence interval without an availability overclaim."""

    rule_id: str
    source_rule_ordinal: int
    endpoint_name: str
    param_pattern: str | None
    season_start: int | None
    season_end: int | None
    state: TemporalState
    evidence_disposition: EvidenceDisposition
    reason: str
    evidence_sha256: str
    revalidation_command: str

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "source_rule_ordinal": self.source_rule_ordinal,
            "endpoint_name": self.endpoint_name,
            "param_pattern": self.param_pattern,
            "season_start": self.season_start,
            "season_end": self.season_end,
            "state": self.state,
            "evidence_disposition": self.evidence_disposition,
            "reason": self.reason,
            "evidence_sha256": self.evidence_sha256,
            "revalidation_command": self.revalidation_command,
        }


@dataclass(frozen=True, slots=True)
class RouteTemporalScope:
    """Provider/result/parameter-specific temporal scope for one silver route."""

    route_id: str
    route_ordinal: int
    provider_authority_sha256: str
    endpoint_name: str
    canonical_endpoint_name: str
    provider_endpoint_id: str
    provider_result_set_name: str | None
    provider_result_set_ordinal: int | None
    param_pattern: str
    provider_required_parameters: tuple[str, ...]
    provider_optional_parameters: tuple[str, ...]
    entity_scope: str
    workload_scope: str
    supported_season_types: tuple[str, ...]
    season_type_capability: str
    sink_ready: bool
    planner_start_season: int
    planner_start_basis: PlannerStartBasis
    planner_deprecated_after: str | None
    availability_state: Literal["unknown"]
    evidence_intervals: tuple[TemporalEvidenceInterval, ...]
    revalidation_required: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "route_ordinal": self.route_ordinal,
            "provider_authority_sha256": self.provider_authority_sha256,
            "endpoint_name": self.endpoint_name,
            "canonical_endpoint_name": self.canonical_endpoint_name,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_result_set_name": self.provider_result_set_name,
            "provider_result_set_ordinal": self.provider_result_set_ordinal,
            "param_pattern": self.param_pattern,
            "provider_required_parameters": list(self.provider_required_parameters),
            "provider_optional_parameters": list(self.provider_optional_parameters),
            "entity_scope": self.entity_scope,
            "workload_scope": self.workload_scope,
            "supported_season_types": list(self.supported_season_types),
            "season_type_capability": self.season_type_capability,
            "sink_ready": self.sink_ready,
            "planner_start_season": self.planner_start_season,
            "planner_start_basis": self.planner_start_basis,
            "planner_deprecated_after": self.planner_deprecated_after,
            "availability_state": self.availability_state,
            "evidence_intervals": [item.to_dict() for item in self.evidence_intervals],
            "revalidation_required": self.revalidation_required,
        }


@dataclass(frozen=True, slots=True)
class TemporalAvailabilityContractBundle:
    """Exact route-registry temporal contract plus all migrated source rules."""

    scopes: tuple[RouteTemporalScope, ...]
    source_rules: tuple[TemporalEvidenceInterval, ...]
    digest: str
    staging_route_contract_sha256: str
    planner_start_basis_counts: tuple[tuple[str, int], ...]
    evidence_state_counts: tuple[tuple[str, int], ...]
    projected_interval_count: int
    _by_route_id: Mapping[str, RouteTemporalScope]

    @property
    def by_route_id(self) -> Mapping[str, RouteTemporalScope]:
        return self._by_route_id

    @property
    def model_green(self) -> bool:
        """Temporal evidence is intentionally incomplete until reviewed probes exist."""

        return False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "nbadb_temporal_availability_contract_bundle",
            "digest": self.digest,
            "staging_route_contract_sha256": self.staging_route_contract_sha256,
            "model_green": self.model_green,
            "summary": {
                "route_scope_count": len(self.scopes),
                "source_rule_count": len(self.source_rules),
                "projected_interval_count": self.projected_interval_count,
                "planner_start_basis_counts": dict(self.planner_start_basis_counts),
                "evidence_state_counts": dict(self.evidence_state_counts),
                "unknown_availability_scope_count": sum(
                    scope.availability_state == "unknown" for scope in self.scopes
                ),
                "revalidation_required_scope_count": sum(
                    scope.revalidation_required for scope in self.scopes
                ),
            },
            "source_rules": [item.to_dict() for item in self.source_rules],
            "scopes": [scope.to_dict() for scope in self.scopes],
        }


@dataclass(frozen=True, slots=True)
class TemporalProbePoint:
    """One bounded season boundary proposed for later authorized observation."""

    season_start: int
    purposes: tuple[str, ...]
    currently_blocked_by_rule_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "season_start": self.season_start,
            "purposes": list(self.purposes),
            "currently_blocked_by_rule_ids": list(self.currently_blocked_by_rule_ids),
        }


@dataclass(frozen=True, slots=True)
class RouteTemporalProbePlan:
    """One route-local no-network plan; it is not an executable request list."""

    route_id: str
    route_ordinal: int
    provider_authority_sha256: str
    provider_endpoint_id: str
    provider_result_set_name: str | None
    provider_result_set_ordinal: int | None
    param_pattern: str
    season_types: tuple[str, ...]
    binding_state: ProbeBindingState
    points: tuple[TemporalProbePoint, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "route_ordinal": self.route_ordinal,
            "provider_authority_sha256": self.provider_authority_sha256,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_result_set_name": self.provider_result_set_name,
            "provider_result_set_ordinal": self.provider_result_set_ordinal,
            "param_pattern": self.param_pattern,
            "season_types": list(self.season_types),
            "binding_state": self.binding_state,
            "points": [point.to_dict() for point in self.points],
        }


@dataclass(frozen=True, slots=True)
class TemporalProbePlan:
    """Deterministic bounded proposal whose execution is separately unauthorized."""

    target_season_start: int
    temporal_contract_sha256: str
    units: tuple[RouteTemporalProbePlan, ...]
    digest: str
    execution_authorized: Literal[False]
    allowed_observation_states: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "nbadb_temporal_probe_plan",
            "target_season_start": self.target_season_start,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "digest": self.digest,
            "execution_authorized": self.execution_authorized,
            "allowed_observation_states": list(self.allowed_observation_states),
            "units": [unit.to_dict() for unit in self.units],
        }


def _rule_identity_payload(rule: EndpointSupportRule, ordinal: int) -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "endpoint_name": rule.endpoint_name,
        "param_pattern": rule.pattern,
        "classification": rule.classification,
        "season_start": rule.season_start,
        "season_end": rule.season_end,
        "reason": rule.reason,
        "evidence_sha256": _canonical_sha256(rule.evidence),
        "revalidation_command": rule.revalidation_command,
    }


def _compile_source_rules(
    rules: Sequence[EndpointSupportRule],
) -> tuple[TemporalEvidenceInterval, ...]:
    compiled: list[TemporalEvidenceInterval] = []
    for ordinal, rule in enumerate(rules):
        if rule.classification != "contract_blocked":
            raise ValueError("temporal source rule has an unsupported classification")
        if (
            rule.season_start is not None
            and rule.season_end is not None
            and rule.season_end < rule.season_start
        ):
            raise ValueError("temporal source rule has a reversed interval")
        identity = _rule_identity_payload(rule, ordinal)
        compiled.append(
            TemporalEvidenceInterval(
                rule_id=f"temporal-rule-{ordinal:03d}-{_canonical_sha256(identity)[:16]}",
                source_rule_ordinal=ordinal,
                endpoint_name=rule.endpoint_name,
                param_pattern=rule.pattern,
                season_start=rule.season_start,
                season_end=rule.season_end,
                state="contract_blocked",
                evidence_disposition="legacy_bounded_rule_not_availability",
                reason=rule.reason,
                evidence_sha256=_canonical_sha256(rule.evidence),
                revalidation_command=rule.revalidation_command,
            )
        )
    return tuple(compiled)


def _endpoint_names_for_route(route: StagingRouteContract) -> frozenset[str]:
    names = {
        route.endpoint_name,
        route.canonical_endpoint_name,
        FULL_EXTRACTION_CONTRACT_ALIASES.get(route.endpoint_name, route.endpoint_name),
    }
    names.update(
        alias
        for alias, target in FULL_EXTRACTION_CONTRACT_ALIASES.items()
        if target in {route.endpoint_name, route.canonical_endpoint_name}
    )
    return frozenset(names)


def _intervals_for_route(
    route: StagingRouteContract,
    source_rules: Sequence[TemporalEvidenceInterval],
) -> tuple[TemporalEvidenceInterval, ...]:
    names = _endpoint_names_for_route(route)
    intervals = tuple(
        rule
        for rule in source_rules
        if rule.endpoint_name in names
        and (rule.param_pattern is None or rule.param_pattern == route.param_pattern)
    )
    return tuple(
        sorted(
            intervals,
            key=lambda item: (
                -1 if item.season_start is None else item.season_start,
                10**9 if item.season_end is None else item.season_end,
                item.source_rule_ordinal,
            ),
        )
    )


def _validate_nonoverlap(intervals: Sequence[TemporalEvidenceInterval]) -> None:
    by_scope: dict[tuple[str, str | None], list[TemporalEvidenceInterval]] = defaultdict(list)
    for interval in intervals:
        by_scope[(interval.endpoint_name, interval.param_pattern)].append(interval)
    for values in by_scope.values():
        ordered = sorted(
            values,
            key=lambda item: (
                -1 if item.season_start is None else item.season_start,
                10**9 if item.season_end is None else item.season_end,
            ),
        )
        previous_end: int | None = None
        for index, interval in enumerate(ordered):
            start = interval.season_start
            end = interval.season_end
            if index and (previous_end is None or start is None or start <= previous_end):
                raise ValueError("temporal source rules overlap within one endpoint scope")
            previous_end = end


def _scope_for_route(
    route: StagingRouteContract,
    intervals: tuple[TemporalEvidenceInterval, ...],
) -> RouteTemporalScope:
    if route.min_season is None:
        planner_start = FALLBACK_PLANNER_START_SEASON
        planner_basis: PlannerStartBasis = "fallback_attempt_unverified"
    else:
        planner_start = route.min_season
        planner_basis = "declared_provider_floor"
    return RouteTemporalScope(
        route_id=route.route_id,
        route_ordinal=route.ordinal,
        provider_authority_sha256=route.provider_authority_sha256,
        endpoint_name=route.endpoint_name,
        canonical_endpoint_name=route.canonical_endpoint_name,
        provider_endpoint_id=route.provider_endpoint_id,
        provider_result_set_name=route.provider_result_set_name,
        provider_result_set_ordinal=route.provider_result_set_ordinal,
        param_pattern=route.param_pattern,
        provider_required_parameters=route.provider_required_parameters,
        provider_optional_parameters=route.provider_optional_parameters,
        entity_scope=route.param_pattern,
        workload_scope=route.param_pattern,
        supported_season_types=route.supported_season_types,
        season_type_capability=route.season_type_capability,
        sink_ready=bool(route.resolved_schema_table and route.resolved_schema_class),
        planner_start_season=planner_start,
        planner_start_basis=planner_basis,
        planner_deprecated_after=route.deprecated_after,
        availability_state="unknown",
        evidence_intervals=intervals,
        revalidation_required=True,
    )


def _digest_payload(
    *,
    scopes: Sequence[RouteTemporalScope],
    source_rules: Sequence[TemporalEvidenceInterval],
    staging_route_contract_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nbadb_temporal_availability_contract_bundle",
        "staging_route_contract_sha256": staging_route_contract_sha256,
        "source_rules": [item.to_dict() for item in source_rules],
        "scopes": [scope.to_dict() for scope in scopes],
    }


def _compile_temporal_availability_contract_bundle() -> TemporalAvailabilityContractBundle:
    route_bundle = staging_route_contract_bundle()
    source_rules = _compile_source_rules(FULL_EXTRACTION_SUPPORT_RULES)
    _validate_nonoverlap(source_rules)
    scopes = tuple(
        _scope_for_route(route, _intervals_for_route(route, source_rules))
        for route in route_bundle.routes
    )
    digest = _canonical_sha256(
        _digest_payload(
            scopes=scopes,
            source_rules=source_rules,
            staging_route_contract_sha256=route_bundle.digest,
        )
    )
    bundle = TemporalAvailabilityContractBundle(
        scopes=scopes,
        source_rules=source_rules,
        digest=digest,
        staging_route_contract_sha256=route_bundle.digest,
        planner_start_basis_counts=tuple(
            sorted(Counter(scope.planner_start_basis for scope in scopes).items())
        ),
        evidence_state_counts=tuple(sorted(Counter(rule.state for rule in source_rules).items())),
        projected_interval_count=sum(len(scope.evidence_intervals) for scope in scopes),
        _by_route_id=MappingProxyType({scope.route_id: scope for scope in scopes}),
    )
    _validate_bundle_structure(bundle)
    return bundle


def _validate_bundle_structure(bundle: TemporalAvailabilityContractBundle) -> None:
    if len(bundle.scopes) != EXPECTED_ROUTE_SCOPE_COUNT:
        raise ValueError("temporal contract differs from the exact route registry")
    if len(bundle.source_rules) != EXPECTED_LEGACY_RULE_COUNT:
        raise ValueError("temporal contract must migrate exactly 149 support rules")
    if tuple(scope.route_ordinal for scope in bundle.scopes) != tuple(
        range(EXPECTED_ROUTE_SCOPE_COUNT)
    ):
        raise ValueError("temporal route ordinals are not exact and contiguous")
    route_ids = tuple(scope.route_id for scope in bundle.scopes)
    if len(set(route_ids)) != EXPECTED_ROUTE_SCOPE_COUNT:
        raise ValueError("temporal route scopes are not unique")
    if tuple(rule.source_rule_ordinal for rule in bundle.source_rules) != tuple(
        range(EXPECTED_LEGACY_RULE_COUNT)
    ):
        raise ValueError("temporal source rule ordinals are not exact and contiguous")
    if len({rule.rule_id for rule in bundle.source_rules}) != EXPECTED_LEGACY_RULE_COUNT:
        raise ValueError("temporal source rule identities are not unique")
    if any(scope.availability_state != "unknown" for scope in bundle.scopes):
        raise ValueError("temporal compiler invented an availability claim")
    if any(not scope.sink_ready for scope in bundle.scopes):
        raise ValueError("temporal compiler found an unresolved route sink")
    if any(
        interval not in bundle.source_rules
        for scope in bundle.scopes
        for interval in scope.evidence_intervals
    ):
        raise ValueError("temporal route references an unknown source rule")
    referenced = {
        interval.rule_id for scope in bundle.scopes for interval in scope.evidence_intervals
    }
    if referenced != {rule.rule_id for rule in bundle.source_rules}:
        raise ValueError("temporal source rule was not projected to a route")
    _validate_nonoverlap(bundle.source_rules)
    if dict(bundle.by_route_id) != {scope.route_id: scope for scope in bundle.scopes}:
        raise ValueError("temporal immutable route index differs from its inventory")
    expected_digest = _canonical_sha256(
        _digest_payload(
            scopes=bundle.scopes,
            source_rules=bundle.source_rules,
            staging_route_contract_sha256=bundle.staging_route_contract_sha256,
        )
    )
    if bundle.digest != expected_digest:
        raise ValueError("temporal contract digest is invalid")


@lru_cache(maxsize=1)
def temporal_availability_contract_bundle() -> TemporalAvailabilityContractBundle:
    """Return the immutable provider/result/route temporal evidence contract."""

    return _compile_temporal_availability_contract_bundle()


def validate_temporal_availability_contract_bundle(
    bundle: TemporalAvailabilityContractBundle,
) -> None:
    """Validate structure, digest, and exact equality to current pinned sources."""

    _validate_bundle_structure(bundle)
    if bundle != temporal_availability_contract_bundle():
        raise ValueError("temporal contract differs from the exact live sources")


def _probe_point_seasons(
    scope: RouteTemporalScope,
    *,
    target_season_start: int,
) -> tuple[TemporalProbePoint, ...]:
    purposes_by_season: dict[int, set[str]] = defaultdict(set)
    purposes_by_season[scope.planner_start_season].add("planner_start_boundary")
    purposes_by_season[target_season_start].add("target_season_observation")
    for interval in scope.evidence_intervals:
        if interval.season_start is not None:
            purposes_by_season[interval.season_start].add("blocked_interval_start_revalidation")
        if interval.season_end is not None:
            purposes_by_season[interval.season_end].add("blocked_interval_end_revalidation")
            if interval.season_end < target_season_start:
                purposes_by_season[interval.season_end + 1].add(
                    "first_season_after_blocked_interval"
                )

    points: list[TemporalProbePoint] = []
    for season_start in sorted(purposes_by_season):
        if season_start < scope.planner_start_season or season_start > target_season_start:
            continue
        blocked = tuple(
            interval.rule_id
            for interval in scope.evidence_intervals
            if (interval.season_start is None or interval.season_start <= season_start)
            and (interval.season_end is None or season_start <= interval.season_end)
        )
        points.append(
            TemporalProbePoint(
                season_start=season_start,
                purposes=tuple(sorted(purposes_by_season[season_start])),
                currently_blocked_by_rule_ids=blocked,
            )
        )
    if not points or len(points) > MAX_TEMPORAL_PROBE_POINTS_PER_SCOPE:
        raise ValueError("temporal probe scope is empty or exceeds its bounded point cap")
    return tuple(points)


def _probe_binding_state(scope: RouteTemporalScope) -> ProbeBindingState:
    if scope.param_pattern in {"player", "player_season", "team", "team_season"}:
        return "observed_entity_binding_required"
    if scope.param_pattern in {"game", "date", "player_team_season"}:
        return "verified_workload_binding_required"
    if scope.param_pattern in {"live", "static"}:
        return "runtime_scope"
    return "season_scope"


def _probe_plan_payload(
    *,
    target_season_start: int,
    temporal_contract_sha256: str,
    units: Sequence[RouteTemporalProbePlan],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nbadb_temporal_probe_plan",
        "target_season_start": target_season_start,
        "temporal_contract_sha256": temporal_contract_sha256,
        "execution_authorized": False,
        "allowed_observation_states": list(ALLOWED_TEMPORAL_OBSERVATION_STATES),
        "units": [unit.to_dict() for unit in units],
    }


def temporal_probe_plan(*, target_season_start: int) -> TemporalProbePlan:
    """Compile a deterministic plan without issuing or authorizing provider calls.

    Entity- and workload-scoped units intentionally omit identifiers.  Their
    ``binding_state`` requires a separately verified discovery/workload artifact
    before any future executor may construct concrete requests.
    """

    if target_season_start < FALLBACK_PLANNER_START_SEASON:
        raise ValueError("temporal probe target season predates the planner floor")
    temporal = temporal_availability_contract_bundle()
    units = tuple(
        RouteTemporalProbePlan(
            route_id=scope.route_id,
            route_ordinal=scope.route_ordinal,
            provider_authority_sha256=scope.provider_authority_sha256,
            provider_endpoint_id=scope.provider_endpoint_id,
            provider_result_set_name=scope.provider_result_set_name,
            provider_result_set_ordinal=scope.provider_result_set_ordinal,
            param_pattern=scope.param_pattern,
            season_types=scope.supported_season_types,
            binding_state=_probe_binding_state(scope),
            points=_probe_point_seasons(
                scope,
                target_season_start=target_season_start,
            ),
        )
        for scope in temporal.scopes
    )
    payload = _probe_plan_payload(
        target_season_start=target_season_start,
        temporal_contract_sha256=temporal.digest,
        units=units,
    )
    plan = TemporalProbePlan(
        target_season_start=target_season_start,
        temporal_contract_sha256=temporal.digest,
        units=units,
        digest=_canonical_sha256(payload),
        execution_authorized=False,
        allowed_observation_states=ALLOWED_TEMPORAL_OBSERVATION_STATES,
    )
    validate_temporal_probe_plan(plan)
    return plan


def validate_temporal_probe_plan(plan: TemporalProbePlan) -> None:
    """Validate bounded membership, parent binding, and no-execution state."""

    temporal = temporal_availability_contract_bundle()
    if plan.execution_authorized is not False:
        raise ValueError("temporal probe plan cannot authorize execution")
    if plan.temporal_contract_sha256 != temporal.digest:
        raise ValueError("temporal probe plan parent digest is invalid")
    if len(plan.units) != EXPECTED_ROUTE_SCOPE_COUNT:
        raise ValueError("temporal probe plan differs from the exact route registry")
    expected_ids = tuple(scope.route_id for scope in temporal.scopes)
    if tuple(unit.route_id for unit in plan.units) != expected_ids:
        raise ValueError("temporal probe plan route order or membership drifted")
    if any(
        not unit.points or len(unit.points) > MAX_TEMPORAL_PROBE_POINTS_PER_SCOPE
        for unit in plan.units
    ):
        raise ValueError("temporal probe plan exceeds its per-scope bound")
    payload = _probe_plan_payload(
        target_season_start=plan.target_season_start,
        temporal_contract_sha256=plan.temporal_contract_sha256,
        units=plan.units,
    )
    if plan.allowed_observation_states != ALLOWED_TEMPORAL_OBSERVATION_STATES:
        raise ValueError("temporal probe observation-state inventory is invalid")
    if plan.digest != _canonical_sha256(payload):
        raise ValueError("temporal probe plan digest is invalid")
