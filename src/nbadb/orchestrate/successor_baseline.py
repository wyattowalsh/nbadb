"""Fail-closed admission of a verified public baseline for successor updates.

The Kaggle client owns byte- and format-level publication verification.  This
module converts only that already-verified snapshot plus an independently
verified private-baseline receipt into the immutable successor parent identity.
It deliberately performs no download, mutation, or storage lookup.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, cast

from nbadb.contracts.actions_artifact import ArtifactMemberIdentityV1
from nbadb.contracts.data_assurance_receipts import (
    DataGreenReceiptV1,
    PrivateCaptureAssuranceReceiptV1,
    RemoteReadbackReceiptV1,
)
from nbadb.contracts.receipt_digest import canonical_receipt_bytes
from nbadb.core.artifact_identity import ASSURED_ARTIFACT_MANIFEST_NAME
from nbadb.kaggle.client import TERMINAL_ASSURANCE_REPORT_NAME
from nbadb.orchestrate.successor_update_contract import BaselineAssuranceIdentity

__all__ = [
    "SuccessorBaselineAdmissionError",
    "baseline_identity_from_production_parent",
    "baseline_identity_from_verified_publication",
]

_MAX_SIGNED_63 = (1 << 63) - 1


class SuccessorBaselineAdmissionError(ValueError):
    """Raised when verified public/private baseline evidence is incomplete."""


def _mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SuccessorBaselineAdmissionError(f"{field_name} must be an object")
    return cast("Mapping[str, object]", value)


def _string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SuccessorBaselineAdmissionError(f"{field_name} must be a nonempty string")
    return value


def _sha256(value: object, *, field_name: str) -> str:
    result = _string(value, field_name=field_name)
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise SuccessorBaselineAdmissionError(f"{field_name} must be a lowercase SHA-256")
    return result


def _source_sha(value: object, *, field_name: str) -> str:
    result = _string(value, field_name=field_name)
    if len(result) != 40 or any(character not in "0123456789abcdef" for character in result):
        raise SuccessorBaselineAdmissionError(
            f"{field_name} must be a 40-character lowercase commit SHA"
        )
    return result


def _positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise SuccessorBaselineAdmissionError(f"{field_name} must be a positive integer")
    return value


def _nonnegative_signed63_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise SuccessorBaselineAdmissionError(f"{field_name} must be a nonnegative integer")
    if value > _MAX_SIGNED_63:
        raise SuccessorBaselineAdmissionError(f"{field_name} exceeds signed-63-bit range")
    return value


def _canonical_resource_path(value: object, *, field_name: str) -> str:
    path_value = _string(value, field_name=field_name)
    path = PurePosixPath(path_value)
    if (
        path_value != path_value.strip()
        or "\\" in path_value
        or path_value.startswith("/")
        or path_value.endswith("/")
        or "//" in path_value
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != path_value
    ):
        raise SuccessorBaselineAdmissionError(
            f"{field_name} must be a canonical normalized relative POSIX path"
        )
    return path_value


def _resource_sha256(
    resources_by_path: Mapping[str, Mapping[str, object]],
    *,
    path: str,
) -> str:
    resource = resources_by_path.get(path)
    if resource is None:
        raise SuccessorBaselineAdmissionError(
            f"verified publication must contain exactly one {path} resource"
        )
    if resource.get("kind") != "file":
        raise SuccessorBaselineAdmissionError(f"{path} resource must be a file")
    return _sha256(resource.get("sha256"), field_name=f"{path} sha256")


def _validated_resources(
    resources: object,
) -> tuple[dict[str, Mapping[str, object]], int]:
    if type(resources) is not list:
        raise SuccessorBaselineAdmissionError("resources must be a nonempty list")
    if not resources:
        raise SuccessorBaselineAdmissionError("resources must be a nonempty list")
    total = 0
    resources_by_path: dict[str, Mapping[str, object]] = {}
    for index, resource in enumerate(resources):
        item = _mapping(resource, field_name=f"resources[{index}]")
        path = _canonical_resource_path(
            item.get("path"),
            field_name=f"resources[{index}].path",
        )
        if path in resources_by_path:
            raise SuccessorBaselineAdmissionError(f"resources contains duplicate path: {path}")
        overlapping_path = next(
            (
                existing_path
                for existing_path in resources_by_path
                if path.startswith(f"{existing_path}/") or existing_path.startswith(f"{path}/")
            ),
            None,
        )
        if overlapping_path is not None:
            raise SuccessorBaselineAdmissionError(
                f"resources contains overlapping paths: {path} and {overlapping_path}"
            )
        if item.get("kind") not in {"file", "directory"}:
            raise SuccessorBaselineAdmissionError(
                f"resources[{index}].kind must be file or directory"
            )
        _sha256(item.get("sha256"), field_name=f"resources[{index}].sha256")
        byte_count = _nonnegative_signed63_int(
            item.get("bytes"),
            field_name=f"resources[{index}].bytes",
        )
        if byte_count > _MAX_SIGNED_63 - total:
            raise SuccessorBaselineAdmissionError("resource byte count exceeds signed-63-bit range")
        total += byte_count
        resources_by_path[path] = item
    return resources_by_path, total


def _require_receipt_member(
    receipt: RemoteReadbackReceiptV1 | PrivateCaptureAssuranceReceiptV1 | DataGreenReceiptV1,
    member: ArtifactMemberIdentityV1,
    *,
    field_name: str,
) -> None:
    if not isinstance(member, ArtifactMemberIdentityV1):
        raise SuccessorBaselineAdmissionError(
            f"{field_name} must be an exact ArtifactMemberIdentityV1"
        )
    try:
        receipt.verify()
        receipt_bytes = canonical_receipt_bytes(receipt.to_payload())
    except (TypeError, ValueError) as exc:
        raise SuccessorBaselineAdmissionError(f"{field_name} receipt is invalid: {exc}") from exc
    observed_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    if member.member_sha256 != observed_sha256 or member.member_size_bytes != len(receipt_bytes):
        raise SuccessorBaselineAdmissionError(
            f"{field_name} artifact member does not bind the exact receipt bytes"
        )


def _require_distinct_evidence_artifacts(
    *members: ArtifactMemberIdentityV1,
) -> None:
    repositories = {member.artifact.repository for member in members}
    if len(repositories) != 1:
        raise SuccessorBaselineAdmissionError(
            "successor parent evidence artifacts must belong to one repository"
        )
    identities = {
        (
            member.artifact.run_id,
            member.artifact.run_attempt,
            member.artifact.artifact_id,
        )
        for member in members
    }
    if len(identities) != len(members):
        raise SuccessorBaselineAdmissionError(
            "readback, private capture, and DATA-GREEN must be independent exact artifacts"
        )


def _require_readback_matches_snapshot(
    snapshot: Mapping[str, Any],
    readback: RemoteReadbackReceiptV1,
) -> None:
    if snapshot.get("dataset") != readback.dataset:
        raise SuccessorBaselineAdmissionError("readback dataset does not match verified snapshot")
    if snapshot.get("fingerprint") != readback.readback_fingerprint:
        raise SuccessorBaselineAdmissionError(
            "readback fingerprint does not match verified snapshot"
        )
    if snapshot.get("installed_public_tree_sha256") != readback.remote_tree_sha256:
        raise SuccessorBaselineAdmissionError(
            "readback tree does not match the installed public snapshot"
        )
    resources_by_path, _total = _validated_resources(snapshot.get("resources"))
    snapshot_files = tuple(
        sorted(
            (
                path,
                _nonnegative_signed63_int(item.get("bytes"), field_name=f"{path} bytes"),
                _sha256(item.get("sha256"), field_name=f"{path} sha256"),
            )
            for path, item in resources_by_path.items()
            if item.get("kind") == "file"
        )
    )
    readback_files = tuple(
        sorted(
            (resource.canonical_path, resource.size_bytes, resource.sha256)
            for resource in readback.resources
        )
    )
    if snapshot_files != readback_files:
        raise SuccessorBaselineAdmissionError(
            "readback resources do not exactly match the verified public snapshot"
        )


def baseline_identity_from_production_parent(
    snapshot: Mapping[str, Any],
    *,
    remote_readback: RemoteReadbackReceiptV1,
    remote_readback_member: ArtifactMemberIdentityV1,
    private_capture: PrivateCaptureAssuranceReceiptV1,
    private_capture_member: ArtifactMemberIdentityV1,
    data_green: DataGreenReceiptV1,
    data_green_member: ArtifactMemberIdentityV1,
) -> BaselineAssuranceIdentity:
    """Admit one exact public/private/DATA-GREEN production parent.

    This is the production entry point. It validates all three sealed receipts,
    binds each to independently identified artifact-member bytes, exact-joins
    their dataset/version/chain/source/disposition/admission/handoff/checkpoint
    identities, and only then derives the immutable baseline identity from the
    already verified public snapshot.
    """

    if not isinstance(remote_readback, RemoteReadbackReceiptV1):
        raise SuccessorBaselineAdmissionError(
            "production parent requires an exact RemoteReadbackReceiptV1"
        )
    if not isinstance(private_capture, PrivateCaptureAssuranceReceiptV1):
        raise SuccessorBaselineAdmissionError(
            "production parent requires an exact PrivateCaptureAssuranceReceiptV1"
        )
    if not isinstance(data_green, DataGreenReceiptV1):
        raise SuccessorBaselineAdmissionError(
            "production parent requires an exact DataGreenReceiptV1"
        )

    _require_receipt_member(
        remote_readback,
        remote_readback_member,
        field_name="remote_readback",
    )
    _require_receipt_member(
        private_capture,
        private_capture_member,
        field_name="private_capture",
    )
    _require_receipt_member(data_green, data_green_member, field_name="data_green")
    _require_distinct_evidence_artifacts(
        remote_readback_member,
        private_capture_member,
        data_green_member,
    )

    if (
        private_capture.chain_id != remote_readback.chain_id
        or private_capture.source_sha != remote_readback.source_sha
    ):
        raise SuccessorBaselineAdmissionError(
            "private capture chain/source does not match remote readback"
        )
    exact_data_green_joins = (
        ("dataset", data_green.dataset, remote_readback.dataset),
        ("dataset_version", data_green.dataset_version, remote_readback.dataset_version),
        ("chain_id", data_green.chain_id, remote_readback.chain_id),
        ("source_sha", data_green.source_sha, remote_readback.source_sha),
        (
            "private_capture_receipt_sha256",
            data_green.private_capture_receipt_sha256,
            private_capture.receipt_sha256,
        ),
        (
            "public_disposition_sha256",
            data_green.public_disposition_sha256,
            remote_readback.public_disposition_sha256,
        ),
        (
            "prepublication_admission_sha256",
            data_green.prepublication_admission_sha256,
            remote_readback.prepublication_admission_sha256,
        ),
        (
            "terminal_handoff_sha256",
            data_green.terminal_handoff_sha256,
            remote_readback.terminal_handoff_sha256,
        ),
        (
            "remote_readback_receipt_sha256",
            data_green.remote_readback_receipt_sha256,
            remote_readback.receipt_sha256,
        ),
    )
    mismatches = [
        field_name
        for field_name, observed, expected in exact_data_green_joins
        if observed != expected
    ]
    if mismatches:
        raise SuccessorBaselineAdmissionError(
            "DATA-GREEN parent evidence does not exact-join: " + ", ".join(mismatches)
        )

    _require_readback_matches_snapshot(snapshot, remote_readback)
    identity = baseline_identity_from_verified_publication(
        snapshot,
        remote_dataset_version=remote_readback.dataset_version,
        private_baseline_receipt_sha256=private_capture.receipt_sha256,
    )
    if identity.checkpoint_database_sha256 != private_capture.private_checkpoint_database_sha256:
        raise SuccessorBaselineAdmissionError(
            "private checkpoint database does not match the public terminal assurance"
        )
    if identity.checkpoint_report_sha256 != private_capture.private_checkpoint_report_sha256:
        raise SuccessorBaselineAdmissionError(
            "private checkpoint report does not match the public terminal assurance"
        )
    return identity


def baseline_identity_from_verified_publication(
    snapshot: Mapping[str, Any],
    *,
    remote_dataset_version: int,
    private_baseline_receipt_sha256: str,
) -> BaselineAssuranceIdentity:
    """Compatibility helper for non-production/publication mechanics tests.

    Production successors must call :func:`baseline_identity_from_production_parent`
    so the private receipt digest cannot be caller-invented. ``snapshot`` must
    still be the successful result of the Kaggle client's strict publication
    validator; private parser input never becomes a Kaggle resource.
    """

    version = _positive_int(remote_dataset_version, field_name="remote_dataset_version")
    private_receipt = _sha256(
        private_baseline_receipt_sha256,
        field_name="private_baseline_receipt_sha256",
    )
    dataset = _string(snapshot.get("dataset"), field_name="dataset")
    remote_bundle_fingerprint_sha256 = _sha256(
        snapshot.get("fingerprint"),
        field_name="remote bundle fingerprint",
    )
    installed_public_tree_sha256 = _sha256(
        snapshot.get("installed_public_tree_sha256"),
        field_name="installed_public_tree_sha256",
    )
    provenance = _mapping(snapshot.get("provenance"), field_name="provenance")
    terminal = _mapping(
        snapshot.get("terminal_assurance"),
        field_name="terminal_assurance",
    )

    chain_id = _string(provenance.get("chain_id"), field_name="provenance.chain_id")
    source_sha = _source_sha(
        provenance.get("source_sha"),
        field_name="provenance.source_sha",
    )
    coverage_fingerprint = _sha256(
        provenance.get("coverage_fingerprint"),
        field_name="provenance.coverage_fingerprint",
    )
    data_tree_fingerprint = _sha256(
        provenance.get("data_tree_fingerprint"),
        field_name="provenance.data_tree_fingerprint",
    )

    for field_name, expected in (
        ("chain_id", chain_id),
        ("source_sha", source_sha),
        ("coverage_fingerprint", coverage_fingerprint),
    ):
        if terminal.get(field_name) != expected:
            raise SuccessorBaselineAdmissionError(
                f"terminal assurance {field_name} does not match public provenance"
            )

    resources_by_path, observed_resource_bytes = _validated_resources(snapshot.get("resources"))
    declared_resource_bytes = _nonnegative_signed63_int(
        snapshot.get("resource_bytes"),
        field_name="resource_bytes",
    )
    if declared_resource_bytes != observed_resource_bytes:
        raise SuccessorBaselineAdmissionError(
            "resource_bytes does not exactly match canonical declared resources"
        )
    installed_public_tree_bytes = _nonnegative_signed63_int(
        snapshot.get("installed_public_tree_bytes"),
        field_name="installed_public_tree_bytes",
    )
    if installed_public_tree_bytes < declared_resource_bytes:
        raise SuccessorBaselineAdmissionError(
            "installed_public_tree_bytes must include every declared resource byte"
        )
    assured_manifest_sha256 = _resource_sha256(
        resources_by_path,
        path=ASSURED_ARTIFACT_MANIFEST_NAME,
    )
    terminal_report_sha256 = _resource_sha256(
        resources_by_path,
        path=TERMINAL_ASSURANCE_REPORT_NAME,
    )

    return BaselineAssuranceIdentity(
        remote_dataset=dataset,
        remote_dataset_version=version,
        chain_id=chain_id,
        source_sha=source_sha,
        coverage_fingerprint=coverage_fingerprint,
        data_tree_fingerprint=data_tree_fingerprint,
        remote_bundle_fingerprint_sha256=remote_bundle_fingerprint_sha256,
        installed_public_tree_sha256=installed_public_tree_sha256,
        installed_public_tree_bytes=installed_public_tree_bytes,
        assured_manifest_sha256=assured_manifest_sha256,
        terminal_assurance_report_sha256=terminal_report_sha256,
        private_baseline_receipt_sha256=private_receipt,
        checkpoint_database_sha256=_sha256(
            terminal.get("checkpoint_database_sha256"),
            field_name="terminal_assurance.checkpoint_database_sha256",
        ),
        checkpoint_report_sha256=_sha256(
            terminal.get("checkpoint_report_sha256"),
            field_name="terminal_assurance.checkpoint_report_sha256",
        ),
        contract_blocked_evidence_sha256=_sha256(
            terminal.get("contract_blocked_evidence_sha256"),
            field_name="terminal_assurance.contract_blocked_evidence_sha256",
        ),
        provider_authority_sha256=_sha256(
            terminal.get("provider_authority_sha256"),
            field_name="terminal_assurance.provider_authority_sha256",
        ),
    )
