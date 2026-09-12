from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace
from typing import Any, cast

import pytest

from nbadb.contracts.actions_artifact import (
    ActionsArtifactIdentityV1,
    ArtifactMemberIdentityV1,
)
from nbadb.contracts.data_assurance_receipts import (
    DataGreenReceiptV1,
    PrivateCaptureAssuranceReceiptV1,
    RemotePrivateExclusionScanV1,
    RemoteReadbackReceiptV1,
    RemoteResourceV1,
    RemoteSchemaObservationV1,
    RemoteValueQueryObservationV1,
)
from nbadb.contracts.receipt_digest import canonical_receipt_bytes
from nbadb.orchestrate.successor_baseline import (
    SuccessorBaselineAdmissionError,
    baseline_identity_from_production_parent,
    baseline_identity_from_verified_publication,
)


def _snapshot() -> dict[str, Any]:
    return {
        "dataset": "maintainer/nbadb",
        "fingerprint": "1" * 64,
        "installed_public_tree_sha256": "0" * 64,
        "installed_public_tree_bytes": 57,
        "resource_bytes": 24,
        "provenance": {
            "chain_id": "full-initial-20260813",
            "source_sha": "a" * 40,
            "coverage_fingerprint": "2" * 64,
            "data_tree_fingerprint": "3" * 64,
        },
        "terminal_assurance": {
            "chain_id": "full-initial-20260813",
            "source_sha": "a" * 40,
            "coverage_fingerprint": "2" * 64,
            "checkpoint_database_sha256": "4" * 64,
            "checkpoint_report_sha256": "5" * 64,
            "contract_blocked_evidence_sha256": "6" * 64,
            "provider_authority_sha256": "7" * 64,
        },
        "resources": [
            {
                "path": "terminal-assurance-report.json",
                "kind": "file",
                "bytes": 11,
                "sha256": "9" * 64,
            },
            {
                "path": "assured-artifact-manifest.json",
                "kind": "file",
                "bytes": 13,
                "sha256": "8" * 64,
            },
        ],
    }


def _private_capture(**overrides: object) -> PrivateCaptureAssuranceReceiptV1:
    values: dict[str, object] = {
        "chain_id": "full-initial-20260813",
        "source_sha": "a" * 40,
        "generation": 2,
        "private_checkpoint_database_sha256": "4" * 64,
        "private_checkpoint_report_sha256": "5" * 64,
        "parser_input_inventory_sha256": "a" * 64,
        "request_observation_inventory_sha256": "b" * 64,
        "result_occurrence_inventory_sha256": "c" * 64,
        "route_landing_inventory_sha256": "d" * 64,
        "response_body_inventory_sha256": "e" * 64,
        "declared_bodyless_inventory_sha256": "f" * 64,
        "capture_digest": "1" * 64,
        "conservation_digest": "2" * 64,
        "reconstruction_digest": "3" * 64,
        "route_closure_digest": "4" * 64,
        "w2_input_digest": "5" * 64,
        "private_resource_count": 4,
        "private_resource_bytes": 4096,
    }
    values.update(overrides)
    return PrivateCaptureAssuranceReceiptV1.build(**values)


def _readback(**overrides: object) -> RemoteReadbackReceiptV1:
    values: dict[str, object] = {
        "dataset": "maintainer/nbadb",
        "dataset_version": 238,
        "source_sha": "a" * 40,
        "chain_id": "full-initial-20260813",
        "terminal_handoff_sha256": "b" * 64,
        "public_disposition_sha256": "c" * 64,
        "prepublication_admission_sha256": "d" * 64,
        "publication_intent_sha256": "e" * 64,
        "publication_marker_sha256": "f" * 64,
        "resources": (
            RemoteResourceV1(
                canonical_path="assured-artifact-manifest.json",
                size_bytes=13,
                sha256="8" * 64,
                media_type="application/json",
            ),
            RemoteResourceV1(
                canonical_path="terminal-assurance-report.json",
                size_bytes=11,
                sha256="9" * 64,
                media_type="application/json",
            ),
        ),
        "remote_inventory_sha256": "6" * 64,
        "remote_tree_sha256": "0" * 64,
        "schema_observations": (
            RemoteSchemaObservationV1(
                relation_name="dim_game",
                ordered_columns=("game_id",),
                physical_types=("VARCHAR",),
                row_count=1,
            ),
        ),
        "value_query_observations": (
            RemoteValueQueryObservationV1(
                query_id="dim-game-count",
                result_sha256="7" * 64,
                result_rows=1,
            ),
        ),
        "private_exclusion_scan": (
            RemotePrivateExclusionScanV1(
                scope="public-candidate",
                scanned_paths=2,
                private_hits=0,
                scan_sha256="8" * 64,
            ),
        ),
        "readback_fingerprint": "1" * 64,
        "parity_ok": True,
    }
    values.update(overrides)
    return RemoteReadbackReceiptV1.build(**values)


def _data_green(
    private_capture: PrivateCaptureAssuranceReceiptV1,
    readback: RemoteReadbackReceiptV1,
    **overrides: object,
) -> DataGreenReceiptV1:
    values: dict[str, object] = {
        "dataset": readback.dataset,
        "dataset_version": readback.dataset_version,
        "source_sha": readback.source_sha,
        "chain_id": readback.chain_id,
        "private_capture_receipt_sha256": private_capture.receipt_sha256,
        "public_disposition_sha256": readback.public_disposition_sha256,
        "prepublication_admission_sha256": readback.prepublication_admission_sha256,
        "terminal_handoff_sha256": readback.terminal_handoff_sha256,
        "publication_intent_sha256": readback.publication_intent_sha256,
        "publication_execution_sha256": "9" * 64,
        "publication_resolution_sha256": "a" * 64,
        "remote_readback_receipt_sha256": readback.receipt_sha256,
        "human_verification_receipt_sha256": "b" * 64,
        "docs_metadata_parity_sha256": "c" * 64,
        "model_status": "RED",
        "data_status": "GREEN",
    }
    values.update(overrides)
    return DataGreenReceiptV1.build(**values)


def _member_for_receipt(
    receipt: RemoteReadbackReceiptV1 | PrivateCaptureAssuranceReceiptV1 | DataGreenReceiptV1,
    *,
    run_id: int,
    artifact_id: int,
    member_path: str,
) -> ArtifactMemberIdentityV1:
    payload = canonical_receipt_bytes(receipt.to_payload())
    artifact = ActionsArtifactIdentityV1(
        repository="maintainer/nbadb",
        run_id=run_id,
        run_attempt=1,
        artifact_id=artifact_id,
        artifact_name=f"parent-evidence-{artifact_id}",
        artifact_digest=f"sha256:{'d' * 64}",
        artifact_size_bytes=len(payload) + 100,
    )
    return ArtifactMemberIdentityV1(
        artifact=artifact,
        member_path=member_path,
        member_sha256=hashlib.sha256(payload).hexdigest(),
        member_size_bytes=len(payload),
    )


def _production_evidence() -> tuple[
    RemoteReadbackReceiptV1,
    ArtifactMemberIdentityV1,
    PrivateCaptureAssuranceReceiptV1,
    ArtifactMemberIdentityV1,
    DataGreenReceiptV1,
    ArtifactMemberIdentityV1,
]:
    private_capture = _private_capture()
    readback = _readback()
    data_green = _data_green(private_capture, readback)
    return (
        readback,
        _member_for_receipt(
            readback,
            run_id=20,
            artifact_id=200,
            member_path="readback/remote-readback.json",
        ),
        private_capture,
        _member_for_receipt(
            private_capture,
            run_id=10,
            artifact_id=100,
            member_path="private/private-capture.json",
        ),
        data_green,
        _member_for_receipt(
            data_green,
            run_id=30,
            artifact_id=300,
            member_path="closeout/data-green.json",
        ),
    )


def test_production_parent_joins_public_private_and_data_green() -> None:
    readback, readback_member, private, private_member, data_green, data_green_member = (
        _production_evidence()
    )
    identity = baseline_identity_from_production_parent(
        _snapshot(),
        remote_readback=readback,
        remote_readback_member=readback_member,
        private_capture=private,
        private_capture_member=private_member,
        data_green=data_green,
        data_green_member=data_green_member,
    )

    assert identity.remote_dataset == readback.dataset
    assert identity.remote_dataset_version == readback.dataset_version
    assert identity.private_baseline_receipt_sha256 == private.receipt_sha256
    assert identity.checkpoint_database_sha256 == private.private_checkpoint_database_sha256
    assert identity.checkpoint_report_sha256 == private.private_checkpoint_report_sha256


def test_production_parent_rejects_public_only_input() -> None:
    readback, readback_member, private, private_member, _data_green_receipt, data_member = (
        _production_evidence()
    )
    with pytest.raises(SuccessorBaselineAdmissionError, match="DataGreenReceiptV1"):
        baseline_identity_from_production_parent(
            _snapshot(),
            remote_readback=readback,
            remote_readback_member=readback_member,
            private_capture=private,
            private_capture_member=private_member,
            data_green=cast("DataGreenReceiptV1", None),
            data_green_member=data_member,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset", "other/dataset"),
        ("dataset_version", 239),
        ("chain_id", "other-chain"),
        ("source_sha", "f" * 40),
        ("private_capture_receipt_sha256", "f" * 64),
        ("public_disposition_sha256", "f" * 64),
        ("prepublication_admission_sha256", "f" * 64),
        ("terminal_handoff_sha256", "f" * 64),
        ("remote_readback_receipt_sha256", "f" * 64),
    ],
)
def test_production_parent_rejects_mixed_evidence(field: str, value: object) -> None:
    readback, readback_member, private, private_member, _data_green_receipt, _data_member = (
        _production_evidence()
    )
    data_green = _data_green(private, readback, **{field: value})
    data_member = _member_for_receipt(
        data_green,
        run_id=30,
        artifact_id=300,
        member_path="closeout/data-green.json",
    )
    with pytest.raises(SuccessorBaselineAdmissionError, match="does not exact-join"):
        baseline_identity_from_production_parent(
            _snapshot(),
            remote_readback=readback,
            remote_readback_member=readback_member,
            private_capture=private,
            private_capture_member=private_member,
            data_green=data_green,
            data_green_member=data_member,
        )


def test_production_parent_rejects_member_receipt_substitution() -> None:
    readback, readback_member, private, private_member, data_green, data_member = (
        _production_evidence()
    )
    with pytest.raises(SuccessorBaselineAdmissionError, match="exact receipt bytes"):
        baseline_identity_from_production_parent(
            _snapshot(),
            remote_readback=readback,
            remote_readback_member=replace(readback_member, member_sha256="f" * 64),
            private_capture=private,
            private_capture_member=private_member,
            data_green=data_green,
            data_green_member=data_member,
        )


def test_production_parent_requires_independent_artifacts() -> None:
    readback, readback_member, private, private_member, data_green, data_member = (
        _production_evidence()
    )
    with pytest.raises(SuccessorBaselineAdmissionError, match="independent exact artifacts"):
        baseline_identity_from_production_parent(
            _snapshot(),
            remote_readback=readback,
            remote_readback_member=readback_member,
            private_capture=private,
            private_capture_member=private_member,
            data_green=data_green,
            data_green_member=replace(data_member, artifact=readback_member.artifact),
        )


def test_production_parent_rejects_private_checkpoint_drift() -> None:
    readback, readback_member, _private, _private_member, _data_green_receipt, _data_member = (
        _production_evidence()
    )
    private = _private_capture(private_checkpoint_database_sha256="e" * 64)
    private_member = _member_for_receipt(
        private,
        run_id=10,
        artifact_id=100,
        member_path="private/private-capture.json",
    )
    data_green = _data_green(private, readback)
    data_member = _member_for_receipt(
        data_green,
        run_id=30,
        artifact_id=300,
        member_path="closeout/data-green.json",
    )
    with pytest.raises(SuccessorBaselineAdmissionError, match="private checkpoint database"):
        baseline_identity_from_production_parent(
            _snapshot(),
            remote_readback=readback,
            remote_readback_member=readback_member,
            private_capture=private,
            private_capture_member=private_member,
            data_green=data_green,
            data_green_member=data_member,
        )


def test_production_parent_rejects_snapshot_readback_resource_drift() -> None:
    readback, readback_member, private, private_member, data_green, data_member = (
        _production_evidence()
    )
    snapshot = _snapshot()
    snapshot["resources"][0]["sha256"] = "f" * 64
    with pytest.raises(SuccessorBaselineAdmissionError, match="resources do not exactly match"):
        baseline_identity_from_production_parent(
            snapshot,
            remote_readback=readback,
            remote_readback_member=readback_member,
            private_capture=private,
            private_capture_member=private_member,
            data_green=data_green,
            data_green_member=data_member,
        )


def test_verified_publication_and_private_receipt_build_exact_baseline_identity() -> None:
    identity = baseline_identity_from_verified_publication(
        _snapshot(),
        remote_dataset_version=238,
        private_baseline_receipt_sha256="b" * 64,
    )

    assert identity.remote_dataset == "maintainer/nbadb"
    assert identity.remote_dataset_version == 238
    assert identity.remote_bundle_fingerprint_sha256 == "1" * 64
    assert identity.installed_public_tree_sha256 == "0" * 64
    assert identity.installed_public_tree_bytes == 57
    assert identity.assured_manifest_sha256 == "8" * 64
    assert identity.terminal_assurance_report_sha256 == "9" * 64
    assert identity.private_baseline_receipt_sha256 == "b" * 64
    assert identity.provider_authority_sha256 == "7" * 64
    assert type(identity).from_dict(identity.to_dict()) == identity


@pytest.mark.parametrize("field_name", ["chain_id", "source_sha", "coverage_fingerprint"])
def test_terminal_authority_must_match_public_provenance(field_name: str) -> None:
    snapshot = _snapshot()
    snapshot["terminal_assurance"][field_name] = (
        "other" if field_name == "chain_id" else "f" * (40 if field_name == "source_sha" else 64)
    )

    with pytest.raises(SuccessorBaselineAdmissionError, match=field_name):
        baseline_identity_from_verified_publication(
            snapshot,
            remote_dataset_version=238,
            private_baseline_receipt_sha256="b" * 64,
        )


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        ("missing_manifest", "exactly one assured-artifact-manifest"),
        ("duplicate_terminal", "duplicate path: terminal-assurance-report"),
        ("directory_manifest", "must be a file"),
        ("missing_private", "private_baseline_receipt_sha256"),
        ("invalid_version", "positive integer"),
        ("missing_provider", "provider_authority_sha256"),
        ("invalid_resource_bytes", "nonnegative integer"),
        ("overflow_resource_sum", "signed-63-bit range"),
        ("mismatched_resource_bytes", "does not exactly match"),
        ("overflow_declared_resource_bytes", "signed-63-bit range"),
        ("overflow_installed_public_tree_bytes", "signed-63-bit range"),
        ("incomplete_installed_public_tree_bytes", "include every declared resource byte"),
        ("overlapping_resources", "overlapping paths"),
    ],
)
def test_incomplete_public_or_private_baseline_fails_closed(mutation: str, error: str) -> None:
    snapshot = deepcopy(_snapshot())
    version: object = 238
    private_receipt = "b" * 64
    if mutation == "missing_manifest":
        snapshot["resources"] = snapshot["resources"][:1]
        snapshot["resource_bytes"] = 11
    elif mutation == "duplicate_terminal":
        snapshot["resources"].append(deepcopy(snapshot["resources"][0]))
    elif mutation == "directory_manifest":
        snapshot["resources"][1]["kind"] = "directory"
    elif mutation == "missing_private":
        private_receipt = ""
    elif mutation == "invalid_version":
        version = True
    elif mutation == "missing_provider":
        del snapshot["terminal_assurance"]["provider_authority_sha256"]
    elif mutation == "invalid_resource_bytes":
        snapshot["resources"][0]["bytes"] = True
    elif mutation == "overflow_resource_sum":
        snapshot["resources"][0]["bytes"] = (1 << 63) - 1
        snapshot["resources"][1]["bytes"] = 1
    elif mutation == "mismatched_resource_bytes":
        snapshot["resource_bytes"] = 23
    elif mutation == "overflow_declared_resource_bytes":
        snapshot["resource_bytes"] = 1 << 63
    elif mutation == "overflow_installed_public_tree_bytes":
        snapshot["installed_public_tree_bytes"] = 1 << 63
    elif mutation == "incomplete_installed_public_tree_bytes":
        snapshot["installed_public_tree_bytes"] = 23
    elif mutation == "overlapping_resources":
        snapshot["resources"].append(
            {
                "path": "assured-artifact-manifest.json/child",
                "kind": "file",
                "bytes": 0,
                "sha256": "c" * 64,
            }
        )

    with pytest.raises(SuccessorBaselineAdmissionError, match=error):
        baseline_identity_from_verified_publication(
            snapshot,
            remote_dataset_version=version,  # type: ignore[arg-type]
            private_baseline_receipt_sha256=private_receipt,
        )


@pytest.mark.parametrize(
    "aliased_path",
    [
        "/terminal-assurance-report.json",
        " terminal-assurance-report.json",
        "terminal-assurance-report.json ",
        "terminal-assurance-report.json/",
        "controls//terminal-assurance-report.json",
        "./terminal-assurance-report.json",
        "controls/../terminal-assurance-report.json",
        "controls\\terminal-assurance-report.json",
    ],
)
def test_resource_paths_must_be_canonical_relative_posix(aliased_path: str) -> None:
    snapshot = _snapshot()
    snapshot["resources"][0]["path"] = aliased_path

    with pytest.raises(
        SuccessorBaselineAdmissionError,
        match="canonical normalized relative POSIX path",
    ):
        baseline_identity_from_verified_publication(
            snapshot,
            remote_dataset_version=238,
            private_baseline_receipt_sha256="b" * 64,
        )
