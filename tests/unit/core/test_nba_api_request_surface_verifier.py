from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
from copy import deepcopy
from dataclasses import fields, replace
from typing import Any

import pytest
from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library.http import NBAStatsHTTP

import nbadb.core.nba_api_request_surface_verifier as verifier_module
from nbadb.core.nba_api_competition_verifier import verify_pinned_competition_authority
from nbadb.core.nba_api_request_surface import (
    AuthoritativeRouteManifest,
    NbaApiRequestSurfaceError,
    RequestClosureIteration,
    RequestClosureReceipt,
    RequestExpansionEvidence,
    RequestRouteBinding,
    RequestScopeDimension,
    RequestScopeManifest,
    RequestTerminalEvidence,
    RouteRequestSpec,
    _route_spec_payload,
    build_pinned_request_surface_payload,
    canonical_provider_request_key,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_request_surface_verifier import (
    _authority,
    _load_resource,
    build_independent_package_inventory,
    build_independent_surface_atoms,
    verify_request_closure_independently,
)
from nbadb.core.nba_api_terminal_state import (
    UpstreamUnavailableSupportAuthority,
    build_terminal_request_binding,
    build_typed_upstream_unavailable_evidence,
)
from nbadb.core.nba_api_terminal_state_verifier import (
    verify_pinned_terminal_state_authority,
)

_A = "a" * 64
_B = "b" * 64
_REQUEST_RESOURCE = "nba_api_request_surface_v1_11_4.json"
_FORBIDDEN_IMPORTS = {
    "nbadb.core.nba_api_terminal_state",
    "nbadb.orchestrate.request_closure_runtime",
    "nbadb.core.nba_api_competition_identity",
    "nbadb.core.nba_api_competition_identity_verifier",
}


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


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


def _unsafe_replace(instance: Any, **changes: object) -> Any:
    clone = object.__new__(type(instance))
    for field in fields(instance):
        object.__setattr__(
            clone, field.name, changes.get(field.name, getattr(instance, field.name))
        )
    return clone


def _route_manifest(route: RouteRequestSpec) -> AuthoritativeRouteManifest:
    authority = pinned_request_surface_authority()
    payload = build_pinned_request_surface_payload()
    return AuthoritativeRouteManifest(
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        derivation_policy_sha256=str(payload["derivation_policy_sha256"]),
        registry_manifest_sha256=_digest([_route_spec_payload(route)]),
        routes=(route,),
    )


def _rebind_terminal_request(
    binding: object,
    **changes: object,
) -> object:
    values = {
        "request_surface_sha256": binding.request_surface_sha256,
        "runtime_contract_payload_sha256": binding.runtime_contract_payload_sha256,
        "provider_authority_sha256": binding.provider_authority_sha256,
        "route_manifest_sha256": binding.route_manifest_sha256,
        "scope_sha256": binding.scope_sha256,
        "provider_request_sha256": binding.provider_request_sha256,
        "source_request_sha256": binding.source_request_sha256,
        "competition_authority_sha256": binding.competition_authority_sha256,
        "competition_scope_sha256": binding.competition_scope_sha256,
        "competition_requirement_sha256": binding.competition_requirement_sha256,
        "role_binding_sha256": binding.role_binding_sha256,
        "source_evidence_sha256": binding.source_evidence_sha256,
        "source_family": binding.source_family,
        "endpoint_id": binding.endpoint_id,
        "route_ids": binding.route_ids,
    }
    values.update(changes)
    return build_terminal_request_binding(**values)  # type: ignore[arg-type]


def _receipt(state: str = "success_nonempty") -> RequestClosureReceipt:
    authority = pinned_request_surface_authority()
    endpoint = authority.endpoint("stats", "CommonAllPlayers")
    parameters = (("season", "2025-26"),)
    route = RouteRequestSpec("route_a", "stats", "CommonAllPlayers", parameters)
    manifest = _route_manifest(route)
    request = materialize_provider_request(
        endpoint,
        dict(parameters),
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    unit = canonical_provider_request_key(
        endpoint,
        dict(parameters),
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    assert request.provider_request_sha256 == unit
    values = dict(request.materialized_parameters)
    dependency_values: dict[str, set[object]] = {}
    for parameter in endpoint.parameters:
        for dependency in parameter.dependencies:
            dependency_values.setdefault(dependency, set()).add(values[parameter.name])
    dimensions = tuple(
        sorted(
            (
                RequestScopeDimension(
                    dependency_id=dependency,
                    source_kind="independent_test_scope",
                    source_authority_sha256=_B,
                    values=tuple(sorted(raw_values, key=str)),
                )
                for dependency, raw_values in dependency_values.items()
            ),
            key=lambda item: item.dimension_sha256,
        )
    )
    scope = RequestScopeManifest(
        request_surface_sha256=authority.surface_sha256,
        scope_id="independent_test_scope",
        seed_route_ids=(route.route_id,),
        dimensions=dimensions,
    )
    seed = RequestExpansionEvidence(
        evidence_id="seed_receipt",
        evidence_kind="seed",
        request_surface_sha256=authority.surface_sha256,
        scope_sha256=scope.scope_sha256,
        input_units=(),
        discovered_units=(unit,),
        source_values=(route.route_id,),
        complete=True,
    )
    fixed = RequestExpansionEvidence(
        evidence_id="fixed_receipt",
        evidence_kind="fixed_point",
        request_surface_sha256=authority.surface_sha256,
        scope_sha256=scope.scope_sha256,
        input_units=(unit,),
        discovered_units=(),
        source_values=(),
        complete=True,
    )
    iterations = (
        RequestClosureIteration(
            iteration=0,
            request_surface_sha256=authority.surface_sha256,
            scope_sha256=scope.scope_sha256,
            input_units=(),
            new_units=(unit,),
            output_units=(unit,),
            evidence=(seed,),
        ),
        RequestClosureIteration(
            iteration=1,
            request_surface_sha256=authority.surface_sha256,
            scope_sha256=scope.scope_sha256,
            input_units=(unit,),
            new_units=(),
            output_units=(unit,),
            evidence=(fixed,),
        ),
    )
    request_binding = build_terminal_request_binding(
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        provider_authority_sha256=_A,
        route_manifest_sha256=manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        provider_request_sha256=unit,
        source_request_sha256=_B,
        competition_authority_sha256=_A,
        competition_scope_sha256=_B,
        competition_requirement_sha256=_A,
        role_binding_sha256=_B,
        source_evidence_sha256=_A,
        source_family=route.source_family,
        endpoint_id=route.endpoint_id,
        route_ids=(route.route_id,),
    )
    evidence_kind = {
        "success_nonempty": "receipt_bound_provider_response",
        "success_empty": "receipt_bound_provider_response",
        "upstream_unavailable": "typed_upstream_unavailable_evidence",
        "contract_blocked": "implementation_or_modeled_contract_gap",
        "transient_failed": "transport_timeout_retry_vpn_or_infrastructure_failure",
        "response_contract_failed": "parser_or_response_contract_failure",
        "unattempted": "budget_cap_policy_or_scheduling_exhaustion",
        "unclassified": "classification_unknown",
    }[state]
    evidence_values = {
        "success_nonempty": (
            ("decoded_results_receipt_sha256", _B),
            ("http_status", 200),
            ("persistence_receipt_sha256", _B),
            ("response_body_sha256", _A),
            ("result_occurrence", "present_nonempty"),
            ("row_count", 1),
        ),
        "success_empty": (
            ("decoded_results_receipt_sha256", _B),
            ("http_status", 200),
            ("persistence_receipt_sha256", _B),
            ("response_body_sha256", _A),
            ("result_occurrence", "present_empty"),
            ("row_count", 0),
        ),
        "upstream_unavailable": (),
        "contract_blocked": (
            ("contract_evidence_sha256", _A),
            ("reason_code", "contract_not_modeled"),
        ),
        "transient_failed": (
            ("attempt_count", 1),
            ("failure_class", "transport_timeout"),
        ),
        "response_contract_failed": (
            ("failure_class", "invalid_response_shape"),
            ("response_body_sha256", _A),
        ),
        "unattempted": (("reason_code", "not_scheduled"),),
        "unclassified": (("classification_input_sha256", _A),),
    }[state]
    unavailable = None
    if state == "upstream_unavailable":
        support_values: dict[str, object] = {
            "authority_kind": "endpoint_support_evidence",
            "authority_version": 1,
            "support_authority_sha256": _A,
            "support_cell_id": "independent_test_support_cell",
            "support_cell_sha256": _B,
            "provider_authority_sha256": request_binding.provider_authority_sha256,
            "request_surface_sha256": request_binding.request_surface_sha256,
            "source_family": request_binding.source_family,
            "endpoint_id": request_binding.endpoint_id,
            "scope_sha256": request_binding.scope_sha256,
            "competition_scope_sha256": request_binding.competition_scope_sha256,
            "source_request_sha256": request_binding.source_request_sha256,
            "provider_request_sha256": request_binding.provider_request_sha256,
            "status": "upstream_unavailable",
            "reason_code": "declared_provider_unavailable",
            "independent_verifier_id": "support_matrix_verifier_v1",
            "independent_verifier_sha256": _A,
        }
        support_values["support_binding_sha256"] = _digest(
            {
                "domain": "nbadb.nba-api.upstream-unavailable-support.v1",
                "payload": support_values,
            }
        )
        support = UpstreamUnavailableSupportAuthority(
            **support_values  # type: ignore[arg-type]
        )
        unavailable = build_typed_upstream_unavailable_evidence(
            request_binding,
            support,
        )
    terminal = RequestTerminalEvidence(
        request_binding=request_binding,
        state=state,  # type: ignore[arg-type]
        evidence_kind=evidence_kind,  # type: ignore[arg-type]
        evidence_values=evidence_values,
        upstream_unavailable_evidence=unavailable,
    )
    return RequestClosureReceipt(
        request_surface_sha256=authority.surface_sha256,
        scope=scope,
        route_manifest=manifest,
        bindings=(RequestRouteBinding(unit, (route.route_id,)),),
        iterations=iterations,
        terminal_evidence=(terminal,),
    )


def test_independent_source_inventory_is_complete_and_deterministic() -> None:
    first = build_independent_package_inventory()
    _authority.cache_clear()
    second = build_independent_package_inventory()

    assert first == second
    assert first.stats_endpoint_count == 139
    assert first.live_endpoint_count == 4
    assert first.parameter_occurrence_count == 1971
    assert first.result_set_count == 409
    assert first.header_occurrence_count == 9944
    assert first.static_dataset_count == 4
    assert first.static_embedded_row_count == 6293
    assert first.static_helper_count == 32
    assert first.distribution_record_entry_count == 195
    assert first.distribution_record_hashed_entry_count == 194
    assert first.source_atom_count == 12072
    assert first.independently_derived_extended_header_count == 47


def test_all_parameter_occurrences_join_source_atoms_without_differences() -> None:
    atoms = [
        atom
        for atom in build_independent_surface_atoms()
        if atom.get("kind") == "parameter_occurrence"
    ]
    occurrences = build_pinned_request_surface_payload()["parameter_occurrences"]
    assert isinstance(occurrences, list)
    fields = (
        "name",
        "query_name",
        "location",
        "required",
        "nullable",
        "has_default",
        "default",
        "default_authority",
        "default_expression",
    )
    atom_rows = {
        (atom["source_family"], atom["endpoint_id"], atom["ordinal"]): tuple(
            atom.get(field) for field in fields
        )
        for atom in atoms
    }
    occurrence_rows = {
        (row["source_family"], row["endpoint_id"], row["ordinal"]): tuple(
            row.get(field) for field in fields
        )
        for row in occurrences
        if isinstance(row, dict)
    }

    assert len(atom_rows) == len(occurrence_rows) == 1971
    assert atom_rows == occurrence_rows
    dynamic_value_types = {
        "GameDate.default": "str",
        "Season.default": "str",
        "SeasonAll.default": "str",
        "SeasonAll_Time.default": "str",
        "SeasonID.default": "str",
        "SeasonYear.default": "int",
    }
    source_signature_differences = []
    for row in occurrences:
        assert isinstance(row, dict)
        expression = row["default_expression"]
        signature_payload = {
            "schema_version": 1,
            "kind": "nba_api_parameter_source_signature",
            "occurrence_id": row["occurrence_id"],
            "ordinal": row["ordinal"],
            "name": row["name"],
            "query_name": row["query_name"],
            "location": row["location"],
            "required": row["required"],
            "nullable": row["nullable"],
            "has_default": row["has_default"],
            "default": row["default"],
            "default_authority": row["default_authority"],
            "default_expression": expression,
            "default_value_type": (
                dynamic_value_types[expression]
                if isinstance(expression, str)
                else type(row["default"]).__name__
                if row["has_default"]
                else None
            ),
        }
        if _digest(signature_payload) != row["source_signature_sha256"]:
            source_signature_differences.append(row["occurrence_id"])
    assert source_signature_differences == []


def test_independent_inventory_rejects_primary_tuple_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = pinned_request_surface_authority()
    endpoint = authority.endpoints[0]
    drifted_endpoint = replace(endpoint, endpoint_slug="tuple_replacement")
    drifted = replace(authority, endpoints=(drifted_endpoint, *authority.endpoints[1:]))
    monkeypatch.setattr(
        "nbadb.core.nba_api_request_surface_verifier.build_request_surface_authority",
        lambda: drifted,
    )
    _authority.cache_clear()

    with pytest.raises(NbaApiRequestSurfaceError, match="rebuilt exact authority"):
        build_independent_package_inventory()


def test_inventory_and_verification_never_send_provider_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("independent verifier attempted network I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _network_forbidden)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", _network_forbidden)
    receipt = _receipt()
    proof = verify_request_closure_independently(receipt)
    assert replace(receipt, independent_proof=proof).green is True


@pytest.mark.parametrize("tamper", ["count", "manifest_digest"])
def test_inventory_rejects_fabricated_counts_and_digests(
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    _authority.cache_clear()

    def _tampered_resource(name: str) -> dict[str, Any]:
        payload = _load_resource(name)
        if name.endswith("request_surface_v1_11_4.json"):
            payload = dict(payload)
            if tamper == "count":
                summary = dict(payload["summary"])
                summary["stats_endpoint_count"] += 1
                payload["summary"] = summary
            else:
                payload["manifest_sha256"] = _A
        return payload

    monkeypatch.setattr(
        "nbadb.core.nba_api_request_surface_verifier._load_resource",
        _tampered_resource,
    )
    with pytest.raises(NbaApiRequestSurfaceError, match="fabricated"):
        build_independent_package_inventory()


def test_independent_inventory_rejects_self_consistent_foreign_surface_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_load = _load_resource

    def _foreign_surface_resource(name: str) -> dict[str, Any]:
        payload = deepcopy(original_load(name))
        if name.endswith("request_surface_v1_11_4.json"):
            payload["surface_sha256"] = _A
            body = dict(payload)
            body.pop("payload_sha256")
            payload["payload_sha256"] = _digest(body)
        return payload

    monkeypatch.setattr(
        "nbadb.core.nba_api_request_surface_verifier._load_resource",
        _foreign_surface_resource,
    )
    _authority.cache_clear()
    with pytest.raises(NbaApiRequestSurfaceError, match="rebuilt exact authority"):
        build_independent_package_inventory()


def test_independent_inventory_rejects_foreign_competition_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_load = _load_resource

    def _foreign_competition_resource(name: str) -> dict[str, Any]:
        payload = deepcopy(original_load(name))
        if name.endswith("request_surface_v1_11_4.json"):
            reserved = dict(payload["reserved_authorities"])
            reserved["league_finite_values"] = _A
            payload["reserved_authorities"] = reserved
            body = dict(payload)
            body.pop("payload_sha256")
            payload["payload_sha256"] = _digest(body)
        return payload

    monkeypatch.setattr(
        "nbadb.core.nba_api_request_surface_verifier._load_resource",
        _foreign_competition_resource,
    )
    _authority.cache_clear()
    with pytest.raises(NbaApiRequestSurfaceError, match="competition authority"):
        build_independent_package_inventory()


def test_independent_inventory_rejects_foreign_competition_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proof = verify_pinned_competition_authority()
    monkeypatch.setattr(
        "nbadb.core.nba_api_request_surface_verifier.verify_pinned_competition_authority",
        lambda: replace(proof, checked_payload_sha256=_A),
    )
    _authority.cache_clear()
    with pytest.raises(NbaApiRequestSurfaceError, match="competition authority"):
        build_independent_package_inventory()


def test_independent_request_surface_rejects_terminal_contract_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_edges = _normalized_import_edges(
        inspect.getsource(verifier_module),
        "nbadb.core.nba_api_request_surface_verifier",
    )
    independent_terminal = "nbadb.core.nba_api_terminal_state_verifier"
    assert any(_imports_target(edge, independent_terminal) for edge in actual_edges)
    assert not any(
        _imports_target(edge, target) for edge in actual_edges for target in _FORBIDDEN_IMPORTS
    )
    for source, module_name, is_package in (
        (
            "import nbadb.core.nba_api_terminal_state_verifier as terminal",
            "nbadb.audit.synthetic",
            False,
        ),
        (
            "from nbadb.core import nba_api_terminal_state_verifier as terminal",
            "nbadb.audit.synthetic",
            False,
        ),
        (
            "from . import nba_api_terminal_state_verifier as terminal",
            "nbadb.core",
            True,
        ),
        (
            "from ..core import nba_api_terminal_state_verifier as terminal",
            "nbadb.audit.synthetic",
            False,
        ),
    ):
        edges = _normalized_import_edges(
            source,
            module_name,
            is_package=is_package,
        )
        assert any(_imports_target(edge, independent_terminal) for edge in edges)
    safe_edges = _normalized_import_edges(
        "import nbadb.core.nba_api_terminal_state_verifier_extra as allowed",
        "nbadb.audit.synthetic",
    )
    assert not any(_imports_target(edge, independent_terminal) for edge in safe_edges)

    release_states = {
        "success_nonempty",
        "success_empty",
        "upstream_unavailable",
    }
    all_states = (
        "success_nonempty",
        "success_empty",
        "upstream_unavailable",
        "contract_blocked",
        "transient_failed",
        "response_contract_failed",
        "unattempted",
        "unclassified",
    )
    for state in all_states:
        receipt = _receipt(state)
        proof = verify_request_closure_independently(receipt)
        verified = replace(receipt, independent_proof=proof)
        assert verified.green is (state in release_states)

    success = _receipt()
    success_terminal = success.terminal_evidence[0]
    for required_receipt in (
        "decoded_results_receipt_sha256",
        "persistence_receipt_sha256",
    ):
        incomplete_values = tuple(
            item for item in success_terminal.evidence_values if item[0] != required_receipt
        )
        incomplete_terminal = _unsafe_replace(
            success_terminal,
            evidence_values=incomplete_values,
        )
        incomplete_receipt = _unsafe_replace(
            success,
            terminal_evidence=(incomplete_terminal,),
        )
        with pytest.raises(NbaApiRequestSurfaceError, match="fields"):
            verify_request_closure_independently(incomplete_receipt)

    for rebinding in (
        {"request_surface_sha256": _A},
        {"runtime_contract_payload_sha256": _A},
        {"route_manifest_sha256": _A},
        {"scope_sha256": _A},
        {"route_ids": ("foreign_alias",)},
        {"source_family": "live"},
        {"endpoint_id": "foreign_endpoint"},
    ):
        rebound_terminal = _unsafe_replace(
            success_terminal,
            request_binding=_rebind_terminal_request(
                success_terminal.request_binding,
                **rebinding,
            ),
        )
        rebound_receipt = _unsafe_replace(
            success,
            terminal_evidence=(rebound_terminal,),
        )
        with pytest.raises(NbaApiRequestSurfaceError, match="binding|aliases"):
            verify_request_closure_independently(rebound_receipt)

    unavailable_receipt = _receipt("upstream_unavailable")
    unavailable_terminal = unavailable_receipt.terminal_evidence[0]
    missing_typed = _unsafe_replace(
        unavailable_terminal,
        upstream_unavailable_evidence=None,
    )
    with pytest.raises(NbaApiRequestSurfaceError, match="complete typed"):
        verify_request_closure_independently(
            _unsafe_replace(
                unavailable_receipt,
                terminal_evidence=(missing_typed,),
            )
        )
    typed = unavailable_terminal.upstream_unavailable_evidence
    assert typed is not None
    unsafe_support = _unsafe_replace(
        typed.support_authority,
        reason_code="unsafe/path",
    )
    unsafe_typed = _unsafe_replace(typed, support_authority=unsafe_support)
    with pytest.raises(NbaApiRequestSurfaceError, match="complete typed"):
        verify_request_closure_independently(
            _unsafe_replace(
                unavailable_receipt,
                terminal_evidence=(
                    _unsafe_replace(
                        unavailable_terminal,
                        upstream_unavailable_evidence=unsafe_typed,
                    ),
                ),
            )
        )

    exact_terminal = verify_pinned_terminal_state_authority()
    drifted_terminal = _unsafe_replace(
        exact_terminal,
        release_terminal_request_states=(
            *exact_terminal.release_terminal_request_states,
            "contract_blocked",
        ),
        incomplete_request_states=tuple(
            state
            for state in exact_terminal.incomplete_request_states
            if state != "contract_blocked"
        ),
    )
    original_load = _load_resource
    terminal_drift_reads: list[str] = []

    def _record_terminal_drift_reads(name: str) -> dict[str, Any]:
        terminal_drift_reads.append(name)
        return original_load(name)

    monkeypatch.setattr(verifier_module, "_load_resource", _record_terminal_drift_reads)
    monkeypatch.setattr(
        verifier_module,
        "verify_pinned_terminal_state_authority",
        lambda: drifted_terminal,
    )
    _authority.cache_clear()
    with pytest.raises(NbaApiRequestSurfaceError, match="terminal policy"):
        build_independent_package_inventory()
    assert _REQUEST_RESOURCE not in terminal_drift_reads

    monkeypatch.setattr(
        verifier_module,
        "verify_pinned_terminal_state_authority",
        verify_pinned_terminal_state_authority,
    )
    for mutation in (
        "four_four_partition",
        "pending_terminal_authority",
        "foreign_terminal_kind",
    ):
        candidate_reads: list[str] = []

        def _terminal_drift_resource(
            name: str,
            *,
            mutation: str = mutation,
            candidate_reads: list[str] = candidate_reads,
        ) -> dict[str, Any]:
            candidate_reads.append(name)
            payload = deepcopy(original_load(name))
            if name == _REQUEST_RESOURCE:
                if mutation == "four_four_partition":
                    payload["release_terminal_request_states"] = [
                        "success_nonempty",
                        "success_empty",
                        "upstream_unavailable",
                        "contract_blocked",
                    ]
                    payload["incomplete_request_states"] = [
                        "transient_failed",
                        "response_contract_failed",
                        "unattempted",
                        "unclassified",
                    ]
                elif mutation == "pending_terminal_authority":
                    payload["terminal_policy_sha256"] = "pending_A1.3a"
                else:
                    kinds = dict(payload["terminal_evidence_kinds"])
                    kinds["contract_blocked"] = "receipt_bound_provider_response"
                    payload["terminal_evidence_kinds"] = kinds
                body = dict(payload)
                body.pop("payload_sha256")
                payload["payload_sha256"] = _digest(body)
            return payload

        monkeypatch.setattr(
            verifier_module,
            "_load_resource",
            _terminal_drift_resource,
        )
        _authority.cache_clear()
        with pytest.raises(NbaApiRequestSurfaceError, match="terminal policy"):
            build_independent_package_inventory()
        assert candidate_reads.count(_REQUEST_RESOURCE) == 1
        assert candidate_reads[-1] == _REQUEST_RESOURCE


def test_verifier_rejects_count_preserving_unit_replacement() -> None:
    receipt = _receipt()
    final = receipt.iterations[-1]
    replaced_final = _unsafe_replace(final, input_units=(_A,), output_units=(_A,))
    forged = _unsafe_replace(receipt, iterations=(receipt.iterations[0], replaced_final))
    with pytest.raises(NbaApiRequestSurfaceError, match="replaces|fixed point|chain"):
        verify_request_closure_independently(forged)


@pytest.mark.parametrize("authority_target", ["receipt", "scope", "runtime", "route"])
def test_verifier_rejects_foreign_authority_and_route_manifests(
    authority_target: str,
) -> None:
    receipt = _receipt()
    if authority_target == "receipt":
        forged = _unsafe_replace(receipt, request_surface_sha256=_A)
    elif authority_target == "scope":
        forged_scope = _unsafe_replace(receipt.scope, request_surface_sha256=_A)
        forged = _unsafe_replace(receipt, scope=forged_scope)
    elif authority_target == "runtime":
        forged_manifest = _unsafe_replace(
            receipt.route_manifest, runtime_contract_payload_sha256=_A
        )
        forged = _unsafe_replace(receipt, route_manifest=forged_manifest)
    else:
        forged_manifest = _unsafe_replace(receipt.route_manifest, registry_manifest_sha256=_A)
        forged = _unsafe_replace(receipt, route_manifest=forged_manifest)
    with pytest.raises(NbaApiRequestSurfaceError, match="foreign|fabricated"):
        verify_request_closure_independently(forged)


@pytest.mark.parametrize("duplicate_target", ["routes", "bindings", "terminal"])
def test_verifier_rejects_duplicate_route_unit_and_terminal_inventories(
    duplicate_target: str,
) -> None:
    receipt = _receipt()
    if duplicate_target == "routes":
        route = receipt.route_manifest.routes[0]
        manifest = _unsafe_replace(receipt.route_manifest, routes=(route, route))
        forged = _unsafe_replace(receipt, route_manifest=manifest)
    elif duplicate_target == "bindings":
        forged = _unsafe_replace(receipt, bindings=(receipt.bindings[0], receipt.bindings[0]))
    else:
        forged = _unsafe_replace(
            receipt,
            terminal_evidence=(receipt.terminal_evidence[0], receipt.terminal_evidence[0]),
        )
    with pytest.raises(NbaApiRequestSurfaceError, match="duplicated|bindings|terminal|route"):
        verify_request_closure_independently(forged)


def test_verifier_rejects_terminal_evidence_mismatch_and_noncanonical_input() -> None:
    receipt = _receipt()
    terminal = receipt.terminal_evidence[0]
    mismatched = _unsafe_replace(terminal, evidence_kind="contract_blocked_receipt")
    forged = _unsafe_replace(receipt, terminal_evidence=(mismatched,))
    with pytest.raises(NbaApiRequestSurfaceError, match="typed evidence mismatch"):
        verify_request_closure_independently(forged)

    reversed_values = _unsafe_replace(terminal, evidence_values=terminal.evidence_values[::-1])
    forged = _unsafe_replace(receipt, terminal_evidence=(reversed_values,))
    with pytest.raises(NbaApiRequestSurfaceError, match="noncanonical"):
        verify_request_closure_independently(forged)


@pytest.mark.parametrize("state", ["upstream_unavailable", "contract_blocked"])
def test_verifier_rejects_unavailable_and_blocked_receipt_mismatch(state: str) -> None:
    receipt = _receipt(state)
    terminal = receipt.terminal_evidence[0]
    field = (
        "contract_evidence_sha256" if state == "upstream_unavailable" else "support_matrix_sha256"
    )
    mismatched = _unsafe_replace(
        terminal,
        evidence_values=((field, _A), ("reason_code", "mismatched_authority")),
    )
    forged = _unsafe_replace(receipt, terminal_evidence=(mismatched,))
    with pytest.raises(NbaApiRequestSurfaceError, match="terminal"):
        verify_request_closure_independently(forged)


@pytest.mark.parametrize(
    "verifier_id",
    ["nbadb_request_surface_primary_v2", "self", "self_verifier"],
)
def test_verifier_rejects_primary_and_self_verifier_identities(verifier_id: str) -> None:
    with pytest.raises(NbaApiRequestSurfaceError, match="identity"):
        verify_request_closure_independently(_receipt(), verifier_id=verifier_id)


def test_verifier_rejects_already_self_verified_receipt() -> None:
    receipt = _receipt()
    proof = verify_request_closure_independently(receipt)
    already_verified = replace(receipt, independent_proof=proof)
    with pytest.raises(NbaApiRequestSurfaceError, match="self-verified"):
        verify_request_closure_independently(already_verified)


def test_green_recomputes_instead_of_trusting_a_matching_proof_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _receipt()
    proof = verify_request_closure_independently(receipt)
    verified = replace(receipt, independent_proof=proof)

    def _reject_fabricated(*_args: object, **_kwargs: object) -> None:
        raise NbaApiRequestSurfaceError("independent verifier rejected receipt")

    monkeypatch.setattr(
        "nbadb.core.nba_api_request_surface_verifier.verify_request_closure_independently",
        _reject_fabricated,
    )
    assert verified.green is False
    with pytest.raises(NbaApiRequestSurfaceError, match="not terminally green"):
        verified.require_green()
