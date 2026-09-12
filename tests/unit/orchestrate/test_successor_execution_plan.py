from __future__ import annotations

import json
from dataclasses import replace

import pytest

from nbadb.orchestrate.successor_execution_plan import (
    SealedUpdateExecutionDispatch,
    SuccessorExecutionPlan,
    SuccessorExecutionPlanError,
    build_successor_execution_plan,
)
from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDispatchPhase,
    SealedProviderDispatch,
)
from nbadb.orchestrate.successor_update_contract import (
    CallMutability,
    PlannedRouteReplacementBinding,
    RequestedRouteScope,
    planned_route_replacement_bindings_sha256,
)
from tests.unit.orchestrate.test_successor_planning_generation_contract import (
    _fixture,
)


def test_build_projects_only_exact_update_dispatches_in_source_order() -> None:
    manifest = _fixture()

    plan = build_successor_execution_plan(manifest)

    expected = tuple(
        dispatch
        for dispatch in manifest.sealed_dispatches
        if dispatch.phase is PlanningDispatchPhase.UPDATE
    )
    assert tuple(item.sealed_dispatch for item in plan.dispatches) == expected
    assert tuple(item.order for item in plan.dispatches) == tuple(range(len(expected)))
    assert plan.baseline_identity_sha256 == manifest.request.baseline_identity_sha256
    assert plan.planning_generation_id == manifest.artifact_identity.planning_generation_id
    assert plan.planning_manifest_sha256 == manifest.artifact_identity.planning_manifest_sha256
    assert plan.sealed_dispatch_inventory_sha256 == (
        manifest.artifact_identity.sealed_dispatch_inventory_sha256
    )
    assert plan.to_dict()["schema_version"] == 2


def test_dispatch_exposes_exact_routes_contracts_and_detached_parameters() -> None:
    plan = build_successor_execution_plan(_fixture())
    dispatch = plan.dispatches[0]

    assert dispatch.endpoint_name == dispatch.sealed_dispatch.endpoint_name
    assert dispatch.staging_route_ids == tuple(
        scope.route_id for scope in dispatch.requested_scopes
    )
    assert dispatch.route_contract_sha256s == tuple(
        scope.route_contract_sha256 for scope in dispatch.requested_scopes
    )
    assert dispatch.mutabilities == tuple(scope.mutability for scope in dispatch.requested_scopes)
    assert dispatch.dependency_identity_sha256s == (
        dispatch.sealed_dispatch.dependency_identity_sha256s
    )
    assert not hasattr(dispatch, "dependency_identity_sha256")
    parameters = dispatch.parameters
    parameters["new_control_key"] = "not-authority"
    assert "new_control_key" not in dispatch.parameters


def test_mutable_planning_roots_remain_fresh_update_dispatches() -> None:
    manifest = _fixture()
    plan = build_successor_execution_plan(manifest)
    planning_scope_ids = {
        scope_id
        for dispatch in manifest.sealed_dispatches
        if dispatch.phase is not PlanningDispatchPhase.UPDATE
        for scope_id in dispatch.requested_scope_identity_sha256s
    }
    update_scope_ids = {
        scope_id
        for dispatch in plan.dispatches
        for scope_id in dispatch.requested_scope_identity_sha256s
    }

    assert planning_scope_ids <= update_scope_ids
    assert all(
        dispatch.sealed_dispatch.phase is PlanningDispatchPhase.UPDATE
        for dispatch in plan.dispatches
    )


def test_plan_round_trip_is_canonical_and_exact() -> None:
    plan = build_successor_execution_plan(_fixture())

    restored = SuccessorExecutionPlan.from_canonical_bytes(plan.canonical_bytes)

    assert restored == plan
    assert restored.canonical_bytes == plan.canonical_bytes
    assert restored.identity_sha256 == plan.identity_sha256
    restored.validate_against_manifest(_fixture())


def test_standalone_plan_must_reconcile_to_its_durable_manifest() -> None:
    manifest = _fixture()
    plan = build_successor_execution_plan(manifest)
    forged = replace(plan, baseline_identity_sha256="0" * 64)

    with pytest.raises(SuccessorExecutionPlanError, match="differs from the durable"):
        forged.validate_against_manifest(manifest)


def test_noncanonical_plan_encoding_fails_closed() -> None:
    plan = build_successor_execution_plan(_fixture())

    with pytest.raises(SuccessorExecutionPlanError, match="not canonical"):
        SuccessorExecutionPlan.from_canonical_bytes(plan.canonical_bytes + b"\n")

    schema_alias = plan.to_dict()
    schema_alias["schema_version"] = True
    with pytest.raises(SuccessorExecutionPlanError, match="schema is invalid"):
        SuccessorExecutionPlan.from_canonical_bytes(
            json.dumps(schema_alias, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )

    old_schema = plan.to_dict()
    old_schema["schema_version"] = 1
    with pytest.raises(SuccessorExecutionPlanError, match="schema is invalid"):
        SuccessorExecutionPlan.from_dict(old_schema)

    nested_old_schema = plan.to_dict()
    nested_old_schema["dispatches"][0]["schema_version"] = 1
    with pytest.raises(SuccessorExecutionPlanError, match="dispatch schema is invalid"):
        SuccessorExecutionPlan.from_dict(nested_old_schema)

    noninteger_order = plan.to_dict()
    noninteger_order["dispatches"][0]["order"] = True
    with pytest.raises(SuccessorExecutionPlanError, match="order must be an integer"):
        SuccessorExecutionPlan.from_dict(noninteger_order)


def test_strict_plan_json_rejects_duplicate_keys_and_nonfinite_numbers() -> None:
    with pytest.raises(SuccessorExecutionPlanError, match="duplicate key"):
        SuccessorExecutionPlan.from_canonical_bytes(b'{"schema_version":2,"schema_version":2}')
    with pytest.raises(SuccessorExecutionPlanError, match="non-finite"):
        SuccessorExecutionPlan.from_canonical_bytes(b'{"schema_version":NaN}')


def test_nested_dispatch_digest_tamper_fails_closed() -> None:
    plan = build_successor_execution_plan(_fixture())
    payload = plan.to_dict()
    payload["dispatches"][0]["sealed_dispatch_identity_sha256"] = "0" * 64

    with pytest.raises(SuccessorExecutionPlanError, match="identity digest differs"):
        SuccessorExecutionPlan.from_dict(payload)


def test_execution_plan_rejects_scalar_missing_or_noncanonical_dependencies() -> None:
    plan = build_successor_execution_plan(_fixture())

    scalar = plan.to_dict()
    sealed = scalar["dispatches"][0]["sealed_dispatch"]
    sealed["dependency_identity_sha256"] = sealed.pop("dependency_identity_sha256s")[0]
    with pytest.raises(SuccessorExecutionPlanError, match="nested execution dispatch"):
        SuccessorExecutionPlan.from_dict(scalar)

    for dependencies in ([], ["d" * 64, "d" * 64], ["e" * 64, "d" * 64]):
        payload = plan.to_dict()
        payload["dispatches"][0]["sealed_dispatch"]["dependency_identity_sha256s"] = dependencies
        with pytest.raises(SuccessorExecutionPlanError, match="nested execution dispatch"):
            SuccessorExecutionPlan.from_dict(payload)


def test_execution_plan_rejects_foreign_or_extra_dependency_against_manifest() -> None:
    manifest = _fixture()
    plan = build_successor_execution_plan(manifest)
    original = plan.dispatches[0]
    dependencies = tuple(sorted((*original.dependency_identity_sha256s, "f" * 64)))
    foreign_dispatch = replace(
        original,
        sealed_dispatch=replace(
            original.sealed_dispatch,
            dependency_identity_sha256s=dependencies,
        ),
    )
    forged = replace(plan, dispatches=(foreign_dispatch, *plan.dispatches[1:]))

    with pytest.raises(SuccessorExecutionPlanError, match="differs from the durable"):
        forged.validate_against_manifest(manifest)


def test_execution_plan_rejects_route_order_or_binding_relabels() -> None:
    plan = build_successor_execution_plan(_fixture())

    multi_route = _logical_dispatch(
        order=0,
        routes=(
            ("fixture_endpoint:stg_a:0", "a" * 64),
            ("fixture_endpoint:stg_b:1", "b" * 64),
        ),
    )
    reordered_routes = replace(plan, dispatches=(multi_route,)).to_dict()
    dispatch = reordered_routes["dispatches"][0]
    dispatch["requested_scopes"] = list(reversed(dispatch["requested_scopes"]))
    with pytest.raises(SuccessorExecutionPlanError, match="scopes differ"):
        SuccessorExecutionPlan.from_dict(reordered_routes)

    relabelled = plan.to_dict()
    bindings = relabelled["planned_route_replacement_bindings"]
    bindings[0]["execution_dispatch_identity_sha256"] = "e" * 64
    fabricated = tuple(PlannedRouteReplacementBinding.from_dict(binding) for binding in bindings)
    relabelled["planned_route_replacement_bindings_sha256"] = (
        planned_route_replacement_bindings_sha256(fabricated)
    )
    with pytest.raises(SuccessorExecutionPlanError, match="differ from execution dispatches"):
        SuccessorExecutionPlan.from_dict(relabelled)

    dependency_relabel = plan.to_dict()
    bindings = dependency_relabel["planned_route_replacement_bindings"]
    bindings[0]["planning_dependency_identity_sha256s"] = ["e" * 64]
    fabricated = tuple(PlannedRouteReplacementBinding.from_dict(binding) for binding in bindings)
    dependency_relabel["planned_route_replacement_bindings_sha256"] = (
        planned_route_replacement_bindings_sha256(fabricated)
    )
    with pytest.raises(SuccessorExecutionPlanError, match="differ from execution dispatches"):
        SuccessorExecutionPlan.from_dict(dependency_relabel)


def test_execution_plan_rejects_incomplete_duplicate_or_reordered_binding_inventory() -> None:
    plan = build_successor_execution_plan(_fixture())

    incomplete = plan.to_dict()
    incomplete["planned_route_replacement_bindings"].pop()
    with pytest.raises(SuccessorExecutionPlanError, match="differ from execution dispatches"):
        SuccessorExecutionPlan.from_dict(incomplete)

    duplicate = plan.to_dict()
    duplicate["planned_route_replacement_bindings"].append(
        duplicate["planned_route_replacement_bindings"][0]
    )
    with pytest.raises(SuccessorExecutionPlanError, match="duplicate scopes"):
        SuccessorExecutionPlan.from_dict(duplicate)

    reordered = plan.to_dict()
    reordered["planned_route_replacement_bindings"].reverse()
    with pytest.raises(SuccessorExecutionPlanError, match="canonical scope order"):
        SuccessorExecutionPlan.from_dict(reordered)


def test_execution_dispatch_rejects_planning_phase() -> None:
    manifest = _fixture()
    planning = manifest.sealed_dispatches[0]
    scope_by_id = {scope.identity_sha256: scope for scope in manifest.requested_route_scopes}

    with pytest.raises(SuccessorExecutionPlanError, match="phase must be update"):
        SealedUpdateExecutionDispatch(
            order=0,
            sealed_dispatch=planning,
            requested_scopes=tuple(
                scope_by_id[scope_id] for scope_id in planning.requested_scope_identity_sha256s
            ),
        )


def test_execution_plan_rejects_duplicate_update_scope() -> None:
    plan = build_successor_execution_plan(_fixture())
    duplicate = replace(plan.dispatches[0], order=len(plan.dispatches))

    with pytest.raises(SuccessorExecutionPlanError, match="more than once"):
        replace(plan, dispatches=(*plan.dispatches, duplicate))


def _logical_dispatch(
    *,
    order: int,
    routes: tuple[tuple[str, str], ...],
    dependencies: tuple[str, ...] = ("d" * 64,),
) -> SealedUpdateExecutionDispatch:
    parameters = {"season": "2025-26"}
    scopes = tuple(
        RequestedRouteScope.from_parameters(
            endpoint_name="fixture_endpoint",
            route_id=route_id,
            route_contract_sha256=contract_sha256,
            parameters=parameters,
            mutability=CallMutability.MUTABLE,
        )
        for route_id, contract_sha256 in routes
    )
    return SealedUpdateExecutionDispatch(
        order=order,
        sealed_dispatch=SealedProviderDispatch.from_parameters(
            phase=PlanningDispatchPhase.UPDATE,
            endpoint_name="fixture_endpoint",
            requested_scope_identity_sha256s=tuple(scope.identity_sha256 for scope in scopes),
            parameters=parameters,
            pattern="season",
            staging_route_ids=tuple(scope.route_id for scope in scopes),
            dependency_identity_sha256s=dependencies,
        ),
        requested_scopes=scopes,
    )


def test_execution_plan_rejects_duplicate_logical_call_with_disjoint_routes() -> None:
    plan = build_successor_execution_plan(_fixture())
    duplicate_calls = (
        _logical_dispatch(
            order=0,
            routes=(("fixture_endpoint:stg_a:0", "a" * 64),),
        ),
        _logical_dispatch(
            order=1,
            routes=(("fixture_endpoint:stg_b:1", "b" * 64),),
        ),
    )

    with pytest.raises(SuccessorExecutionPlanError, match="logical provider call"):
        replace(plan, dispatches=duplicate_calls)


def test_execution_plan_accepts_one_logical_call_with_multiple_exact_routes() -> None:
    plan = build_successor_execution_plan(_fixture())
    multi_route = _logical_dispatch(
        order=0,
        routes=(
            ("fixture_endpoint:stg_a:0", "a" * 64),
            ("fixture_endpoint:stg_b:1", "b" * 64),
        ),
        dependencies=("c" * 64, "d" * 64),
    )

    accepted = replace(plan, dispatches=(multi_route,))

    assert accepted.dispatches == (multi_route,)
    assert accepted.dispatches[0].staging_route_ids == (
        "fixture_endpoint:stg_a:0",
        "fixture_endpoint:stg_b:1",
    )
    assert accepted.dispatches[0].dependency_identity_sha256s == (
        "c" * 64,
        "d" * 64,
    )
    assert tuple(
        binding.requested_scope_sha256 for binding in accepted.planned_route_replacement_bindings
    ) == tuple(sorted(scope.identity_sha256 for scope in multi_route.requested_scopes))
    assert all(
        binding.execution_dispatch_identity_sha256 == multi_route.identity_sha256
        and binding.planning_dependency_identity_sha256s == ("c" * 64, "d" * 64)
        for binding in accepted.planned_route_replacement_bindings
    )
    assert accepted.planned_route_replacement_bindings_sha256 == (
        planned_route_replacement_bindings_sha256(accepted.planned_route_replacement_bindings)
    )


def test_builder_rejects_non_manifest() -> None:
    with pytest.raises(SuccessorExecutionPlanError, match="PlanningGenerationManifest"):
        build_successor_execution_plan(object())  # type: ignore[arg-type]
