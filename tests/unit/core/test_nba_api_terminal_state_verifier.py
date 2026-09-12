from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
from copy import deepcopy
from dataclasses import asdict, replace
from typing import TYPE_CHECKING

import pytest

import nbadb.core.nba_api_terminal_state_verifier as verifier_module
from nbadb.core.nba_api_terminal_state_verifier import (
    NbaApiTerminalStateVerificationError,
    build_independent_terminal_request_binding,
    build_independent_terminal_state_payload,
    build_independent_typed_upstream_unavailable_evidence,
    build_independent_upstream_unavailable_support_authority,
    reproduce_typed_upstream_unavailable_evidence,
    verify_pinned_terminal_state_authority,
    verify_terminal_state_authority_file,
)

if TYPE_CHECKING:
    from pathlib import Path

_FORBIDDEN_IMPORTS = {
    "nbadb.core.nba_api_terminal_state",
    "nbadb.core.nba_api_request_surface",
    "nbadb.core.nba_api_request_surface_verifier",
    "nbadb.orchestrate.request_closure_runtime",
    "nbadb.core.nba_api_competition_identity",
    "nbadb.core.nba_api_competition_identity_verifier",
}
_POLICY_FIELDS = {
    "accounting_state_contracts",
    "domain_separators",
    "incomplete_request_states",
    "kind",
    "nba_api_version",
    "optional_absent_contract",
    "release_terminal_request_states",
    "result_occurrence_states",
    "schema_version",
    "task_id",
    "wire_request_states",
}


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _resign(payload: dict[str, object]) -> None:
    payload["source_inventory_sha256"] = _digest(payload["source_inventory"])
    payload["terminal_policy_sha256"] = _digest({key: payload[key] for key in _POLICY_FIELDS})
    body = dict(payload)
    body.pop("payload_sha256", None)
    payload["payload_sha256"] = _digest(body)


def _write_candidate(path: Path, payload: dict[str, object]) -> Path:
    path.write_bytes(_canonical(payload) + b"\n")
    return path


def _normalized_import_edges(
    source: str,
    module_name: str,
    *,
    is_package: bool = False,
) -> set[str]:
    tree = ast.parse(source)
    package = module_name if is_package else module_name.rpartition(".")[0]
    edges: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            edges.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                relative_name = "." * node.level + (node.module or "")
                base = importlib.util.resolve_name(relative_name, package)
            else:
                base = node.module or ""
            if base:
                edges.add(base)
            for alias in node.names:
                if alias.name != "*":
                    edges.add(f"{base}.{alias.name}" if base else alias.name)
    return edges


def _imports_target(edge: str, target: str) -> bool:
    return edge == target or edge.startswith(target + ".")


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def test_independent_terminal_contract_matches_primary_without_importing_primary() -> None:
    expected = build_independent_terminal_state_payload()
    proof = verify_pinned_terminal_state_authority()

    actual_edges = _normalized_import_edges(
        inspect.getsource(verifier_module),
        "nbadb.core.nba_api_terminal_state_verifier",
    )
    assert not any(
        _imports_target(edge, target) for edge in actual_edges for target in _FORBIDDEN_IMPORTS
    )
    for target in sorted(_FORBIDDEN_IMPORTS):
        parent, leaf = target.rsplit(".", 1)
        package_part = parent.split(".", 1)[1]
        assert _imports_target(target, target)
        assert _imports_target(f"{target}.child", target)
        assert not _imports_target(f"{target}_extra", target)
        positive_import_fixtures = (
            (f"import {target} as forbidden", "nbadb.audit.synthetic", False),
            (f"from {parent} import {leaf} as forbidden", "nbadb.audit.synthetic", False),
            (f"import {target}.child as forbidden", "nbadb.audit.synthetic", False),
            (f"from . import {leaf} as forbidden", parent, True),
            (f"from ..{package_part} import {leaf} as forbidden", "nbadb.audit.synthetic", False),
        )
        for source, module_name, is_package in positive_import_fixtures:
            edges = _normalized_import_edges(
                source,
                module_name,
                is_package=is_package,
            )
            assert any(_imports_target(edge, target) for edge in edges)
        safe_leaf = f"{leaf}_extra"
        safe_negative_fixtures = (
            f"import {parent}.{safe_leaf} as allowed",
            f"from {parent} import {safe_leaf} as allowed",
        )
        for source in safe_negative_fixtures:
            edges = _normalized_import_edges(source, "nbadb.audit.synthetic")
            assert not any(_imports_target(edge, target) for edge in edges)
    assert proof.wire_request_states == (
        "success_nonempty",
        "success_empty",
        "upstream_unavailable",
        "contract_blocked",
        "transient_failed",
        "response_contract_failed",
        "unattempted",
        "unclassified",
    )
    assert proof.release_terminal_request_states == (
        "success_nonempty",
        "success_empty",
        "upstream_unavailable",
    )
    assert proof.incomplete_request_states == (
        "contract_blocked",
        "transient_failed",
        "response_contract_failed",
        "unattempted",
        "unclassified",
    )
    assert proof.result_occurrence_states == (
        "present_nonempty",
        "present_empty",
        "absent_optional",
    )
    assert proof.checked_payload_sha256 == expected["payload_sha256"]
    assert tuple(row.state for row in proof.accounting_state_contracts) == (
        *proof.release_terminal_request_states,
        *proof.incomplete_request_states,
    )

    request_arguments = {
        "request_surface_sha256": _sha("request-surface"),
        "runtime_contract_payload_sha256": _sha("runtime-contract"),
        "provider_authority_sha256": _sha("provider-authority"),
        "route_manifest_sha256": _sha("route-manifest"),
        "scope_sha256": _sha("scope"),
        "provider_request_sha256": _sha("provider-request"),
        "source_request_sha256": _sha("source-request"),
        "competition_authority_sha256": _sha("competition-authority"),
        "competition_scope_sha256": _sha("competition-scope"),
        "competition_requirement_sha256": _sha("competition-requirement"),
        "role_binding_sha256": _sha("role-binding"),
        "source_evidence_sha256": _sha("source-evidence"),
        "source_family": "stats",
        "endpoint_id": "LeagueGameLog",
        "route_ids": ("league_game_log",),
    }
    request = build_independent_terminal_request_binding(**request_arguments)

    class RouteTuple(tuple[str, ...]):
        pass

    for field, unsafe_value in (
        ("source_family", "foreign_family"),
        ("endpoint_id", "../unsafe_endpoint"),
        ("endpoint_id", "unsafe/endpoint"),
        ("endpoint_id", "a" * 257),
        ("route_ids", ("unsafe/route",)),
        ("route_ids", ("z_route", "a_route")),
        ("route_ids", ["league_game_log"]),
        ("route_ids", RouteTuple(("league_game_log",))),
    ):
        unsafe_request = {**request_arguments, field: unsafe_value}
        with pytest.raises(NbaApiTerminalStateVerificationError):
            build_independent_terminal_request_binding(**unsafe_request)

    support_arguments = {
        "authority_kind": "endpoint_support_cell",
        "authority_version": 1,
        "support_authority_sha256": _sha("support-authority"),
        "support_cell_id": "stats:LeagueGameLog:00",
        "support_cell_sha256": _sha("support-cell"),
        "provider_authority_sha256": request.provider_authority_sha256,
        "request_surface_sha256": request.request_surface_sha256,
        "source_family": request.source_family,
        "endpoint_id": request.endpoint_id,
        "scope_sha256": request.scope_sha256,
        "competition_scope_sha256": request.competition_scope_sha256,
        "source_request_sha256": request.source_request_sha256,
        "provider_request_sha256": request.provider_request_sha256,
        "status": "upstream_unavailable",
        "reason_code": "provider_contract_absent_for_scope",
        "independent_verifier_id": "support-verifier-v1",
        "independent_verifier_sha256": _sha("support-verifier"),
    }
    support = build_independent_upstream_unavailable_support_authority(**support_arguments)
    for field, invalid_value in (
        ("authority_version", True),
        ("authority_version", 0),
        ("support_cell_sha256", "A" * 64),
    ):
        invalid_support = {**support_arguments, field: invalid_value}
        with pytest.raises(NbaApiTerminalStateVerificationError):
            build_independent_upstream_unavailable_support_authority(**invalid_support)
    for field in (
        "authority_kind",
        "support_cell_id",
        "reason_code",
        "independent_verifier_id",
    ):
        for unsafe_value in ("../unsafe/identity", "a" * 257):
            unsafe_support = {**support_arguments, field: unsafe_value}
            with pytest.raises(NbaApiTerminalStateVerificationError, match="safe"):
                build_independent_upstream_unavailable_support_authority(**unsafe_support)

    evidence = build_independent_typed_upstream_unavailable_evidence(request, support)
    serialized_evidence = asdict(evidence)
    serialized_request = serialized_evidence["request_binding"]
    assert isinstance(serialized_request, dict)
    serialized_request["route_ids"] = list(serialized_request["route_ids"])
    assert reproduce_typed_upstream_unavailable_evidence(serialized_evidence) == evidence

    class EvidenceMapping(dict[str, object]):
        pass

    with pytest.raises(NbaApiTerminalStateVerificationError, match="schema"):
        reproduce_typed_upstream_unavailable_evidence(EvidenceMapping(serialized_evidence))
    with pytest.raises(NbaApiTerminalStateVerificationError, match="concrete type"):
        build_independent_typed_upstream_unavailable_evidence(  # type: ignore[arg-type]
            object(),
            support,
        )
    with pytest.raises(NbaApiTerminalStateVerificationError, match="concrete type"):
        build_independent_typed_upstream_unavailable_evidence(  # type: ignore[arg-type]
            request,
            object(),
        )
    cross_binding_mutations = {
        "request_surface_sha256": _sha("foreign-request-surface"),
        "provider_authority_sha256": _sha("foreign-provider-authority"),
        "provider_request_sha256": _sha("foreign-provider-request"),
        "scope_sha256": _sha("foreign-scope"),
        "competition_scope_sha256": _sha("foreign-competition-scope"),
        "source_request_sha256": _sha("foreign-source-request"),
        "source_family": "live",
        "endpoint_id": "ForeignEndpoint",
    }
    for field, value in cross_binding_mutations.items():
        rebound_support = build_independent_upstream_unavailable_support_authority(
            **{**support_arguments, field: value}
        )
        with pytest.raises(NbaApiTerminalStateVerificationError, match="foreign request"):
            build_independent_typed_upstream_unavailable_evidence(
                request,
                rebound_support,
            )
    with pytest.raises(NbaApiTerminalStateVerificationError, match="request binding digest"):
        build_independent_typed_upstream_unavailable_evidence(
            replace(request, request_binding_sha256=_sha("tampered-request-binding")),
            support,
        )
    with pytest.raises(NbaApiTerminalStateVerificationError, match="support binding digest"):
        build_independent_typed_upstream_unavailable_evidence(
            request,
            replace(support, support_binding_sha256=_sha("tampered-support-binding")),
        )
    serialized_evidence["unavailable_evidence_sha256"] = _sha("tampered-evidence")
    with pytest.raises(NbaApiTerminalStateVerificationError, match="evidence digest"):
        reproduce_typed_upstream_unavailable_evidence(serialized_evidence)


def test_independent_verifier_rejects_foreign_release_terminal_state(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_independent_terminal_state_payload())
    wire = payload["wire_request_states"]
    release = payload["release_terminal_request_states"]
    contracts = payload["accounting_state_contracts"]
    assert isinstance(wire, list)
    assert isinstance(release, list)
    assert isinstance(contracts, list)
    wire[0] = "foreign_success"
    release[0] = "foreign_success"
    assert isinstance(contracts[0], dict)
    contracts[0]["state"] = "foreign_success"
    _resign(payload)

    with pytest.raises(NbaApiTerminalStateVerificationError, match="independent policy"):
        verify_terminal_state_authority_file(
            _write_candidate(tmp_path / "foreign-release.json", payload)
        )


def test_independent_verifier_rejects_release_and_incomplete_partition_rebinding(
    tmp_path: Path,
) -> None:
    payload = deepcopy(build_independent_terminal_state_payload())
    release = payload["release_terminal_request_states"]
    incomplete = payload["incomplete_request_states"]
    contracts = payload["accounting_state_contracts"]
    assert isinstance(release, list)
    assert isinstance(incomplete, list)
    assert isinstance(contracts, list)
    release[2], incomplete[0] = incomplete[0], release[2]
    assert isinstance(contracts[2], dict)
    assert isinstance(contracts[3], dict)
    contracts[2]["release_terminal"] = False
    contracts[2]["state_class"] = "incomplete"
    contracts[3]["release_terminal"] = True
    contracts[3]["state_class"] = "release_terminal"
    _resign(payload)

    with pytest.raises(NbaApiTerminalStateVerificationError, match="independent policy"):
        verify_terminal_state_authority_file(
            _write_candidate(tmp_path / "partition-rebinding.json", payload)
        )


def test_independent_verifier_rejects_missing_or_duplicate_accounting_states(
    tmp_path: Path,
) -> None:
    base = build_independent_terminal_state_payload()
    candidates = []

    missing = deepcopy(base)
    missing_contracts = missing["accounting_state_contracts"]
    assert isinstance(missing_contracts, list)
    missing_contracts.pop()
    _resign(missing)
    candidates.append(("missing", missing))

    duplicate = deepcopy(base)
    duplicate_contracts = duplicate["accounting_state_contracts"]
    assert isinstance(duplicate_contracts, list)
    duplicate_contracts[-1] = deepcopy(duplicate_contracts[-2])
    _resign(duplicate)
    candidates.append(("duplicate", duplicate))

    for label, candidate in candidates:
        with pytest.raises(
            NbaApiTerminalStateVerificationError,
            match="independent policy",
        ):
            verify_terminal_state_authority_file(
                _write_candidate(tmp_path / f"{label}-accounting.json", candidate)
            )


def test_independent_verifier_rejects_resource_digest_drift(tmp_path: Path) -> None:
    expected = build_independent_terminal_state_payload()
    mutations = {
        "source-inventory": "source_inventory_sha256",
        "terminal-policy": "terminal_policy_sha256",
        "payload": "payload_sha256",
    }
    for label, field in mutations.items():
        candidate = deepcopy(expected)
        candidate[field] = "0" * 64
        with pytest.raises(NbaApiTerminalStateVerificationError, match="digest"):
            verify_terminal_state_authority_file(
                _write_candidate(tmp_path / f"{label}-digest.json", candidate)
            )

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(NbaApiTerminalStateVerificationError, match="canonical JSON"):
        verify_terminal_state_authority_file(noncanonical)
