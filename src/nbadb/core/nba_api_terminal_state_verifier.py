"""Independent, no-network verifier for the NBA API terminal-state authority.

This module reconstructs the complete terminal policy without importing the
primary terminal-state implementation or any request, runtime, or competition
compiler.  The checked resource is deliberately read only after that
reconstruction is complete.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Mapping


if TYPE_CHECKING:
    from pathlib import Path

_RESOURCE: Final = "nba_api_terminal_state_v1_11_4.json"
_TASK_ID: Final = "A1.3a"
_NBA_API_VERSION: Final = "1.11.4"
_SCHEMA_VERSION: Final = 1
_KIND: Final = "nbadb_nba_api_terminal_state_authority"
_VERIFIER_ID: Final = "nbadb_independent_terminal_state_v1"

_REQUEST_BINDING_DOMAIN: Final = "nbadb.nba-api.terminal-request-binding.v1"
_SUPPORT_BINDING_DOMAIN: Final = "nbadb.nba-api.upstream-unavailable-support.v1"
_UNAVAILABLE_EVIDENCE_DOMAIN: Final = "nbadb.nba-api.upstream-unavailable-evidence.v1"

_WIRE_REQUEST_STATES: Final = (
    "success_nonempty",
    "success_empty",
    "upstream_unavailable",
    "contract_blocked",
    "transient_failed",
    "response_contract_failed",
    "unattempted",
    "unclassified",
)
_RELEASE_TERMINAL_REQUEST_STATES: Final = _WIRE_REQUEST_STATES[:3]
_INCOMPLETE_REQUEST_STATES: Final = _WIRE_REQUEST_STATES[3:]
_RESULT_OCCURRENCE_STATES: Final = (
    "present_nonempty",
    "present_empty",
    "absent_optional",
)
_OPTIONAL_ABSENT_CONTRACT: Final = (
    "absent_optional is a result-occurrence classification only; it is not "
    "success_empty, not a request state, and never contributes to "
    "release-terminal coverage"
)

_RESOURCE_KEYS: Final = {
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
_SHA256_LENGTH: Final = 64
_SAFE_IDENTIFIER_RE: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}",
    flags=re.ASCII,
)


class NbaApiTerminalStateVerificationError(ValueError):
    """Independent terminal-state verification failed closed."""


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
        raise NbaApiTerminalStateVerificationError(
            "terminal-state authority is not canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _domain_digest(domain: str, payload: object) -> str:
    return _digest({"domain": domain, "payload": payload})


def _require_sha256(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NbaApiTerminalStateVerificationError(f"{field} must be a lowercase canonical SHA-256")
    return value


def _require_nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise NbaApiTerminalStateVerificationError(f"{field} must be a nonempty trimmed string")
    return value


def _require_safe_identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or _SAFE_IDENTIFIER_RE.fullmatch(value) is None:
        raise NbaApiTerminalStateVerificationError(f"{field} must be a safe nonempty identifier")
    return value


def _require_source_family(value: object) -> str:
    if not isinstance(value, str) or value not in {"stats", "live"}:
        raise NbaApiTerminalStateVerificationError("source_family must be stats or live")
    return value


def _require_exact_keys(
    value: object,
    expected: set[str],
    field: str,
) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != expected:
        raise NbaApiTerminalStateVerificationError(
            f"{field} fields do not match the independent schema"
        )
    return cast("Mapping[str, object]", value)


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiTerminalStateVerificationError(
                f"terminal-state resource contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiTerminalStateVerificationError(
        f"terminal-state resource contains non-finite JSON constant: {value}"
    )


@dataclass(frozen=True, slots=True)
class IndependentAccountingStateContract:
    """One independently reconstructed request-accounting contract."""

    state: str
    state_class: str
    release_terminal: bool
    evidence_kind: str
    required_result_occurrence: str | None
    row_count_rule: str
    requires_response_body: bool
    requires_decoded_results: bool
    requires_persisted_results: bool
    requires_typed_upstream_unavailable_evidence: bool
    requires_independent_verification: bool


@dataclass(frozen=True, slots=True)
class IndependentTerminalRequestBinding:
    """Independent reproduction of the complete terminal request binding."""

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


@dataclass(frozen=True, slots=True)
class IndependentUpstreamUnavailableSupportAuthority:
    """Independent reproduction of a typed unavailable-support authority."""

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


@dataclass(frozen=True, slots=True)
class IndependentTypedUpstreamUnavailableEvidence:
    """Complete typed evidence; a digest without this body is insufficient."""

    request_binding: IndependentTerminalRequestBinding
    support_authority: IndependentUpstreamUnavailableSupportAuthority
    state: str
    unavailable_evidence_sha256: str


@dataclass(frozen=True, slots=True)
class IndependentTerminalStateProof:
    """Independent equality proof for the checked terminal-state authority."""

    verifier_id: str
    wire_request_states: tuple[str, ...]
    release_terminal_request_states: tuple[str, ...]
    incomplete_request_states: tuple[str, ...]
    result_occurrence_states: tuple[str, ...]
    accounting_state_contracts: tuple[IndependentAccountingStateContract, ...]
    source_inventory_sha256: str
    terminal_policy_sha256: str
    checked_payload_sha256: str
    proof_sha256: str


def _request_binding_mapping(value: IndependentTerminalRequestBinding) -> dict[str, object]:
    return {
        "request_surface_sha256": value.request_surface_sha256,
        "runtime_contract_payload_sha256": value.runtime_contract_payload_sha256,
        "provider_authority_sha256": value.provider_authority_sha256,
        "route_manifest_sha256": value.route_manifest_sha256,
        "scope_sha256": value.scope_sha256,
        "provider_request_sha256": value.provider_request_sha256,
        "source_request_sha256": value.source_request_sha256,
        "competition_authority_sha256": value.competition_authority_sha256,
        "competition_scope_sha256": value.competition_scope_sha256,
        "competition_requirement_sha256": value.competition_requirement_sha256,
        "role_binding_sha256": value.role_binding_sha256,
        "source_evidence_sha256": value.source_evidence_sha256,
        "source_family": value.source_family,
        "endpoint_id": value.endpoint_id,
        "route_ids": list(value.route_ids),
        "request_binding_sha256": value.request_binding_sha256,
    }


def _support_authority_mapping(
    value: IndependentUpstreamUnavailableSupportAuthority,
) -> dict[str, object]:
    return {
        "authority_kind": value.authority_kind,
        "authority_version": value.authority_version,
        "support_authority_sha256": value.support_authority_sha256,
        "support_cell_id": value.support_cell_id,
        "support_cell_sha256": value.support_cell_sha256,
        "provider_authority_sha256": value.provider_authority_sha256,
        "request_surface_sha256": value.request_surface_sha256,
        "source_family": value.source_family,
        "endpoint_id": value.endpoint_id,
        "scope_sha256": value.scope_sha256,
        "competition_scope_sha256": value.competition_scope_sha256,
        "source_request_sha256": value.source_request_sha256,
        "provider_request_sha256": value.provider_request_sha256,
        "status": value.status,
        "reason_code": value.reason_code,
        "independent_verifier_id": value.independent_verifier_id,
        "independent_verifier_sha256": value.independent_verifier_sha256,
        "support_binding_sha256": value.support_binding_sha256,
    }


def build_independent_terminal_request_binding(
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
) -> IndependentTerminalRequestBinding:
    """Build the request binding from the packet-declared complete typed body."""

    digest_fields = {
        "request_surface_sha256": _require_sha256(request_surface_sha256, "request_surface_sha256"),
        "runtime_contract_payload_sha256": _require_sha256(
            runtime_contract_payload_sha256, "runtime_contract_payload_sha256"
        ),
        "provider_authority_sha256": _require_sha256(
            provider_authority_sha256, "provider_authority_sha256"
        ),
        "route_manifest_sha256": _require_sha256(route_manifest_sha256, "route_manifest_sha256"),
        "scope_sha256": _require_sha256(scope_sha256, "scope_sha256"),
        "provider_request_sha256": _require_sha256(
            provider_request_sha256, "provider_request_sha256"
        ),
        "source_request_sha256": _require_sha256(source_request_sha256, "source_request_sha256"),
        "competition_authority_sha256": _require_sha256(
            competition_authority_sha256, "competition_authority_sha256"
        ),
        "competition_scope_sha256": _require_sha256(
            competition_scope_sha256, "competition_scope_sha256"
        ),
        "competition_requirement_sha256": _require_sha256(
            competition_requirement_sha256, "competition_requirement_sha256"
        ),
        "role_binding_sha256": _require_sha256(role_binding_sha256, "role_binding_sha256"),
        "source_evidence_sha256": _require_sha256(source_evidence_sha256, "source_evidence_sha256"),
    }
    normalized_source_family = _require_source_family(source_family)
    normalized_endpoint_id = _require_safe_identifier(endpoint_id, "endpoint_id")
    if (
        type(route_ids) is not tuple
        or not route_ids
        or any(
            not isinstance(route_id, str) or _SAFE_IDENTIFIER_RE.fullmatch(route_id) is None
            for route_id in route_ids
        )
        or len(route_ids) != len(set(route_ids))
        or route_ids != tuple(sorted(route_ids))
    ):
        raise NbaApiTerminalStateVerificationError(
            "route_ids must be sorted, unique, safe, and nonempty"
        )
    body = {
        **digest_fields,
        "source_family": normalized_source_family,
        "endpoint_id": normalized_endpoint_id,
        "route_ids": list(route_ids),
    }
    return IndependentTerminalRequestBinding(
        **digest_fields,
        source_family=normalized_source_family,
        endpoint_id=normalized_endpoint_id,
        route_ids=route_ids,
        request_binding_sha256=_domain_digest(_REQUEST_BINDING_DOMAIN, body),
    )


def reproduce_terminal_request_binding(
    value: object,
) -> IndependentTerminalRequestBinding:
    """Validate and reproduce a serialized terminal request binding."""

    expected_keys = {
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
        "source_family",
        "endpoint_id",
        "route_ids",
        "request_binding_sha256",
    }
    mapping = _require_exact_keys(value, expected_keys, "request_binding")
    route_ids_value = mapping["route_ids"]
    if type(route_ids_value) is not list:
        raise NbaApiTerminalStateVerificationError("route_ids must be an ordered array")
    reproduced = build_independent_terminal_request_binding(
        request_surface_sha256=cast("str", mapping["request_surface_sha256"]),
        runtime_contract_payload_sha256=cast("str", mapping["runtime_contract_payload_sha256"]),
        provider_authority_sha256=cast("str", mapping["provider_authority_sha256"]),
        route_manifest_sha256=cast("str", mapping["route_manifest_sha256"]),
        scope_sha256=cast("str", mapping["scope_sha256"]),
        provider_request_sha256=cast("str", mapping["provider_request_sha256"]),
        source_request_sha256=cast("str", mapping["source_request_sha256"]),
        competition_authority_sha256=cast("str", mapping["competition_authority_sha256"]),
        competition_scope_sha256=cast("str", mapping["competition_scope_sha256"]),
        competition_requirement_sha256=cast("str", mapping["competition_requirement_sha256"]),
        role_binding_sha256=cast("str", mapping["role_binding_sha256"]),
        source_evidence_sha256=cast("str", mapping["source_evidence_sha256"]),
        source_family=cast("str", mapping["source_family"]),
        endpoint_id=cast("str", mapping["endpoint_id"]),
        route_ids=tuple(cast("list[str] | tuple[str, ...]", route_ids_value)),
    )
    supplied = _require_sha256(mapping["request_binding_sha256"], "request_binding_sha256")
    if supplied != reproduced.request_binding_sha256:
        raise NbaApiTerminalStateVerificationError(
            "terminal request binding digest does not match its complete typed body"
        )
    return reproduced


def build_independent_upstream_unavailable_support_authority(
    *,
    authority_kind: str,
    authority_version: int,
    support_authority_sha256: str,
    support_cell_id: str,
    support_cell_sha256: str,
    provider_authority_sha256: str,
    request_surface_sha256: str,
    source_family: str,
    endpoint_id: str,
    scope_sha256: str,
    competition_scope_sha256: str,
    source_request_sha256: str,
    provider_request_sha256: str,
    status: str,
    reason_code: str,
    independent_verifier_id: str,
    independent_verifier_sha256: str,
) -> IndependentUpstreamUnavailableSupportAuthority:
    """Build the exact typed authority supporting upstream unavailability."""

    if isinstance(authority_version, bool) or not isinstance(authority_version, int):
        raise NbaApiTerminalStateVerificationError("authority_version must be an integer")
    if authority_version < 1:
        raise NbaApiTerminalStateVerificationError("authority_version must be positive")
    normalized = {
        "authority_kind": _require_safe_identifier(authority_kind, "authority_kind"),
        "authority_version": authority_version,
        "support_authority_sha256": _require_sha256(
            support_authority_sha256, "support_authority_sha256"
        ),
        "support_cell_id": _require_safe_identifier(support_cell_id, "support_cell_id"),
        "support_cell_sha256": _require_sha256(support_cell_sha256, "support_cell_sha256"),
        "provider_authority_sha256": _require_sha256(
            provider_authority_sha256, "provider_authority_sha256"
        ),
        "request_surface_sha256": _require_sha256(request_surface_sha256, "request_surface_sha256"),
        "source_family": _require_source_family(source_family),
        "endpoint_id": _require_safe_identifier(endpoint_id, "endpoint_id"),
        "scope_sha256": _require_sha256(scope_sha256, "scope_sha256"),
        "competition_scope_sha256": _require_sha256(
            competition_scope_sha256, "competition_scope_sha256"
        ),
        "source_request_sha256": _require_sha256(source_request_sha256, "source_request_sha256"),
        "provider_request_sha256": _require_sha256(
            provider_request_sha256, "provider_request_sha256"
        ),
        "status": _require_safe_identifier(status, "status"),
        "reason_code": _require_safe_identifier(reason_code, "reason_code"),
        "independent_verifier_id": _require_safe_identifier(
            independent_verifier_id, "independent_verifier_id"
        ),
        "independent_verifier_sha256": _require_sha256(
            independent_verifier_sha256, "independent_verifier_sha256"
        ),
    }
    if normalized["status"] != "upstream_unavailable":
        raise NbaApiTerminalStateVerificationError(
            "support authority status must be upstream_unavailable"
        )
    return IndependentUpstreamUnavailableSupportAuthority(
        **normalized,
        support_binding_sha256=_domain_digest(_SUPPORT_BINDING_DOMAIN, normalized),
    )


def reproduce_upstream_unavailable_support_authority(
    value: object,
) -> IndependentUpstreamUnavailableSupportAuthority:
    """Validate and reproduce a serialized unavailable-support authority."""

    expected_keys = {
        "authority_kind",
        "authority_version",
        "support_authority_sha256",
        "support_cell_id",
        "support_cell_sha256",
        "provider_authority_sha256",
        "request_surface_sha256",
        "source_family",
        "endpoint_id",
        "scope_sha256",
        "competition_scope_sha256",
        "source_request_sha256",
        "provider_request_sha256",
        "status",
        "reason_code",
        "independent_verifier_id",
        "independent_verifier_sha256",
        "support_binding_sha256",
    }
    mapping = _require_exact_keys(value, expected_keys, "support_authority")
    reproduced = build_independent_upstream_unavailable_support_authority(
        authority_kind=cast("str", mapping["authority_kind"]),
        authority_version=cast("int", mapping["authority_version"]),
        support_authority_sha256=cast("str", mapping["support_authority_sha256"]),
        support_cell_id=cast("str", mapping["support_cell_id"]),
        support_cell_sha256=cast("str", mapping["support_cell_sha256"]),
        provider_authority_sha256=cast("str", mapping["provider_authority_sha256"]),
        request_surface_sha256=cast("str", mapping["request_surface_sha256"]),
        source_family=cast("str", mapping["source_family"]),
        endpoint_id=cast("str", mapping["endpoint_id"]),
        scope_sha256=cast("str", mapping["scope_sha256"]),
        competition_scope_sha256=cast("str", mapping["competition_scope_sha256"]),
        source_request_sha256=cast("str", mapping["source_request_sha256"]),
        provider_request_sha256=cast("str", mapping["provider_request_sha256"]),
        status=cast("str", mapping["status"]),
        reason_code=cast("str", mapping["reason_code"]),
        independent_verifier_id=cast("str", mapping["independent_verifier_id"]),
        independent_verifier_sha256=cast("str", mapping["independent_verifier_sha256"]),
    )
    supplied = _require_sha256(mapping["support_binding_sha256"], "support_binding_sha256")
    if supplied != reproduced.support_binding_sha256:
        raise NbaApiTerminalStateVerificationError(
            "support binding digest does not match its complete typed body"
        )
    return reproduced


def build_independent_typed_upstream_unavailable_evidence(
    request_binding: IndependentTerminalRequestBinding,
    support_authority: IndependentUpstreamUnavailableSupportAuthority,
) -> IndependentTypedUpstreamUnavailableEvidence:
    """Cross-bind the complete request and support bodies as unavailable evidence."""

    if type(request_binding) is not IndependentTerminalRequestBinding:
        raise NbaApiTerminalStateVerificationError(
            "typed evidence request binding must use the independent concrete type"
        )
    if type(support_authority) is not IndependentUpstreamUnavailableSupportAuthority:
        raise NbaApiTerminalStateVerificationError(
            "typed evidence support authority must use the independent concrete type"
        )
    request_binding = reproduce_terminal_request_binding(_request_binding_mapping(request_binding))
    support_authority = reproduce_upstream_unavailable_support_authority(
        _support_authority_mapping(support_authority)
    )
    comparisons = (
        (request_binding.request_surface_sha256, support_authority.request_surface_sha256),
        (request_binding.provider_authority_sha256, support_authority.provider_authority_sha256),
        (request_binding.provider_request_sha256, support_authority.provider_request_sha256),
        (request_binding.scope_sha256, support_authority.scope_sha256),
        (request_binding.competition_scope_sha256, support_authority.competition_scope_sha256),
        (request_binding.source_request_sha256, support_authority.source_request_sha256),
        (request_binding.source_family, support_authority.source_family),
        (request_binding.endpoint_id, support_authority.endpoint_id),
    )
    if any(left != right for left, right in comparisons):
        raise NbaApiTerminalStateVerificationError(
            "upstream-unavailable support authority is rebound to a foreign request"
        )
    state = "upstream_unavailable"
    body = {
        "request_binding": _request_binding_mapping(request_binding),
        "support_authority": _support_authority_mapping(support_authority),
        "state": state,
    }
    return IndependentTypedUpstreamUnavailableEvidence(
        request_binding=request_binding,
        support_authority=support_authority,
        state=state,
        unavailable_evidence_sha256=_domain_digest(_UNAVAILABLE_EVIDENCE_DOMAIN, body),
    )


def reproduce_typed_upstream_unavailable_evidence(
    value: object,
) -> IndependentTypedUpstreamUnavailableEvidence:
    """Validate and fully reproduce serialized typed unavailable evidence."""

    mapping = _require_exact_keys(
        value,
        {
            "request_binding",
            "support_authority",
            "state",
            "unavailable_evidence_sha256",
        },
        "typed_upstream_unavailable_evidence",
    )
    if mapping["state"] != "upstream_unavailable":
        raise NbaApiTerminalStateVerificationError(
            "typed unavailable evidence state must be upstream_unavailable"
        )
    request_binding = reproduce_terminal_request_binding(mapping["request_binding"])
    support_authority = reproduce_upstream_unavailable_support_authority(
        mapping["support_authority"]
    )
    reproduced = build_independent_typed_upstream_unavailable_evidence(
        request_binding,
        support_authority,
    )
    supplied = _require_sha256(
        mapping["unavailable_evidence_sha256"], "unavailable_evidence_sha256"
    )
    if supplied != reproduced.unavailable_evidence_sha256:
        raise NbaApiTerminalStateVerificationError(
            "unavailable evidence digest does not match its complete typed body"
        )
    return reproduced


def _contract(
    state: str,
    state_class: str,
    release_terminal: bool,
    evidence_kind: str,
    required_result_occurrence: str | None,
    row_count_rule: str,
    *,
    response_body: bool = False,
    decoded_results: bool = False,
    persisted_results: bool = False,
    typed_unavailable: bool = False,
    independent_verification: bool = False,
) -> dict[str, object]:
    return {
        "evidence_kind": evidence_kind,
        "release_terminal": release_terminal,
        "required_result_occurrence": required_result_occurrence,
        "requires_decoded_results": decoded_results,
        "requires_independent_verification": independent_verification,
        "requires_persisted_results": persisted_results,
        "requires_response_body": response_body,
        "requires_typed_upstream_unavailable_evidence": typed_unavailable,
        "row_count_rule": row_count_rule,
        "state": state,
        "state_class": state_class,
    }


def _derive_accounting_state_contracts() -> list[dict[str, object]]:
    complete = [
        _contract(
            "success_nonempty",
            "release_terminal",
            True,
            "receipt_bound_provider_response",
            "present_nonempty",
            "positive",
            response_body=True,
            decoded_results=True,
            persisted_results=True,
        ),
        _contract(
            "success_empty",
            "release_terminal",
            True,
            "receipt_bound_provider_response",
            "present_empty",
            "zero",
            response_body=True,
            decoded_results=True,
            persisted_results=True,
        ),
        _contract(
            "upstream_unavailable",
            "release_terminal",
            True,
            "typed_upstream_unavailable_evidence",
            None,
            "not_applicable",
            typed_unavailable=True,
            independent_verification=True,
        ),
    ]
    incomplete_evidence = (
        ("contract_blocked", "implementation_or_modeled_contract_gap"),
        ("transient_failed", "transport_timeout_retry_vpn_or_infrastructure_failure"),
        ("response_contract_failed", "parser_or_response_contract_failure"),
        ("unattempted", "budget_cap_policy_or_scheduling_exhaustion"),
        ("unclassified", "classification_unknown"),
    )
    complete.extend(
        _contract(
            state,
            "incomplete",
            False,
            evidence_kind,
            None,
            "not_applicable",
        )
        for state, evidence_kind in incomplete_evidence
    )
    return complete


def _terminal_policy_body(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "accounting_state_contracts": payload["accounting_state_contracts"],
        "domain_separators": payload["domain_separators"],
        "incomplete_request_states": payload["incomplete_request_states"],
        "kind": payload["kind"],
        "nba_api_version": payload["nba_api_version"],
        "optional_absent_contract": payload["optional_absent_contract"],
        "release_terminal_request_states": payload["release_terminal_request_states"],
        "result_occurrence_states": payload["result_occurrence_states"],
        "schema_version": payload["schema_version"],
        "task_id": payload["task_id"],
        "wire_request_states": payload["wire_request_states"],
    }


def build_independent_terminal_state_payload() -> dict[str, object]:
    """Reconstruct the complete checked authority from the sealed policy."""

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
        "accounting_state_contracts": _derive_accounting_state_contracts(),
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
        "domain_separators": {
            "request_binding": _REQUEST_BINDING_DOMAIN,
            "support_binding": _SUPPORT_BINDING_DOMAIN,
            "unavailable_evidence": _UNAVAILABLE_EVIDENCE_DOMAIN,
        },
        "false_green_counters": {
            "bare_digest_upstream_unavailable_promotions": 0,
            "contract_blocked_promoted_to_release_terminal": 0,
            "incomplete_state_promotions": 0,
            "optional_absent_request_success_promotions": 0,
        },
        "incomplete_request_states": list(_INCOMPLETE_REQUEST_STATES),
        "kind": _KIND,
        "nba_api_version": _NBA_API_VERSION,
        "optional_absent_contract": _OPTIONAL_ABSENT_CONTRACT,
        "release_terminal_request_states": list(_RELEASE_TERMINAL_REQUEST_STATES),
        "result_occurrence_states": list(_RESULT_OCCURRENCE_STATES),
        "schema_version": _SCHEMA_VERSION,
        "source_inventory": source_inventory,
        "source_inventory_sha256": _digest(source_inventory),
        "task_id": _TASK_ID,
        "wire_request_states": list(_WIRE_REQUEST_STATES),
    }
    payload["terminal_policy_sha256"] = _digest(_terminal_policy_body(payload))
    payload["payload_sha256"] = _digest(payload)
    return payload


def _load_checked_resource(path: Path | None) -> tuple[bytes, dict[str, object]]:
    try:
        raw = (
            resources.files("nbadb.contracts").joinpath(_RESOURCE).read_bytes()
            if path is None
            else path.read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiTerminalStateVerificationError(
            "terminal-state resource cannot be read"
        ) from exc
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiTerminalStateVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiTerminalStateVerificationError(
            "terminal-state resource cannot be decoded"
        ) from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value) + b"\n":
        raise NbaApiTerminalStateVerificationError(
            "terminal-state resource bytes are not canonical JSON"
        )
    return raw, cast("dict[str, object]", value)


def _typed_contracts(
    rows: object,
) -> tuple[IndependentAccountingStateContract, ...]:
    if not isinstance(rows, list):
        raise NbaApiTerminalStateVerificationError(
            "accounting_state_contracts must be an ordered array"
        )
    expected_keys = {
        "evidence_kind",
        "release_terminal",
        "required_result_occurrence",
        "requires_decoded_results",
        "requires_independent_verification",
        "requires_persisted_results",
        "requires_response_body",
        "requires_typed_upstream_unavailable_evidence",
        "row_count_rule",
        "state",
        "state_class",
    }
    typed: list[IndependentAccountingStateContract] = []
    for index, raw_row in enumerate(rows):
        row = _require_exact_keys(
            raw_row,
            expected_keys,
            f"accounting_state_contracts[{index}]",
        )
        bool_fields = (
            "release_terminal",
            "requires_decoded_results",
            "requires_independent_verification",
            "requires_persisted_results",
            "requires_response_body",
            "requires_typed_upstream_unavailable_evidence",
        )
        if any(type(row[field]) is not bool for field in bool_fields):
            raise NbaApiTerminalStateVerificationError(
                f"accounting_state_contracts[{index}] boolean field drift"
            )
        occurrence = row["required_result_occurrence"]
        if occurrence is not None and not isinstance(occurrence, str):
            raise NbaApiTerminalStateVerificationError(
                f"accounting_state_contracts[{index}] occurrence type drift"
            )
        typed.append(
            IndependentAccountingStateContract(
                state=_require_nonempty_string(row["state"], "state"),
                state_class=_require_nonempty_string(row["state_class"], "state_class"),
                release_terminal=cast("bool", row["release_terminal"]),
                evidence_kind=_require_nonempty_string(row["evidence_kind"], "evidence_kind"),
                required_result_occurrence=occurrence,
                row_count_rule=_require_nonempty_string(row["row_count_rule"], "row_count_rule"),
                requires_response_body=cast("bool", row["requires_response_body"]),
                requires_decoded_results=cast("bool", row["requires_decoded_results"]),
                requires_persisted_results=cast("bool", row["requires_persisted_results"]),
                requires_typed_upstream_unavailable_evidence=cast(
                    "bool", row["requires_typed_upstream_unavailable_evidence"]
                ),
                requires_independent_verification=cast(
                    "bool", row["requires_independent_verification"]
                ),
            )
        )
    return tuple(typed)


def _verify(path: Path | None) -> IndependentTerminalStateProof:
    expected = build_independent_terminal_state_payload()
    # Candidate-resource read is intentionally last in the derivation sequence.
    _, candidate = _load_checked_resource(path)
    if set(candidate) != _RESOURCE_KEYS:
        raise NbaApiTerminalStateVerificationError(
            "terminal-state resource fields do not match the exact schema"
        )
    source_inventory = candidate.get("source_inventory")
    if candidate.get("source_inventory_sha256") != _digest(source_inventory):
        raise NbaApiTerminalStateVerificationError(
            "terminal-state source-inventory digest is invalid"
        )
    if candidate.get("terminal_policy_sha256") != _digest(_terminal_policy_body(candidate)):
        raise NbaApiTerminalStateVerificationError(
            "terminal-state semantic policy digest is invalid"
        )
    payload_body = dict(candidate)
    supplied_payload_sha256 = _require_sha256(
        payload_body.pop("payload_sha256", None), "payload_sha256"
    )
    if supplied_payload_sha256 != _digest(payload_body):
        raise NbaApiTerminalStateVerificationError("terminal-state payload digest is invalid")
    if candidate != expected:
        raise NbaApiTerminalStateVerificationError(
            "checked terminal-state authority differs from independent policy"
        )
    typed_contracts = _typed_contracts(candidate["accounting_state_contracts"])
    proof_body = {
        "schema_version": 1,
        "kind": "nbadb_independent_terminal_state_proof",
        "verifier_id": _VERIFIER_ID,
        "wire_request_states": list(_WIRE_REQUEST_STATES),
        "release_terminal_request_states": list(_RELEASE_TERMINAL_REQUEST_STATES),
        "incomplete_request_states": list(_INCOMPLETE_REQUEST_STATES),
        "result_occurrence_states": list(_RESULT_OCCURRENCE_STATES),
        "accounting_state_contracts": candidate["accounting_state_contracts"],
        "source_inventory_sha256": candidate["source_inventory_sha256"],
        "terminal_policy_sha256": candidate["terminal_policy_sha256"],
        "checked_payload_sha256": supplied_payload_sha256,
    }
    return IndependentTerminalStateProof(
        verifier_id=_VERIFIER_ID,
        wire_request_states=_WIRE_REQUEST_STATES,
        release_terminal_request_states=_RELEASE_TERMINAL_REQUEST_STATES,
        incomplete_request_states=_INCOMPLETE_REQUEST_STATES,
        result_occurrence_states=_RESULT_OCCURRENCE_STATES,
        accounting_state_contracts=typed_contracts,
        source_inventory_sha256=cast("str", candidate["source_inventory_sha256"]),
        terminal_policy_sha256=cast("str", candidate["terminal_policy_sha256"]),
        checked_payload_sha256=supplied_payload_sha256,
        proof_sha256=_digest(proof_body),
    )


@lru_cache(maxsize=1)
def verify_pinned_terminal_state_authority() -> IndependentTerminalStateProof:
    """Verify the packaged authority against the independent reconstruction."""

    return _verify(None)


def verify_terminal_state_authority_file(path: Path) -> IndependentTerminalStateProof:
    """Verify an explicit candidate resource without caching it."""

    return _verify(path)


__all__ = [
    "IndependentAccountingStateContract",
    "IndependentTerminalRequestBinding",
    "IndependentTerminalStateProof",
    "IndependentTypedUpstreamUnavailableEvidence",
    "IndependentUpstreamUnavailableSupportAuthority",
    "NbaApiTerminalStateVerificationError",
    "build_independent_terminal_request_binding",
    "build_independent_terminal_state_payload",
    "build_independent_typed_upstream_unavailable_evidence",
    "build_independent_upstream_unavailable_support_authority",
    "reproduce_terminal_request_binding",
    "reproduce_typed_upstream_unavailable_evidence",
    "reproduce_upstream_unavailable_support_authority",
    "verify_pinned_terminal_state_authority",
    "verify_terminal_state_authority_file",
]
