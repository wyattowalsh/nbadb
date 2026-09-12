from __future__ import annotations

import ast
import hashlib
import inspect
import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from nbadb.core import nba_api_terminal_state as terminal
from nbadb.core.nba_api_terminal_state import (
    INCOMPLETE_REQUEST_STATES,
    NBA_API_TERMINAL_STATE_RESOURCE,
    RELEASE_TERMINAL_REQUEST_STATES,
    REQUEST_ACCOUNTING_STATES,
    RESULT_OCCURRENCE_STATES,
    NbaApiTerminalStateError,
    UpstreamUnavailableSupportAuthority,
    build_pinned_terminal_state_payload,
    build_terminal_request_binding,
    build_typed_upstream_unavailable_evidence,
    is_release_terminal_request_state,
    load_pinned_terminal_state_payload,
    write_pinned_terminal_state,
)


def _resource_path() -> Path:
    return (
        Path(__file__).parents[3] / "src" / "nbadb" / "contracts" / NBA_API_TERMINAL_STATE_RESOURCE
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _domain_digest(domain: str, value: object) -> str:
    return hashlib.sha256(_canonical_bytes({"domain": domain, "payload": value})).hexdigest()


def _binding() -> terminal.TerminalRequestBinding:
    digests = [hashlib.sha256(f"binding-{index}".encode()).hexdigest() for index in range(12)]
    return build_terminal_request_binding(
        request_surface_sha256=digests[0],
        runtime_contract_payload_sha256=digests[1],
        provider_authority_sha256=digests[2],
        route_manifest_sha256=digests[3],
        scope_sha256=digests[4],
        provider_request_sha256=digests[5],
        source_request_sha256=digests[6],
        competition_authority_sha256=digests[7],
        competition_scope_sha256=digests[8],
        competition_requirement_sha256=digests[9],
        role_binding_sha256=digests[10],
        source_evidence_sha256=digests[11],
        source_family="stats",
        endpoint_id="league_game_log",
        route_ids=("route-a", "route-b"),
    )


def _support_authority(
    binding: terminal.TerminalRequestBinding,
    **overrides: object,
) -> UpstreamUnavailableSupportAuthority:
    values: dict[str, object] = {
        "authority_kind": "endpoint_support_evidence",
        "authority_version": 1,
        "support_authority_sha256": hashlib.sha256(b"support-authority").hexdigest(),
        "support_cell_id": "cell-1946-47",
        "support_cell_sha256": hashlib.sha256(b"support-cell").hexdigest(),
        "provider_authority_sha256": binding.provider_authority_sha256,
        "request_surface_sha256": binding.request_surface_sha256,
        "source_family": binding.source_family,
        "endpoint_id": binding.endpoint_id,
        "scope_sha256": binding.scope_sha256,
        "competition_scope_sha256": binding.competition_scope_sha256,
        "source_request_sha256": binding.source_request_sha256,
        "provider_request_sha256": binding.provider_request_sha256,
        "status": "upstream_unavailable",
        "reason_code": "declared_provider_unavailable",
        "independent_verifier_id": "support_matrix_verifier_v1",
        "independent_verifier_sha256": hashlib.sha256(b"support-verifier").hexdigest(),
    }
    values.update(overrides)
    support_body = dict(values)
    values["support_binding_sha256"] = _domain_digest(
        "nbadb.nba-api.upstream-unavailable-support.v1",
        support_body,
    )
    return UpstreamUnavailableSupportAuthority(**values)  # type: ignore[arg-type]


def _contracts_by_state() -> dict[str, dict[str, object]]:
    rows = build_pinned_terminal_state_payload()["accounting_state_contracts"]
    assert isinstance(rows, list)
    return {str(row["state"]): row for row in rows if isinstance(row, dict)}


def test_release_terminal_states_exact_set() -> None:
    assert RELEASE_TERMINAL_REQUEST_STATES == (
        "success_nonempty",
        "success_empty",
        "upstream_unavailable",
    )
    assert REQUEST_ACCOUNTING_STATES == (
        "success_nonempty",
        "success_empty",
        "upstream_unavailable",
        "contract_blocked",
        "transient_failed",
        "response_contract_failed",
        "unattempted",
        "unclassified",
    )
    assert (
        tuple(
            state for state in REQUEST_ACCOUNTING_STATES if is_release_terminal_request_state(state)
        )
        == RELEASE_TERMINAL_REQUEST_STATES
    )


def test_success_nonempty_requires_receipt_bound_positive_row_evidence() -> None:
    contract = _contracts_by_state()["success_nonempty"]
    assert contract == {
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
    }


def test_success_empty_requires_present_zero_row_result_evidence() -> None:
    contract = _contracts_by_state()["success_empty"]
    assert contract["required_result_occurrence"] == "present_empty"
    assert contract["row_count_rule"] == "zero"
    assert contract["requires_response_body"] is True
    assert contract["requires_decoded_results"] is True
    assert contract["requires_persisted_results"] is True
    assert "absent_optional" not in RELEASE_TERMINAL_REQUEST_STATES
    assert RESULT_OCCURRENCE_STATES == (
        "present_nonempty",
        "present_empty",
        "absent_optional",
    )


def test_upstream_unavailable_requires_independent_scope_bound_evidence() -> None:
    binding = _binding()
    support = _support_authority(binding)
    evidence = build_typed_upstream_unavailable_evidence(binding, support)
    assert evidence.state == "upstream_unavailable"
    assert evidence.request_binding == binding
    assert evidence.support_authority == support
    assert len(evidence.unavailable_evidence_sha256) == 64
    with pytest.raises(NbaApiTerminalStateError, match="rebinds scope_sha256"):
        build_typed_upstream_unavailable_evidence(
            binding,
            _support_authority(binding, scope_sha256=hashlib.sha256(b"foreign-scope").hexdigest()),
        )
    with pytest.raises(NbaApiTerminalStateError, match="digest is invalid"):
        replace(evidence, unavailable_evidence_sha256="0" * 64)


def test_incomplete_states_are_conserved_but_never_release_terminal() -> None:
    assert INCOMPLETE_REQUEST_STATES == (
        "contract_blocked",
        "transient_failed",
        "response_contract_failed",
        "unattempted",
        "unclassified",
    )
    assert set(RELEASE_TERMINAL_REQUEST_STATES).isdisjoint(INCOMPLETE_REQUEST_STATES)
    assert RELEASE_TERMINAL_REQUEST_STATES + INCOMPLETE_REQUEST_STATES == REQUEST_ACCOUNTING_STATES
    contracts = _contracts_by_state()
    for state in INCOMPLETE_REQUEST_STATES:
        assert is_release_terminal_request_state(state) is False
        assert contracts[state]["release_terminal"] is False
        assert contracts[state]["state_class"] == "incomplete"


def test_terminal_contract_resource_is_canonical_and_byte_idempotent(tmp_path: Path) -> None:
    pass_a = tmp_path / "pass-a" / NBA_API_TERMINAL_STATE_RESOURCE
    pass_b = tmp_path / "pass-b" / NBA_API_TERMINAL_STATE_RESOURCE
    assert write_pinned_terminal_state(pass_a) is False
    assert write_pinned_terminal_state(pass_b) is False
    assert write_pinned_terminal_state(pass_a) is True
    assert write_pinned_terminal_state(pass_a, check=True) is True
    assert pass_a.read_bytes() == pass_b.read_bytes() == _resource_path().read_bytes()
    assert pass_a.read_bytes() == _canonical_bytes(build_pinned_terminal_state_payload()) + b"\n"
    assert load_pinned_terminal_state_payload(pass_a) == build_pinned_terminal_state_payload()


def test_terminal_contract_has_no_request_or_competition_dependency() -> None:
    current_package = "nbadb.core"
    forbidden_prefixes = (
        "nbadb.core.nba_api_request_surface",
        "nbadb.orchestrate.request_closure_runtime",
        "nbadb.core.nba_api_competition_identity",
    )

    def import_edges(import_tree: ast.AST) -> set[str]:
        edges: set[str] = set()
        for node in ast.walk(import_tree):
            if isinstance(node, ast.Import):
                edges.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package_parts = current_package.split(".")
                    assert node.level <= len(package_parts)
                    parent = ".".join(package_parts[: len(package_parts) - node.level + 1])
                    module = ".".join(part for part in (parent, node.module) if part)
                else:
                    module = node.module or ""
                if module:
                    edges.add(module)
                edges.update(
                    f"{module}.{alias.name}" if module else alias.name for alias in node.names
                )
        return edges

    def forbidden_import_edges(import_tree: ast.AST) -> set[str]:
        return {
            edge
            for edge in import_edges(import_tree)
            for forbidden in forbidden_prefixes
            if edge == forbidden or edge.startswith(f"{forbidden}.")
        }

    source_path = Path(inspect.getsourcefile(terminal) or "")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    assert not forbidden_import_edges(tree)
    assert forbidden_import_edges(
        ast.parse("import nbadb.core.nba_api_request_surface as request_surface")
    )
    assert forbidden_import_edges(
        ast.parse(
            "from nbadb.core.nba_api_request_surface import "
            "build_pinned_request_surface_payload as build_payload"
        )
    )
    assert forbidden_import_edges(
        ast.parse("from nbadb.core import nba_api_request_surface as request_surface")
    )
    assert forbidden_import_edges(
        ast.parse("from . import nba_api_competition_identity as competition_identity")
    )
    assert not forbidden_import_edges(
        ast.parse("import safe.package.nba_api_request_surface_helper")
    )
    assert not forbidden_import_edges(ast.parse("import nbadb.core.nba_api_request_surface_utils"))
    payload = build_pinned_terminal_state_payload()
    assert payload["source_inventory"] == [
        {
            "name": "terminal_state_contract",
            "source_kind": "task_packet_policy",
            "task_id": "A1.3a",
            "upstream_resources": [],
        },
        {
            "name": "public_api_contract",
            "source_kind": "task_packet_policy",
            "task_id": "A1.3a",
            "upstream_resources": [],
        },
    ]


def test_terminal_state_module_exports_exact_public_contract() -> None:
    assert terminal.__all__ == [
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
    assert tuple(field.name for field in fields(terminal.TerminalRequestBinding)) == (
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
    )
    assert tuple(field.name for field in fields(terminal.UpstreamUnavailableSupportAuthority)) == (
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
    )
    assert tuple(field.name for field in fields(terminal.TypedUpstreamUnavailableEvidence)) == (
        "request_binding",
        "support_authority",
        "state",
        "unavailable_evidence_sha256",
    )
