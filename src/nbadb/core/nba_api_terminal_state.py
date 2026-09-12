"""Canonical release-terminal accounting for the pinned NBA API surface.

This module is deliberately independent of request compilation, extraction,
and competition identity.  It defines the finite wire-state partition and the
typed evidence needed to call one exact request release-terminal.  The checked
JSON resource is a deterministic policy receipt, not an observation of an
upstream request.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Final, Literal, cast

if TYPE_CHECKING:
    from pathlib import Path

TERMINAL_STATE_SCHEMA_VERSION: Final = 1
NBA_API_TERMINAL_STATE_RESOURCE: Final = "nba_api_terminal_state_v1_11_4.json"

type ReleaseTerminalRequestState = Literal[
    "success_nonempty",
    "success_empty",
    "upstream_unavailable",
]
type IncompleteRequestState = Literal[
    "contract_blocked",
    "transient_failed",
    "response_contract_failed",
    "unattempted",
    "unclassified",
]
type RequestAccountingState = ReleaseTerminalRequestState | IncompleteRequestState
type ResultOccurrenceState = Literal[
    "present_nonempty",
    "present_empty",
    "absent_optional",
]

RELEASE_TERMINAL_REQUEST_STATES: Final[tuple[ReleaseTerminalRequestState, ...]] = (
    "success_nonempty",
    "success_empty",
    "upstream_unavailable",
)
INCOMPLETE_REQUEST_STATES: Final[tuple[IncompleteRequestState, ...]] = (
    "contract_blocked",
    "transient_failed",
    "response_contract_failed",
    "unattempted",
    "unclassified",
)
REQUEST_ACCOUNTING_STATES: Final[tuple[RequestAccountingState, ...]] = (
    *RELEASE_TERMINAL_REQUEST_STATES,
    *INCOMPLETE_REQUEST_STATES,
)
RESULT_OCCURRENCE_STATES: Final[tuple[ResultOccurrenceState, ...]] = (
    "present_nonempty",
    "present_empty",
    "absent_optional",
)

_REQUEST_BINDING_DOMAIN = "nbadb.nba-api.terminal-request-binding.v1"
_SUPPORT_BINDING_DOMAIN = "nbadb.nba-api.upstream-unavailable-support.v1"
_UNAVAILABLE_EVIDENCE_DOMAIN = "nbadb.nba-api.upstream-unavailable-evidence.v1"
_KIND = "nbadb_nba_api_terminal_state_authority"
_TASK_ID = "A1.3a"
_NBA_API_VERSION = "1.11.4"
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", flags=re.ASCII)
_SHA256_RE = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class NbaApiTerminalStateError(ValueError):
    """A terminal-state policy or typed evidence object is invalid."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiTerminalStateError("terminal-state value is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _domain_digest(domain: str, value: object) -> str:
    return _digest({"domain": domain, "payload": value})


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiTerminalStateError(f"{field} must be a canonical SHA-256")
    return value


def _require_safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None:
        raise NbaApiTerminalStateError(f"{field} must be a safe nonempty identifier")
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiTerminalStateError(
                f"terminal-state resource contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiTerminalStateError(
        f"terminal-state resource contains non-finite JSON constant: {value}"
    )


def _request_binding_body(
    *,
    request_surface_sha256: str,
    runtime_contract_payload_sha256: str,
    provider_authority_sha256: str,
    route_manifest_sha256: str,
    scope_sha256: str,
    provider_request_sha256: str,
    source_request_sha256: str,
    competition_authority_sha256: str,
    competition_scope_sha256: str,
    competition_requirement_sha256: str,
    role_binding_sha256: str,
    source_evidence_sha256: str,
    source_family: str,
    endpoint_id: str,
    route_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "competition_authority_sha256": competition_authority_sha256,
        "competition_requirement_sha256": competition_requirement_sha256,
        "competition_scope_sha256": competition_scope_sha256,
        "endpoint_id": endpoint_id,
        "provider_authority_sha256": provider_authority_sha256,
        "provider_request_sha256": provider_request_sha256,
        "request_surface_sha256": request_surface_sha256,
        "role_binding_sha256": role_binding_sha256,
        "route_ids": list(route_ids),
        "route_manifest_sha256": route_manifest_sha256,
        "runtime_contract_payload_sha256": runtime_contract_payload_sha256,
        "scope_sha256": scope_sha256,
        "source_evidence_sha256": source_evidence_sha256,
        "source_family": source_family,
        "source_request_sha256": source_request_sha256,
    }


@dataclass(frozen=True, slots=True)
class TerminalRequestBinding:
    """All authorities needed to identify one competition-qualified request."""

    request_surface_sha256: str
    runtime_contract_payload_sha256: str
    provider_authority_sha256: str
    route_manifest_sha256: str
    scope_sha256: str
    provider_request_sha256: str
    source_request_sha256: str
    competition_authority_sha256: str
    competition_scope_sha256: str
    competition_requirement_sha256: str
    role_binding_sha256: str
    source_evidence_sha256: str
    source_family: str
    endpoint_id: str
    route_ids: tuple[str, ...]
    request_binding_sha256: str

    def __post_init__(self) -> None:
        for field in (
            "request_surface_sha256",
            "runtime_contract_payload_sha256",
            "provider_authority_sha256",
            "route_manifest_sha256",
            "scope_sha256",
            "provider_request_sha256",
            "source_request_sha256",
            "competition_authority_sha256",
            "competition_scope_sha256",
            "competition_requirement_sha256",
            "role_binding_sha256",
            "source_evidence_sha256",
            "request_binding_sha256",
        ):
            _require_digest(getattr(self, field), field)
        if self.source_family not in {"stats", "live"}:
            raise NbaApiTerminalStateError("source_family must be stats or live")
        _require_safe_id(self.endpoint_id, "endpoint_id")
        if (
            type(self.route_ids) is not tuple
            or not self.route_ids
            or self.route_ids != tuple(sorted(set(self.route_ids)))
            or any(_SAFE_ID_RE.fullmatch(route_id) is None for route_id in self.route_ids)
        ):
            raise NbaApiTerminalStateError("route_ids must be sorted, unique, safe, and nonempty")
        expected = _domain_digest(_REQUEST_BINDING_DOMAIN, self._body())
        if self.request_binding_sha256 != expected:
            raise NbaApiTerminalStateError("request binding digest is invalid")

    def _body(self) -> dict[str, object]:
        return _request_binding_body(
            request_surface_sha256=self.request_surface_sha256,
            runtime_contract_payload_sha256=self.runtime_contract_payload_sha256,
            provider_authority_sha256=self.provider_authority_sha256,
            route_manifest_sha256=self.route_manifest_sha256,
            scope_sha256=self.scope_sha256,
            provider_request_sha256=self.provider_request_sha256,
            source_request_sha256=self.source_request_sha256,
            competition_authority_sha256=self.competition_authority_sha256,
            competition_scope_sha256=self.competition_scope_sha256,
            competition_requirement_sha256=self.competition_requirement_sha256,
            role_binding_sha256=self.role_binding_sha256,
            source_evidence_sha256=self.source_evidence_sha256,
            source_family=self.source_family,
            endpoint_id=self.endpoint_id,
            route_ids=self.route_ids,
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "request_binding_sha256": self.request_binding_sha256}


def _support_binding_body(
    authority: UpstreamUnavailableSupportAuthority,
) -> dict[str, object]:
    return {
        "authority_kind": authority.authority_kind,
        "authority_version": authority.authority_version,
        "competition_scope_sha256": authority.competition_scope_sha256,
        "endpoint_id": authority.endpoint_id,
        "independent_verifier_id": authority.independent_verifier_id,
        "independent_verifier_sha256": authority.independent_verifier_sha256,
        "provider_authority_sha256": authority.provider_authority_sha256,
        "provider_request_sha256": authority.provider_request_sha256,
        "reason_code": authority.reason_code,
        "request_surface_sha256": authority.request_surface_sha256,
        "scope_sha256": authority.scope_sha256,
        "source_family": authority.source_family,
        "source_request_sha256": authority.source_request_sha256,
        "status": authority.status,
        "support_authority_sha256": authority.support_authority_sha256,
        "support_cell_id": authority.support_cell_id,
        "support_cell_sha256": authority.support_cell_sha256,
    }


@dataclass(frozen=True, slots=True)
class UpstreamUnavailableSupportAuthority:
    """Independent, exact-scope support cell for provider unavailability."""

    authority_kind: str
    authority_version: int
    support_authority_sha256: str
    support_cell_id: str
    support_cell_sha256: str
    provider_authority_sha256: str
    request_surface_sha256: str
    source_family: str
    endpoint_id: str
    scope_sha256: str
    competition_scope_sha256: str
    source_request_sha256: str
    provider_request_sha256: str
    status: str
    reason_code: str
    independent_verifier_id: str
    independent_verifier_sha256: str
    support_binding_sha256: str

    def __post_init__(self) -> None:
        _require_safe_id(self.authority_kind, "authority_kind")
        if (
            isinstance(self.authority_version, bool)
            or not isinstance(self.authority_version, int)
            or self.authority_version <= 0
        ):
            raise NbaApiTerminalStateError("authority_version must be a positive integer")
        for field in (
            "support_authority_sha256",
            "support_cell_sha256",
            "provider_authority_sha256",
            "request_surface_sha256",
            "scope_sha256",
            "competition_scope_sha256",
            "source_request_sha256",
            "provider_request_sha256",
            "independent_verifier_sha256",
            "support_binding_sha256",
        ):
            _require_digest(getattr(self, field), field)
        for field in (
            "support_cell_id",
            "endpoint_id",
            "reason_code",
            "independent_verifier_id",
        ):
            _require_safe_id(getattr(self, field), field)
        if self.source_family not in {"stats", "live"}:
            raise NbaApiTerminalStateError("source_family must be stats or live")
        if self.status != "upstream_unavailable":
            raise NbaApiTerminalStateError("support authority status must be upstream_unavailable")
        expected = _domain_digest(_SUPPORT_BINDING_DOMAIN, _support_binding_body(self))
        if self.support_binding_sha256 != expected:
            raise NbaApiTerminalStateError("support binding digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            **_support_binding_body(self),
            "support_binding_sha256": self.support_binding_sha256,
        }


def _unavailable_evidence_body(
    request_binding: TerminalRequestBinding,
    support_authority: UpstreamUnavailableSupportAuthority,
) -> dict[str, object]:
    return {
        "request_binding": request_binding.to_dict(),
        "state": "upstream_unavailable",
        "support_authority": support_authority.to_dict(),
    }


@dataclass(frozen=True, slots=True)
class TypedUpstreamUnavailableEvidence:
    """Complete typed evidence for the only non-response terminal state."""

    request_binding: TerminalRequestBinding
    support_authority: UpstreamUnavailableSupportAuthority
    state: Literal["upstream_unavailable"]
    unavailable_evidence_sha256: str

    def __post_init__(self) -> None:
        if type(self.request_binding) is not TerminalRequestBinding:
            raise NbaApiTerminalStateError("typed evidence request binding is invalid")
        if type(self.support_authority) is not UpstreamUnavailableSupportAuthority:
            raise NbaApiTerminalStateError("typed evidence support authority is invalid")
        if self.state != "upstream_unavailable":
            raise NbaApiTerminalStateError("typed evidence state must be upstream_unavailable")
        request = self.request_binding
        support = self.support_authority
        for field in (
            "request_surface_sha256",
            "provider_authority_sha256",
            "provider_request_sha256",
            "scope_sha256",
            "competition_scope_sha256",
            "source_request_sha256",
            "source_family",
            "endpoint_id",
        ):
            if getattr(request, field) != getattr(support, field):
                raise NbaApiTerminalStateError(
                    f"typed upstream-unavailable evidence rebinds {field}"
                )
        _require_digest(self.unavailable_evidence_sha256, "unavailable_evidence_sha256")
        expected = _domain_digest(
            _UNAVAILABLE_EVIDENCE_DOMAIN,
            _unavailable_evidence_body(request, support),
        )
        if self.unavailable_evidence_sha256 != expected:
            raise NbaApiTerminalStateError("typed unavailable evidence digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            **_unavailable_evidence_body(self.request_binding, self.support_authority),
            "unavailable_evidence_sha256": self.unavailable_evidence_sha256,
        }


def build_terminal_request_binding(
    *,
    request_surface_sha256: str,
    runtime_contract_payload_sha256: str,
    provider_authority_sha256: str,
    route_manifest_sha256: str,
    scope_sha256: str,
    provider_request_sha256: str,
    source_request_sha256: str,
    competition_authority_sha256: str,
    competition_scope_sha256: str,
    competition_requirement_sha256: str,
    role_binding_sha256: str,
    source_evidence_sha256: str,
    source_family: str,
    endpoint_id: str,
    route_ids: tuple[str, ...],
) -> TerminalRequestBinding:
    """Build one canonical request binding and its domain-separated digest."""

    body = _request_binding_body(
        request_surface_sha256=request_surface_sha256,
        runtime_contract_payload_sha256=runtime_contract_payload_sha256,
        provider_authority_sha256=provider_authority_sha256,
        route_manifest_sha256=route_manifest_sha256,
        scope_sha256=scope_sha256,
        provider_request_sha256=provider_request_sha256,
        source_request_sha256=source_request_sha256,
        competition_authority_sha256=competition_authority_sha256,
        competition_scope_sha256=competition_scope_sha256,
        competition_requirement_sha256=competition_requirement_sha256,
        role_binding_sha256=role_binding_sha256,
        source_evidence_sha256=source_evidence_sha256,
        source_family=source_family,
        endpoint_id=endpoint_id,
        route_ids=route_ids,
    )
    return TerminalRequestBinding(
        request_surface_sha256=request_surface_sha256,
        runtime_contract_payload_sha256=runtime_contract_payload_sha256,
        provider_authority_sha256=provider_authority_sha256,
        route_manifest_sha256=route_manifest_sha256,
        scope_sha256=scope_sha256,
        provider_request_sha256=provider_request_sha256,
        source_request_sha256=source_request_sha256,
        competition_authority_sha256=competition_authority_sha256,
        competition_scope_sha256=competition_scope_sha256,
        competition_requirement_sha256=competition_requirement_sha256,
        role_binding_sha256=role_binding_sha256,
        source_evidence_sha256=source_evidence_sha256,
        source_family=source_family,
        endpoint_id=endpoint_id,
        route_ids=route_ids,
        request_binding_sha256=_domain_digest(_REQUEST_BINDING_DOMAIN, body),
    )


def build_typed_upstream_unavailable_evidence(
    request_binding: TerminalRequestBinding,
    support_authority: UpstreamUnavailableSupportAuthority,
) -> TypedUpstreamUnavailableEvidence:
    """Cross-bind one request to independently verified unavailable support."""

    body = _unavailable_evidence_body(request_binding, support_authority)
    return TypedUpstreamUnavailableEvidence(
        request_binding=request_binding,
        support_authority=support_authority,
        state="upstream_unavailable",
        unavailable_evidence_sha256=_domain_digest(_UNAVAILABLE_EVIDENCE_DOMAIN, body),
    )


def is_release_terminal_request_state(state: RequestAccountingState) -> bool:
    """Return whether one declared request state is release-terminal."""

    return state in RELEASE_TERMINAL_REQUEST_STATES


def _accounting_state_contracts() -> list[dict[str, object]]:
    common_incomplete = {
        "release_terminal": False,
        "required_result_occurrence": None,
        "requires_decoded_results": False,
        "requires_independent_verification": False,
        "requires_persisted_results": False,
        "requires_response_body": False,
        "requires_typed_upstream_unavailable_evidence": False,
        "row_count_rule": "not_applicable",
        "state_class": "incomplete",
    }
    return [
        {
            "evidence_kind": "receipt_bound_provider_response",
            "release_terminal": True,
            "required_result_occurrence": "present_nonempty",
            "requires_decoded_results": True,
            "requires_independent_verification": False,
            "requires_persisted_results": True,
            "requires_response_body": True,
            "requires_typed_upstream_unavailable_evidence": False,
            "row_count_rule": "positive",
            "state": "success_nonempty",
            "state_class": "release_terminal",
        },
        {
            "evidence_kind": "receipt_bound_provider_response",
            "release_terminal": True,
            "required_result_occurrence": "present_empty",
            "requires_decoded_results": True,
            "requires_independent_verification": False,
            "requires_persisted_results": True,
            "requires_response_body": True,
            "requires_typed_upstream_unavailable_evidence": False,
            "row_count_rule": "zero",
            "state": "success_empty",
            "state_class": "release_terminal",
        },
        {
            "evidence_kind": "typed_upstream_unavailable_evidence",
            "release_terminal": True,
            "required_result_occurrence": None,
            "requires_decoded_results": False,
            "requires_independent_verification": True,
            "requires_persisted_results": False,
            "requires_response_body": False,
            "requires_typed_upstream_unavailable_evidence": True,
            "row_count_rule": "not_applicable",
            "state": "upstream_unavailable",
            "state_class": "release_terminal",
        },
        {
            **common_incomplete,
            "evidence_kind": "implementation_or_modeled_contract_gap",
            "state": "contract_blocked",
        },
        {
            **common_incomplete,
            "evidence_kind": "transport_timeout_retry_vpn_or_infrastructure_failure",
            "state": "transient_failed",
        },
        {
            **common_incomplete,
            "evidence_kind": "parser_or_response_contract_failure",
            "state": "response_contract_failed",
        },
        {
            **common_incomplete,
            "evidence_kind": "budget_cap_policy_or_scheduling_exhaustion",
            "state": "unattempted",
        },
        {
            **common_incomplete,
            "evidence_kind": "classification_unknown",
            "state": "unclassified",
        },
    ]


def _policy_body() -> dict[str, object]:
    return {
        "accounting_state_contracts": _accounting_state_contracts(),
        "domain_separators": {
            "request_binding": _REQUEST_BINDING_DOMAIN,
            "support_binding": _SUPPORT_BINDING_DOMAIN,
            "unavailable_evidence": _UNAVAILABLE_EVIDENCE_DOMAIN,
        },
        "incomplete_request_states": list(INCOMPLETE_REQUEST_STATES),
        "kind": _KIND,
        "nba_api_version": _NBA_API_VERSION,
        "optional_absent_contract": (
            "absent_optional is a result-occurrence classification only; it is not "
            "success_empty, not a request state, and never contributes to release-terminal "
            "coverage"
        ),
        "release_terminal_request_states": list(RELEASE_TERMINAL_REQUEST_STATES),
        "result_occurrence_states": list(RESULT_OCCURRENCE_STATES),
        "schema_version": TERMINAL_STATE_SCHEMA_VERSION,
        "task_id": _TASK_ID,
        "wire_request_states": list(REQUEST_ACCOUNTING_STATES),
    }


def build_pinned_terminal_state_payload() -> dict[str, object]:
    """Build the deterministic dependency-free terminal-state policy receipt."""

    policy = _policy_body()
    source_inventory: list[dict[str, object]] = [
        {
            "name": "terminal_state_contract",
            "source_kind": "task_packet_policy",
            "task_id": _TASK_ID,
            "upstream_resources": [],
        },
        {
            "name": "public_api_contract",
            "source_kind": "task_packet_policy",
            "task_id": _TASK_ID,
            "upstream_resources": [],
        },
    ]
    payload: dict[str, object] = {
        **policy,
        "canonicalization": {
            "allow_nan": False,
            "encoding": "utf-8",
            "ensure_ascii": False,
            "object_keys": "sorted",
            "payload_digest_excludes": ["payload_sha256"],
            "semantic_digest_terminal_lf": False,
            "separators": [",", ":"],
            "terminal_lf": True,
        },
        "false_green_counters": {
            "bare_digest_upstream_unavailable_promotions": 0,
            "contract_blocked_promoted_to_release_terminal": 0,
            "incomplete_state_promotions": 0,
            "optional_absent_request_success_promotions": 0,
        },
        "source_inventory": source_inventory,
        "source_inventory_sha256": _digest(source_inventory),
        "terminal_policy_sha256": _digest(policy),
    }
    payload["payload_sha256"] = _digest(payload)
    return payload


def write_pinned_terminal_state(path: Path, *, check: bool = False) -> bool:
    """Write or check the canonical terminal-state checked resource."""

    encoded = _canonical_bytes(build_pinned_terminal_state_payload()) + b"\n"
    if path.is_file() and path.read_bytes() == encoded:
        return True
    if check:
        raise NbaApiTerminalStateError("pinned terminal-state policy has generated drift")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return False


def load_pinned_terminal_state_payload(path: Path | None = None) -> dict[str, object]:
    """Strictly load and reproduce the checked terminal-state policy."""

    try:
        raw = (
            resources.files("nbadb.contracts")
            .joinpath(NBA_API_TERMINAL_STATE_RESOURCE)
            .read_bytes()
            if path is None
            else path.read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiTerminalStateError("terminal-state resource cannot be read") from exc
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiTerminalStateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiTerminalStateError("terminal-state resource cannot be decoded") from exc
    if not isinstance(payload, dict) or raw != _canonical_bytes(payload) + b"\n":
        raise NbaApiTerminalStateError("terminal-state resource bytes are not canonical JSON")
    expected_fields = {
        "accounting_state_contracts",
        "canonicalization",
        "domain_separators",
        "false_green_counters",
        "incomplete_request_states",
        "kind",
        "nba_api_version",
        "optional_absent_contract",
        "payload_sha256",
        "release_terminal_request_states",
        "result_occurrence_states",
        "schema_version",
        "source_inventory",
        "source_inventory_sha256",
        "task_id",
        "terminal_policy_sha256",
        "wire_request_states",
    }
    if set(payload) != expected_fields:
        raise NbaApiTerminalStateError("terminal-state resource fields do not match the schema")
    body = dict(payload)
    payload_sha256 = body.pop("payload_sha256", None)
    if _require_digest(payload_sha256, "payload_sha256") != _digest(body):
        raise NbaApiTerminalStateError("terminal-state resource payload digest is invalid")
    if payload != build_pinned_terminal_state_payload():
        raise NbaApiTerminalStateError("terminal-state resource differs from the canonical policy")
    return cast("dict[str, object]", payload)


__all__ = [
    "INCOMPLETE_REQUEST_STATES",
    "NBA_API_TERMINAL_STATE_RESOURCE",
    "RELEASE_TERMINAL_REQUEST_STATES",
    "REQUEST_ACCOUNTING_STATES",
    "RESULT_OCCURRENCE_STATES",
    "TERMINAL_STATE_SCHEMA_VERSION",
    "IncompleteRequestState",
    "NbaApiTerminalStateError",
    "ReleaseTerminalRequestState",
    "RequestAccountingState",
    "ResultOccurrenceState",
    "TerminalRequestBinding",
    "TypedUpstreamUnavailableEvidence",
    "UpstreamUnavailableSupportAuthority",
    "build_pinned_terminal_state_payload",
    "build_terminal_request_binding",
    "build_typed_upstream_unavailable_evidence",
    "is_release_terminal_request_state",
    "load_pinned_terminal_state_payload",
    "write_pinned_terminal_state",
]
