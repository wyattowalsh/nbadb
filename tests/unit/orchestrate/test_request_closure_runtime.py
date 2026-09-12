from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace

import pytest
from nba_api.live.nba.library.http import NBALiveHTTP
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.core.nba_api_request_surface import (
    NbaApiRequestSurfaceError,
    RequestScopeDimension,
    RequestScopeManifest,
    materialize_provider_request,
    pinned_request_surface_authority,
)
from nbadb.core.nba_api_terminal_state import (
    TerminalRequestBinding,
    TypedUpstreamUnavailableEvidence,
    UpstreamUnavailableSupportAuthority,
    build_terminal_request_binding,
    build_typed_upstream_unavailable_evidence,
)
from nbadb.orchestrate.request_closure_runtime import (
    REQUEST_CLOSURE_RUNTIME_SCHEMA_VERSION,
    PersistedStagingReceipt,
    RequestClosureAdapterInput,
    RequestClosureRuntimeError,
    RequestClosureRuntimeReceipt,
    RequestObservation,
    ResultSetReceipt,
    RouteRequestSpecInput,
    build_authoritative_route_manifest,
    build_request_closure_runtime_receipt,
)

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64
_D = "d" * 64
_E = "e" * 64
_F = "f" * 64
_G = "0" * 64
_SEASON = "2025-26"
_SUPPORT_BINDING_DOMAIN = "nbadb.nba-api.upstream-unavailable-support.v1"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _domain_sha256(domain: str, value: object) -> str:
    return _sha256({"domain": domain, "payload": value})


def _request_binding(
    *,
    request_surface_sha256: str,
    runtime_contract_payload_sha256: str,
    route_manifest_sha256: str,
    scope_sha256: str,
    provider_request_sha256: str,
    source_family: str,
    endpoint_id: str,
    route_ids: tuple[str, ...],
    **overrides: object,
) -> TerminalRequestBinding:
    values: dict[str, object] = {
        "request_surface_sha256": request_surface_sha256,
        "runtime_contract_payload_sha256": runtime_contract_payload_sha256,
        "provider_authority_sha256": _A,
        "route_manifest_sha256": route_manifest_sha256,
        "scope_sha256": scope_sha256,
        "provider_request_sha256": provider_request_sha256,
        "source_request_sha256": _B,
        "competition_authority_sha256": _C,
        "competition_scope_sha256": _D,
        "competition_requirement_sha256": _E,
        "role_binding_sha256": _F,
        "source_evidence_sha256": _G,
        "source_family": source_family,
        "endpoint_id": endpoint_id,
        "route_ids": route_ids,
    }
    values.update(overrides)
    return build_terminal_request_binding(**values)  # type: ignore[arg-type]


def _upstream_unavailable_evidence(
    request_binding: TerminalRequestBinding,
) -> TypedUpstreamUnavailableEvidence:
    support_body = {
        "authority_kind": "endpoint_support_cell",
        "authority_version": 1,
        "support_authority_sha256": _A,
        "support_cell_id": "stats:CommonAllPlayers:unavailable",
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
        "reason_code": "provider_contract_absent_for_scope",
        "independent_verifier_id": "support-verifier-v1",
        "independent_verifier_sha256": _C,
    }
    support = UpstreamUnavailableSupportAuthority(
        **support_body,
        support_binding_sha256=_domain_sha256(
            _SUPPORT_BINDING_DOMAIN,
            support_body,
        ),
    )
    return build_typed_upstream_unavailable_evidence(request_binding, support)


def _scope(
    *,
    route_ids: tuple[str, ...],
    seed_route_ids: tuple[str, ...] | None = None,
) -> RequestScopeManifest:
    authority = pinned_request_surface_authority()
    endpoint = authority.endpoint("stats", "CommonAllPlayers")
    request = materialize_provider_request(
        endpoint,
        {"season": _SEASON},
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    materialized = dict(request.materialized_parameters)
    dimensions = []
    for dependency in sorted(
        {dependency for item in endpoint.parameters for dependency in item.dependencies}
    ):
        values = {
            materialized[item.name]
            for item in endpoint.parameters
            if dependency in item.dependencies
        }
        dimensions.append(
            RequestScopeDimension(
                dependency_id=dependency,
                source_kind="request_closure_runtime_test",
                source_authority_sha256=_B,
                values=tuple(sorted(values, key=lambda value: _canonical(value))),
            )
        )
    return RequestScopeManifest(
        request_surface_sha256=authority.surface_sha256,
        scope_id="request_closure_runtime_test",
        seed_route_ids=seed_route_ids or route_ids,
        dimensions=tuple(sorted(dimensions, key=lambda item: item.dimension_sha256)),
    )


def _success_receipt(
    *,
    row_count: int = 1,
    aliases: bool = False,
) -> RequestClosureRuntimeReceipt:
    authority = pinned_request_surface_authority()
    route_ids = ("route_a", "route_b") if aliases else ("route_a",)
    route_inputs = tuple(
        RouteRequestSpecInput(
            route_id=route_id,
            source_family="stats",
            endpoint_id="CommonAllPlayers",
            parameters=(("season", _SEASON),),
        )
        for route_id in route_ids
    )
    manifest = build_authoritative_route_manifest(route_inputs)
    scope = _scope(route_ids=route_ids, seed_route_ids=(route_ids[0],))
    endpoint = authority.endpoint("stats", "CommonAllPlayers")
    request = materialize_provider_request(
        endpoint,
        {"season": _SEASON},
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
    )
    result_set = ResultSetReceipt(
        ordinal=0,
        result_set_name="CommonAllPlayers",
        occurrence_state="present_nonempty" if row_count else "present_empty",
        row_count=row_count,
        ordered_columns_sha256=_C,
        result_set_payload_sha256=_D,
    )
    staging = PersistedStagingReceipt(
        result_set_ordinal=0,
        result_set_name="CommonAllPlayers",
        staging_key="stg_common_all_players",
        row_count=row_count,
        result_set_payload_sha256=_D,
        staging_receipt_root_sha256=_E,
    )
    request_binding = _request_binding(
        request_surface_sha256=authority.surface_sha256,
        runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        route_manifest_sha256=manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        provider_request_sha256=request.provider_request_sha256,
        source_family="stats",
        endpoint_id="CommonAllPlayers",
        route_ids=route_ids,
    )
    observation = RequestObservation(
        request_surface_sha256=authority.surface_sha256,
        route_manifest_sha256=manifest.manifest_sha256,
        scope_sha256=scope.scope_sha256,
        provider_request_sha256=request.provider_request_sha256,
        source_family="stats",
        endpoint_id="CommonAllPlayers",
        route_ids=route_ids,
        request_binding=request_binding,
        state="success_nonempty" if row_count else "success_empty",
        attempt_count=1,
        http_status=200,
        response_body_sha256=_F,
        response_body_bytes=128,
        parser_input_sha256=_A,
        result_sets=(result_set,),
        staging_receipts=(staging,),
    )
    return build_request_closure_runtime_receipt(
        RequestClosureAdapterInput(manifest, scope, (observation,))
    )


def _classified_receipt(
    state: str,
    *,
    attempt_count: int,
    outcome: dict[str, object] | None = None,
) -> RequestClosureRuntimeReceipt:
    success = _success_receipt()
    observation = success.observations[0]
    values = dict(outcome or {})
    if state == "upstream_unavailable":
        values["upstream_unavailable_evidence"] = _upstream_unavailable_evidence(
            observation.request_binding
        )
    classified = RequestObservation(
        request_surface_sha256=observation.request_surface_sha256,
        route_manifest_sha256=observation.route_manifest_sha256,
        scope_sha256=observation.scope_sha256,
        provider_request_sha256=observation.provider_request_sha256,
        source_family=observation.source_family,
        endpoint_id=observation.endpoint_id,
        route_ids=observation.route_ids,
        request_binding=observation.request_binding,
        state=state,
        attempt_count=attempt_count,
        **values,  # type: ignore[arg-type]
    )
    return build_request_closure_runtime_receipt(
        RequestClosureAdapterInput(
            success.route_manifest,
            success.scope,
            (classified,),
        )
    )


@pytest.fixture(scope="module")
def receipt() -> RequestClosureRuntimeReceipt:
    return _success_receipt()


def test_builds_independently_verified_path_free_receipt(
    receipt: RequestClosureRuntimeReceipt,
) -> None:
    authority = pinned_request_surface_authority()
    payload = receipt.to_dict()
    closure = payload["closure"]
    assert isinstance(closure, dict)
    assert receipt.green is True
    assert receipt.closure.independent_proof is not None
    assert receipt.closure.independent_proof.verifier_id == "nbadb_independent_package_ast_v1"
    assert receipt.persisted_staging_receipt_roots == (_E,)
    assert payload["schema_version"] == REQUEST_CLOSURE_RUNTIME_SCHEMA_VERSION == 2
    assert payload["terminal_policy_sha256"] == authority.terminal_policy_sha256
    assert payload["request_binding_inventory_sha256"] == (
        receipt.closure.request_binding_inventory_sha256
    )
    assert closure["terminal_policy_sha256"] == authority.terminal_policy_sha256
    assert closure["request_binding_inventory"] == [
        receipt.observations[0].request_binding.to_dict()
    ]
    assert closure["request_binding_inventory_sha256"] == (
        receipt.closure.request_binding_inventory_sha256
    )
    assert closure["terminal_evidence"] == [receipt.closure.terminal_evidence[0].to_dict()]
    assert payload["persisted_staging_receipt_roots_sha256"] == (
        receipt.persisted_staging_receipt_roots_sha256
    )
    encoded = receipt.canonical_bytes.decode("utf-8")
    assert "path" not in payload
    assert "/tmp" not in encoded


def test_runtime_builder_and_codec_never_issue_provider_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def network_forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("request closure runtime attempted network I/O")

    monkeypatch.setattr(NBAStatsHTTP, "send_api_request", network_forbidden)
    monkeypatch.setattr(NBALiveHTTP, "send_api_request", network_forbidden)
    built = _success_receipt()
    assert RequestClosureRuntimeReceipt.from_canonical_bytes(built.canonical_bytes) == built


def test_codec_rejects_duplicate_keys_and_noncanonical_bytes(
    receipt: RequestClosureRuntimeReceipt,
) -> None:
    duplicate = b'{"kind":"nbadb_request_closure_runtime_receipt",' + receipt.canonical_bytes[1:]
    with pytest.raises(RequestClosureRuntimeError, match="duplicate key"):
        RequestClosureRuntimeReceipt.from_canonical_bytes(duplicate)

    pretty = json.dumps(receipt.to_dict(), indent=2, sort_keys=True).encode("utf-8")
    with pytest.raises(RequestClosureRuntimeError, match="not canonical"):
        RequestClosureRuntimeReceipt.from_canonical_bytes(pretty)

    with pytest.raises(RequestClosureRuntimeError, match="must be bytes"):
        RequestClosureRuntimeReceipt.from_canonical_bytes("{}")  # type: ignore[arg-type]

    legacy = copy.deepcopy(receipt.to_dict())
    legacy["schema_version"] = 1
    with pytest.raises(RequestClosureRuntimeError, match="schema is unsupported"):
        RequestClosureRuntimeReceipt.from_canonical_bytes(_canonical(legacy))


@pytest.mark.parametrize("target", ["body", "result_set", "staging_root", "closure"])
def test_codec_rejects_nested_receipt_tampering(
    receipt: RequestClosureRuntimeReceipt,
    target: str,
) -> None:
    payload = copy.deepcopy(receipt.to_dict())
    observations = payload["observations"]
    assert isinstance(observations, list)
    observation = observations[0]
    assert isinstance(observation, dict)
    if target == "body":
        observation["response_body_sha256"] = _A
    elif target == "result_set":
        result_sets = observation["result_sets"]
        staging = observation["staging_receipts"]
        assert isinstance(result_sets, list) and isinstance(staging, list)
        assert isinstance(result_sets[0], dict) and isinstance(staging[0], dict)
        result_sets[0]["result_set_payload_sha256"] = _B
        staging[0]["result_set_payload_sha256"] = _B
    elif target == "staging_root":
        staging = observation["staging_receipts"]
        assert isinstance(staging, list) and isinstance(staging[0], dict)
        staging[0]["staging_receipt_root_sha256"] = _A
    else:
        closure = payload["closure"]
        assert isinstance(closure, dict)
        proof = closure["independent_proof"]
        assert isinstance(proof, dict)
        proof["terminal_inventory_sha256"] = _A
    with pytest.raises(RequestClosureRuntimeError):
        RequestClosureRuntimeReceipt.from_canonical_bytes(_canonical(payload))

    if target == "closure":
        nested_binding = copy.deepcopy(receipt.to_dict())
        nested_closure = nested_binding["closure"]
        assert isinstance(nested_closure, dict)
        inventory = nested_closure["request_binding_inventory"]
        assert isinstance(inventory, list) and isinstance(inventory[0], dict)
        inventory[0]["source_evidence_sha256"] = _A
        with pytest.raises(RequestClosureRuntimeError):
            RequestClosureRuntimeReceipt.from_canonical_bytes(_canonical(nested_binding))

        unavailable = copy.deepcopy(
            _classified_receipt("upstream_unavailable", attempt_count=0).to_dict()
        )
        unavailable_observations = unavailable["observations"]
        assert isinstance(unavailable_observations, list)
        unavailable_observation = unavailable_observations[0]
        assert isinstance(unavailable_observation, dict)
        typed = unavailable_observation["upstream_unavailable_evidence"]
        assert isinstance(typed, dict)
        support = typed["support_authority"]
        assert isinstance(support, dict)
        support["support_cell_id"] = "stats:CommonAllPlayers:rebound"
        with pytest.raises(RequestClosureRuntimeError):
            RequestClosureRuntimeReceipt.from_canonical_bytes(_canonical(unavailable))


def test_foreign_authority_is_rejected() -> None:
    authority = pinned_request_surface_authority()
    with pytest.raises(RequestClosureRuntimeError, match="foreign authority"):
        build_authoritative_route_manifest(
            (
                RouteRequestSpecInput(
                    "route_a",
                    "stats",
                    "CommonAllPlayers",
                    (),
                ),
            ),
            request_surface_sha256=_A,
            runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        )

    receipt = _success_receipt()
    observation = receipt.observations[0]
    for field, value in (
        ("request_surface_sha256", _A),
        ("route_manifest_sha256", _A),
        ("scope_sha256", _A),
        ("provider_request_sha256", _A),
        ("source_family", "live"),
        ("endpoint_id", "ForeignEndpoint"),
        ("route_ids", ("foreign_route",)),
    ):
        with pytest.raises(RequestClosureRuntimeError, match="foreign"):
            replace(observation, **{field: value})

    foreign_runtime_binding = _request_binding(
        request_surface_sha256=observation.request_surface_sha256,
        runtime_contract_payload_sha256=_A,
        route_manifest_sha256=observation.route_manifest_sha256,
        scope_sha256=observation.scope_sha256,
        provider_request_sha256=observation.provider_request_sha256,
        source_family=observation.source_family,
        endpoint_id=observation.endpoint_id,
        route_ids=observation.route_ids,
    )
    foreign = replace(observation, request_binding=foreign_runtime_binding)
    with pytest.raises(RequestClosureRuntimeError, match="foreign"):
        build_request_closure_runtime_receipt(
            RequestClosureAdapterInput(receipt.route_manifest, receipt.scope, (foreign,))
        )


def test_duplicate_and_missing_terminal_units_are_rejected(
    receipt: RequestClosureRuntimeReceipt,
) -> None:
    observation = receipt.observations[0]
    with pytest.raises(RequestClosureRuntimeError, match="sorted, unique"):
        RequestClosureAdapterInput(
            receipt.route_manifest,
            receipt.scope,
            (observation, observation),
        )
    with pytest.raises(RequestClosureRuntimeError, match="sorted, unique"):
        RequestClosureAdapterInput(receipt.route_manifest, receipt.scope, ())


def test_present_empty_is_distinct_from_missing_and_nonempty() -> None:
    empty = _success_receipt(row_count=0)
    nonempty = _success_receipt(row_count=3)
    assert empty.green is True
    assert empty.closure.success_empty == 1
    assert empty.closure.success_nonempty == 0
    assert empty.observations[0].result_sets[0].row_count == 0
    assert empty.observations[0].result_sets[0].occurrence_state == "present_empty"
    assert empty.observations[0].staging_receipts[0].row_count == 0
    assert nonempty.closure.success_nonempty == 1
    assert nonempty.closure.success_empty == 0
    assert nonempty.observations[0].result_sets[0].occurrence_state == ("present_nonempty")

    with pytest.raises(RequestClosureRuntimeError, match="body/result-set/staging"):
        replace(
            empty.observations[0],
            result_sets=(),
            staging_receipts=(),
        )

    absent = ResultSetReceipt(
        ordinal=0,
        result_set_name="CommonAllPlayers",
        occurrence_state="absent_optional",
        row_count=None,
        ordered_columns_sha256=None,
        result_set_payload_sha256=None,
    )
    with pytest.raises(RequestClosureRuntimeError, match="body/result-set/staging"):
        replace(
            empty.observations[0],
            result_sets=(absent,),
            staging_receipts=(),
        )


def test_alias_routes_share_one_exact_provider_unit() -> None:
    receipt = _success_receipt(aliases=True)
    assert len(receipt.route_manifest.routes) == 2
    assert len(receipt.closure.bindings) == 1
    assert receipt.closure.bindings[0].route_ids == ("route_a", "route_b")
    assert len(receipt.observations) == 1


def test_result_set_and_staging_receipts_must_conserve_rows_and_payloads() -> None:
    receipt = _success_receipt()
    observation = receipt.observations[0]
    staging = observation.staging_receipts[0]
    with pytest.raises(RequestClosureRuntimeError, match="does not conserve"):
        replace(
            observation,
            staging_receipts=(replace(staging, row_count=staging.row_count + 1),),
        )
    with pytest.raises(RequestClosureRuntimeError, match="each present result"):
        replace(observation, staging_receipts=())

    invented_result = replace(
        observation.result_sets[0],
        result_set_name="InventedResultSet",
    )
    invented_staging = replace(
        staging,
        result_set_name="InventedResultSet",
    )
    invented_observation = replace(
        observation,
        result_sets=(invented_result,),
        staging_receipts=(invented_staging,),
    )
    with pytest.raises(RequestClosureRuntimeError, match="omits or invents"):
        build_request_closure_runtime_receipt(
            RequestClosureAdapterInput(
                receipt.route_manifest,
                receipt.scope,
                (invented_observation,),
            )
        )


def test_static_datasets_cannot_be_fabricated_as_http_request_units() -> None:
    with pytest.raises(NbaApiRequestSurfaceError, match="source_family"):
        RouteRequestSpecInput(
            route_id="static_players",
            source_family="static",
            endpoint_id="players",
            parameters=(),
        )


@pytest.mark.parametrize(
    ("state", "attempt_count", "kwargs", "expected_kind"),
    [
        (
            "upstream_unavailable",
            0,
            {},
            "typed_upstream_unavailable_evidence",
        ),
        (
            "contract_blocked",
            0,
            {"reason_code": "scope_not_modeled", "contract_evidence_sha256": _B},
            "implementation_or_modeled_contract_gap",
        ),
        (
            "transient_failed",
            2,
            {"failure_class": "transport_timeout"},
            "transport_timeout_retry_vpn_or_infrastructure_failure",
        ),
        (
            "response_contract_failed",
            1,
            {
                "failure_class": "invalid_response_shape",
                "http_status": 200,
                "response_body_sha256": _C,
                "response_body_bytes": 64,
                "parser_input_sha256": _D,
            },
            "parser_or_response_contract_failure",
        ),
        (
            "unattempted",
            0,
            {"reason_code": "not_scheduled"},
            "budget_cap_policy_or_scheduling_exhaustion",
        ),
        (
            "unclassified",
            1,
            {"classification_input_sha256": _E},
            "classification_unknown",
        ),
    ],
)
def test_all_non_success_outcomes_are_bound_and_independently_verified(
    state: str,
    attempt_count: int,
    kwargs: dict[str, object],
    expected_kind: str,
) -> None:
    receipt = _classified_receipt(
        state,
        attempt_count=attempt_count,
        outcome=kwargs,
    )
    assert receipt.closure.independent_proof is not None
    assert receipt.closure.terminal_evidence[0].evidence_kind == expected_kind
    assert receipt.green is (state == "upstream_unavailable")


def test_runtime_green_accepts_only_success_nonempty_success_empty_and_upstream_unavailable() -> (
    None
):
    success_nonempty = _success_receipt(row_count=2)
    success_empty = _success_receipt(row_count=0)
    upstream_unavailable = _classified_receipt(
        "upstream_unavailable",
        attempt_count=0,
    )
    release_receipts = {
        "success_nonempty": success_nonempty,
        "success_empty": success_empty,
        "upstream_unavailable": upstream_unavailable,
    }
    assert tuple(release_receipts) == (
        "success_nonempty",
        "success_empty",
        "upstream_unavailable",
    )
    assert all(item.green for item in release_receipts.values())

    for state, expected_occurrence, expected_rows in (
        ("success_nonempty", "present_nonempty", 2),
        ("success_empty", "present_empty", 0),
    ):
        current = release_receipts[state]
        observation = current.observations[0]
        evidence = current.closure.terminal_evidence[0]
        assert evidence.request_binding == observation.request_binding
        assert evidence.state == state
        assert evidence.evidence_kind == "receipt_bound_provider_response"
        assert dict(evidence.evidence_values) == {
            "decoded_results_receipt_sha256": observation.result_set_inventory_sha256,
            "http_status": 200,
            "persistence_receipt_sha256": observation.staging_receipt_inventory_sha256,
            "response_body_sha256": _F,
            "result_occurrence": expected_occurrence,
            "row_count": expected_rows,
        }
        assert evidence.upstream_unavailable_evidence is None

    unavailable_observation = upstream_unavailable.observations[0]
    unavailable_evidence = upstream_unavailable.closure.terminal_evidence[0]
    assert unavailable_evidence.request_binding == unavailable_observation.request_binding
    assert unavailable_evidence.state == "upstream_unavailable"
    assert unavailable_evidence.evidence_kind == ("typed_upstream_unavailable_evidence")
    assert unavailable_evidence.evidence_values == ()
    assert unavailable_evidence.upstream_unavailable_evidence == (
        unavailable_observation.upstream_unavailable_evidence
    )
    assert unavailable_evidence.upstream_unavailable_evidence is not None
    assert unavailable_evidence.upstream_unavailable_evidence.to_dict() == (
        unavailable_observation.upstream_unavailable_evidence.to_dict()
    )
    assert (
        RequestClosureRuntimeReceipt.from_canonical_bytes(upstream_unavailable.canonical_bytes)
        == upstream_unavailable
    )

    incomplete_receipts = {
        "contract_blocked": _classified_receipt(
            "contract_blocked",
            attempt_count=0,
            outcome={
                "reason_code": "scope_not_modeled",
                "contract_evidence_sha256": _B,
            },
        ),
        "transient_failed": _classified_receipt(
            "transient_failed",
            attempt_count=2,
            outcome={"failure_class": "transport_timeout"},
        ),
        "response_contract_failed": _classified_receipt(
            "response_contract_failed",
            attempt_count=1,
            outcome={
                "failure_class": "invalid_response_shape",
                "http_status": 200,
                "response_body_sha256": _C,
                "response_body_bytes": 64,
                "parser_input_sha256": _D,
            },
        ),
        "unattempted": _classified_receipt(
            "unattempted",
            attempt_count=0,
            outcome={"reason_code": "not_scheduled"},
        ),
        "unclassified": _classified_receipt(
            "unclassified",
            attempt_count=1,
            outcome={"classification_input_sha256": _E},
        ),
    }
    assert tuple(incomplete_receipts) == (
        "contract_blocked",
        "transient_failed",
        "response_contract_failed",
        "unattempted",
        "unclassified",
    )
    assert all(not item.green for item in incomplete_receipts.values())
    assert {
        state: item.closure.terminal_evidence[0].evidence_kind
        for state, item in incomplete_receipts.items()
    } == {
        "contract_blocked": "implementation_or_modeled_contract_gap",
        "transient_failed": ("transport_timeout_retry_vpn_or_infrastructure_failure"),
        "response_contract_failed": "parser_or_response_contract_failure",
        "unattempted": "budget_cap_policy_or_scheduling_exhaustion",
        "unclassified": "classification_unknown",
    }
