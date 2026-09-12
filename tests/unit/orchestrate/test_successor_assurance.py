from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any

import pytest

from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.kaggle.metadata import expected_full_publication_resource_contract
from nbadb.orchestrate.capture_session import PrivateGenerationIdentity
from nbadb.orchestrate.successor_assurance import (
    SUCCESSOR_ASSURANCE_MANIFEST_DIGEST_DOMAIN,
    SUCCESSOR_ASSURANCE_MANIFEST_KIND,
    SuccessorAssuranceContractError,
    SuccessorDatabaseEvidence,
    SuccessorPublicEvidence,
    SuccessorPublicResourceAttestation,
    SuccessorScanEvidence,
    SuccessorTerminalAssuranceReportV7,
    SuccessorTransformOutputAttestation,
    emit_successor_assurance_manifest,
    validate_successor_terminal_assurance_report,
    verify_successor_assurance_manifest,
)
from nbadb.orchestrate.successor_planning_contract import (
    SuccessorPlanningEvidence,
    build_successor_planning_evidence,
    finalize_successor_update_intent,
)
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    CallMutability,
    DeltaDisposition,
    ObservedDeltaReceipt,
    RequestedRouteScope,
    SuccessorGenerationBuild,
    SuccessorUpdateMode,
    canonical_sha256,
)
from nbadb.orchestrate.transformers import expected_transform_output_tables
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_publication_inventory import (
    w2_public_value_authority_publication_tables,
)
from tests.unit.orchestrate.test_successor_planning_generation_contract import (
    _synthetic_manifest,
)

_SOURCE_SHA = "b" * 40
_BLOCKED_EVIDENCE = {"schema_version": 1, "contract_blocked_lanes": []}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _w2_database_authority(
    expected_call_count: int,
    *,
    marker: str = "successor",
) -> W2DatabaseAuthorityReceiptV1:
    relation_counts = tuple(
        (entry.table_name, expected_call_count)
        for entry in w2_public_value_authority_publication_tables()
    )
    return W2DatabaseAuthorityReceiptV1.build(
        w2_required_logical_call_count=expected_call_count,
        w2_source_call_admission_inventory_sha256=_digest(f"{marker}:admissions"),
        raw_authority_v2_bundle_count=expected_call_count,
        raw_authority_v2_bundle_inventory_sha256=_digest(f"{marker}:raw-bundles"),
        raw_authority_v2_persistence_receipt_inventory_sha256=_digest(f"{marker}:raw-persistence"),
        w2_publication_receipt_count=expected_call_count,
        w2_publication_receipt_inventory_sha256=_digest(f"{marker}:publication"),
        w2_exact_six_schema_inventory_sha256=_digest(f"{marker}:exact-six"),
        w2_relation_row_counts=relation_counts,
        w2_relation_row_count=sum(row_count for _table_name, row_count in relation_counts),
        w2_relation_inventory_sha256=_digest(f"{marker}:relations"),
    )


def _synthetic_public_resource_bytes() -> int:
    controls = {"assured-artifact-manifest.json", "terminal-assurance-report.json"}
    resources = (
        item
        for item in sorted(expected_full_publication_resource_contract().items())
        if item[0] not in controls
    )
    return sum(index + 1 for index, _item in enumerate(resources))


def _baseline() -> BaselineAssuranceIdentity:
    provider = expected_nba_api_provider_authority()
    return BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=238,
        chain_id="full-baseline-20260801",
        source_sha="a" * 40,
        coverage_fingerprint="1" * 64,
        data_tree_fingerprint="2" * 64,
        remote_bundle_fingerprint_sha256="3" * 64,
        installed_public_tree_sha256="4" * 64,
        installed_public_tree_bytes=_synthetic_public_resource_bytes(),
        assured_manifest_sha256="5" * 64,
        terminal_assurance_report_sha256="6" * 64,
        private_baseline_receipt_sha256="7" * 64,
        checkpoint_database_sha256="8" * 64,
        checkpoint_report_sha256="9" * 64,
        contract_blocked_evidence_sha256=canonical_sha256(_BLOCKED_EVIDENCE),
        provider_authority_sha256=str(provider["authority_sha256"]),
    )


def _scope(
    marker: str,
    *,
    endpoint_name: str = "league_game_log",
    parameter_marker: str | None = None,
) -> RequestedRouteScope:
    if endpoint_name == "schedule_int":
        route_id = {
            "2": "schedule_int:stg_schedule_int:0",
            "3": "schedule_int:stg_schedule_int_weeks:1",
            "4": "schedule_int:stg_schedule_int_broadcaster:2",
        }[marker]
    elif endpoint_name == "league_game_log":
        route_id = "league_game_log:stg_league_game_log:0"
    else:
        route_id = "schedule_int:stg_schedule_int:0"
    route = staging_route_contract_bundle().by_route_id[route_id]
    return RequestedRouteScope.from_parameters(
        endpoint_name=endpoint_name,
        route_id=route_id,
        route_contract_sha256=route.contract_sha256,
        parameters={"marker": parameter_marker or marker},
        mutability=CallMutability.MUTABLE,
    )


def _planning(
    baseline: BaselineAssuranceIdentity,
    *,
    resolved_scopes: tuple[RequestedRouteScope, ...] | None = None,
) -> tuple[SuccessorPlanningEvidence, tuple[RequestedRouteScope, ...]]:
    resolved = resolved_scopes or (
        _scope("2", endpoint_name="schedule_int", parameter_marker="wave-zero"),
        _scope("3", endpoint_name="schedule_int", parameter_marker="wave-one"),
        _scope("4", endpoint_name="schedule_int"),
    )
    wave_0_key = (resolved[0].endpoint_name, resolved[0].scope_sha256)
    wave_1_index = next(
        index
        for index, scope in enumerate(resolved[1:], start=1)
        if (scope.endpoint_name, scope.scope_sha256) != wave_0_key
    )
    manifest_scopes = (
        resolved[0],
        resolved[wave_1_index],
        *(scope for index, scope in enumerate(resolved) if index not in {0, wave_1_index}),
    )
    evidence = build_successor_planning_evidence(
        planning_generation_manifest=_synthetic_manifest(
            baseline_identity_sha256=baseline.identity_sha256,
            mode=SuccessorUpdateMode.DAILY,
            source_sha=_SOURCE_SHA,
            cutoff_utc="2026-08-06T12:00:00Z",
            as_of_utc="2026-08-13T12:00:00Z",
            update_scopes=manifest_scopes,
        ),
    )
    return evidence, resolved


def _receipt(
    *,
    baseline: BaselineAssuranceIdentity,
    intent_sha256: str,
    scope: RequestedRouteScope,
    execution_dispatch_identity_sha256: str,
    planning_dependency_identity_sha256s: tuple[str, ...],
    marker: str,
    prior: str,
    persisted: str,
    disposition: DeltaDisposition = DeltaDisposition.OBSERVED,
) -> ObservedDeltaReceipt:
    return ObservedDeltaReceipt(
        baseline_identity_sha256=baseline.identity_sha256,
        update_intent_sha256=intent_sha256,
        source_sha=_SOURCE_SHA,
        requested_scope_sha256=scope.identity_sha256,
        execution_dispatch_identity_sha256=execution_dispatch_identity_sha256,
        planning_dependency_identity_sha256s=planning_dependency_identity_sha256s,
        disposition=disposition,
        logical_call_receipt_sha256=marker * 64,
        prior_persisted_content_sha256=prior * 64,
        source_scope_replacement_sha256=hex((int(marker, 16) + 4) % 16)[2:] * 64,
        persisted_content_sha256=persisted * 64,
        persisted_schema_sha256=hex((int(marker, 16) + 5) % 16)[2:] * 64,
        persisted_row_count=0 if disposition is DeltaDisposition.TYPED_ZERO else 12,
        typed_zero_reason_code=(
            "provider_success_empty" if disposition is DeltaDisposition.TYPED_ZERO else None
        ),
    )


def _build(
    baseline: BaselineAssuranceIdentity,
    evidence: SuccessorPlanningEvidence,
    scopes: tuple[RequestedRouteScope, ...],
) -> tuple[Any, SuccessorGenerationBuild]:
    intent = finalize_successor_update_intent(evidence)
    bindings_by_scope = {
        binding.requested_scope_sha256: binding
        for binding in evidence.execution_plan.planned_route_replacement_bindings
    }
    dispatch_roots: dict[str, str] = {}
    marker_values = iter("56789abcdef")
    receipts: list[ObservedDeltaReceipt] = []
    for index, scope in enumerate(scopes):
        binding = bindings_by_scope[scope.identity_sha256]
        marker = dispatch_roots.setdefault(
            binding.execution_dispatch_identity_sha256,
            next(marker_values),
        )
        disposition = DeltaDisposition.TYPED_ZERO if index == 2 else DeltaDisposition.OBSERVED
        prior = ("1", "3", "4", "8")[index]
        persisted = ("2", "3", "5", "9")[index]
        receipts.append(
            _receipt(
                baseline=baseline,
                intent_sha256=intent.identity_sha256,
                scope=scope,
                execution_dispatch_identity_sha256=(binding.execution_dispatch_identity_sha256),
                planning_dependency_identity_sha256s=(binding.planning_dependency_identity_sha256s),
                marker=marker,
                prior=prior,
                persisted=persisted,
                disposition=disposition,
            )
        )
    build = SuccessorGenerationBuild(
        baseline_identity_sha256=baseline.identity_sha256,
        update_intent_sha256=intent.identity_sha256,
        source_sha=_SOURCE_SHA,
        observed_delta_receipts=tuple(receipts),
    )
    return intent, build


def _binding_payloads(
    *,
    provider_sha256: str,
    intent: Any,
    build: SuccessorGenerationBuild,
) -> list[dict[str, Any]]:
    scopes_by_identity = {scope.identity_sha256: scope for scope in intent.requested_scopes}
    grouped: dict[str, dict[str, Any]] = {}
    for receipt in build.observed_delta_receipts:
        scope = scopes_by_identity[receipt.requested_scope_sha256]
        binding = grouped.setdefault(
            receipt.logical_call_receipt_sha256,
            {
                "endpoint_name": scope.endpoint_name,
                "logical_call_receipt_sha256": receipt.logical_call_receipt_sha256,
                "logical_parameters_sha256": scope.scope_sha256,
                "provider_authority_sha256": provider_sha256,
                "result_route_ids": [],
            },
        )
        binding["result_route_ids"].append(scope.route_id)
    return [
        {
            **grouped[root],
            "result_route_ids": sorted(grouped[root]["result_route_ids"]),
        }
        for root in sorted(grouped)
    ]


def _private_generation(
    provider_sha256: str,
    *,
    intent: Any,
    build: SuccessorGenerationBuild,
) -> PrivateGenerationIdentity:
    bindings = _binding_payloads(
        provider_sha256=provider_sha256,
        intent=intent,
        build=build,
    )
    roots = tuple(binding["logical_call_receipt_sha256"] for binding in bindings)
    call_count = len(roots)
    return PrivateGenerationIdentity(
        manifest_sha256="d" * 64,
        provider_authority_sha256=provider_sha256,
        semantic_source_sha=_SOURCE_SHA,
        chain_id="daily-successor-20260813",
        lane_id="daily-update",
        workflow_run_id=123456,
        workflow_run_attempt=1,
        artifact_count=call_count * 3,
        done_call_count=call_count,
        done_call_receipt_sha256s=roots,
        done_call_bindings_sha256=canonical_sha256(bindings),
        done_attempt_count=call_count,
        done_blob_count=call_count,
        orphan_call_count=0,
        orphan_attempt_count=0,
        orphan_blob_count=0,
        stored_bytes=4096,
    )


def _transforms() -> tuple[SuccessorTransformOutputAttestation, ...]:
    return tuple(
        SuccessorTransformOutputAttestation(
            table_name=table_name,
            row_count=0 if table_name == "agg_all_time_leaders" else 1,
            schema_sha256=_digest(f"schema:{table_name}"),
            content_sha256=_digest(f"content:{table_name}"),
        )
        for table_name in sorted(expected_transform_output_tables(include_live=True))
    )


def _public() -> SuccessorPublicEvidence:
    contract = expected_full_publication_resource_contract()
    controls = {"assured-artifact-manifest.json", "terminal-assurance-report.json"}
    return SuccessorPublicEvidence(
        resources=tuple(
            SuccessorPublicResourceAttestation(
                resource_id=resource_id,
                kind=kind,
                bytes=index + 1,
                sha256=_digest(f"resource:{resource_id}"),
            )
            for index, (resource_id, kind) in enumerate(
                item for item in sorted(contract.items()) if item[0] not in controls
            )
        )
    )


def _report(
    *,
    resolved_scopes: tuple[RequestedRouteScope, ...] | None = None,
) -> SuccessorTerminalAssuranceReportV7:
    baseline = _baseline()
    planning, scopes = _planning(baseline, resolved_scopes=resolved_scopes)
    intent, build = _build(baseline, planning, scopes)
    provider = expected_nba_api_provider_authority()
    private_generation = _private_generation(
        str(provider["authority_sha256"]),
        intent=intent,
        build=build,
    )
    public = _public()
    duckdb = public.resource("nba.duckdb")
    sqlite = public.resource("nba.sqlite")
    return SuccessorTerminalAssuranceReportV7.create(
        chain_id="daily-successor-20260813",
        source_sha=_SOURCE_SHA,
        coverage_fingerprint=baseline.coverage_fingerprint,
        generation=1,
        baseline=baseline,
        planning_evidence=planning,
        intent=intent,
        build=build,
        update_private_generation=private_generation,
        transform_outputs=_transforms(),
        scan_evidence=SuccessorScanEvidence(
            report_sha256="e" * 64,
            status="passed",
            fail_on="error",
            full_publication=True,
            error_count=0,
        ),
        public_evidence=public,
        database_evidence=SuccessorDatabaseEvidence(
            duckdb_sha256=duckdb.sha256,
            duckdb_bytes=duckdb.bytes,
            sqlite_sha256=sqlite.sha256,
            sqlite_bytes=sqlite.bytes,
        ),
        w2_database_authority=_w2_database_authority(private_generation.done_call_count),
        contract_blocked_evidence=_BLOCKED_EVIDENCE,
        provider_authority=provider,
    )


def _payload() -> dict[str, Any]:
    return json.loads(_report().canonical_bytes)


def test_schema_v7_round_trip_is_canonical_path_free_and_identity_compatible() -> None:
    report = _report()

    assert report.schema_version == 7
    assert report.model_green is True
    assert report.data_green is True
    expected_resource_count = len(expected_full_publication_resource_contract())
    assert report.transform_output_count == len(_transforms())
    assert report.public_evidence.resource_count == expected_resource_count
    assert report.public_evidence.data_resource_count == expected_resource_count - 2
    assert report.delta_coverage.changed_scope_count == 1
    assert report.delta_coverage.no_change_scope_count == 1
    assert report.delta_coverage.typed_zero_scope_count == 1
    assert report.w2_database_authority_closed is True
    assert report.w2_database_authority_sha256 == (report.w2_database_authority.receipt_sha256)
    assert report.w2_expected_call_count == report.update_private_generation.done_call_count
    assert len(report.w2_expected_call_inventory_sha256) == 64
    assert len(report.w2_database_authority.w2_relation_row_counts) == 6
    assert report.canonical_bytes.endswith(b"\n")
    assert validate_successor_terminal_assurance_report(report.canonical_bytes) == report
    assert validate_successor_terminal_assurance_report(report.to_dict()) == report

    payload = report.to_dict()
    assert "successor_assured_manifest_sha256" not in payload
    serialized = report.canonical_bytes.decode("utf-8")
    assert '"/Users/' not in serialized
    assert '"file://' not in serialized
    _assert_public_planning_identities(payload["planning_evidence"])

    identity = report.to_successor_assurance_identity(
        successor_assured_manifest_sha256="f" * 64,
        installed_public_tree_sha256="0" * 64,
    )
    assert identity.successor_validation_report_sha256 == report.content_sha256
    assert identity.planned_route_replacement_bindings_sha256 == (
        report.planned_route_replacement_bindings_sha256
    )
    assert identity.transform_inventory_sha256 == report.transform_inventory_sha256
    assert identity.publication_resource_inventory_sha256 == (
        report.public_evidence.publication_resource_inventory_sha256
    )
    assert identity.installed_public_tree_sha256 == "0" * 64
    assert identity.successor_assured_manifest_sha256 == "f" * 64


def test_terminal_report_w2_authority_is_exact_complete_and_not_swappable() -> None:
    report = _report()
    required_fields = (
        "w2_database_authority",
        "w2_database_authority_sha256",
        "w2_expected_call_count",
        "w2_expected_call_inventory_sha256",
        "w2_database_authority_closed",
    )
    for field_name in required_fields:
        payload = report.to_dict()
        payload.pop(field_name)
        with pytest.raises(SuccessorAssuranceContractError, match="fields are invalid"):
            validate_successor_terminal_assurance_report(payload)

    mutations: tuple[tuple[str, object], ...] = (
        ("w2_database_authority_sha256", "0" * 64),
        ("w2_expected_call_count", report.w2_expected_call_count + 1),
        ("w2_expected_call_inventory_sha256", "0" * 64),
        ("w2_database_authority_closed", False),
    )
    for field_name, replacement_value in mutations:
        payload = report.to_dict()
        payload[field_name] = replacement_value
        with pytest.raises(SuccessorAssuranceContractError):
            validate_successor_terminal_assurance_report(payload)

    foreign = _w2_database_authority(
        report.w2_expected_call_count,
        marker="foreign-successor",
    )
    payload = report.to_dict()
    payload["w2_database_authority"] = foreign.to_dict()
    payload["w2_database_authority_sha256"] = foreign.receipt_sha256
    with pytest.raises(SuccessorAssuranceContractError, match="derived fields differ"):
        validate_successor_terminal_assurance_report(payload)

    payload = report.to_dict()
    w2_payload = payload["w2_database_authority"]
    assert isinstance(w2_payload, dict)
    w2_payload.pop("w2_exact_six_schema_inventory_sha256")
    with pytest.raises(SuccessorAssuranceContractError, match="W2 database authority"):
        validate_successor_terminal_assurance_report(payload)


def _assert_public_planning_identities(planning: object) -> None:
    assert isinstance(planning, dict)
    assert "parameters" not in json.dumps(planning)
    manifest = planning["planning_generation_manifest"]
    plan = planning["execution_plan"]
    assert isinstance(manifest, dict)
    assert isinstance(plan, dict)
    assert "members" not in manifest
    assert "waves" not in manifest
    assert "sealed_dispatches" not in manifest
    assert "requested_route_scopes" not in manifest
    assert "request" not in manifest
    assert "dispatches" not in plan
    assert "parameters" not in manifest
    assert "parameters" not in plan


def test_report_binds_exact_baseline_planning_intent_build_and_private_generation() -> None:
    report = _report()
    assert report.baseline_identity_sha256 == report.baseline.identity_sha256
    assert report.planning_generation_manifest_sha256 == (
        report.planning_evidence.planning_generation_manifest.identity_sha256
    )
    assert report.execution_plan_sha256 == report.planning_evidence.execution_plan.identity_sha256
    assert report.update_intent_sha256 == report.intent.identity_sha256
    assert report.build_sha256 == report.build.identity_sha256
    assert (
        report.private_generation_receipt_sha256 == report.update_private_generation.identity_sha256
    )
    assert report.provider_authority_sha256 == report.baseline.provider_authority_sha256
    assert (
        report.contract_blocked_evidence_sha256 == report.baseline.contract_blocked_evidence_sha256
    )


def test_one_logical_root_may_bind_multiple_exact_result_routes() -> None:
    report = _report(
        resolved_scopes=(
            _scope("2", endpoint_name="schedule_int", parameter_marker="shared"),
            _scope("3", endpoint_name="schedule_int", parameter_marker="shared"),
            _scope("4", endpoint_name="schedule_int"),
        )
    )
    provider_sha256 = report.provider_authority_sha256
    expected_bindings = _binding_payloads(
        provider_sha256=provider_sha256,
        intent=report.intent,
        build=report.build,
    )

    assert len(report.build.observed_delta_receipts) == 3
    assert len(expected_bindings) == 2
    assert expected_bindings[0] == {
        "endpoint_name": "schedule_int",
        "logical_call_receipt_sha256": "5" * 64,
        "logical_parameters_sha256": next(
            scope.scope_sha256
            for scope in report.intent.requested_scopes
            if scope.route_id == "schedule_int:stg_schedule_int:0"
        ),
        "provider_authority_sha256": provider_sha256,
        "result_route_ids": [
            "schedule_int:stg_schedule_int:0",
            "schedule_int:stg_schedule_int_weeks:1",
        ],
    }
    assert report.update_private_generation.done_call_count == 2
    assert report.update_private_generation.done_call_receipt_sha256s == (
        "5" * 64,
        "7" * 64,
    )
    assert report.update_private_generation.done_call_bindings_sha256 == canonical_sha256(
        expected_bindings
    )
    assert validate_successor_terminal_assurance_report(report.canonical_bytes) == report


@pytest.mark.parametrize(
    ("field_name", "foreign_value"),
    (
        ("endpoint_name", "foreign_endpoint"),
        ("logical_parameters_sha256", "0" * 64),
        ("provider_authority_sha256", "0" * 64),
        ("result_route_ids", ["foreign_route:stg_foreign_route:0"]),
    ),
)
def test_private_binding_digest_rejects_same_count_authority_drift(
    field_name: str,
    foreign_value: Any,
) -> None:
    report = _report()
    bindings = _binding_payloads(
        provider_sha256=report.provider_authority_sha256,
        intent=report.intent,
        build=report.build,
    )
    bindings[0][field_name] = foreign_value
    private = replace(
        report.update_private_generation,
        done_call_bindings_sha256=canonical_sha256(bindings),
    )

    with pytest.raises(SuccessorAssuranceContractError, match="does not reconcile"):
        replace(report, update_private_generation=private)


def test_private_binding_rejects_foreign_root_with_same_count() -> None:
    report = _report()
    bindings = _binding_payloads(
        provider_sha256=report.provider_authority_sha256,
        intent=report.intent,
        build=report.build,
    )
    original_roots = tuple(report.update_private_generation.done_call_receipt_sha256s)
    bindings[1]["logical_call_receipt_sha256"] = "8" * 64
    foreign_roots = tuple(sorted((original_roots[0], "8" * 64, *original_roots[2:])))
    private = replace(
        report.update_private_generation,
        done_call_receipt_sha256s=foreign_roots,
        done_call_bindings_sha256=canonical_sha256(bindings),
    )

    with pytest.raises(SuccessorAssuranceContractError, match="does not reconcile"):
        replace(report, update_private_generation=private)


@pytest.mark.parametrize(
    ("drifted_scope", "message"),
    (
        (
            _scope(
                "3",
                endpoint_name="league_game_log",
                parameter_marker="shared",
            ),
            "one logical call receipt is relabelled across execution dispatches",
        ),
        (
            _scope("3", endpoint_name="schedule_int", parameter_marker="foreign"),
            "one logical call receipt is relabelled across execution dispatches",
        ),
    ),
)
def test_routes_sharing_a_logical_root_require_one_endpoint_and_parameter_authority(
    drifted_scope: RequestedRouteScope,
    message: str,
) -> None:
    scopes = (
        _scope("2", endpoint_name="schedule_int", parameter_marker="shared"),
        drifted_scope,
        _scope("4", endpoint_name="schedule_int"),
    )

    baseline = _baseline()
    planning, resolved = _planning(baseline, resolved_scopes=scopes)
    intent = finalize_successor_update_intent(planning)
    bindings = {
        binding.requested_scope_sha256: binding
        for binding in planning.execution_plan.planned_route_replacement_bindings
    }
    receipts = tuple(
        _receipt(
            baseline=baseline,
            intent_sha256=intent.identity_sha256,
            scope=scope,
            execution_dispatch_identity_sha256=(
                bindings[scope.identity_sha256].execution_dispatch_identity_sha256
            ),
            planning_dependency_identity_sha256s=(
                bindings[scope.identity_sha256].planning_dependency_identity_sha256s
            ),
            marker="5" if index < 2 else "7",
            prior=str(index + 1),
            persisted=str(index + 2),
        )
        for index, scope in enumerate(resolved)
    )
    with pytest.raises(ValueError, match=message):
        SuccessorGenerationBuild(
            baseline_identity_sha256=baseline.identity_sha256,
            update_intent_sha256=intent.identity_sha256,
            source_sha=_SOURCE_SHA,
            observed_delta_receipts=receipts,
        )


def test_registered_route_endpoint_authority_cannot_be_redeclared() -> None:
    route = staging_route_contract_bundle().by_route_id["schedule_int:stg_schedule_int:0"]
    scopes = (
        RequestedRouteScope.from_parameters(
            endpoint_name="foreign_endpoint",
            route_id="schedule_int:stg_schedule_int:0",
            route_contract_sha256=route.contract_sha256,
            parameters={"marker": "shared"},
            mutability=CallMutability.MUTABLE,
        ),
        _scope("3", endpoint_name="schedule_int", parameter_marker="shared"),
        _scope("4", endpoint_name="schedule_int"),
    )

    with pytest.raises(
        SuccessorAssuranceContractError,
        match="registered staging route contract",
    ):
        _report(resolved_scopes=scopes)


def test_registered_route_contract_digest_cannot_be_redeclared() -> None:
    scopes = (
        replace(
            _scope("2", endpoint_name="schedule_int", parameter_marker="shared"),
            route_contract_sha256="0" * 64,
        ),
        _scope("3", endpoint_name="schedule_int", parameter_marker="shared"),
        _scope("4", endpoint_name="schedule_int"),
    )

    with pytest.raises(
        SuccessorAssuranceContractError,
        match="digest differs from the registered staging route contract",
    ):
        _report(resolved_scopes=scopes)


def test_strict_parser_rejects_extra_fields_and_derived_digest_tampering() -> None:
    payload = _payload()
    payload["schema_version"] = 6
    with pytest.raises(SuccessorAssuranceContractError, match="schema or truth state is invalid"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    payload.pop("planned_route_replacement_bindings_sha256")
    with pytest.raises(SuccessorAssuranceContractError, match="missing"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    payload["planned_route_replacement_bindings_sha256"] = "0" * 64
    with pytest.raises(SuccessorAssuranceContractError, match="derived fields differ"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    payload["unexpected"] = True
    with pytest.raises(SuccessorAssuranceContractError, match="unexpected"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    payload["transform_inventory_sha256"] = "0" * 64
    with pytest.raises(SuccessorAssuranceContractError, match="derived fields differ"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    payload["private_generation_receipt_sha256"] = "0" * 64
    with pytest.raises(SuccessorAssuranceContractError, match="derived fields differ"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    private = payload["update_private_generation"]
    assert isinstance(private, dict)
    private.pop("done_call_bindings_sha256")
    with pytest.raises(SuccessorAssuranceContractError, match="missing"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    private = payload["update_private_generation"]
    assert isinstance(private, dict)
    private["done_call_bindings_sha256"] = "0" * 64
    with pytest.raises(SuccessorAssuranceContractError, match="binding digest differs"):
        validate_successor_terminal_assurance_report(payload)


def test_every_schema_backed_transform_is_required_sorted_and_unique() -> None:
    payload = _payload()
    outputs = payload["transform_outputs"]
    assert isinstance(outputs, list)
    outputs.pop()
    payload["transform_output_count"] = len(outputs)
    payload["transform_inventory_sha256"] = canonical_sha256(outputs)
    with pytest.raises(
        SuccessorAssuranceContractError,
        match="does not exactly cover",
    ):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    outputs = payload["transform_outputs"]
    assert isinstance(outputs, list)
    outputs[0], outputs[1] = outputs[1], outputs[0]
    payload["transform_inventory_sha256"] = canonical_sha256(outputs)
    with pytest.raises(SuccessorAssuranceContractError, match="sorted"):
        validate_successor_terminal_assurance_report(payload)


def test_changed_no_change_and_typed_zero_must_exactly_close_requested_scopes() -> None:
    payload = _payload()
    coverage = payload["delta_coverage"]
    assert isinstance(coverage, dict)
    changed = coverage["changed_scope_sha256s"]
    no_change = coverage["no_change_scope_sha256s"]
    assert isinstance(changed, list)
    assert isinstance(no_change, list)
    no_change.append(changed[0])
    no_change.sort()
    coverage["no_change_scope_count"] = len(no_change)
    coverage["requested_scope_count"] = (
        coverage["changed_scope_count"]
        + coverage["no_change_scope_count"]
        + coverage["typed_zero_scope_count"]
    )
    body = dict(coverage)
    body.pop("coverage_sha256")
    coverage["coverage_sha256"] = canonical_sha256(body)
    payload["delta_coverage_sha256"] = coverage["coverage_sha256"]
    with pytest.raises(SuccessorAssuranceContractError, match="disjoint"):
        validate_successor_terminal_assurance_report(payload)


def test_full_public_resource_contract_is_exact_without_control_file_hash_cycle() -> None:
    report = _report()
    assert report.public_evidence.control_resources == (
        "assured-artifact-manifest.json",
        "terminal-assurance-report.json",
    )
    resource_ids = {item.resource_id for item in report.public_evidence.resources}
    assert "assured-artifact-manifest.json" not in resource_ids
    assert "terminal-assurance-report.json" not in resource_ids
    assert len(resource_ids) + len(report.public_evidence.control_resources) == len(
        expected_full_publication_resource_contract()
    )

    payload = _payload()
    public = payload["public_evidence"]
    assert isinstance(public, dict)
    resources = public["resources"]
    assert isinstance(resources, list)
    resources.pop()
    with pytest.raises(SuccessorAssuranceContractError, match="does not match"):
        validate_successor_terminal_assurance_report(payload)


def test_database_and_scan_evidence_fail_closed() -> None:
    report = _report()
    with pytest.raises(SuccessorAssuranceContractError, match="database evidence"):
        replace(
            report,
            database_evidence=replace(
                report.database_evidence,
                duckdb_sha256="0" * 64,
            ),
        )
    with pytest.raises(SuccessorAssuranceContractError, match="passed fail-on-error"):
        replace(report.scan_evidence, status="failed")
    with pytest.raises(SuccessorAssuranceContractError, match="zero-error"):
        replace(report.scan_evidence, error_count=1)


def test_provider_and_inherited_blocked_authority_cannot_drift() -> None:
    payload = _payload()
    provider = payload["provider_authority"]
    assert isinstance(provider, dict)
    provider["authority_sha256"] = "0" * 64
    with pytest.raises(SuccessorAssuranceContractError, match="provider authority"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    blocked = payload["contract_blocked_evidence"]
    assert isinstance(blocked, dict)
    blocked["unexpected"] = []
    with pytest.raises(SuccessorAssuranceContractError, match="contract-blocked"):
        validate_successor_terminal_assurance_report(payload)


def test_model_and_data_truth_and_private_call_reconciliation_are_mandatory() -> None:
    payload = _payload()
    payload["data_green"] = False
    with pytest.raises(SuccessorAssuranceContractError, match="truth state"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    private = payload["update_private_generation"]
    assert isinstance(private, dict)
    private["done_call_count"] = 1
    with pytest.raises(SuccessorAssuranceContractError, match="does not reconcile"):
        validate_successor_terminal_assurance_report(payload)

    payload = _payload()
    private = payload["update_private_generation"]
    assert isinstance(private, dict)
    roots = private["done_call_receipt_sha256s"]
    assert isinstance(roots, list)
    roots[0] = "8" * 64
    roots.sort()
    private["done_call_receipts_sha256"] = canonical_sha256(roots)
    with pytest.raises(SuccessorAssuranceContractError, match="logical-call roots differ"):
        validate_successor_terminal_assurance_report(payload)


def test_public_report_rejects_embedded_private_planning_bytes() -> None:
    payload = _payload()
    planning = payload["planning_evidence"]
    assert isinstance(planning, dict)
    private_manifest = _planning(_baseline())[0].planning_generation_manifest.to_dict()
    planning["planning_generation_manifest"] = private_manifest
    with pytest.raises(SuccessorAssuranceContractError, match="path-free planning identities"):
        validate_successor_terminal_assurance_report(payload)


def test_absolute_resource_paths_and_noncanonical_document_bytes_are_rejected() -> None:
    payload = _payload()
    public = payload["public_evidence"]
    assert isinstance(public, dict)
    resources = public["resources"]
    assert isinstance(resources, list)
    assert isinstance(resources[0], dict)
    resources[0]["resource_id"] = "/tmp/private.csv"
    with pytest.raises(SuccessorAssuranceContractError, match="absolute filesystem path"):
        validate_successor_terminal_assurance_report(payload)

    report = _report()
    pretty = (json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(SuccessorAssuranceContractError, match="bytes are not canonical"):
        validate_successor_terminal_assurance_report(pretty)


def test_successor_manifest_digest_is_supplied_only_after_report_validation() -> None:
    report = _report()
    with pytest.raises(SuccessorAssuranceContractError, match="lowercase SHA-256"):
        report.to_successor_assurance_identity(
            successor_assured_manifest_sha256="A" * 64,
            installed_public_tree_sha256="0" * 64,
        )
    with pytest.raises(SuccessorAssuranceContractError, match="installed_public_tree_sha256"):
        report.to_successor_assurance_identity(
            successor_assured_manifest_sha256="f" * 64,
            installed_public_tree_sha256="A" * 64,
        )


def _emit_manifest(
    report: SuccessorTerminalAssuranceReportV7 | None = None,
    *,
    resolved_scopes: tuple[RequestedRouteScope, ...] | None = None,
) -> tuple[Any, Any]:
    current = report or _report(resolved_scopes=resolved_scopes)
    return current, emit_successor_assurance_manifest(
        current,
        successor_assured_manifest_sha256="f" * 64,
        installed_public_tree_sha256="0" * 64,
    )


def test_emit_and_verify_bind_planning_generation_dispatch_and_one_to_many() -> None:
    report, manifest = _emit_manifest(
        resolved_scopes=(
            _scope("2", endpoint_name="schedule_int", parameter_marker="shared"),
            _scope("3", endpoint_name="schedule_int", parameter_marker="shared"),
            _scope("4", endpoint_name="schedule_int"),
        )
    )
    planning = report.planning_evidence
    execution_plan = planning.execution_plan
    verified = verify_successor_assurance_manifest(
        manifest.canonical_bytes,
        report=report,
        successor_assured_manifest_sha256="f" * 64,
        installed_public_tree_sha256="0" * 64,
        expected_planning_generation_manifest_sha256=(
            planning.planning_generation_manifest.identity_sha256
        ),
        expected_sealed_dispatch_inventory_sha256=(execution_plan.sealed_dispatch_inventory_sha256),
        expected_logical_call_bindings_sha256=(
            report.update_private_generation.done_call_bindings_sha256
        ),
    )

    assert verified == manifest
    assert verified.kind == SUCCESSOR_ASSURANCE_MANIFEST_KIND
    assert verified.digest_domain == SUCCESSOR_ASSURANCE_MANIFEST_DIGEST_DOMAIN
    assert verified.planning_generation_manifest_sha256 == (
        planning.planning_generation_manifest.identity_sha256
    )
    assert verified.planning_generation_id == execution_plan.planning_generation_id
    assert verified.planning_artifact_identity_sha256 == (
        execution_plan.planning_artifact_identity_sha256
    )
    assert verified.planning_manifest_sha256 == execution_plan.planning_manifest_sha256
    assert verified.sealed_dispatch_inventory_sha256 == (
        execution_plan.sealed_dispatch_inventory_sha256
    )
    assert verified.execution_plan_sha256 == report.execution_plan_sha256
    assert verified.logical_call_count == 2
    assert verified.route_receipt_count == 3
    assert verified.logical_calls[0].logical_call_receipt_sha256 == "5" * 64
    assert verified.logical_calls[0].result_route_ids == (
        "schedule_int:stg_schedule_int:0",
        "schedule_int:stg_schedule_int_weeks:1",
    )
    assert tuple(item.route_id for item in verified.logical_calls[0].route_receipts) == (
        "schedule_int:stg_schedule_int:0",
        "schedule_int:stg_schedule_int_weeks:1",
    )
    assert verified.logical_call_bindings_sha256 == (
        report.update_private_generation.done_call_bindings_sha256
    )
    assert verified.w2_database_authority == report.w2_database_authority
    assert verified.w2_database_authority_sha256 == report.w2_database_authority_sha256
    assert verified.w2_expected_call_count == report.w2_expected_call_count
    assert verified.w2_expected_call_inventory_sha256 == (report.w2_expected_call_inventory_sha256)
    assert verified.w2_database_authority_closed is True
    assert (
        report.to_successor_assurance_identity(
            successor_assured_manifest_sha256="f" * 64,
            installed_public_tree_sha256="0" * 64,
        )
        == verified.to_successor_assurance_identity()
    )
    assert verify_successor_assurance_manifest(manifest.to_dict()) == manifest


def test_manifest_w2_authority_cannot_be_omitted_or_cross_report_swapped() -> None:
    report, manifest = _emit_manifest()
    required_fields = (
        "w2_database_authority",
        "w2_database_authority_sha256",
        "w2_expected_call_count",
        "w2_expected_call_inventory_sha256",
        "w2_database_authority_closed",
    )
    for field_name in required_fields:
        payload = manifest.to_dict()
        payload.pop(field_name)
        with pytest.raises(SuccessorAssuranceContractError, match="fields are invalid"):
            verify_successor_assurance_manifest(payload)

    foreign_report = replace(
        report,
        w2_database_authority=_w2_database_authority(
            report.w2_expected_call_count,
            marker="foreign-manifest",
        ),
    )
    foreign_manifest = emit_successor_assurance_manifest(
        foreign_report,
        successor_assured_manifest_sha256="f" * 64,
        installed_public_tree_sha256="0" * 64,
    )
    assert verify_successor_assurance_manifest(foreign_manifest.to_dict()) == foreign_manifest
    with pytest.raises(
        SuccessorAssuranceContractError,
        match="does not match the emitted report authority",
    ):
        verify_successor_assurance_manifest(foreign_manifest.to_dict(), report=report)


def test_verify_rejects_planning_generation_or_dispatch_manifest_drift() -> None:
    _report_value, manifest = _emit_manifest()
    payload = manifest.to_dict()
    payload["planning_generation_manifest_sha256"] = "0" * 64
    with pytest.raises(SuccessorAssuranceContractError, match="derived fields differ"):
        verify_successor_assurance_manifest(payload)

    payload = manifest.to_dict()
    payload["sealed_dispatch_inventory_sha256"] = "0" * 64
    with pytest.raises(SuccessorAssuranceContractError, match="derived fields differ"):
        verify_successor_assurance_manifest(payload)

    with pytest.raises(
        SuccessorAssuranceContractError,
        match="planning_generation_manifest_sha256",
    ):
        verify_successor_assurance_manifest(
            manifest,
            expected_planning_generation_manifest_sha256="0" * 64,
        )
    with pytest.raises(
        SuccessorAssuranceContractError,
        match="sealed_dispatch_inventory_sha256",
    ):
        verify_successor_assurance_manifest(
            manifest,
            expected_sealed_dispatch_inventory_sha256="0" * 64,
        )


def test_verify_rejects_missing_or_split_one_to_many_route_receipts() -> None:
    _report_value, manifest = _emit_manifest(
        resolved_scopes=(
            _scope("2", endpoint_name="schedule_int", parameter_marker="shared"),
            _scope("3", endpoint_name="schedule_int", parameter_marker="shared"),
            _scope("4", endpoint_name="schedule_int"),
        )
    )
    payload = manifest.to_dict()
    first_call = payload["logical_calls"][0]
    dropped = first_call["route_receipts"].pop()
    first_call["result_route_ids"] = [
        route_id for route_id in first_call["result_route_ids"] if route_id != dropped["route_id"]
    ]
    with pytest.raises(SuccessorAssuranceContractError, match="W2 database authority"):
        verify_successor_assurance_manifest(payload)

    payload = manifest.to_dict()
    payload["logical_calls"][0]["route_receipts"].pop()
    with pytest.raises(
        SuccessorAssuranceContractError,
        match="do not exactly cover result routes",
    ):
        verify_successor_assurance_manifest(payload)

    payload = manifest.to_dict()
    payload["logical_calls"][1]["logical_call_receipt_sha256"] = payload["logical_calls"][0][
        "logical_call_receipt_sha256"
    ]
    with pytest.raises(SuccessorAssuranceContractError, match="duplicate logical-call roots"):
        verify_successor_assurance_manifest(payload)


def test_emit_rejects_report_that_is_not_validated_terminal_assurance() -> None:
    with pytest.raises(SuccessorAssuranceContractError, match="validated terminal report"):
        emit_successor_assurance_manifest(
            object(),  # type: ignore[arg-type]
            successor_assured_manifest_sha256="f" * 64,
            installed_public_tree_sha256="0" * 64,
        )
