from __future__ import annotations

import hashlib
import importlib
import inspect
import json
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library.http import NBAStatsHTTP
from nba_api.stats.static import players as static_players

from nbadb.core import nba_api_request_surface as request_surface
from nbadb.core.nba_api_competition import load_pinned_competition_payload
from nbadb.core.nba_api_request_surface import (
    AuthoritativeRouteManifest,
    CanonicalProviderRequest,
    IndependentClosureProof,
    NbaApiRequestSurfaceError,
    ParameterConstraintEdge,
    RequestClosureIteration,
    RequestClosureReceipt,
    RequestExpansionEvidence,
    RequestRouteBinding,
    RequestScopeDimension,
    RequestScopeManifest,
    RequestTerminalEvidence,
    RouteRequestSpec,
    _classify_parameter,
    _route_spec_payload,
    _validate_parameter_constraint_graph,
    build_pinned_request_surface_payload,
    build_request_surface_authority,
    canonical_provider_request_key,
    load_pinned_request_surface_payload,
    materialize_provider_request,
    pinned_request_surface_authority,
    require_route_conservation,
    write_pinned_request_surface,
)
from nbadb.core.nba_api_terminal_state import (
    UpstreamUnavailableSupportAuthority,
    build_terminal_request_binding,
    build_typed_upstream_unavailable_evidence,
    load_pinned_terminal_state_payload,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from nbadb.core.nba_api_request_surface import (
        EndpointRequestSurface,
        EvidenceValue,
        RequestSurfaceAuthority,
    )


_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        + b"\n"
    )


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)[:-1]).hexdigest()


def _authority() -> RequestSurfaceAuthority:
    return pinned_request_surface_authority()


def test_immutable_authority_and_policy_digests_are_memoized_and_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = _authority()
    pinned_digest = authority.surface_sha256
    expected_pinned = request_surface._sha256(request_surface._authority_payload(authority))
    expected_policy = request_surface._sha256(request_surface._derivation_policy_payload())
    real_sha256 = request_surface._sha256
    hashed_values: list[object] = []

    def _counting_sha256(value: object) -> str:
        hashed_values.append(value)
        return real_sha256(value)

    monkeypatch.setattr(request_surface, "_sha256", _counting_sha256)
    isolated = replace(authority, endpoints=authority.endpoints[:1])
    isolated_digest = isolated.surface_sha256
    construction_hash_count = len(hashed_values)

    assert isolated_digest == real_sha256(request_surface._authority_payload(isolated))
    canonical_verification_hash_count = len(hashed_values)
    assert isolated_digest != pinned_digest
    assert pinned_digest == expected_pinned
    assert authority.surface_sha256 == pinned_digest
    assert isolated.surface_sha256 == isolated_digest
    assert construction_hash_count > 0
    assert canonical_verification_hash_count >= construction_hash_count
    assert len(hashed_values) == canonical_verification_hash_count

    request_surface._derivation_policy_sha256.cache_clear()
    assert request_surface._derivation_policy_sha256() == expected_policy
    assert request_surface._derivation_policy_sha256() == expected_policy
    assert len(hashed_values) == canonical_verification_hash_count + 1


def _request_key(endpoint: EndpointRequestSurface, parameters: Mapping[str, object]) -> str:
    authority = _authority()
    return canonical_provider_request_key(
        endpoint,
        parameters,
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )


def _route_manifest(routes: tuple[RouteRequestSpec, ...]) -> AuthoritativeRouteManifest:
    authority = _authority()
    payload = build_pinned_request_surface_payload()
    return AuthoritativeRouteManifest(
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        derivation_policy_sha256=str(payload["derivation_policy_sha256"]),
        registry_manifest_sha256=_canonical_digest(
            [_route_spec_payload(route) for route in routes]
        ),
        routes=routes,
    )


def _bindings(manifest: AuthoritativeRouteManifest) -> tuple[RequestRouteBinding, ...]:
    authority = _authority()
    grouped: dict[str, list[str]] = {}
    for route in manifest.routes:
        endpoint = authority.endpoint(route.source_family, route.endpoint_id)
        key = _request_key(endpoint, route.parameter_mapping)
        grouped.setdefault(key, []).append(route.route_id)
    return tuple(
        RequestRouteBinding(key, tuple(sorted(route_ids)))
        for key, route_ids in sorted(grouped.items())
    )


def _scope_for_endpoint(
    endpoint: EndpointRequestSurface,
    *,
    seed_route_id: str,
    parameters: Mapping[str, object],
    filter_authorizations: tuple[tuple[str, EvidenceValue], ...] = (),
) -> RequestScopeManifest:
    authority = _authority()
    materialized = materialize_provider_request(
        endpoint,
        parameters,
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    parameter_values = dict(materialized.materialized_parameters)
    values_by_dependency: dict[str, dict[bytes, EvidenceValue]] = {}
    for parameter in endpoint.parameters:
        value = parameter_values[parameter.name]
        for dependency in parameter.dependencies:
            values_by_dependency.setdefault(dependency, {})[_canonical_bytes(value)[:-1]] = value
    dimensions = [
        RequestScopeDimension(
            dependency_id=dependency,
            source_kind="test_scope_inventory",
            source_authority_sha256=_B,
            values=tuple(values[key] for key in sorted(values)),
        )
        for dependency, values in sorted(values_by_dependency.items())
    ]
    dimensions.extend(
        RequestScopeDimension(
            dependency_id="explicit_scope_manifest",
            source_kind="test_filter_inventory",
            source_authority_sha256=_C,
            values=(value,),
            endpoint_id=endpoint.endpoint_id,
            parameter_name=parameter_name,
        )
        for parameter_name, value in filter_authorizations
    )
    return RequestScopeManifest(
        request_surface_sha256=authority.surface_sha256,
        scope_id="test_scope",
        seed_route_ids=(seed_route_id,),
        dimensions=tuple(sorted(dimensions, key=lambda item: item.dimension_sha256)),
    )


def _receipt(
    *,
    route: RouteRequestSpec | None = None,
    terminal_state: str = "success_nonempty",
    independent: bool = True,
    filter_authorizations: tuple[tuple[str, EvidenceValue], ...] = (),
) -> RequestClosureReceipt:
    authority = _authority()
    route = route or RouteRequestSpec(
        route_id="route_a",
        source_family="stats",
        endpoint_id="CommonAllPlayers",
        parameters=(("season", "2025-26"),),
    )
    manifest = _route_manifest((route,))
    bindings = _bindings(manifest)
    unit = bindings[0].provider_request_sha256
    endpoint = authority.endpoint(route.source_family, route.endpoint_id)
    scope = _scope_for_endpoint(
        endpoint,
        seed_route_id=route.route_id,
        parameters=route.parameter_mapping,
        filter_authorizations=filter_authorizations,
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
        evidence_id="fixed_point_receipt",
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
        competition_authority_sha256=_C,
        competition_scope_sha256=_A,
        competition_requirement_sha256=_B,
        role_binding_sha256=_C,
        source_evidence_sha256=_A,
        source_family=route.source_family,
        endpoint_id=route.endpoint_id,
        route_ids=bindings[0].route_ids,
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
    }[terminal_state]
    evidence_values = {
        "success_nonempty": (
            ("decoded_results_receipt_sha256", _B),
            ("http_status", 200),
            ("persistence_receipt_sha256", _C),
            ("response_body_sha256", _A),
            ("result_occurrence", "present_nonempty"),
            ("row_count", 1),
        ),
        "success_empty": (
            ("decoded_results_receipt_sha256", _B),
            ("http_status", 200),
            ("persistence_receipt_sha256", _C),
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
    }[terminal_state]
    if route.pagination_series_id is not None:
        assert route.pagination_ordinal is not None
        pagination_values: list[tuple[str, EvidenceValue]] = [
            ("pagination_ordinal", route.pagination_ordinal),
            ("pagination_terminal", route.pagination_terminal),
        ]
        if route.pagination_terminal:
            pagination_values.append(("pagination_termination_reason", "declared_total"))
        evidence_values = tuple(sorted((*evidence_values, *pagination_values)))
    upstream_unavailable_evidence = None
    if terminal_state == "upstream_unavailable":
        support_values: dict[str, object] = {
            "authority_kind": "endpoint_support_evidence",
            "authority_version": 1,
            "support_authority_sha256": _A,
            "support_cell_id": "test_support_cell",
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
            "independent_verifier_sha256": _C,
        }
        support_values["support_binding_sha256"] = _canonical_digest(
            {
                "domain": "nbadb.nba-api.upstream-unavailable-support.v1",
                "payload": support_values,
            }
        )
        support = UpstreamUnavailableSupportAuthority(
            **support_values  # type: ignore[arg-type]
        )
        upstream_unavailable_evidence = build_typed_upstream_unavailable_evidence(
            request_binding,
            support,
        )
    terminal = (
        RequestTerminalEvidence(
            request_binding=request_binding,
            state=terminal_state,  # type: ignore[arg-type]
            evidence_kind=evidence_kind,  # type: ignore[arg-type]
            evidence_values=evidence_values,
            upstream_unavailable_evidence=upstream_unavailable_evidence,
        ),
    )
    primary = RequestClosureReceipt(
        request_surface_sha256=authority.surface_sha256,
        scope=scope,
        route_manifest=manifest,
        bindings=bindings,
        iterations=iterations,
        terminal_evidence=terminal,
    )
    if not independent:
        return primary
    proof = IndependentClosureProof(
        verifier_id="independent_test_rebuilder",
        request_surface_sha256=authority.surface_sha256,
        scope_sha256=scope.scope_sha256,
        route_manifest_sha256=manifest.manifest_sha256,
        unit_inventory_sha256=_canonical_digest([unit]),
        terminal_inventory_sha256=primary.terminal_inventory_sha256,
    )
    return replace(primary, independent_proof=proof)


def test_compact_artifact_reproduces_complete_exact_pin_surface() -> None:
    payload = load_pinned_request_surface_payload()
    authority = _authority()
    summary = payload["summary"]
    assert isinstance(summary, dict)

    assert payload == build_pinned_request_surface_payload()
    assert payload["surface_sha256"] == authority.surface_sha256
    assert payload["independent_proof"] == {
        "required": True,
        "schema_version": 1,
        "kind": "independent_package_rebuilder_receipt",
        "claim_status": "not_supplied_by_this_artifact",
    }
    assert summary["stats_endpoint_count"] == 139
    assert summary["live_endpoint_count"] == 4
    assert summary["parameter_occurrence_count"] == 1971
    assert summary["typed_parameter_domain_count"] == 1971
    assert summary["source_signature_count"] == 1971
    assert summary["parameter_name_count"] == 339
    assert summary["parameter_constraint_node_count"] == 1981
    assert summary["parameter_constraint_edge_count"] == 2060
    assert summary["static_dataset_count"] == 4
    assert summary["static_embedded_row_count"] == 6293
    assert summary["static_helper_count"] == 32
    assert summary["in_scope_static_helper_count"] == 32
    assert summary["out_of_scope_static_helper_count"] == 0
    assert len(payload["manifest"]["endpoint_contracts"]) == 143
    assert len(payload["manifest"]["static_datasets"]) == 4
    assert len(payload["parameter_occurrences"]) == 1971
    assert payload["reserved_authorities"] == {
        "league_finite_values": load_pinned_competition_payload()["payload_sha256"],
        "release_terminal_state": load_pinned_terminal_state_payload()["terminal_policy_sha256"],
    }
    constraint_graph = payload["parameter_constraint_graph"]
    assert isinstance(constraint_graph, dict)
    assert constraint_graph["graph_sha256"] == summary["parameter_constraint_graph_sha256"]


def test_request_surface_binds_release_terminal_contract_without_hash_cycle() -> None:
    authority = _authority()
    request_payload = build_pinned_request_surface_payload()
    terminal_payload = load_pinned_terminal_state_payload()
    terminal_policy_sha256 = "7226e797a685755311b7b9073f905d7288150e3412d52d95423ef0093548388d"
    evidence_kinds = {
        "success_nonempty": "receipt_bound_provider_response",
        "success_empty": "receipt_bound_provider_response",
        "upstream_unavailable": "typed_upstream_unavailable_evidence",
        "contract_blocked": "implementation_or_modeled_contract_gap",
        "transient_failed": "transport_timeout_retry_vpn_or_infrastructure_failure",
        "response_contract_failed": "parser_or_response_contract_failure",
        "unattempted": "budget_cap_policy_or_scheduling_exhaustion",
        "unclassified": "classification_unknown",
    }

    assert terminal_payload["terminal_policy_sha256"] == terminal_policy_sha256
    assert authority.terminal_policy_sha256 == terminal_policy_sha256
    assert request_payload["schema_version"] == 3
    assert request_payload["derivation_policy_version"] == 6
    assert request_payload["terminal_policy_sha256"] == terminal_policy_sha256
    assert request_payload["reserved_authorities"]["release_terminal_state"] == (
        terminal_policy_sha256
    )
    assert request_payload["manifest"]["terminal_policy_sha256"] == terminal_policy_sha256
    assert request_payload["release_terminal_request_states"] == [
        "success_nonempty",
        "success_empty",
        "upstream_unavailable",
    ]
    assert request_payload["incomplete_request_states"] == [
        "contract_blocked",
        "transient_failed",
        "response_contract_failed",
        "unattempted",
        "unclassified",
    ]
    assert request_payload["terminal_evidence_kinds"] == evidence_kinds
    assert all(item["upstream_resources"] == [] for item in terminal_payload["source_inventory"])
    assert "request_surface_sha256" not in terminal_payload

    success = _receipt(independent=False)
    success_evidence = success.terminal_evidence[0]
    assert success_evidence.request_binding.request_surface_sha256 == authority.surface_sha256
    assert success_evidence.request_binding.route_manifest_sha256 == (
        success.route_manifest.manifest_sha256
    )
    assert set(success_evidence.to_dict()) == {
        "request_binding",
        "state",
        "evidence_kind",
        "evidence_values",
        "upstream_unavailable_evidence",
    }
    assert success.request_binding_inventory_sha256
    with pytest.raises(NbaApiRequestSurfaceError, match="contradicts its state"):
        replace(
            success_evidence,
            evidence_values=tuple(
                (name, "absent_optional" if name == "result_occurrence" else value)
                for name, value in success_evidence.evidence_values
            ),
        )

    unavailable = _receipt(terminal_state="upstream_unavailable", independent=False)
    unavailable_evidence = unavailable.terminal_evidence[0]
    assert unavailable_evidence.evidence_values == ()
    assert unavailable_evidence.upstream_unavailable_evidence is not None
    assert unavailable_evidence.upstream_unavailable_evidence.request_binding == (
        unavailable_evidence.request_binding
    )
    assert unavailable.upstream_unavailable == 1
    assert unavailable.unavailable_evidence_sha256

    pagination_values = (
        ("pagination_ordinal", 0),
        ("pagination_terminal", True),
        ("pagination_termination_reason", "declared_total"),
    )
    paginated_evidence = replace(
        unavailable_evidence,
        evidence_values=pagination_values,
    )
    assert paginated_evidence.evidence_values == pagination_values
    assert paginated_evidence.request_binding is unavailable_evidence.request_binding
    assert (
        paginated_evidence.upstream_unavailable_evidence
        is unavailable_evidence.upstream_unavailable_evidence
    )
    assert paginated_evidence.evidence_sha256 != unavailable_evidence.evidence_sha256

    with pytest.raises(
        NbaApiRequestSurfaceError,
        match="terminal evidence fields do not match the accounting-state contract",
    ):
        replace(
            unavailable_evidence,
            evidence_values=(("row_count", 0),),
        )

    paginated = _receipt(
        route=RouteRequestSpec(
            route_id="league_log_page_0",
            source_family="stats",
            endpoint_id="LeagueGameLog",
            parameters=(("season", "2025-26"),),
            pagination_series_id="league_log",
            pagination_ordinal=0,
            pagination_terminal=True,
        ),
        terminal_state="upstream_unavailable",
        independent=False,
    )
    paginated_terminal = paginated.terminal_evidence[0]
    assert paginated_terminal.evidence_values == pagination_values
    incomplete_pagination = replace(
        paginated_terminal,
        evidence_values=tuple(
            item
            for item in paginated_terminal.evidence_values
            if item[0] != "pagination_termination_reason"
        ),
    )
    with pytest.raises(
        NbaApiRequestSurfaceError,
        match="terminal pagination page lacks a concrete stop reason",
    ):
        replace(paginated, terminal_evidence=(incomplete_pagination,))

    contract_blocked = _receipt(terminal_state="contract_blocked")
    assert contract_blocked.contract_blocked == 1
    assert contract_blocked.green is False


def test_every_parameter_has_semantic_role_and_concrete_evidence() -> None:
    authority = _authority()

    assert len(authority.endpoints) == 143
    assert authority.parameter_occurrence_count == 1971
    assert all(
        parameter.semantic_role
        and parameter.evidence
        and all(item.evidence_sha256 for item in parameter.evidence)
        for endpoint in authority.endpoints
        for parameter in endpoint.parameters
    )
    common_all_players = authority.endpoint("stats", "CommonAllPlayers")
    season = common_all_players.parameter("season")
    assert season.semantic_role == "scope_axis"
    assert season.dependencies == ("season_scope",)
    box_score = authority.endpoint("live", "BoxScore")
    assert box_score.parameter("game_id").semantic_role == "discovery_key"
    counter = authority.endpoint("stats", "LeagueGameLog").parameter("counter")
    assert counter.semantic_role == "pagination_cursor"
    assert {item.evidence_kind for item in counter.evidence} == {
        "bounded_interval",
        "pagination_until_terminal",
    }
    country = authority.endpoint("stats", "AssistTracker").parameter("country_nullable")
    neutral = next(item for item in country.evidence if item.evidence_kind == "neutral_value")
    assert neutral.neutral_value == ""


def test_request_surface_binds_competition_authority_for_all_league_occurrences() -> None:
    authority = _authority()
    checked_competition = load_pinned_competition_payload()
    expected_values = ("00", "01", "10", "15", "20")
    league_occurrences = [
        parameter
        for endpoint in authority.endpoints
        for parameter in endpoint.parameters
        if parameter.domain_kind == "league_scope"
    ]

    assert len(league_occurrences) == 112
    assert Counter(item.name for item in league_occurrences) == {
        "league_id": 63,
        "league_id_nullable": 47,
        "person1_league_id": 1,
        "person2_league_id": 1,
    }
    for parameter in league_occurrences:
        finite = [
            item for item in parameter.evidence if item.evidence_kind == "provider_finite_values"
        ]
        assert len(finite) == 1
        assert finite[0].finite_values == expected_values
        assert finite[0].authority.endswith(str(checked_competition["payload_sha256"]))
    request_payload = build_pinned_request_surface_payload()
    assert (
        request_payload["reserved_authorities"]["league_finite_values"]
        == (checked_competition["payload_sha256"])
    )
    assert request_payload["summary"]["evidence_kind_counts"]["provider_finite_values"] == 738


def test_request_surface_rejects_foreign_competition_value() -> None:
    authority = _authority()
    endpoint = authority.endpoint("stats", "CommonAllPlayers")

    for league_id in ("00", "01", "10", "15", "20"):
        request = materialize_provider_request(
            endpoint,
            {"league_id": league_id, "season": "2025-26"},
            request_surface_sha256=authority.surface_sha256,
            runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        )
        assert dict(request.materialized_parameters)["league_id"] == league_id
    with pytest.raises(NbaApiRequestSurfaceError, match="provider finite domain"):
        materialize_provider_request(
            endpoint,
            {"league_id": "99", "season": "2025-26"},
            request_surface_sha256=authority.surface_sha256,
            runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        )


def test_parameter_occurrence_requires_typed_domain_evidence() -> None:
    authority = _authority()
    parameters = tuple(
        parameter for endpoint in authority.endpoints for parameter in endpoint.parameters
    )

    assert len(parameters) == 1971
    assert len({parameter.occurrence_id for parameter in parameters}) == 1971
    assert len({parameter.typed_domain_sha256 for parameter in parameters}) == 1971
    assert all(
        parameter.source_signature_sha256 and parameter.typed_domain_sha256 and parameter.evidence
        for parameter in parameters
    )
    with pytest.raises(NbaApiRequestSurfaceError, match="evidence.*nonempty"):
        replace(parameters[0], evidence=())


def test_parameter_constraint_graph_rejects_cycles() -> None:
    nodes = (
        "parameter:stats:CycleFixture:0000:lower",
        "parameter:stats:CycleFixture:0001:upper",
    )
    edges = tuple(
        sorted(
            (
                ParameterConstraintEdge(
                    source_node=nodes[0],
                    target_node=nodes[1],
                    constraint_kind="lower_lte_upper_if_both_present",
                    authority="test_order_constraint_v1",
                ),
                ParameterConstraintEdge(
                    source_node=nodes[1],
                    target_node=nodes[0],
                    constraint_kind="lower_lte_upper_if_both_present",
                    authority="test_order_constraint_v1",
                ),
            ),
            key=request_surface._constraint_sort_key,
        )
    )

    with pytest.raises(NbaApiRequestSurfaceError, match="contains a cycle"):
        _validate_parameter_constraint_graph(nodes, edges)


def test_count_preserving_domain_or_route_replacement_changes_authority() -> None:
    authority = _authority()
    endpoint = authority.endpoints[0]
    replacement = replace(endpoint, endpoint_slug="count_preserving_route_replacement")
    mutated = replace(authority, endpoints=(replacement, *authority.endpoints[1:]))

    assert len(mutated.endpoints) == len(authority.endpoints)
    assert mutated.parameter_occurrence_count == authority.parameter_occurrence_count
    assert mutated.surface_sha256 != authority.surface_sha256

    first = endpoint.parameters[0]
    foreign = next(
        parameter for candidate in authority.endpoints[1:] for parameter in candidate.parameters
    )
    with pytest.raises(NbaApiRequestSurfaceError, match="typed-domain authority differs"):
        replace(first, typed_domain_sha256=foreign.typed_domain_sha256)


def test_foreign_default_or_domain_authority_is_rejected() -> None:
    authority = _authority()
    season = authority.endpoint("stats", "CommonAllPlayers").parameter("season")
    other_season = authority.endpoint("stats", "AssistLeaders").parameter("season")

    assert season.name == other_season.name
    assert season.occurrence_id != other_season.occurrence_id
    assert season.typed_domain_sha256 != other_season.typed_domain_sha256
    with pytest.raises(NbaApiRequestSurfaceError, match="dynamic provider default"):
        replace(season, default="2024-25")
    with pytest.raises(NbaApiRequestSurfaceError, match="authority differs"):
        replace(season, default_authority="provider_literal_or_required_v1")
    with pytest.raises(NbaApiRequestSurfaceError, match="authority differs"):
        replace(season, default_expression=None)
    with pytest.raises(NbaApiRequestSurfaceError, match="typed-domain authority differs"):
        replace(season, typed_domain_sha256=other_season.typed_domain_sha256)


def test_all_dynamic_defaults_are_exact_source_expression_authorities() -> None:
    authority = _authority()
    dynamic = [
        parameter
        for endpoint in authority.endpoints
        for parameter in endpoint.parameters
        if parameter.default_authority == "provider_dynamic_default_expression_v1"
    ]

    assert len(dynamic) == 90
    assert Counter(parameter.default_expression for parameter in dynamic) == {
        "GameDate.default": 2,
        "Season.default": 77,
        "SeasonAll.default": 1,
        "SeasonAll_Time.default": 1,
        "SeasonID.default": 2,
        "SeasonYear.default": 7,
    }
    assert all(
        parameter.has_default and parameter.default is None and not parameter.nullable
        for parameter in dynamic
    )


def test_dynamic_defaults_require_explicit_validated_scope_values_and_bind_request_keys() -> None:
    authority = _authority()
    examples = (
        ("CommonAllPlayers", "season", "1946-47", "1947-48"),
        ("ScoreboardV2", "game_date", "2025-10-22", "2025-10-23"),
    )
    for endpoint_id, parameter_name, first_value, second_value in examples:
        endpoint = authority.endpoint("stats", endpoint_id)
        with pytest.raises(NbaApiRequestSurfaceError, match="explicit scope value is required"):
            _request_key(endpoint, {})
        first = materialize_provider_request(
            endpoint,
            {parameter_name: first_value},
            request_surface_sha256=authority.surface_sha256,
            runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        )
        second = materialize_provider_request(
            endpoint,
            {parameter_name: second_value},
            request_surface_sha256=authority.surface_sha256,
            runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        )
        assert dict(first.materialized_parameters)[parameter_name] == first_value
        assert first.provider_request_sha256 != second.provider_request_sha256

    with pytest.raises(NbaApiRequestSurfaceError, match="consecutive-season domain"):
        _request_key(
            authority.endpoint("stats", "CommonAllPlayers"),
            {"season": "2025-27"},
        )
    with pytest.raises(NbaApiRequestSurfaceError, match="calendar-date domain"):
        _request_key(
            authority.endpoint("stats", "ScoreboardV2"),
            {"game_date": "2025-02-30"},
        )


def test_dynamic_calendar_and_season_shifts_do_not_change_checked_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = build_pinned_request_surface_payload()
    runtime = request_surface.load_pinned_runtime_contract_payload()
    replacements: dict[tuple[str, str], EvidenceValue] = {
        ("ScoreboardV2", "game_date"): "2099-01-02",
        ("CommonAllPlayers", "season"): "2099-00",
        ("PlayerNextNGames", "season_all"): "2099-00",
        ("DraftCombineStats", "season_all_time"): "2099-00",
        ("PlayoffPicture", "season_id"): "22099",
        ("DraftBoard", "season_year"): 2099,
    }
    contracts = runtime["contracts"]
    assert isinstance(contracts, dict)
    for (endpoint_id, parameter_name), replacement in replacements.items():
        contract = contracts[endpoint_id]
        assert isinstance(contract, dict)
        defaults = contract["parameter_defaults"]
        assert isinstance(defaults, list)
        row = next(
            item
            for item in defaults
            if isinstance(item, dict) and item.get("name") == parameter_name
        )
        assert row == {
            "name": parameter_name,
            "value_type": type(replacement).__name__,
            "default_authority": "provider_dynamic_default_expression_v1",
            "default_expression": {
                "game_date": "GameDate.default",
                "season": "Season.default",
                "season_all": "SeasonAll.default",
                "season_all_time": "SeasonAll_Time.default",
                "season_id": "SeasonID.default",
                "season_year": "SeasonYear.default",
            }[parameter_name],
        }
        module = importlib.import_module(contract["module_name"])
        endpoint_class = getattr(module, contract["runtime_class_name"])
        initializer = endpoint_class.__init__
        parameters = tuple(inspect.signature(initializer).parameters.values())
        defaulted = tuple(
            parameter
            for parameter in parameters
            if parameter.name != "self"
            and parameter.kind
            in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
            and parameter.default is not inspect.Parameter.empty
        )
        defaults_tuple = initializer.__defaults__
        assert defaults_tuple is not None and len(defaults_tuple) == len(defaulted)
        shifted_defaults = list(defaults_tuple)
        shifted_defaults[[item.name for item in defaulted].index(parameter_name)] = replacement
        monkeypatch.setattr(initializer, "__defaults__", tuple(shifted_defaults))

    request_surface.build_request_surface_authority.cache_clear()
    try:
        assert build_pinned_request_surface_payload() == baseline
    finally:
        request_surface.build_request_surface_authority.cache_clear()


def test_materialization_enforces_ordered_cross_parameter_constraints() -> None:
    endpoint = _authority().endpoint("stats", "AssistTracker")

    _request_key(
        endpoint,
        {"date_from_nullable": "01/01/2025", "date_to_nullable": "2025-01-31"},
    )
    with pytest.raises(NbaApiRequestSurfaceError, match="ordered cross-parameter"):
        _request_key(
            endpoint,
            {"date_from_nullable": "2025-02-01", "date_to_nullable": "01/31/2025"},
        )


def test_unknown_future_parameter_fails_closed() -> None:
    with pytest.raises(NbaApiRequestSurfaceError, match="unclassified request parameter"):
        _classify_parameter("future_free_text_parameter")


def test_all_nba_and_wnba_static_helpers_bind_exact_embedded_bodies() -> None:
    authority = _authority()
    datasets = {dataset.dataset_id: dataset for dataset in authority.static_datasets}
    helpers = {helper.helper_id: helper for helper in authority.static_helpers}

    assert set(datasets) == {
        "static_players",
        "static_teams",
        "static_wnba_players",
        "static_wnba_teams",
    }
    assert all(helper.scope_status == "in_scope" for helper in helpers.values())
    assert (
        helpers["players.get_wnba_players"].embedded_body_sha256
        == datasets["static_wnba_players"].embedded_body_sha256
    )
    assert (
        helpers["teams.get_wnba_teams"].embedded_body_sha256
        == datasets["static_wnba_teams"].embedded_body_sha256
    )


def test_wnba_embedded_body_tamper_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        static_players,
        "wnba_players",
        [*static_players.wnba_players, list(static_players.wnba_players[0])],
    )
    build_request_surface_authority.cache_clear()
    with pytest.raises(NbaApiRequestSurfaceError, match="differs from runtime contract"):
        build_request_surface_authority()


def test_surface_rebuild_never_sends_provider_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_request(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("request-surface discovery attempted network I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _unexpected_request)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", _unexpected_request)
    build_request_surface_authority.cache_clear()
    authority = build_request_surface_authority()
    assert len(authority.endpoints) == 143
    assert len(authority.static_datasets) == 4


@pytest.mark.parametrize(
    "raw, message",
    [
        (b'{"schema_version":3,"schema_version":3}\n', "duplicate object key"),
        (b'{"nested":{"value":1,"value":2}}\n', "duplicate object key"),
        (b'{"value":NaN}\n', "non-finite JSON constant"),
        (b"{}", "not canonical JSON"),
    ],
)
def test_artifact_loader_rejects_duplicate_nonfinite_and_noncanonical_bytes(
    tmp_path: Path,
    raw: bytes,
    message: str,
) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(NbaApiRequestSurfaceError, match=message):
        load_pinned_request_surface_payload(path)


def test_artifact_loader_rejects_pretty_print_and_extra_fields(tmp_path: Path) -> None:
    payload = build_pinned_request_surface_payload()
    pretty = tmp_path / "pretty.json"
    pretty.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with pytest.raises(NbaApiRequestSurfaceError, match="not canonical JSON"):
        load_pinned_request_surface_payload(pretty)

    extra = dict(payload)
    extra["unexpected"] = True
    body = dict(extra)
    body.pop("payload_sha256")
    extra["payload_sha256"] = _canonical_digest(body)
    extra_path = tmp_path / "extra.json"
    extra_path.write_bytes(_canonical_bytes(extra))
    with pytest.raises(NbaApiRequestSurfaceError, match="fields do not match schema"):
        load_pinned_request_surface_payload(extra_path)


def test_artifact_tamper_fails_even_with_recomputed_outer_digest(tmp_path: Path) -> None:
    payload = build_pinned_request_surface_payload()
    original_summary = payload["summary"]
    assert isinstance(original_summary, dict)
    summary = dict(original_summary)
    summary["parameter_occurrence_count"] += 1
    payload["summary"] = summary
    body = dict(payload)
    body.pop("payload_sha256")
    payload["payload_sha256"] = _canonical_digest(body)
    path = tmp_path / "tampered.json"
    path.write_bytes(_canonical_bytes(payload))
    with pytest.raises(NbaApiRequestSurfaceError, match="exact pinned package surface"):
        load_pinned_request_surface_payload(path)


def test_artifact_writer_is_deterministic_and_check_mode_fails_on_drift(
    tmp_path: Path,
) -> None:
    path = tmp_path / "request-surface.json"
    assert write_pinned_request_surface(path) is False
    assert write_pinned_request_surface(path) is True
    assert write_pinned_request_surface(path, check=True) is True
    assert path.read_bytes() == _canonical_bytes(build_pinned_request_surface_payload())
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(NbaApiRequestSurfaceError, match="generated drift"):
        write_pinned_request_surface(path, check=True)


def test_provider_request_key_is_authority_bound_and_serializes_exact_wire_request() -> None:
    authority = _authority()
    endpoint = authority.endpoint("stats", "CommonAllPlayers")
    request = materialize_provider_request(
        endpoint,
        {"season": "2025-26"},
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    assert request.url_path == "/stats/commonallplayers"
    assert request.query_string == "IsOnlyCurrentSeason=0&LeagueID=00&Season=2025-26"
    assert request.full_url.endswith(f"?{request.query_string}")
    assert request.provider_request_sha256 == _request_key(endpoint, {"season": "2025-26"})

    live = authority.endpoint("live", "BoxScore")
    live_request = materialize_provider_request(
        live,
        {"game_id": "0022500001"},
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    assert live_request.url_path.endswith("/boxscore/boxscore_0022500001.json")
    assert live_request.query_string == ""


def test_provider_request_key_rejects_foreign_authority_endpoint_and_invalid_values() -> None:
    authority = _authority()
    endpoint = authority.endpoint("stats", "CommonAllPlayers")
    with pytest.raises(NbaApiRequestSurfaceError, match="foreign surface authority"):
        canonical_provider_request_key(
            endpoint,
            {},
            request_surface_sha256=_A,
            runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        )
    with pytest.raises(NbaApiRequestSurfaceError, match="foreign runtime authority"):
        canonical_provider_request_key(
            endpoint,
            {},
            request_surface_sha256=authority.surface_sha256,
            runtime_contract_payload_sha256=_B,
        )
    forged = replace(endpoint, endpoint_slug="foreign")
    with pytest.raises(NbaApiRequestSurfaceError, match="differs from pinned authority"):
        _request_key(forged, {})
    with pytest.raises(NbaApiRequestSurfaceError, match="invalid concrete type"):
        _request_key(endpoint, {"is_only_current_season": True})
    with pytest.raises(NbaApiRequestSurfaceError, match="does not permit null"):
        _request_key(endpoint, {"season": None})
    with pytest.raises(NbaApiRequestSurfaceError, match="unknown endpoint parameters"):
        _request_key(endpoint, {"unknown": "value"})
    live = authority.endpoint("live", "BoxScore")
    with pytest.raises(NbaApiRequestSurfaceError, match="exact pattern"):
        _request_key(live, {"game_id": "bad"})
    with pytest.raises(NbaApiRequestSurfaceError, match="required endpoint parameter"):
        _request_key(live, {})


def test_provider_request_key_rejects_semantically_out_of_domain_scope_values() -> None:
    authority = _authority()
    common_players = authority.endpoint("stats", "CommonAllPlayers")
    historical = materialize_provider_request(
        common_players,
        {"season": "1946-47"},
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    assert dict(historical.materialized_parameters)["season"] == "1946-47"

    for parameters, message in (
        ({"season": "2025-27"}, "consecutive-season domain"),
        ({"season": "2025/26"}, "season-label domain"),
        ({"season": "\u0662\u0660\u0662\u0665-\u0662\u0666"}, "season-label domain"),
        ({"league_id": "NBA"}, "league-id domain"),
        ({"league_id": "\u0660\u0660"}, "league-id domain"),
        ({"season": None}, "does not permit null"),
    ):
        with pytest.raises(NbaApiRequestSurfaceError, match=message):
            _request_key(common_players, parameters)

    league_log = authority.endpoint("stats", "LeagueGameLog")
    with pytest.raises(NbaApiRequestSurfaceError, match="calendar-date domain"):
        _request_key(
            league_log,
            {"date_from_nullable": "02/30/2025", "season": "2025-26"},
        )
    with pytest.raises(NbaApiRequestSurfaceError, match="provider finite domain"):
        _request_key(
            league_log,
            {"season": "2025-26", "season_type_all_star": "Postseason"},
        )

    assist = authority.endpoint("stats", "AssistTracker")
    with pytest.raises(NbaApiRequestSurfaceError, match="bounded domain"):
        _request_key(assist, {"month_nullable": 13})
    with pytest.raises(NbaApiRequestSurfaceError, match="numeric wire value"):
        _request_key(assist, {"month_nullable": "\u0661"})
    live = authority.endpoint("live", "BoxScore")
    with pytest.raises(NbaApiRequestSurfaceError, match="exact pattern"):
        _request_key(live, {"game_id": "\u0660" * 10})


def test_canonical_provider_request_rejects_direct_self_consistent_forgery() -> None:
    authority = _authority()
    endpoint = authority.endpoint("stats", "CommonAllPlayers")
    request = materialize_provider_request(
        endpoint,
        {"season": "1946-47"},
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    assert isinstance(request, CanonicalProviderRequest)

    with pytest.raises(NbaApiRequestSurfaceError, match="foreign surface"):
        replace(request, request_surface_sha256=_A)
    with pytest.raises(NbaApiRequestSurfaceError, match="foreign runtime"):
        replace(request, runtime_contract_payload_sha256=_B)
    with pytest.raises(NbaApiRequestSurfaceError, match="differs from pinned materialization"):
        replace(request, full_url=f"{request.full_url}/forged")
    with pytest.raises(NbaApiRequestSurfaceError, match="parameter inventory differs"):
        replace(request, materialized_parameters=tuple(reversed(request.materialized_parameters)))
    with pytest.raises(NbaApiRequestSurfaceError, match="differs from pinned materialization"):
        replace(request, provider_request_sha256=_A)


def test_route_conservation_recomputes_bindings_and_rejects_alias_misuse() -> None:
    routes = (
        RouteRequestSpec(
            "route_a",
            "stats",
            "CommonAllPlayers",
            (("season", "2025-26"),),
        ),
        RouteRequestSpec(
            "route_b",
            "stats",
            "CommonAllPlayers",
            (("season", "2025-26"),),
        ),
        RouteRequestSpec(
            "route_c",
            "stats",
            "CommonAllPlayers",
            (("season", "2024-25"),),
        ),
    )
    manifest = _route_manifest(routes)
    bindings = _bindings(manifest)
    require_route_conservation(manifest, bindings)
    assert {binding.route_ids for binding in bindings} == {
        ("route_a", "route_b"),
        ("route_c",),
    }

    wrong = (
        RequestRouteBinding(bindings[0].provider_request_sha256, ("route_a",)),
        RequestRouteBinding(bindings[1].provider_request_sha256, ("route_b", "route_c")),
    )
    with pytest.raises(NbaApiRequestSurfaceError, match="not independently conserved"):
        require_route_conservation(manifest, wrong)


def test_route_manifest_rejects_pagination_truncation() -> None:
    route = RouteRequestSpec(
        "league_log_page_0",
        "stats",
        "LeagueGameLog",
        (("season", "2025-26"),),
        pagination_series_id="league_log",
        pagination_ordinal=0,
        pagination_terminal=False,
    )
    with pytest.raises(NbaApiRequestSurfaceError, match="lacks one exact terminal"):
        _route_manifest((route,))

    valid = replace(route, pagination_terminal=True)
    manifest = _route_manifest((valid,))
    require_route_conservation(manifest, _bindings(manifest))
    with pytest.raises(NbaApiRequestSurfaceError, match="concrete route inventory"):
        replace(manifest, registry_manifest_sha256=_B)


def test_closure_uses_actual_sets_and_rejects_count_preserving_replacement() -> None:
    receipt = _receipt()
    assert receipt.fixed_point is True
    assert receipt.green is True
    receipt.require_green()

    with pytest.raises(NbaApiRequestSurfaceError, match="exact input-plus-delta union"):
        RequestClosureIteration(
            iteration=0,
            request_surface_sha256=receipt.request_surface_sha256,
            scope_sha256=receipt.scope_sha256,
            input_units=(_A,),
            new_units=(_B,),
            output_units=(_A, _C),
            evidence=(
                RequestExpansionEvidence(
                    evidence_id="replacement",
                    evidence_kind="scope_expansion",
                    request_surface_sha256=receipt.request_surface_sha256,
                    scope_sha256=receipt.scope_sha256,
                    input_units=(_A,),
                    discovered_units=(_B,),
                    source_values=("scope",),
                    complete=True,
                ),
            ),
        )


def test_closure_rejects_mismatched_evidence_and_pagination_truncation() -> None:
    receipt = _receipt()
    with pytest.raises(NbaApiRequestSurfaceError, match="unrelated to its scope"):
        RequestClosureIteration(
            iteration=0,
            request_surface_sha256=receipt.request_surface_sha256,
            scope_sha256=receipt.scope_sha256,
            input_units=(),
            new_units=(_A,),
            output_units=(_A,),
            evidence=(
                RequestExpansionEvidence(
                    evidence_id="unrelated",
                    evidence_kind="seed",
                    request_surface_sha256=receipt.request_surface_sha256,
                    scope_sha256=_B,
                    input_units=(),
                    discovered_units=(_A,),
                    source_values=("seed",),
                    complete=True,
                ),
            ),
        )
    with pytest.raises(NbaApiRequestSurfaceError, match="pagination evidence is truncated"):
        RequestExpansionEvidence(
            evidence_id="truncated_pages",
            evidence_kind="pagination_expansion",
            request_surface_sha256=receipt.request_surface_sha256,
            scope_sha256=receipt.scope_sha256,
            input_units=(),
            discovered_units=(_A,),
            source_values=(0,),
            complete=True,
            pagination_ordinals=(0, 1),
            pagination_terminal_ordinal=0,
        )


def test_closure_requires_related_independent_proof_and_terminal_inventory() -> None:
    primary = _receipt(independent=False)
    assert primary.green is False
    with pytest.raises(NbaApiRequestSurfaceError, match="required independent proof"):
        primary.require_green()

    bad = IndependentClosureProof(
        verifier_id="independent_test_rebuilder",
        request_surface_sha256=primary.request_surface_sha256,
        scope_sha256=primary.scope_sha256,
        route_manifest_sha256=primary.route_manifest.manifest_sha256,
        unit_inventory_sha256=_A,
        terminal_inventory_sha256=primary.terminal_inventory_sha256,
    )
    with pytest.raises(NbaApiRequestSurfaceError, match="unrelated to the recomputed"):
        replace(primary, independent_proof=bad)
    with pytest.raises(NbaApiRequestSurfaceError, match="each request unit exactly once"):
        foreign_binding = build_terminal_request_binding(
            request_surface_sha256=primary.request_surface_sha256,
            runtime_contract_payload_sha256=(
                primary.route_manifest.runtime_contract_payload_sha256
            ),
            provider_authority_sha256=_A,
            route_manifest_sha256=primary.route_manifest.manifest_sha256,
            scope_sha256=primary.scope_sha256,
            provider_request_sha256=_A,
            source_request_sha256=_B,
            competition_authority_sha256=_C,
            competition_scope_sha256=_A,
            competition_requirement_sha256=_B,
            role_binding_sha256=_C,
            source_evidence_sha256=_A,
            source_family=primary.route_manifest.routes[0].source_family,
            endpoint_id=primary.route_manifest.routes[0].endpoint_id,
            route_ids=primary.bindings[0].route_ids,
        )
        replace(
            primary,
            terminal_evidence=(
                replace(primary.terminal_evidence[0], request_binding=foreign_binding),
            ),
        )


def test_closure_receipt_digest_binds_authority_and_actual_inventories() -> None:
    primary = _receipt(independent=False)
    alias = _receipt(
        route=RouteRequestSpec(
            route_id="route_alias",
            source_family="stats",
            endpoint_id="CommonAllPlayers",
            parameters=(("season", "2025-26"),),
        ),
        independent=False,
    )
    verified = _receipt()

    assert primary.unit_inventory == alias.unit_inventory
    assert primary.unit_inventory_sha256 == _canonical_digest(list(primary.unit_inventory))
    assert primary.terminal_inventory_sha256 != alias.terminal_inventory_sha256
    assert primary.scope_sha256 != alias.scope_sha256
    assert primary.iteration_inventory_sha256 != alias.iteration_inventory_sha256
    assert primary.primary_receipt_sha256 != alias.primary_receipt_sha256
    assert primary.primary_receipt_sha256 == verified.primary_receipt_sha256
    assert primary.receipt_sha256 != verified.receipt_sha256


def test_scope_authorization_uses_canonical_scalar_identity() -> None:
    authority = _authority()
    scope = RequestScopeManifest(
        request_surface_sha256=authority.surface_sha256,
        scope_id="typed_scope",
        seed_route_ids=("route_a",),
        dimensions=(
            RequestScopeDimension(
                dependency_id="explicit_scope_manifest",
                source_kind="typed_test_inventory",
                source_authority_sha256=_A,
                values=(True,),
                endpoint_id="CommonAllPlayers",
                parameter_name="is_only_current_season",
            ),
        ),
    )
    assert scope.authorizes_parameter(
        "CommonAllPlayers",
        "is_only_current_season",
        ("explicit_scope_manifest",),
        True,
    )
    assert not scope.authorizes_parameter(
        "CommonAllPlayers",
        "is_only_current_season",
        ("explicit_scope_manifest",),
        1,
    )


def test_nonterminal_state_is_conserved_but_not_green() -> None:
    receipt = _receipt(terminal_state="transient_failed")
    assert receipt.fixed_point is True
    assert receipt.transient_failed == 1
    assert receipt.green is False
    with pytest.raises(NbaApiRequestSurfaceError, match="not terminally green"):
        receipt.require_green()


def test_non_neutral_filter_requires_parameter_specific_scope_evidence() -> None:
    route = RouteRequestSpec(
        route_id="assist_us",
        source_family="stats",
        endpoint_id="AssistTracker",
        parameters=(("country_nullable", "US"),),
    )
    with pytest.raises(NbaApiRequestSurfaceError, match="non-neutral filter"):
        _receipt(route=route)

    receipt = _receipt(
        route=route,
        filter_authorizations=(("country_nullable", "US"),),
    )
    assert receipt.green is True


def test_adversarial_materialization_and_closure_paths_never_send_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected_request(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("request proof attempted network I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", _unexpected_request)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", _unexpected_request)
    authority = _authority()
    endpoint = authority.endpoint("stats", "CommonAllPlayers")
    assert _request_key(endpoint, {"season": "1946-47"})
    with pytest.raises(NbaApiRequestSurfaceError, match="consecutive-season domain"):
        _request_key(endpoint, {"season": "1946-49"})
    _receipt().require_green()
