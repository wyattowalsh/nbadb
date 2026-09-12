from __future__ import annotations

import asyncio
import hashlib
import json
import os
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pytest

import nbadb.orchestrate.successor_assurance_builder as assurance_builder_module
from nbadb.core.artifact_identity import (
    ASSURED_ARTIFACT_MANIFEST_NAME,
    build_assured_artifact_manifest,
)
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.orchestrate.successor_assurance import (
    SuccessorDatabaseEvidence,
    SuccessorScanEvidence,
    SuccessorTerminalAssuranceReportV7,
    validate_successor_terminal_assurance_report,
    verify_successor_assurance_manifest,
)
from nbadb.orchestrate.successor_assurance_builder import (
    ExactSuccessorAssuranceBuilder,
    SuccessorAssuranceBuilderError,
    validate_successor_baseline_controls,
)
from nbadb.orchestrate.successor_coordinator import SuccessorAssuranceBuildInput
from nbadb.orchestrate.successor_generation_store import SuccessorGenerationStore
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_publication_inventory import (
    SuccessorPublicationInventoryEvidence,
)
from nbadb.orchestrate.successor_scan_evidence import (
    SuccessorFullPublicationScanResult,
)
from nbadb.orchestrate.successor_transform_authority import TransformOutputAttestation
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    RequestedRouteScope,
    SuccessorGenerationState,
    SuccessorUpdateTransaction,
    canonical_sha256,
)
from tests.unit.orchestrate.test_successor_assurance import (
    _BLOCKED_EVIDENCE,
    _SOURCE_SHA,
    _build,
    _planning,
    _private_generation,
    _public,
    _report,
    _scope,
    _transforms,
    _w2_database_authority,
)

if TYPE_CHECKING:
    from pathlib import Path

_REPORT_NAME = "terminal-assurance-report.json"


class _Scanner:
    def __init__(self, result: SuccessorFullPublicationScanResult) -> None:
        self.result = result
        self.calls: list[tuple[Path, tuple[int, int] | None]] = []

    def __call__(
        self,
        public_root: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> SuccessorFullPublicationScanResult:
        self.calls.append((public_root, expected_root_identity))
        return self.result


class _Inventory:
    def __init__(self, result: SuccessorPublicationInventoryEvidence) -> None:
        self.result = result
        self.calls: list[tuple[Path, tuple[int, int] | None]] = []

    def __call__(
        self,
        public_root: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> SuccessorPublicationInventoryEvidence:
        self.calls.append((public_root, expected_root_identity))
        return self.result


class _PrivateResolver:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def verify(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return kwargs["expected_identity"]


def _harness(
    tmp_path: Path,
    *,
    report: SuccessorTerminalAssuranceReportV7 | None = None,
    candidate_root: Path | None = None,
    resolved_scopes: tuple[RequestedRouteScope, ...] | None = None,
) -> tuple[
    SuccessorAssuranceBuildInput,
    ExactSuccessorAssuranceBuilder,
    _Scanner,
    _Inventory,
]:
    report = report or _report(resolved_scopes=resolved_scopes)
    planning, _scopes = _planning(report.baseline, resolved_scopes=resolved_scopes)
    candidate_root = candidate_root or tmp_path / "candidate"
    public_root = candidate_root / "public"
    public_root.mkdir(parents=True, exist_ok=True)
    if not (public_root / "nba.duckdb").exists():
        (public_root / "nba.duckdb").write_bytes(b"candidate-duckdb")
    if not (public_root / "nba.sqlite").exists():
        (public_root / "nba.sqlite").write_bytes(b"candidate-sqlite")
    execution_tree = measure_installed_public_tree(public_root)
    transaction = SuccessorUpdateTransaction(
        state=SuccessorGenerationState.BUILT,
        generation=report.generation,
        baseline=report.baseline,
        intent=report.intent,
        build=report.build,
    )
    build_input = SuccessorAssuranceBuildInput(
        candidate_root=candidate_root,
        baseline=report.baseline,
        planning_evidence=planning,
        execution_plan=planning.execution_plan,
        planned_route_replacement_bindings_sha256=(
            report.planned_route_replacement_bindings_sha256
        ),
        transaction=transaction,
        update_private_generation=report.update_private_generation,
        transform_outputs=report.transform_outputs,
        execution_installed_public_tree_sha256=(execution_tree.installed_public_tree_sha256),
    )
    scan = SuccessorFullPublicationScanResult(
        database_sha256=report.database_evidence.duckdb_sha256,
        database_bytes=report.database_evidence.duckdb_bytes,
        tables_scanned=670,
        checks_run=1,
        w2_database_authority=report.w2_database_authority,
        findings=(),
    )
    scanner = _Scanner(scan)
    inventory = _Inventory(
        SuccessorPublicationInventoryEvidence(
            public_evidence=report.public_evidence,
            database_evidence=report.database_evidence,
            transform_outputs=tuple(
                TransformOutputAttestation(
                    table_name=item.table_name,
                    row_count=item.row_count,
                    schema_sha256=item.schema_sha256,
                    content_sha256=item.content_sha256,
                )
                for item in report.transform_outputs
            ),
        )
    )
    builder = ExactSuccessorAssuranceBuilder(
        chain_id=report.chain_id,
        contract_blocked_evidence=_BLOCKED_EVIDENCE,
        provider_authority=expected_nba_api_provider_authority(),
        scanner=scanner,
        inventory=inventory,
        installed_tree=measure_installed_public_tree,
        private_generation_resolver=_PrivateResolver(),
    )
    return build_input, builder, scanner, inventory


def _successor_report_for_baseline(
    baseline: BaselineAssuranceIdentity,
) -> SuccessorTerminalAssuranceReportV7:
    planning, scopes = _planning(baseline)
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


def _schema3_controls(
    public_root: Path,
) -> tuple[BaselineAssuranceIdentity, bytes, bytes]:
    provider = expected_nba_api_provider_authority()
    evidence = {"schema_version": 1, "contract_blocked_lanes": []}
    evidence_sha256 = canonical_sha256(evidence)
    chain_id = "full-initial-20260813"
    source_sha = "a" * 40
    coverage_fingerprint = "1" * 64
    checkpoint_database_sha256 = "8" * 64
    checkpoint_report = {
        "chain_id": chain_id,
        "source_sha": source_sha,
        "coverage_fingerprint": coverage_fingerprint,
        "artifact_name": f"full-extraction-checkpoint-{chain_id}-iter-1",
        "checkpoint_generation": 1,
        "database_sha256": checkpoint_database_sha256,
        "contract_blocked_lane_count": 0,
        "contract_blocked_evidence": evidence,
        "contract_blocked_evidence_sha256": evidence_sha256,
        "provider_authority": provider,
        "provider_authority_sha256": provider["authority_sha256"],
        "terminal_ready": True,
        "active_lane_count": 0,
        "run_id": "123456",
        "included_lane_ids": ["historical-season-2024"],
        "included_lane_coverage_hashes": {"historical-season-2024": "c" * 64},
        "included_run_ids": ["123456"],
        "complete_lane_count": 1,
        "manifest_lane_count": 1,
        "skipped_lane_count": 0,
        "missing_lane_ids": [],
        "skipped_complete_lane_ids": [],
        "current_lane_attestation_failures": [],
        "workload_contract_errors": [],
    }
    checkpoint_report_sha256 = hashlib.sha256(
        json.dumps(checkpoint_report, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report_payload = {
        "schema_version": 3,
        "chain_id": chain_id,
        "source_sha": source_sha,
        "coverage_fingerprint": coverage_fingerprint,
        "checkpoint_artifact_name": checkpoint_report["artifact_name"],
        "checkpoint_generation": 1,
        "checkpoint_database_sha256": checkpoint_database_sha256,
        "checkpoint_report_sha256": checkpoint_report_sha256,
        "checkpoint_report": checkpoint_report,
        "contract_blocked_lane_count": 0,
        "contract_blocked_evidence": evidence,
        "contract_blocked_evidence_sha256": evidence_sha256,
        "provider_authority": provider,
        "provider_authority_sha256": provider["authority_sha256"],
    }
    report_bytes = (json.dumps(report_payload, indent=2, sort_keys=True) + "\n").encode()
    (public_root / _REPORT_NAME).write_bytes(report_bytes)
    build_assured_artifact_manifest(
        public_root,
        chain_id=chain_id,
        source_sha=source_sha,
        coverage_fingerprint=coverage_fingerprint,
    )
    manifest_bytes = (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).read_bytes()
    installed_tree = measure_installed_public_tree(public_root)
    baseline = BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=238,
        chain_id=chain_id,
        source_sha=source_sha,
        coverage_fingerprint=coverage_fingerprint,
        data_tree_fingerprint=json.loads(manifest_bytes)["data_tree_fingerprint"],
        remote_bundle_fingerprint_sha256="3" * 64,
        installed_public_tree_sha256=installed_tree.installed_public_tree_sha256,
        installed_public_tree_bytes=installed_tree.byte_count,
        assured_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        terminal_assurance_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        private_baseline_receipt_sha256="7" * 64,
        checkpoint_database_sha256=checkpoint_database_sha256,
        checkpoint_report_sha256=checkpoint_report_sha256,
        contract_blocked_evidence_sha256=evidence_sha256,
        provider_authority_sha256=str(provider["authority_sha256"]),
    )
    return baseline, report_bytes, manifest_bytes


def _inherited_successor_harness(
    tmp_path: Path,
) -> tuple[
    SuccessorAssuranceBuildInput,
    ExactSuccessorAssuranceBuilder,
    _Scanner,
    _Inventory,
    bytes,
    bytes,
]:
    baseline_public = tmp_path / "baseline-public"
    baseline_public.mkdir(parents=True)
    (baseline_public / "nba.duckdb").write_bytes(b"candidate-duckdb")
    (baseline_public / "nba.sqlite").write_bytes(b"candidate-sqlite")
    prior_report = _report()
    prior_report_bytes = prior_report.canonical_bytes
    (baseline_public / _REPORT_NAME).write_bytes(prior_report_bytes)
    build_assured_artifact_manifest(
        baseline_public,
        chain_id=prior_report.chain_id,
        source_sha=prior_report.source_sha,
        coverage_fingerprint=prior_report.coverage_fingerprint,
        sentinel_excluded_paths=frozenset({_REPORT_NAME}),
    )
    prior_manifest_bytes = (baseline_public / ASSURED_ARTIFACT_MANIFEST_NAME).read_bytes()
    baseline_tree = measure_installed_public_tree(baseline_public)
    baseline = BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=239,
        chain_id=prior_report.chain_id,
        source_sha=prior_report.source_sha,
        coverage_fingerprint=prior_report.coverage_fingerprint,
        data_tree_fingerprint=json.loads(prior_manifest_bytes)["data_tree_fingerprint"],
        remote_bundle_fingerprint_sha256="a" * 64,
        installed_public_tree_sha256=baseline_tree.installed_public_tree_sha256,
        installed_public_tree_bytes=baseline_tree.byte_count,
        assured_manifest_sha256=hashlib.sha256(prior_manifest_bytes).hexdigest(),
        terminal_assurance_report_sha256=hashlib.sha256(prior_report_bytes).hexdigest(),
        private_baseline_receipt_sha256="b" * 64,
        checkpoint_database_sha256=prior_report.database_evidence.duckdb_sha256,
        checkpoint_report_sha256=prior_report.content_sha256,
        contract_blocked_evidence_sha256=prior_report.contract_blocked_evidence_sha256,
        provider_authority_sha256=prior_report.provider_authority_sha256,
    )
    report = _successor_report_for_baseline(baseline)
    built_transaction = SuccessorUpdateTransaction(
        state=SuccessorGenerationState.BUILT,
        generation=report.generation,
        baseline=report.baseline,
        intent=report.intent,
        build=report.build,
    )
    candidate_transaction = SuccessorUpdateTransaction.candidate(
        generation=report.generation,
        baseline=report.baseline,
        intent=report.intent,
    )
    store = SuccessorGenerationStore(tmp_path / "store")
    candidate_root = store.prepare_candidate_from_baseline(
        baseline_public,
        candidate_transaction,
        candidate_max_bytes=8 * 1024 * 1024,
        private_generation_estimated_bytes=4096,
        rollback_reserve_bytes=4096,
        minimum_free_bytes=4096,
        monotonic_now_seconds=100.0,
        monotonic_deadline_seconds=200.0,
        minimum_deadline_headroom_seconds=30.0,
    )
    (candidate_root / "public" / "nba.sqlite").write_bytes(b"changed-successor-sqlite")
    execution_tree = measure_installed_public_tree(candidate_root / "public")
    result = _harness(tmp_path, report=report, candidate_root=candidate_root)
    build_input, builder, scanner, inventory = result
    build_input = replace(
        build_input,
        transaction=built_transaction,
        execution_installed_public_tree_sha256=execution_tree.installed_public_tree_sha256,
    )
    return (
        build_input,
        builder,
        scanner,
        inventory,
        prior_report_bytes,
        prior_manifest_bytes,
    )


def _schema3_inherited_harness(
    tmp_path: Path,
) -> tuple[SuccessorAssuranceBuildInput, ExactSuccessorAssuranceBuilder, bytes]:
    baseline_public = tmp_path / "baseline-public"
    baseline_public.mkdir(parents=True)
    (baseline_public / "nba.duckdb").write_bytes(b"candidate-duckdb")
    (baseline_public / "nba.sqlite").write_bytes(b"candidate-sqlite")
    baseline, old_report, _old_manifest = _schema3_controls(baseline_public)
    report = _successor_report_for_baseline(baseline)
    candidate_transaction = SuccessorUpdateTransaction.candidate(
        generation=report.generation,
        baseline=report.baseline,
        intent=report.intent,
    )
    store = SuccessorGenerationStore(tmp_path / "store")
    candidate_root = store.prepare_candidate_from_baseline(
        baseline_public,
        candidate_transaction,
        candidate_max_bytes=8 * 1024 * 1024,
        private_generation_estimated_bytes=4096,
        rollback_reserve_bytes=4096,
        minimum_free_bytes=4096,
        monotonic_now_seconds=100.0,
        monotonic_deadline_seconds=200.0,
        minimum_deadline_headroom_seconds=30.0,
    )
    (candidate_root / "public" / "nba.sqlite").write_bytes(b"changed-schema3-successor")
    execution_tree = measure_installed_public_tree(candidate_root / "public")
    build_input, builder, _scanner, _inventory = _harness(
        tmp_path,
        report=report,
        candidate_root=candidate_root,
    )
    return (
        replace(
            build_input,
            execution_installed_public_tree_sha256=(execution_tree.installed_public_tree_sha256),
        ),
        builder,
        old_report,
    )


def _run(
    builder: ExactSuccessorAssuranceBuilder,
    build_input: SuccessorAssuranceBuildInput,
) -> Any:
    return asyncio.run(builder(build_input))


def test_fresh_and_reentered_assurance_are_byte_identical_and_root_bound(
    tmp_path: Path,
) -> None:
    build_input, builder, scanner, inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"
    expected_root = public_root.stat().st_dev, public_root.stat().st_ino

    first = _run(builder, build_input)
    report_bytes = (public_root / _REPORT_NAME).read_bytes()
    manifest_bytes = (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).read_bytes()
    second = _run(builder, build_input)

    assert second == first
    assert (public_root / _REPORT_NAME).read_bytes() == report_bytes
    assert (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).read_bytes() == manifest_bytes
    assert validate_successor_terminal_assurance_report(report_bytes).content_sha256 == (
        first.successor_validation_report_sha256
    )
    assert len(scanner.calls) == 4
    assert len(inventory.calls) == 4
    resolver = builder.private_generation_resolver
    assert isinstance(resolver, _PrivateResolver)
    assert len(resolver.calls) == 2
    assert all(call == (public_root, expected_root) for call in scanner.calls)
    assert all(call == (public_root, expected_root) for call in inventory.calls)
    assert measure_installed_public_tree(public_root).installed_public_tree_sha256 == (
        first.installed_public_tree_sha256
    )


def test_builder_emits_and_verifies_planning_dispatch_and_one_to_many_authority(
    tmp_path: Path,
) -> None:
    resolved_scopes = (
        _scope("2", endpoint_name="schedule_int", parameter_marker="shared"),
        _scope("3", endpoint_name="schedule_int", parameter_marker="shared"),
        _scope("4", endpoint_name="schedule_int"),
    )
    build_input, builder, scanner, _inventory = _harness(
        tmp_path,
        report=_report(resolved_scopes=resolved_scopes),
        resolved_scopes=resolved_scopes,
    )
    public_root = build_input.candidate_root / "public"

    identity = _run(builder, build_input)
    report = validate_successor_terminal_assurance_report((public_root / _REPORT_NAME).read_bytes())
    planning = build_input.planning_evidence
    verified = verify_successor_assurance_manifest(
        report.to_successor_assurance_manifest(
            successor_assured_manifest_sha256=identity.successor_assured_manifest_sha256,
            installed_public_tree_sha256=identity.installed_public_tree_sha256,
        ).canonical_bytes,
        report=report,
        successor_assured_manifest_sha256=identity.successor_assured_manifest_sha256,
        installed_public_tree_sha256=identity.installed_public_tree_sha256,
        expected_planning_generation_manifest_sha256=(
            planning.planning_generation_manifest.identity_sha256
        ),
        expected_sealed_dispatch_inventory_sha256=(
            planning.execution_plan.sealed_dispatch_inventory_sha256
        ),
        expected_logical_call_bindings_sha256=(
            build_input.update_private_generation.done_call_bindings_sha256
        ),
    )

    assert verified.to_successor_assurance_identity() == identity
    assert verified.planning_generation_manifest_sha256 == (
        planning.planning_generation_manifest.identity_sha256
    )
    assert verified.sealed_dispatch_inventory_sha256 == (
        planning.execution_plan.sealed_dispatch_inventory_sha256
    )
    assert verified.logical_call_count == len(
        build_input.update_private_generation.done_call_receipt_sha256s
    )
    assert build_input.transaction.build is not None
    assert verified.route_receipt_count == len(
        build_input.transaction.build.observed_delta_receipts
    )
    assert verified.logical_call_count < verified.route_receipt_count
    assert report.w2_database_authority == scanner.result.w2_database_authority
    assert verified.w2_database_authority == scanner.result.w2_database_authority
    assert verified.w2_database_authority_sha256 == (
        scanner.result.w2_database_authority.receipt_sha256
    )
    assert verified.w2_expected_call_count == verified.logical_call_count
    assert verified.w2_database_authority_closed is True


def test_builder_reentry_rejects_a_swapped_scan_w2_receipt(tmp_path: Path) -> None:
    build_input, builder, scanner, _inventory = _harness(tmp_path)
    _run(builder, build_input)

    scanner.result = replace(
        scanner.result,
        w2_database_authority=_w2_database_authority(
            scanner.result.w2_database_authority.w2_required_logical_call_count,
            marker="swapped-builder-reentry",
        ),
    )
    with pytest.raises(
        SuccessorAssuranceBuilderError,
        match="existing terminal assurance report differs",
    ):
        _run(builder, build_input)


def test_report_only_resume_rebuilds_the_exact_manifest(tmp_path: Path) -> None:
    build_input, builder, _scanner, _inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"
    first = _run(builder, build_input)
    report_bytes = (public_root / _REPORT_NAME).read_bytes()
    (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).unlink()

    resumed = _run(builder, build_input)

    assert (public_root / _REPORT_NAME).read_bytes() == report_bytes
    assert resumed == first


@pytest.mark.parametrize(
    "crash_state",
    ["old_both", "old_report_only", "old_controls_unlinked"],
)
def test_real_copied_current_rolls_authenticated_controls_and_recovers_crashes(
    tmp_path: Path,
    crash_state: str,
) -> None:
    (
        build_input,
        builder,
        _scanner,
        _inventory,
        old_report,
        old_manifest,
    ) = _inherited_successor_harness(tmp_path)
    candidate_root = build_input.candidate_root
    public_root = candidate_root / "public"
    receipt_name = assurance_builder_module._rollover_receipt_name(
        candidate_name=candidate_root.name,
        generation_identity_sha256=build_input.transaction.generation_identity_sha256,
    )
    receipt_path = candidate_root.parent / receipt_name

    if crash_state != "old_both":
        candidate_descriptor, candidate_stat = assurance_builder_module._open_directory(
            candidate_root,
            label="test candidate",
        )
        staging_descriptor, _staging_stat = assurance_builder_module._open_directory(
            candidate_root.parent,
            label="test staging",
        )
        public_descriptor = os.open(
            "public",
            assurance_builder_module._DIRECTORY_FLAGS,
            dir_fd=candidate_descriptor,
        )
        try:
            public_stat = os.fstat(public_descriptor)
            data_tree = assurance_builder_module._without_controls(
                measure_installed_public_tree(public_root)
            )
            receipt = assurance_builder_module._rollover_receipt_bytes(
                build_input=build_input,
                candidate_name=candidate_root.name,
                candidate_identity=(candidate_stat.st_dev, candidate_stat.st_ino),
                public_identity=(public_stat.st_dev, public_stat.st_ino),
                data_tree=data_tree,
                report_bytes=old_report,
                manifest_bytes=old_manifest,
            )
            assurance_builder_module._publish_rollover_receipt_no_replace(
                staging_descriptor,
                name=receipt_name,
                encoded=receipt,
            )
            os.unlink(ASSURED_ARTIFACT_MANIFEST_NAME, dir_fd=public_descriptor)
            os.fsync(public_descriptor)
            if crash_state == "old_controls_unlinked":
                os.unlink(_REPORT_NAME, dir_fd=public_descriptor)
                os.fsync(public_descriptor)
        finally:
            os.close(public_descriptor)
            os.close(candidate_descriptor)
            os.close(staging_descriptor)

    identity = _run(builder, build_input)
    new_report = (public_root / _REPORT_NAME).read_bytes()
    new_manifest = (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).read_bytes()

    assert new_report != old_report
    assert new_manifest != old_manifest
    assert not receipt_path.exists()
    assert validate_successor_terminal_assurance_report(new_report).content_sha256 == (
        identity.successor_validation_report_sha256
    )
    assert _run(builder, build_input) == identity
    assert (public_root / _REPORT_NAME).read_bytes() == new_report
    assert (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).read_bytes() == new_manifest


def test_rollover_durable_closure_rejects_data_mutation_with_recomputed_controls(
    tmp_path: Path,
) -> None:
    build_input, builder, _scanner, inventory, _old_report, _old_manifest = (
        _inherited_successor_harness(tmp_path)
    )
    public_root = build_input.candidate_root / "public"
    _run(builder, build_input)

    report_path = public_root / _REPORT_NAME
    manifest_path = public_root / ASSURED_ARTIFACT_MANIFEST_NAME
    report_path.unlink()
    manifest_path.unlink()
    (public_root / "nba.sqlite").write_bytes(b"mutated-after-rollover-closure")
    mutated_public = replace(
        inventory.result.public_evidence,
        resources=tuple(
            replace(
                resource,
                bytes=len(b"mutated-after-rollover-closure"),
                sha256=hashlib.sha256(b"mutated-after-rollover-closure").hexdigest(),
            )
            if resource.resource_id == "nba.sqlite"
            else resource
            for resource in inventory.result.public_evidence.resources
        ),
    )
    mutated_sqlite = mutated_public.resource("nba.sqlite")
    mutated_database = replace(
        inventory.result.database_evidence,
        sqlite_sha256=mutated_sqlite.sha256,
        sqlite_bytes=mutated_sqlite.bytes,
    )
    mutated_report = SuccessorTerminalAssuranceReportV7.create(
        chain_id=builder.chain_id,
        source_sha=build_input.transaction.intent.source_sha,
        coverage_fingerprint=build_input.baseline.coverage_fingerprint,
        generation=build_input.transaction.generation,
        baseline=build_input.baseline,
        planning_evidence=build_input.planning_evidence,
        intent=build_input.transaction.intent,
        build=build_input.transaction.build,
        update_private_generation=build_input.update_private_generation,
        transform_outputs=build_input.transform_outputs,
        scan_evidence=_report().scan_evidence,
        public_evidence=mutated_public,
        database_evidence=mutated_database,
        w2_database_authority=_report().w2_database_authority,
        contract_blocked_evidence=_BLOCKED_EVIDENCE,
        provider_authority=expected_nba_api_provider_authority(),
    )
    report_path.write_bytes(mutated_report.canonical_bytes)
    build_assured_artifact_manifest(
        public_root,
        chain_id=mutated_report.chain_id,
        source_sha=mutated_report.source_sha,
        coverage_fingerprint=mutated_report.coverage_fingerprint,
        sentinel_excluded_paths=frozenset({_REPORT_NAME}),
    )

    with pytest.raises(SuccessorAssuranceBuilderError, match="rollover.*closure"):
        _run(builder, build_input)


def test_schema3_copied_current_rolls_changed_data_and_rejects_closure_drift(
    tmp_path: Path,
) -> None:
    build_input, builder, old_report = _schema3_inherited_harness(tmp_path / "valid")
    public_root = build_input.candidate_root / "public"

    identity = _run(builder, build_input)

    assert (public_root / _REPORT_NAME).read_bytes() != old_report
    assert not any(
        path.name.startswith(".successor-assurance-rollover-")
        for path in build_input.candidate_root.parent.iterdir()
    )
    assert (
        identity.successor_validation_report_sha256
        == hashlib.sha256((public_root / _REPORT_NAME).read_bytes()).hexdigest()
    )

    for mutation in ("unknown_field", "closure_drift"):
        forged_input, forged_builder, forged_report = _schema3_inherited_harness(
            tmp_path / mutation
        )
        forged_public = forged_input.candidate_root / "public"
        payload = json.loads(forged_report)
        if mutation == "unknown_field":
            payload["foreign"] = "authority"
        else:
            payload["checkpoint_report"]["complete_lane_count"] = 0
            payload["checkpoint_report_sha256"] = hashlib.sha256(
                json.dumps(
                    payload["checkpoint_report"],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        tampered = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
        (forged_public / _REPORT_NAME).write_bytes(tampered)
        baseline = replace(
            forged_input.baseline,
            terminal_assurance_report_sha256=hashlib.sha256(tampered).hexdigest(),
            checkpoint_report_sha256=payload["checkpoint_report_sha256"],
        )
        report = _successor_report_for_baseline(baseline)
        planning, _scopes = _planning(baseline)
        transaction = SuccessorUpdateTransaction(
            state=SuccessorGenerationState.BUILT,
            generation=report.generation,
            baseline=baseline,
            intent=report.intent,
            build=report.build,
        )
        tampered_tree = measure_installed_public_tree(forged_public)
        forged_input = SuccessorAssuranceBuildInput(
            candidate_root=forged_input.candidate_root,
            baseline=baseline,
            planning_evidence=planning,
            execution_plan=planning.execution_plan,
            planned_route_replacement_bindings_sha256=(
                report.planned_route_replacement_bindings_sha256
            ),
            transaction=transaction,
            update_private_generation=report.update_private_generation,
            transform_outputs=report.transform_outputs,
            execution_installed_public_tree_sha256=(tampered_tree.installed_public_tree_sha256),
        )
        forged_builder = replace(
            forged_builder,
            private_generation_resolver=_PrivateResolver(),
        )
        with pytest.raises(SuccessorAssuranceBuilderError):
            _run(forged_builder, forged_input)
        assert (forged_public / _REPORT_NAME).read_bytes() == tampered


def test_public_baseline_control_validator_accepts_exact_v7_and_v3_bytes(
    tmp_path: Path,
) -> None:
    v7_input, _builder, _scanner, _inventory, v7_report, v7_manifest = _inherited_successor_harness(
        tmp_path / "v7"
    )
    validate_successor_baseline_controls(
        baseline=v7_input.baseline,
        terminal_assurance_report_bytes=v7_report,
        assured_artifact_manifest_bytes=v7_manifest,
    )

    schema3_root = tmp_path / "schema3"
    schema3_root.mkdir()
    schema3_baseline, schema3_report, schema3_manifest = _schema3_controls(schema3_root)
    validate_successor_baseline_controls(
        baseline=schema3_baseline,
        terminal_assurance_report_bytes=schema3_report,
        assured_artifact_manifest_bytes=schema3_manifest,
    )


@pytest.mark.parametrize("mutation", ["report", "manifest"])
def test_public_baseline_control_validator_rejects_foreign_bytes(
    tmp_path: Path,
    mutation: str,
) -> None:
    build_input, _builder, _scanner, _inventory, report, manifest = _inherited_successor_harness(
        tmp_path
    )
    with pytest.raises(SuccessorAssuranceBuilderError):
        validate_successor_baseline_controls(
            baseline=build_input.baseline,
            terminal_assurance_report_bytes=(b"foreign\n" if mutation == "report" else report),
            assured_artifact_manifest_bytes=(b"foreign\n" if mutation == "manifest" else manifest),
        )


@pytest.mark.parametrize(
    ("authority", "replacement"),
    [
        ("manifest", "same"),
        ("manifest", "foreign"),
        ("report", "same"),
        ("report", "foreign"),
        ("receipt", "same"),
        ("receipt", "foreign"),
    ],
)
def test_rollover_retirement_preserves_admitted_and_racing_authorities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority: str,
    replacement: str,
) -> None:
    build_input, builder, _scanner, _inventory, old_report, old_manifest = (
        _inherited_successor_harness(tmp_path)
    )
    candidate_root = build_input.candidate_root
    if authority == "manifest":
        authority_name = ASSURED_ARTIFACT_MANIFEST_NAME
        authority_path = candidate_root / "public" / authority_name
        admitted = old_manifest
    elif authority == "report":
        authority_name = _REPORT_NAME
        authority_path = candidate_root / "public" / authority_name
        admitted = old_report
    else:
        authority_name = assurance_builder_module._rollover_receipt_name(
            candidate_name=candidate_root.name,
            generation_identity_sha256=build_input.transaction.generation_identity_sha256,
        )
        authority_path = candidate_root.parent / authority_name
        admitted = b""
    displaced = candidate_root.parent / f"displaced-{authority}-{replacement}"
    replacement_bytes = b"foreign-authority\n"
    original_rename = assurance_builder_module._rename_no_replace
    raced = False

    def _race_at_native_rename(
        source_descriptor: int,
        source_name: str,
        target_descriptor: int,
        target_name: str,
    ) -> None:
        nonlocal admitted, raced, replacement_bytes
        if source_name == authority_name and not raced:
            admitted = authority_path.read_bytes()
            if replacement == "same":
                replacement_bytes = admitted
            authority_path.rename(displaced)
            authority_path.write_bytes(replacement_bytes)
            if authority == "receipt":
                authority_path.chmod(0o600)
            raced = True
        original_rename(
            source_descriptor,
            source_name,
            target_descriptor,
            target_name,
        )

    monkeypatch.setattr(assurance_builder_module, "_rename_no_replace", _race_at_native_rename)

    with pytest.raises(SuccessorAssuranceBuilderError, match="changed or was replaced"):
        _run(builder, build_input)
    assert raced is True
    assert authority_path.read_bytes() == replacement_bytes
    assert displaced.read_bytes() == admitted


@pytest.mark.parametrize("mutation", ["deleted", "foreign"])
def test_receipt_retirement_revalidates_durable_closure_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    build_input, builder, _scanner, _inventory, _old_report, _old_manifest = (
        _inherited_successor_harness(tmp_path)
    )
    candidate_root = build_input.candidate_root
    closure_name = assurance_builder_module._rollover_closure_name(
        candidate_name=candidate_root.name,
        generation_identity_sha256=build_input.transaction.generation_identity_sha256,
    )
    closure_path = candidate_root.parent / closure_name
    original_retire = assurance_builder_module._retire_rollover_receipt_if_exact

    def _tamper_after_receipt_retirement(*args: Any, **kwargs: Any) -> None:
        original_retire(*args, **kwargs)
        closure_path.unlink()
        if mutation == "foreign":
            closure_path.write_bytes(b"foreign-closure\n")
            closure_path.chmod(0o600)

    monkeypatch.setattr(
        assurance_builder_module,
        "_retire_rollover_receipt_if_exact",
        _tamper_after_receipt_retirement,
    )

    with pytest.raises(SuccessorAssuranceBuilderError, match="rollover closure changed"):
        _run(builder, build_input)
    if mutation == "deleted":
        assert not closure_path.exists()
    else:
        assert closure_path.read_bytes() == b"foreign-closure\n"

    monkeypatch.setattr(
        assurance_builder_module,
        "_retire_rollover_receipt_if_exact",
        original_retire,
    )
    with pytest.raises(SuccessorAssuranceBuilderError, match="rollover.*closure"):
        _run(builder, build_input)


@pytest.mark.parametrize("replacement", ["same", "foreign"])
def test_receipt_recreation_after_retirement_fails_first_call_without_healing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    build_input, builder, _scanner, _inventory, _old_report, _old_manifest = (
        _inherited_successor_harness(tmp_path)
    )
    candidate_root = build_input.candidate_root
    receipt_name = assurance_builder_module._rollover_receipt_name(
        candidate_name=candidate_root.name,
        generation_identity_sha256=build_input.transaction.generation_identity_sha256,
    )
    receipt_path = candidate_root.parent / receipt_name
    original_retire = assurance_builder_module._retire_rollover_receipt_if_exact
    injected = b""

    def _recreate_after_receipt_retirement(*args: Any, **kwargs: Any) -> None:
        nonlocal injected
        original_retire(*args, **kwargs)
        injected = kwargs["expected"] if replacement == "same" else b"foreign-receipt\n"
        receipt_path.write_bytes(injected)
        receipt_path.chmod(0o600)

    monkeypatch.setattr(
        assurance_builder_module,
        "_retire_rollover_receipt_if_exact",
        _recreate_after_receipt_retirement,
    )

    with pytest.raises(SuccessorAssuranceBuilderError, match="receipt absence"):
        _run(builder, build_input)
    assert receipt_path.read_bytes() == injected


@pytest.mark.parametrize(
    "mutation",
    [
        "closure_deleted",
        "closure_same",
        "closure_foreign",
        "report_same",
        "report_foreign",
        "manifest_same",
        "manifest_foreign",
        "data_same",
        "data_foreign",
    ],
)
def test_final_root_check_mutation_fails_first_call_and_preserves_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    build_input, builder, _scanner, _inventory, _old_report, _old_manifest = (
        _inherited_successor_harness(tmp_path)
    )
    candidate_root = build_input.candidate_root
    public_root = candidate_root / "public"
    closure_name = assurance_builder_module._rollover_closure_name(
        candidate_name=candidate_root.name,
        generation_identity_sha256=build_input.transaction.generation_identity_sha256,
    )
    closure_path = candidate_root.parent / closure_name
    report_path = public_root / _REPORT_NAME
    manifest_path = public_root / ASSURED_ARTIFACT_MANIFEST_NAME
    data_path = public_root / "nba.sqlite"
    original_require = assurance_builder_module._require_directory_identity
    injected = False
    preserved: bytes | None = None

    def _mutate_at_final_public_root(*args: Any, **kwargs: Any) -> None:
        nonlocal injected, preserved
        original_require(*args, **kwargs)
        if (
            injected
            or kwargs.get("label") != "successor public root"
            or not closure_path.exists()
            or not report_path.exists()
            or not manifest_path.exists()
        ):
            return
        injected = True
        if mutation.startswith("closure_"):
            admitted = closure_path.read_bytes()
            if mutation == "closure_deleted":
                closure_path.unlink()
                return
            preserved = (
                admitted if mutation == "closure_same" else b"foreign-closure-at-final-root\n"
            )
            closure_path.write_bytes(preserved)
            closure_path.chmod(0o600)
            return
        authority_path = {
            "report": report_path,
            "manifest": manifest_path,
            "data": data_path,
        }[mutation.split("_", 1)[0]]
        admitted = authority_path.read_bytes()
        preserved = admitted if mutation.endswith("_same") else b"foreign-final-authority\n"
        authority_path.write_bytes(preserved)

    monkeypatch.setattr(
        assurance_builder_module,
        "_require_directory_identity",
        _mutate_at_final_public_root,
    )

    with pytest.raises(SuccessorAssuranceBuilderError):
        _run(builder, build_input)
    assert injected is True
    if mutation == "closure_deleted":
        assert not closure_path.exists()
    elif mutation.startswith("closure_"):
        assert closure_path.read_bytes() == preserved
    else:
        authority_path = {
            "report": report_path,
            "manifest": manifest_path,
            "data": data_path,
        }[mutation.split("_", 1)[0]]
        assert authority_path.read_bytes() == preserved


@pytest.mark.parametrize("replacement", ["same", "foreign"])
def test_receipt_recreation_after_final_absence_fails_and_preserves_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    build_input, builder, _scanner, _inventory, _old_report, _old_manifest = (
        _inherited_successor_harness(tmp_path)
    )
    candidate_root = build_input.candidate_root
    receipt_name = assurance_builder_module._rollover_receipt_name(
        candidate_name=candidate_root.name,
        generation_identity_sha256=build_input.transaction.generation_identity_sha256,
    )
    closure_name = assurance_builder_module._rollover_closure_name(
        candidate_name=candidate_root.name,
        generation_identity_sha256=build_input.transaction.generation_identity_sha256,
    )
    receipt_path = candidate_root.parent / receipt_name
    closure_path = candidate_root.parent / closure_name
    original_require = assurance_builder_module._require_directory_identity
    original_read = assurance_builder_module._read_optional_rollover_receipt
    armed = False
    admitted = b""
    injected = b""

    def _arm_after_final_root_check(*args: Any, **kwargs: Any) -> None:
        nonlocal armed
        original_require(*args, **kwargs)
        if kwargs.get("label") == "successor assurance staging root" and closure_path.exists():
            armed = True

    def _recreate_after_observed_absence(*args: Any, **kwargs: Any) -> Any:
        nonlocal admitted, injected
        observed = original_read(*args, **kwargs)
        if observed is not None:
            admitted = observed[0]
        elif armed and not injected:
            injected = admitted if replacement == "same" else b"foreign-final-receipt\n"
            receipt_path.write_bytes(injected)
            receipt_path.chmod(0o600)
        return observed

    monkeypatch.setattr(
        assurance_builder_module,
        "_require_directory_identity",
        _arm_after_final_root_check,
    )
    monkeypatch.setattr(
        assurance_builder_module,
        "_read_optional_rollover_receipt",
        _recreate_after_observed_absence,
    )

    with pytest.raises(SuccessorAssuranceBuilderError, match="receipt absence"):
        _run(builder, build_input)
    assert armed is True
    assert injected
    assert receipt_path.read_bytes() == injected


def test_rollover_rejects_foreign_mixed_and_noncanonical_inherited_controls(
    tmp_path: Path,
) -> None:
    for mutation in ("manifest_only", "mixed", "noncanonical_report"):
        (
            build_input,
            builder,
            scanner,
            inventory,
            old_report,
            _old_manifest,
        ) = _inherited_successor_harness(tmp_path / mutation)
        public_root = build_input.candidate_root / "public"
        report_path = public_root / _REPORT_NAME
        manifest_path = public_root / ASSURED_ARTIFACT_MANIFEST_NAME
        if mutation == "manifest_only":
            report_path.unlink()
        elif mutation == "mixed":
            report_path.write_bytes(b"foreign-report\n")
        else:
            payload = json.loads(old_report)
            tampered = json.dumps(payload, indent=1, sort_keys=True).encode() + b"\n"
            report_path.write_bytes(tampered)
            baseline = replace(
                build_input.baseline,
                terminal_assurance_report_sha256=hashlib.sha256(tampered).hexdigest(),
            )
            report = _successor_report_for_baseline(baseline)
            planning, _scopes = _planning(baseline)
            transaction = SuccessorUpdateTransaction(
                state=SuccessorGenerationState.BUILT,
                generation=report.generation,
                baseline=baseline,
                intent=report.intent,
                build=report.build,
            )
            build_input = SuccessorAssuranceBuildInput(
                candidate_root=build_input.candidate_root,
                baseline=baseline,
                planning_evidence=planning,
                execution_plan=planning.execution_plan,
                planned_route_replacement_bindings_sha256=(
                    report.planned_route_replacement_bindings_sha256
                ),
                transaction=transaction,
                update_private_generation=report.update_private_generation,
                transform_outputs=report.transform_outputs,
                execution_installed_public_tree_sha256=(
                    measure_installed_public_tree(public_root).installed_public_tree_sha256
                ),
            )
            builder = replace(
                builder,
                scanner=scanner,
                inventory=inventory,
                private_generation_resolver=_PrivateResolver(),
            )

        with pytest.raises(SuccessorAssuranceBuilderError):
            _run(builder, build_input)
        if mutation == "manifest_only":
            assert not report_path.exists()
        elif mutation == "mixed":
            assert report_path.read_bytes() == b"foreign-report\n"
        else:
            assert report_path.read_bytes() == tampered
        assert manifest_path.exists()


@pytest.mark.parametrize("staging_state", ["partial", "complete", "linked"])
def test_control_publication_recovers_exact_reserved_staging_state(
    tmp_path: Path,
    staging_state: str,
) -> None:
    build_input, builder, _scanner, _inventory = _harness(tmp_path)
    candidate_root = build_input.candidate_root
    public_root = candidate_root / "public"
    first = _run(builder, build_input)
    report_path = public_root / _REPORT_NAME
    manifest_path = public_root / ASSURED_ARTIFACT_MANIFEST_NAME
    report_bytes = report_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    report_temp = candidate_root.parent / assurance_builder_module._control_staging_name(
        candidate_name=candidate_root.name,
        control_name=_REPORT_NAME,
        encoded=report_bytes,
    )

    if staging_state == "linked":
        os.link(report_path, report_temp)
    else:
        report_path.unlink()
        manifest_path.unlink()
        if staging_state == "partial":
            report_temp.write_bytes(report_bytes[: len(report_bytes) // 2])
            report_temp.chmod(0o600)
        else:
            report_temp.write_bytes(report_bytes)
            report_temp.chmod(0o644)

    resumed = _run(builder, build_input)

    assert resumed == first
    assert report_path.read_bytes() == report_bytes
    assert manifest_path.read_bytes() == manifest_bytes
    assert not report_temp.exists()


def test_control_publication_rejects_foreign_reserved_staging_bytes(
    tmp_path: Path,
) -> None:
    build_input, builder, _scanner, _inventory = _harness(tmp_path)
    candidate_root = build_input.candidate_root
    public_root = candidate_root / "public"
    _run(builder, build_input)
    report_path = public_root / _REPORT_NAME
    manifest_path = public_root / ASSURED_ARTIFACT_MANIFEST_NAME
    report_bytes = report_path.read_bytes()
    report_path.unlink()
    manifest_path.unlink()
    report_temp = candidate_root.parent / assurance_builder_module._control_staging_name(
        candidate_name=candidate_root.name,
        control_name=_REPORT_NAME,
        encoded=report_bytes,
    )
    report_temp.write_bytes(b"foreign-staging-bytes")
    report_temp.chmod(0o644)

    with pytest.raises(SuccessorAssuranceBuilderError, match="staging entry differs"):
        _run(builder, build_input)
    assert report_temp.read_bytes() == b"foreign-staging-bytes"
    assert not report_path.exists()
    assert not manifest_path.exists()


def test_manifest_only_and_foreign_controls_fail_without_overwrite(tmp_path: Path) -> None:
    build_input, builder, _scanner, _inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"
    manifest_path = public_root / ASSURED_ARTIFACT_MANIFEST_NAME
    manifest_path.write_bytes(b"foreign-manifest\n")

    with pytest.raises(SuccessorAssuranceBuilderError, match="cannot exist without"):
        _run(builder, build_input)
    assert manifest_path.read_bytes() == b"foreign-manifest\n"
    assert not (public_root / _REPORT_NAME).exists()

    manifest_path.unlink()
    report_path = public_root / _REPORT_NAME
    report_path.write_bytes(b"{}\n")
    with pytest.raises((SuccessorAssuranceBuilderError, ValueError)):
        _run(builder, build_input)
    assert report_path.read_bytes() == b"{}\n"
    assert not manifest_path.exists()


def test_execution_tree_and_inherited_authority_drift_fail_before_controls(
    tmp_path: Path,
) -> None:
    build_input, builder, _scanner, _inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"
    (public_root / "nba.duckdb").write_bytes(b"changed-after-execution")

    with pytest.raises(SuccessorAssuranceBuilderError, match="completed execution authority"):
        _run(builder, build_input)
    assert not (public_root / _REPORT_NAME).exists()
    assert not (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).exists()

    build_input, _builder, scanner, inventory = _harness(tmp_path / "authority")
    bad_builder = ExactSuccessorAssuranceBuilder(
        chain_id="foreign-chain",
        contract_blocked_evidence=_BLOCKED_EVIDENCE,
        provider_authority=expected_nba_api_provider_authority(),
        scanner=scanner,
        inventory=inventory,
        installed_tree=measure_installed_public_tree,
        private_generation_resolver=_PrivateResolver(),
    )
    with pytest.raises(SuccessorAssuranceBuilderError, match="chain or semantic source"):
        _run(bad_builder, build_input)
    assert scanner.calls == []
    assert inventory.calls == []


def test_retained_private_generation_is_reverified_before_scan_or_controls(
    tmp_path: Path,
) -> None:
    build_input, builder, scanner, inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"
    retained = build_input.update_private_generation
    forged = replace(retained, manifest_sha256="0" * 64)

    class _RetainedResolver(_PrivateResolver):
        def verify(self, **kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return retained

    builder = replace(builder, private_generation_resolver=_RetainedResolver())
    forged_input = replace(build_input, update_private_generation=forged)

    with pytest.raises(SuccessorAssuranceBuilderError, match="retained private generation"):
        _run(builder, forged_input)
    assert scanner.calls == []
    assert inventory.calls == []
    assert not (public_root / _REPORT_NAME).exists()
    assert not (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).exists()


def test_scan_and_inventory_database_mismatch_fails_before_controls(tmp_path: Path) -> None:
    build_input, builder, scanner, _inventory = _harness(tmp_path)
    scanner.result = replace(scanner.result, database_sha256="0" * 64)
    public_root = build_input.candidate_root / "public"

    with pytest.raises(SuccessorAssuranceBuilderError, match="scan database differs"):
        _run(builder, build_input)
    assert not (public_root / _REPORT_NAME).exists()
    assert not (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).exists()


@pytest.mark.parametrize("field", ["row_count", "schema_sha256", "content_sha256"])
def test_forged_transform_attestation_fails_before_controls(
    tmp_path: Path,
    field: str,
) -> None:
    build_input, builder, scanner, inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"
    original = build_input.transform_outputs[0]
    value: object = original.row_count + 1 if field == "row_count" else "0" * 64
    forged = replace(original, **{field: value})
    forged_input = replace(
        build_input,
        transform_outputs=(forged, *build_input.transform_outputs[1:]),
    )

    with pytest.raises(SuccessorAssuranceBuilderError, match="candidate DuckDB authority"):
        _run(builder, forged_input)
    assert len(scanner.calls) == 1
    assert len(inventory.calls) == 1
    assert not (public_root / _REPORT_NAME).exists()
    assert not (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).exists()


def test_public_root_swap_is_rejected_without_publishing_to_canonical_name(
    tmp_path: Path,
) -> None:
    build_input, builder, scanner, _inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"
    displaced = build_input.candidate_root / "public-displaced"
    replacement = build_input.candidate_root / "public-replacement"
    replacement.mkdir()
    (replacement / "nba.duckdb").write_bytes(b"replacement")

    class _SwappingScanner(_Scanner):
        def __call__(
            self,
            public_root_arg: Path,
            *,
            expected_root_identity: tuple[int, int] | None = None,
        ) -> SuccessorFullPublicationScanResult:
            public_root.rename(displaced)
            replacement.rename(public_root)
            return super().__call__(
                public_root_arg,
                expected_root_identity=expected_root_identity,
            )

    swapping = _SwappingScanner(scanner.result)
    builder = replace(builder, scanner=swapping)

    with pytest.raises(SuccessorAssuranceBuilderError, match="public root"):
        _run(builder, build_input)
    assert not (public_root / _REPORT_NAME).exists()
    assert not (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).exists()


def test_post_inventory_data_mutation_fails_instead_of_blessing_new_tree(
    tmp_path: Path,
) -> None:
    build_input, builder, _scanner, inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"

    class _MutatingInventory(_Inventory):
        def __call__(
            self,
            public_root_arg: Path,
            *,
            expected_root_identity: tuple[int, int] | None = None,
        ) -> SuccessorPublicationInventoryEvidence:
            result = super().__call__(
                public_root_arg,
                expected_root_identity=expected_root_identity,
            )
            if len(self.calls) == 2:
                (public_root / "nba.sqlite").write_bytes(b"mutated-after-second-inventory")
            return result

    builder = replace(builder, inventory=_MutatingInventory(inventory.result))

    with pytest.raises(SuccessorAssuranceBuilderError, match="changed during terminal assurance"):
        _run(builder, build_input)


def test_manifest_swap_after_verification_is_not_hashed_as_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_input, builder, _scanner, _inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"
    original_verify = assurance_builder_module.verify_assured_artifact_manifest

    def _swap_after_verify(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_verify(*args, **kwargs)
        (public_root / ASSURED_ARTIFACT_MANIFEST_NAME).write_bytes(b"invalid-replacement\n")
        return result

    monkeypatch.setattr(
        assurance_builder_module,
        "verify_assured_artifact_manifest",
        _swap_after_verify,
    )

    with pytest.raises(SuccessorAssuranceBuilderError, match="changed while being verified"):
        _run(builder, build_input)


@pytest.mark.parametrize("mutation", ["extra_key", "duplicate_key", "nonfinite", "minified"])
def test_reentry_rejects_noncanonical_manifest_without_overwriting_it(
    tmp_path: Path,
    mutation: str,
) -> None:
    build_input, builder, _scanner, _inventory = _harness(tmp_path)
    public_root = build_input.candidate_root / "public"
    _run(builder, build_input)
    manifest_path = public_root / ASSURED_ARTIFACT_MANIFEST_NAME
    encoded = manifest_path.read_bytes()
    payload = json.loads(encoded)
    if mutation == "extra_key":
        payload["foreign_unvalidated_authority"] = {"value": "foreign"}
        tampered = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    elif mutation == "duplicate_key":
        tampered = b'{\n  "bytes": 0,\n' + encoded[2:]
    elif mutation == "nonfinite":
        tampered = encoded.replace(
            f'"bytes": {payload["bytes"]}'.encode(),
            b'"bytes": NaN',
            1,
        )
    else:
        tampered = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    manifest_path.write_bytes(tampered)

    with pytest.raises(SuccessorAssuranceBuilderError):
        _run(builder, build_input)
    assert manifest_path.read_bytes() == tampered


def test_candidate_ancestor_swap_preserving_public_inode_is_rejected(
    tmp_path: Path,
) -> None:
    build_input, builder, _scanner, inventory = _harness(tmp_path)
    candidate_root = build_input.candidate_root
    public_root = candidate_root / "public"
    displaced = candidate_root.with_name("candidate-displaced")

    class _AncestorSwappingInventory(_Inventory):
        def __call__(
            self,
            public_root_arg: Path,
            *,
            expected_root_identity: tuple[int, int] | None = None,
        ) -> SuccessorPublicationInventoryEvidence:
            result = super().__call__(
                public_root_arg,
                expected_root_identity=expected_root_identity,
            )
            if len(self.calls) == 2:
                candidate_root.rename(displaced)
                candidate_root.mkdir()
                (displaced / "public").rename(public_root)
            return result

    builder = replace(builder, inventory=_AncestorSwappingInventory(inventory.result))

    with pytest.raises(SuccessorAssuranceBuilderError, match="candidate root"):
        _run(builder, build_input)
