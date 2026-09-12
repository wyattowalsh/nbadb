from __future__ import annotations

from dataclasses import replace

import pytest

from nbadb.orchestrate.successor_planning_contract import (
    SuccessorPlanningContractError,
    SuccessorPlanningEvidence,
    SuccessorPlanningPublicIdentity,
    SuccessorPlanningRequest,
    build_successor_planning_evidence,
    finalize_successor_update_intent,
)
from nbadb.orchestrate.successor_update_contract import (
    CallMutability,
    RequestedRouteScope,
    SuccessorUpdateMode,
)
from tests.unit.orchestrate.test_successor_planning_generation_contract import (
    _fixture,
)


def _scope(marker: str) -> RequestedRouteScope:
    return RequestedRouteScope.from_parameters(
        endpoint_name="league_game_log",
        route_id=f"league_game_log:stg_league_game_log:{int(marker, 16)}",
        route_contract_sha256=marker * 64,
        parameters={"marker": marker},
        mutability=CallMutability.MUTABLE,
    )


def _request(*scopes: RequestedRouteScope) -> SuccessorPlanningRequest:
    return SuccessorPlanningRequest(
        baseline_identity_sha256="a" * 64,
        mode=SuccessorUpdateMode.MONTHLY,
        source_sha="b" * 40,
        cutoff_utc="2026-07-01T00:00:00Z",
        as_of_utc="2026-08-01T00:00:00Z",
        workflow_run_id=17,
        workflow_run_attempt=2,
        requested_planning_scopes=tuple(scopes),
    )


def test_planning_evidence_round_trip_binds_manifest_and_execution_plan() -> None:
    manifest = _fixture()
    evidence = build_successor_planning_evidence(
        planning_generation_manifest=manifest,
    )

    restored = SuccessorPlanningEvidence.from_dict(evidence.to_dict())

    assert restored == evidence
    assert restored.request.to_dict() == manifest.request.to_dict()
    assert restored.planning_generation_manifest.identity_sha256 == manifest.identity_sha256
    restored.execution_plan.validate_against_manifest(manifest)
    assert restored.planned_route_replacement_bindings_sha256 == (
        restored.execution_plan.planned_route_replacement_bindings_sha256
    )
    assert restored.to_dict()["schema_version"] == 3
    assert len(evidence.identity_sha256) == 64


def test_planning_public_identity_omits_member_wave_and_parameter_bodies() -> None:
    evidence = build_successor_planning_evidence(
        planning_generation_manifest=_fixture(),
    )
    public = SuccessorPlanningPublicIdentity.from_evidence(evidence)
    payload = evidence.to_public_dict()

    assert public.to_dict() == payload
    assert SuccessorPlanningPublicIdentity.from_dict(payload) == public
    assert "members" not in payload["planning_generation_manifest"]
    assert "waves" not in payload["planning_generation_manifest"]
    assert "sealed_dispatches" not in payload["planning_generation_manifest"]
    assert "request" not in payload["planning_generation_manifest"]
    assert "requested_route_scopes" not in payload["planning_generation_manifest"]
    assert "dispatches" not in payload["execution_plan"]
    assert "parameters" not in payload["planning_generation_manifest"]
    assert "parameters" not in payload["execution_plan"]
    assert payload["planning_generation_manifest"]["identity_sha256"] == (
        evidence.planning_generation_manifest.identity_sha256
    )
    assert payload["execution_plan"]["identity_sha256"] == evidence.execution_plan.identity_sha256
    assert payload["execution_plan"]["planning_generation_id"] == (
        evidence.execution_plan.planning_generation_id
    )


def test_planning_public_identity_rejects_private_manifest_body() -> None:
    evidence = build_successor_planning_evidence(
        planning_generation_manifest=_fixture(),
    )
    payload = evidence.to_public_dict()
    payload["planning_generation_manifest"] = evidence.planning_generation_manifest.to_dict()

    with pytest.raises(SuccessorPlanningContractError, match="public identity"):
        SuccessorPlanningPublicIdentity.from_dict(payload)


def test_final_intent_uses_only_sealed_update_execution_scopes() -> None:
    evidence = build_successor_planning_evidence(
        planning_generation_manifest=_fixture(),
    )

    intent = finalize_successor_update_intent(evidence)

    expected = tuple(
        sorted(
            (
                scope
                for dispatch in evidence.execution_plan.dispatches
                for scope in dispatch.requested_scopes
            ),
            key=lambda scope: scope.identity_sha256,
        )
    )
    assert intent.planning_generation_manifest_sha256 == (
        evidence.planning_generation_manifest.identity_sha256
    )
    assert intent.successor_execution_plan_sha256 == evidence.execution_plan.identity_sha256
    assert intent.planned_route_replacement_bindings_sha256 == (
        evidence.execution_plan.planned_route_replacement_bindings_sha256
    )
    assert intent.requested_scopes == expected


def test_planning_request_rejects_duplicate_or_noncanonical_scope_inventory() -> None:
    scope = _scope("1")
    with pytest.raises(SuccessorPlanningContractError, match="duplicates"):
        _request(scope, scope)

    payload = _request(scope).to_dict()
    payload["requested_planning_scopes_sha256"] = "0" * 64
    with pytest.raises(SuccessorPlanningContractError, match="digest differs"):
        SuccessorPlanningRequest.from_dict(payload)

    payload = _request(scope).to_dict()
    payload["schema_version"] = True
    with pytest.raises(SuccessorPlanningContractError, match="schema is invalid"):
        SuccessorPlanningRequest.from_dict(payload)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("workflow_run_id", True),
        ("workflow_run_id", 1.0),
        ("workflow_run_id", 0),
        ("workflow_run_attempt", False),
        ("workflow_run_attempt", 2.0),
        ("workflow_run_attempt", 0),
    ],
)
def test_planning_request_rejects_invalid_workflow_coordinates(
    field_name: str,
    value: object,
) -> None:
    request = _request(_scope("1"))

    with pytest.raises(
        SuccessorPlanningContractError,
        match=rf"{field_name} must be a positive integer",
    ):
        replace(request, **{field_name: value})

    payload = request.to_dict()
    payload[field_name] = value
    with pytest.raises(
        SuccessorPlanningContractError,
        match=rf"{field_name} must be a positive integer",
    ):
        SuccessorPlanningRequest.from_dict(payload)


@pytest.mark.parametrize("field_name", ["workflow_run_id", "workflow_run_attempt"])
def test_planning_request_requires_exact_workflow_coordinate_fields(field_name: str) -> None:
    payload = _request(_scope("1")).to_dict()
    del payload[field_name]

    with pytest.raises(SuccessorPlanningContractError, match="fields are invalid"):
        SuccessorPlanningRequest.from_dict(payload)

    payload = _request(_scope("1")).to_dict()
    payload["unexpected_workflow_coordinate"] = 1
    with pytest.raises(SuccessorPlanningContractError, match="fields are invalid"):
        SuccessorPlanningRequest.from_dict(payload)


def test_planning_request_identity_binds_workflow_coordinates() -> None:
    request = _request(_scope("1"))

    assert SuccessorPlanningRequest.from_dict(request.to_dict()) == request
    assert replace(request, workflow_run_id=request.workflow_run_id + 1).identity_sha256 != (
        request.identity_sha256
    )
    assert (
        replace(
            request,
            workflow_run_attempt=request.workflow_run_attempt + 1,
        ).identity_sha256
        != request.identity_sha256
    )


def test_planning_evidence_rejects_numeric_schema_alias() -> None:
    evidence = build_successor_planning_evidence(
        planning_generation_manifest=_fixture(),
    )
    payload = evidence.to_dict()
    payload["schema_version"] = 3.0

    with pytest.raises(SuccessorPlanningContractError, match="schema is invalid"):
        SuccessorPlanningEvidence.from_dict(payload)


def test_planning_evidence_rejects_tampered_manifest_digest() -> None:
    evidence = build_successor_planning_evidence(
        planning_generation_manifest=_fixture(),
    )
    payload = evidence.to_dict()
    payload["planning_generation_manifest_sha256"] = "0" * 64

    with pytest.raises(SuccessorPlanningContractError, match="authority digest differs"):
        SuccessorPlanningEvidence.from_dict(payload)


def test_planning_evidence_rejects_execution_plan_drift() -> None:
    evidence = build_successor_planning_evidence(
        planning_generation_manifest=_fixture(),
    )
    payload = evidence.to_dict()
    payload["execution_plan"]["baseline_identity_sha256"] = "0" * 64

    with pytest.raises(SuccessorPlanningContractError, match="differs from its planning"):
        SuccessorPlanningEvidence.from_dict(payload)


def test_planning_evidence_rejects_planned_route_binding_digest_drift() -> None:
    evidence = build_successor_planning_evidence(
        planning_generation_manifest=_fixture(),
    )
    payload = evidence.to_dict()
    payload["planned_route_replacement_bindings_sha256"] = "0" * 64

    with pytest.raises(
        SuccessorPlanningContractError,
        match="planned route replacement binding digest differs",
    ):
        SuccessorPlanningEvidence.from_dict(payload)


def test_planning_evidence_rejects_schema_v2_without_binding_authority() -> None:
    payload = build_successor_planning_evidence(
        planning_generation_manifest=_fixture(),
    ).to_dict()
    payload["schema_version"] = 2
    del payload["planned_route_replacement_bindings_sha256"]

    with pytest.raises(SuccessorPlanningContractError, match="fields are invalid"):
        SuccessorPlanningEvidence.from_dict(payload)


def test_planning_evidence_rejects_old_path_free_schema_without_fallback() -> None:
    payload = {
        "schema_version": 1,
        "kind": "successor_planning_evidence",
        "request": _fixture().request.to_dict(),
        "private_generation_receipt_sha256": "f" * 64,
        "receipts": [],
        "receipts_sha256": "0" * 64,
        "resolved_requested_scopes": [],
        "resolved_requested_scopes_sha256": "0" * 64,
    }

    with pytest.raises(SuccessorPlanningContractError, match="fields are invalid"):
        SuccessorPlanningEvidence.from_dict(payload)


def test_planning_evidence_requires_data_bearing_manifest() -> None:
    with pytest.raises(SuccessorPlanningContractError, match="PlanningGenerationManifest"):
        SuccessorPlanningEvidence(planning_generation_manifest=object())  # type: ignore[arg-type]
