from __future__ import annotations

import errno
import hashlib
import inspect
import json
import os
import shutil
import signal
import stat
import sys
import tempfile
from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import pytest

from nbadb.core.config import NbaDbSettings
from nbadb.kaggle.client import KaggleClient
from nbadb.orchestrate.successor_generation_store import SuccessorGenerationStore
from nbadb.orchestrate.successor_inventory import measure_installed_public_tree
from nbadb.orchestrate.successor_update_contract import (
    BaselineAssuranceIdentity,
    CallMutability,
    DeltaDisposition,
    ObservedDeltaReceipt,
    PlannedRouteReplacementBinding,
    RequestedRouteScope,
    SuccessorAssuranceIdentity,
    SuccessorUpdateIntent,
    SuccessorUpdateMode,
    SuccessorUpdateTransaction,
    planned_route_replacement_bindings_sha256,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from nbadb.kaggle.publication_ledger import PublicationLedger


@pytest.fixture(autouse=True)
def _simulate_separately_reviewed_publication_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep client mechanics testable behind the independently tested rights gate."""
    monkeypatch.setattr(
        "nbadb.kaggle.client.assert_public_kaggle_publication_admitted",
        lambda: None,
    )


def test_durable_claim_is_textually_adjacent_to_kaggle_upload_call() -> None:
    source = inspect.getsource(KaggleClient._upload_claimed)
    assert (
        "execution_receipt = publication_ledger.claim_pending(durable_receipt)\n"
        "                    kagglehub.dataset_upload("
    ) in source


def _valid_publication_marker() -> dict[str, object]:
    return {
        "schema_version": 1,
        "dataset": "wyattowalsh/basketball",
        "publish_key": "a" * 20,
        "bundle_fingerprint": "b" * 64,
        "data_tree_fingerprint": "c" * 64,
        "metadata_sha256": "d" * 64,
        "resource_count": 1,
        "resource_bytes": 4,
        "resources": [
            {
                "path": "nba.sqlite",
                "kind": "file",
                "bytes": 4,
                "sha256": "e" * 64,
            }
        ],
    }


def _remote_tree(files: dict[str, bytes]) -> dict[str, object]:
    inventory = [
        {
            "path": path,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for path, content in sorted(files.items())
    ]
    fingerprint_source = json.dumps(inventory, sort_keys=True, separators=(",", ":"))
    return {
        "file_count": len(inventory),
        "bytes": sum(item["bytes"] for item in inventory),
        "files": inventory,
        "fingerprint": hashlib.sha256(fingerprint_source.encode()).hexdigest(),
    }


def _write_remote_tree(root: Path, files: dict[str, bytes]) -> None:
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _remote_file_downloader(root: Path, *, version: int = 42):
    def download(download_root: Path, requested_version: int, relative_path: str):
        assert requested_version == version
        destination = download_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative_path, destination)
        return destination, version

    return download


def _valid_publication_state() -> dict[str, object]:
    publish_key = "a" * 20
    timestamp = "2026-07-11T12:00:00+00:00"
    return {
        "schema_version": 1,
        "updated_at": timestamp,
        "datasets": {
            "wyattowalsh/basketball": {
                "publications": {
                    publish_key: {
                        "dataset": "wyattowalsh/basketball",
                        "publish_key": publish_key,
                        "bundle_fingerprint": "b" * 64,
                        "state": "resolved",
                        "last_status": "uploaded_remote_verified",
                        "last_transition_at": timestamp,
                        "resolved_at": timestamp,
                        "resolved_version": 42,
                        "serialization": {
                            "mechanism": "process_mutex_and_advisory_file_lock",
                            "scope": "same_process_and_same_host_shared_log_directory",
                            "cross_host_supported": False,
                            "cross_host_guard": "remote_marker_and_exact_version_reconciliation",
                        },
                    }
                }
            }
        },
    }


def _kaggle_api_http_error(
    status_code: int,
    *,
    url: str = "https://www.kaggle.com/api/v1/datasets/download/test/nbadb-publication.json",
) -> Exception:
    import requests
    from kagglehub.exceptions import KaggleApiHTTPError

    response = requests.Response()
    response.status_code = status_code
    response.url = url
    return KaggleApiHTTPError(f"HTTP {status_code}", response=response)


def test_sync_duckdb_replaces_stale_local_duckdb_when_only_sqlite_downloaded(tmp_path) -> None:
    sqlite_path = tmp_path / "nba.sqlite"
    duckdb_path = tmp_path / "nba.duckdb"
    sqlite_path.write_bytes(b"sqlite")
    duckdb_path.write_bytes(b"stale")

    with patch.object(KaggleClient, "_seed_duckdb_from_sqlite") as seed:
        KaggleClient._sync_duckdb_after_download(tmp_path, copied_names={"nba.sqlite"})

    assert not duckdb_path.exists()
    seed.assert_called_once_with(sqlite_path, duckdb_path)


def test_sync_duckdb_keeps_downloaded_duckdb(tmp_path) -> None:
    sqlite_path = tmp_path / "nba.sqlite"
    duckdb_path = tmp_path / "nba.duckdb"
    sqlite_path.write_bytes(b"sqlite")
    duckdb_path.write_bytes(b"fresh")

    with patch.object(KaggleClient, "_seed_duckdb_from_sqlite") as seed:
        KaggleClient._sync_duckdb_after_download(
            tmp_path,
            copied_names={"nba.sqlite", "nba.duckdb"},
        )

    assert duckdb_path.read_bytes() == b"fresh"
    seed.assert_not_called()


def test_sync_duckdb_ignores_stale_local_sqlite_when_sqlite_not_downloaded(tmp_path) -> None:
    sqlite_path = tmp_path / "nba.sqlite"
    duckdb_path = tmp_path / "nba.duckdb"
    sqlite_path.write_bytes(b"stale-sqlite")
    duckdb_path.write_bytes(b"current-duckdb")

    with patch.object(KaggleClient, "_seed_duckdb_from_sqlite") as seed:
        KaggleClient._sync_duckdb_after_download(tmp_path, copied_names={"csv"})

    assert duckdb_path.read_bytes() == b"current-duckdb"
    seed.assert_not_called()


def test_ensure_metadata_fails_when_data_dir_is_missing(tmp_path) -> None:
    missing_dir = tmp_path / "missing"

    with pytest.raises(FileNotFoundError, match="Metadata data_dir does not exist"):
        KaggleClient().ensure_metadata(missing_dir)

    assert not missing_dir.exists()


def test_remote_publication_marker_uses_exact_resolver_version_not_output_path(tmp_path) -> None:
    remote_dir = tmp_path / "cache" / "versions" / "999"
    remote_dir.mkdir(parents=True)
    marker = _valid_publication_marker()
    marker_path = KaggleClient._write_publication_marker(remote_dir, marker)
    download_root = tmp_path / "download"
    client = KaggleClient()

    with patch(
        "kagglehub.registry.dataset_resolver",
        return_value=(str(marker_path), 42),
    ) as resolver:
        observed_marker, version = client._download_remote_publication_marker(download_root)

    assert observed_marker == marker
    assert version == 42
    handle, requested_path = resolver.call_args.args
    assert str(handle) == "wyattowalsh/basketball"
    assert handle.version is None
    assert requested_path == "nbadb-publication.json"
    assert resolver.call_args.kwargs == {
        "output_dir": str(download_root),
        "force_download": True,
    }


def test_remote_publication_marker_requires_exact_positive_resolver_version(tmp_path) -> None:
    remote_dir = tmp_path / "remote"
    remote_dir.mkdir()
    marker_path = KaggleClient._write_publication_marker(remote_dir, _valid_publication_marker())
    client = KaggleClient()

    with (
        patch(
            "kagglehub.registry.dataset_resolver",
            return_value=(str(marker_path), None),
        ),
        pytest.raises(RuntimeError, match="did not resolve an exact dataset version"),
    ):
        client._download_remote_publication_marker(tmp_path / "download")


def test_resolve_remote_dataset_version_uses_dataset_metadata_api() -> None:
    api_client = MagicMock()
    api_client.__enter__.return_value = api_client
    api_client.datasets.dataset_api_client.get_dataset.return_value.current_version_number = 238
    client = KaggleClient()

    with patch("kagglehub.clients.build_kaggle_client", return_value=api_client):
        version = client._resolve_remote_dataset_version()

    assert version == 238
    request = api_client.datasets.dataset_api_client.get_dataset.call_args.args[0]
    assert request.owner_slug == "wyattowalsh"
    assert request.dataset_slug == "basketball"
    api_client.__exit__.assert_called_once()


@pytest.mark.parametrize("version", [None, 0, -1, True])
def test_resolve_remote_dataset_version_requires_exact_positive_version(version: object) -> None:
    api_client = MagicMock()
    api_client.__enter__.return_value = api_client
    api_client.datasets.dataset_api_client.get_dataset.return_value.current_version_number = version
    client = KaggleClient()

    with (
        patch("kagglehub.clients.build_kaggle_client", return_value=api_client),
        pytest.raises(RuntimeError, match="did not resolve an exact dataset version"),
    ):
        client._resolve_remote_dataset_version()


def _verified_successor_snapshot() -> dict[str, object]:
    return {
        "dataset": "wyattowalsh/basketball",
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
                "path": "assured-artifact-manifest.json",
                "kind": "file",
                "bytes": 13,
                "sha256": "8" * 64,
            },
            {
                "path": "terminal-assurance-report.json",
                "kind": "file",
                "bytes": 11,
                "sha256": "9" * 64,
            },
        ],
    }


def test_snapshot_upload_bundle_separates_resources_from_complete_installed_tree(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    resource_bytes = b"declared-resource"
    marker_bytes = b'{"schema_version": 2}\n'
    metadata = {
        "id": "wyattowalsh/basketball",
        "resources": [{"path": "data.bin"}],
    }
    metadata_bytes = (json.dumps(metadata, sort_keys=True) + "\n").encode()
    (tmp_path / "data.bin").write_bytes(resource_bytes)
    (tmp_path / "dataset-metadata.json").write_bytes(metadata_bytes)
    (tmp_path / "nbadb-publication.json").write_bytes(marker_bytes)

    snapshot = client._snapshot_upload_bundle(tmp_path)
    installed = measure_installed_public_tree(tmp_path)

    assert snapshot["resource_bytes"] == len(resource_bytes)
    assert snapshot["installed_public_tree_bytes"] == (
        len(resource_bytes) + len(metadata_bytes) + len(marker_bytes)
    )
    assert snapshot["installed_public_tree_bytes"] > snapshot["resource_bytes"]
    assert snapshot["installed_public_tree_bytes"] == installed.byte_count
    assert snapshot["installed_public_tree_sha256"] == installed.installed_public_tree_sha256


def test_snapshot_upload_bundle_rejects_resource_mutation_before_final_tree(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    resource = tmp_path / "data.bin"
    resource.write_bytes(b"before")
    (tmp_path / "dataset-metadata.json").write_text(
        json.dumps(
            {
                "id": "wyattowalsh/basketball",
                "resources": [{"path": "data.bin"}],
            }
        ),
        encoding="utf-8",
    )
    measured = False

    def mutate_then_measure(
        path: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ):
        nonlocal measured
        if not measured:
            resource.write_bytes(b"after!")
            measured = True
        return measure_installed_public_tree(path, expected_root_identity=expected_root_identity)

    with (
        patch(
            "nbadb.kaggle.client.measure_installed_public_tree",
            side_effect=mutate_then_measure,
        ),
        pytest.raises(ValueError, match="declared resource changed"),
    ):
        client._snapshot_upload_bundle(tmp_path)

    assert measured is True


def test_snapshot_upload_bundle_rejects_directory_resource_mutation_before_final_tree(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    resource = tmp_path / "parquet" / "table"
    resource.mkdir(parents=True)
    child = resource / "table.parquet"
    child.write_bytes(b"before")
    (tmp_path / "dataset-metadata.json").write_text(
        json.dumps(
            {
                "id": "wyattowalsh/basketball",
                "resources": [{"path": "parquet/table"}],
            }
        ),
        encoding="utf-8",
    )
    measured = False

    def mutate_then_measure(
        path: Path,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ):
        nonlocal measured
        if not measured:
            child.write_bytes(b"after!")
            measured = True
        return measure_installed_public_tree(path, expected_root_identity=expected_root_identity)

    with (
        patch.object(
            KaggleClient,
            "_validate_parquet_file",
            return_value={"engine": "parquet"},
        ),
        patch(
            "nbadb.kaggle.client.measure_installed_public_tree",
            side_effect=mutate_then_measure,
        ),
        pytest.raises(ValueError, match="declared directory resource changed"),
    ):
        client._snapshot_upload_bundle(tmp_path)

    assert measured is True


def _successor_v7_admission_fixture(tmp_path: Path):
    report_bytes = b'{"schema_version":7}\n'
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    data_resource = {
        "path": "nba.duckdb",
        "kind": "file",
        "bytes": 12,
        "sha256": "1" * 64,
    }
    report_resource = {
        "path": "terminal-assurance-report.json",
        "kind": "file",
        "bytes": len(report_bytes),
        "sha256": report_sha256,
    }
    manifest_resource = {
        "path": "assured-artifact-manifest.json",
        "kind": "file",
        "bytes": 321,
        "sha256": "2" * 64,
    }
    resources = [manifest_resource, data_resource, report_resource]
    assured_manifest = {
        "chain_id": "daily-successor-20260813",
        "source_sha": "a" * 40,
        "coverage_fingerprint": "3" * 64,
        "data_tree_fingerprint": "4" * 64,
        "files": [
            {
                "path": data_resource["path"],
                "bytes": data_resource["bytes"],
                "sha256": data_resource["sha256"],
            },
            {
                "path": report_resource["path"],
                "bytes": report_resource["bytes"],
                "sha256": report_resource["sha256"],
            },
        ],
    }
    identity_payload = {
        "baseline_identity_sha256": "5" * 64,
        "update_intent_sha256": "6" * 64,
        "source_sha": assured_manifest["source_sha"],
        "generation": 2,
        "requested_scopes_sha256": "7" * 64,
        "observed_delta_receipts_sha256": "8" * 64,
        "planned_route_replacement_bindings_sha256": "f" * 64,
        "transform_inventory_sha256": "9" * 64,
        "scan_report_sha256": "a" * 64,
        "publication_resource_inventory_sha256": "b" * 64,
        "installed_public_tree_sha256": "0" * 64,
        "private_generation_receipt_sha256": "c" * 64,
        "successor_data_tree_fingerprint": "d" * 64,
        "successor_assured_manifest_sha256": manifest_resource["sha256"],
        "successor_validation_report_sha256": report_sha256,
    }
    identity = SimpleNamespace(
        **identity_payload,
        identity_sha256="e" * 64,
        to_dict=MagicMock(return_value=identity_payload),
    )
    baseline = SimpleNamespace(
        checkpoint_database_sha256="f" * 64,
        checkpoint_report_sha256="0" * 64,
        contract_blocked_evidence_sha256="1" * 64,
        provider_authority_sha256="2" * 64,
    )
    report = SimpleNamespace(
        schema_version=7,
        kind="successor_terminal_assurance_report",
        model_green=True,
        data_green=True,
        chain_id=assured_manifest["chain_id"],
        source_sha=assured_manifest["source_sha"],
        coverage_fingerprint=assured_manifest["coverage_fingerprint"],
        content_sha256=report_sha256,
        baseline=baseline,
        database_evidence=SimpleNamespace(duckdb_sha256=data_resource["sha256"]),
        public_evidence=SimpleNamespace(
            resources=(
                SimpleNamespace(
                    resource_id=data_resource["path"],
                    kind=data_resource["kind"],
                    bytes=data_resource["bytes"],
                    sha256=data_resource["sha256"],
                ),
            )
        ),
        contract_blocked_lane_count=0,
        planning_generation_manifest_sha256="3" * 64,
        execution_plan_sha256="4" * 64,
        planned_route_replacement_bindings_sha256="f" * 64,
        planning_evidence=SimpleNamespace(
            execution_plan=SimpleNamespace(
                planning_artifact_identity_sha256="5" * 64,
                planning_manifest_sha256="6" * 64,
                sealed_dispatch_inventory_sha256="7" * 64,
                planning_generation_id="planning-generation",
            )
        ),
        build_sha256="4" * 64,
        delta_coverage_sha256="5" * 64,
        transform_output_count=254,
        to_successor_assurance_identity=MagicMock(return_value=identity),
    )
    report_path = tmp_path / "terminal-assurance-report.json"
    report_path.write_bytes(report_bytes)
    return report_path, report_bytes, assured_manifest, resources, report, identity


def _real_successor_current_authority_fixture(
    tmp_path: Path,
) -> tuple[
    SuccessorGenerationStore,
    Path,
    SuccessorUpdateTransaction,
    dict[str, Any],
    list[dict[str, Any]],
    SimpleNamespace,
]:
    """Build one real frozen store authority around compact mocked v7 evidence."""

    report_bytes = b'{"schema_version":7}\n'
    data_bytes = b"current-promoted-duckdb"
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    data_sha256 = hashlib.sha256(data_bytes).hexdigest()
    baseline = BaselineAssuranceIdentity(
        remote_dataset="maintainer/nbadb",
        remote_dataset_version=238,
        chain_id="full-initial",
        source_sha="a" * 40,
        coverage_fingerprint="1" * 64,
        data_tree_fingerprint="2" * 64,
        remote_bundle_fingerprint_sha256="3" * 64,
        installed_public_tree_sha256="4" * 64,
        installed_public_tree_bytes=len(data_bytes),
        assured_manifest_sha256="5" * 64,
        terminal_assurance_report_sha256="6" * 64,
        private_baseline_receipt_sha256="7" * 64,
        checkpoint_database_sha256="8" * 64,
        checkpoint_report_sha256="9" * 64,
        contract_blocked_evidence_sha256="a" * 64,
        provider_authority_sha256="b" * 64,
    )
    scope = RequestedRouteScope.from_parameters(
        endpoint_name="scoreboard",
        route_id="scoreboard.current",
        route_contract_sha256="c" * 64,
        parameters={"game_date": "2026-08-13"},
        mutability=CallMutability.MUTABLE,
    )
    dispatch_identity = "0" * 64
    planning_dependencies = ("d" * 64,)
    planned_bindings_sha256 = planned_route_replacement_bindings_sha256(
        (
            PlannedRouteReplacementBinding(
                requested_scope_sha256=scope.identity_sha256,
                execution_dispatch_identity_sha256=dispatch_identity,
                planning_dependency_identity_sha256s=planning_dependencies,
            ),
        )
    )
    intent = SuccessorUpdateIntent(
        baseline_identity_sha256=baseline.identity_sha256,
        planning_generation_manifest_sha256="d" * 64,
        successor_execution_plan_sha256="e" * 64,
        planned_route_replacement_bindings_sha256=planned_bindings_sha256,
        mode=SuccessorUpdateMode.DAILY,
        source_sha="e" * 40,
        cutoff_utc="2026-08-12T00:00:00Z",
        as_of_utc="2026-08-13T00:00:00Z",
        requested_scopes=(scope,),
    )
    receipt = ObservedDeltaReceipt(
        baseline_identity_sha256=baseline.identity_sha256,
        update_intent_sha256=intent.identity_sha256,
        source_sha=intent.source_sha,
        requested_scope_sha256=scope.identity_sha256,
        execution_dispatch_identity_sha256=dispatch_identity,
        planning_dependency_identity_sha256s=planning_dependencies,
        disposition=DeltaDisposition.OBSERVED,
        logical_call_receipt_sha256="f" * 64,
        prior_persisted_content_sha256="0" * 64,
        source_scope_replacement_sha256="1" * 64,
        persisted_content_sha256="2" * 64,
        persisted_schema_sha256="3" * 64,
        persisted_row_count=1,
    )
    candidate_transaction = SuccessorUpdateTransaction.candidate(
        generation=1,
        baseline=baseline,
        intent=intent,
    )
    built = candidate_transaction.mark_built(observed_delta_receipts=(receipt,))
    assert built.build is not None
    store = SuccessorGenerationStore(tmp_path / "successor-store")
    candidate_root = store.candidate_path(candidate_transaction)
    public_root = candidate_root / "public"
    public_root.mkdir(parents=True)

    assured_manifest = {
        "chain_id": "daily-successor-current",
        "source_sha": intent.source_sha,
        "coverage_fingerprint": baseline.coverage_fingerprint,
        "data_tree_fingerprint": "4" * 64,
        "files": [
            {
                "path": "nba.duckdb",
                "bytes": len(data_bytes),
                "sha256": data_sha256,
            },
            {
                "path": "terminal-assurance-report.json",
                "bytes": len(report_bytes),
                "sha256": report_sha256,
            },
        ],
    }
    manifest_bytes = (
        json.dumps(assured_manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    (public_root / "nba.duckdb").write_bytes(data_bytes)
    (public_root / "terminal-assurance-report.json").write_bytes(report_bytes)
    (public_root / "assured-artifact-manifest.json").write_bytes(manifest_bytes)
    installed_tree_sha256 = measure_installed_public_tree(public_root).installed_public_tree_sha256
    assurance = SuccessorAssuranceIdentity(
        baseline_identity_sha256=baseline.identity_sha256,
        update_intent_sha256=intent.identity_sha256,
        source_sha=intent.source_sha,
        generation=1,
        requested_scopes_sha256=intent.requested_scopes_sha256,
        observed_delta_receipts_sha256=built.build.observed_delta_receipts_sha256,
        planned_route_replacement_bindings_sha256=(
            built.build.planned_route_replacement_bindings_sha256
        ),
        transform_inventory_sha256="5" * 64,
        scan_report_sha256="6" * 64,
        publication_resource_inventory_sha256="7" * 64,
        installed_public_tree_sha256=installed_tree_sha256,
        private_generation_receipt_sha256="8" * 64,
        successor_data_tree_fingerprint="9" * 64,
        successor_assured_manifest_sha256=manifest_sha256,
        successor_validation_report_sha256=report_sha256,
    )
    validated = built.mark_validated(assurance)
    promoted = validated.promote()
    store.record_transaction(candidate_root, candidate_transaction)
    store.record_transaction(candidate_root, built)
    store.record_transaction(candidate_root, validated)
    store.record_promoted_candidate(candidate_root, promoted)
    with patch.object(store, "_gate_publication_before_promote"):
        store.promote(candidate_root, promoted)

    resources = [
        {
            "path": "assured-artifact-manifest.json",
            "kind": "file",
            "bytes": len(manifest_bytes),
            "sha256": manifest_sha256,
        },
        {
            "path": "nba.duckdb",
            "kind": "file",
            "bytes": len(data_bytes),
            "sha256": data_sha256,
        },
        {
            "path": "terminal-assurance-report.json",
            "kind": "file",
            "bytes": len(report_bytes),
            "sha256": report_sha256,
        },
    ]
    report = SimpleNamespace(
        schema_version=7,
        kind="successor_terminal_assurance_report",
        model_green=True,
        data_green=True,
        chain_id=assured_manifest["chain_id"],
        source_sha=assured_manifest["source_sha"],
        coverage_fingerprint=assured_manifest["coverage_fingerprint"],
        content_sha256=report_sha256,
        baseline=baseline,
        database_evidence=SimpleNamespace(duckdb_sha256=data_sha256),
        public_evidence=SimpleNamespace(
            resources=(
                SimpleNamespace(
                    resource_id="nba.duckdb",
                    kind="file",
                    bytes=len(data_bytes),
                    sha256=data_sha256,
                ),
            )
        ),
        contract_blocked_lane_count=0,
        planning_generation_manifest_sha256=(intent.planning_generation_manifest_sha256),
        execution_plan_sha256=intent.successor_execution_plan_sha256,
        planned_route_replacement_bindings_sha256=(
            intent.planned_route_replacement_bindings_sha256
        ),
        planning_evidence=SimpleNamespace(
            execution_plan=SimpleNamespace(
                planning_artifact_identity_sha256="b" * 64,
                planning_manifest_sha256=intent.planning_generation_manifest_sha256,
                sealed_dispatch_inventory_sha256="c" * 64,
                planning_generation_id="planning-generation",
            )
        ),
        build_sha256=built.build.identity_sha256,
        delta_coverage_sha256="a" * 64,
        transform_output_count=254,
        to_successor_assurance_identity=MagicMock(return_value=assurance),
    )
    return (
        store,
        candidate_root,
        promoted,
        assured_manifest,
        resources,
        report,
    )


def test_successor_terminal_assurance_v7_binds_exact_public_controls_and_baseline(
    tmp_path: Path,
) -> None:
    report_path, report_bytes, manifest, resources, report, identity = (
        _successor_v7_admission_fixture(tmp_path)
    )

    with patch(
        "nbadb.orchestrate.successor_assurance.validate_successor_terminal_assurance_report",
        return_value=report,
    ) as validate:
        normalized = KaggleClient._validate_terminal_assurance_report(
            report_path,
            assured_manifest=manifest,
            resource_inventory=resources,
            installed_public_tree_sha256="0" * 64,
        )

    validate.assert_called_once_with(report_bytes)
    report.to_successor_assurance_identity.assert_called_once_with(
        successor_assured_manifest_sha256="2" * 64,
        installed_public_tree_sha256="0" * 64,
    )
    assert normalized["schema_version"] == 7
    assert normalized["chain_id"] == manifest["chain_id"]
    assert normalized["checkpoint_database_sha256"] == "1" * 64
    assert normalized["checkpoint_report_sha256"] == hashlib.sha256(report_bytes).hexdigest()
    assert normalized["inherited_baseline_checkpoint_database_sha256"] == "f" * 64
    assert normalized["inherited_baseline_checkpoint_report_sha256"] == "0" * 64
    assert normalized["contract_blocked_evidence_sha256"] == "1" * 64
    assert normalized["provider_authority_sha256"] == "2" * 64
    assert (
        normalized["planned_route_replacement_bindings_sha256"]
        == report.planned_route_replacement_bindings_sha256
    )
    assert (
        normalized["successor_validation_report_sha256"] == hashlib.sha256(report_bytes).hexdigest()
    )
    assert normalized["successor_assured_manifest_sha256"] == "2" * 64
    assert normalized["successor_assurance_identity_sha256"] == identity.identity_sha256


def test_successor_terminal_assurance_v7_rejects_foreign_route_binding_identity(
    tmp_path: Path,
) -> None:
    report_path, _report_bytes, manifest, resources, report, identity = (
        _successor_v7_admission_fixture(tmp_path)
    )
    identity.planned_route_replacement_bindings_sha256 = "0" * 64

    with (
        patch(
            "nbadb.orchestrate.successor_assurance.validate_successor_terminal_assurance_report",
            return_value=report,
        ),
        pytest.raises(ValueError, match="route bindings.*do not reconcile"),
    ):
        KaggleClient._validate_terminal_assurance_report(
            report_path,
            assured_manifest=manifest,
            resource_inventory=resources,
            installed_public_tree_sha256="0" * 64,
        )


def test_successor_terminal_assurance_v6_is_not_a_compatibility_route(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "terminal-assurance-report.json"
    report_path.write_text('{"schema_version":6}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported schema"):
        KaggleClient._validate_terminal_assurance_report(
            report_path,
            assured_manifest={},
        )


def test_successor_v7_full_publication_requires_explicit_generation_store(
    tmp_path: Path,
) -> None:
    report_path, _report_bytes, manifest, resources, _report, _identity = (
        _successor_v7_admission_fixture(tmp_path)
    )

    with pytest.raises(ValueError, match="explicit current generation store"):
        KaggleClient._validate_terminal_assurance_report(
            report_path,
            assured_manifest=manifest,
            resource_inventory=resources,
            installed_public_tree_sha256="0" * 64,
            successor_data_root=tmp_path,
            require_successor_current_authority=True,
        )


def test_successor_v7_current_promoted_public_tree_is_accepted(tmp_path: Path) -> None:
    store, candidate_root, promoted, manifest, resources, report = (
        _real_successor_current_authority_fixture(tmp_path)
    )
    assurance = promoted.promoted_assurance
    report_path = candidate_root / "public" / "terminal-assurance-report.json"

    with (
        patch(
            "nbadb.orchestrate.successor_assurance.validate_successor_terminal_assurance_report",
            return_value=report,
        ),
        patch.object(store, "read_current", wraps=store.read_current) as read_current,
    ):
        normalized = KaggleClient._validate_terminal_assurance_report(
            report_path,
            assured_manifest=manifest,
            resource_inventory=resources,
            installed_public_tree_sha256=assurance.installed_public_tree_sha256,
            successor_generation_store=store,
            successor_data_root=candidate_root / "public",
            require_successor_current_authority=True,
        )

    assert normalized["successor_assurance_identity_sha256"] == assurance.identity_sha256
    assert read_current.call_count == 2
    report.to_successor_assurance_identity.assert_called_once_with(
        successor_assured_manifest_sha256=assurance.successor_assured_manifest_sha256,
        installed_public_tree_sha256=assurance.installed_public_tree_sha256,
    )


def test_successor_v7_rejects_self_consistent_rewritten_local_candidate(
    tmp_path: Path,
) -> None:
    store, candidate_root, promoted, manifest, _resources, report = (
        _real_successor_current_authority_fixture(tmp_path)
    )
    current_public = candidate_root / "public"
    rewritten_public = tmp_path / "rewritten-public"
    shutil.copytree(current_public, rewritten_public)
    for path in (rewritten_public, *rewritten_public.rglob("*")):
        path.chmod(0o700 if path.is_dir() else 0o600)

    rewritten_data = b"self-consistent-rewritten-duckdb"
    rewritten_data_sha256 = hashlib.sha256(rewritten_data).hexdigest()
    (rewritten_public / "nba.duckdb").write_bytes(rewritten_data)
    rewritten_manifest = json.loads(json.dumps(manifest))
    rewritten_manifest["files"][0] = {
        "path": "nba.duckdb",
        "bytes": len(rewritten_data),
        "sha256": rewritten_data_sha256,
    }
    rewritten_manifest_bytes = (
        json.dumps(rewritten_manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    (rewritten_public / "assured-artifact-manifest.json").write_bytes(rewritten_manifest_bytes)
    rewritten_manifest_sha256 = hashlib.sha256(rewritten_manifest_bytes).hexdigest()
    rewritten_tree_sha256 = measure_installed_public_tree(
        rewritten_public
    ).installed_public_tree_sha256
    report_bytes = (rewritten_public / "terminal-assurance-report.json").read_bytes()
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    rewritten_resources = [
        {
            "path": "assured-artifact-manifest.json",
            "kind": "file",
            "bytes": len(rewritten_manifest_bytes),
            "sha256": rewritten_manifest_sha256,
        },
        {
            "path": "nba.duckdb",
            "kind": "file",
            "bytes": len(rewritten_data),
            "sha256": rewritten_data_sha256,
        },
        {
            "path": "terminal-assurance-report.json",
            "kind": "file",
            "bytes": len(report_bytes),
            "sha256": report_sha256,
        },
    ]
    rewritten_assurance = replace(
        promoted.promoted_assurance,
        installed_public_tree_sha256=rewritten_tree_sha256,
        successor_assured_manifest_sha256=rewritten_manifest_sha256,
    )
    report.database_evidence = SimpleNamespace(duckdb_sha256=rewritten_data_sha256)
    report.public_evidence = SimpleNamespace(
        resources=(
            SimpleNamespace(
                resource_id="nba.duckdb",
                kind="file",
                bytes=len(rewritten_data),
                sha256=rewritten_data_sha256,
            ),
        )
    )
    report.to_successor_assurance_identity = MagicMock(return_value=rewritten_assurance)

    with (
        patch(
            "nbadb.orchestrate.successor_assurance.validate_successor_terminal_assurance_report",
            return_value=report,
        ),
        pytest.raises(ValueError, match="not the exact current candidate public directory"),
    ):
        KaggleClient._validate_terminal_assurance_report(
            rewritten_public / "terminal-assurance-report.json",
            assured_manifest=rewritten_manifest,
            resource_inventory=rewritten_resources,
            installed_public_tree_sha256=rewritten_tree_sha256,
            successor_generation_store=store,
            successor_data_root=rewritten_public,
            require_successor_current_authority=True,
        )


def test_successor_v7_rejects_noncurrent_store_candidate(tmp_path: Path) -> None:
    store, current_candidate, promoted, manifest, resources, report = (
        _real_successor_current_authority_fixture(tmp_path)
    )
    noncurrent = SuccessorUpdateTransaction.candidate(
        generation=2,
        baseline=promoted.baseline,
        intent=promoted.intent,
    )
    noncurrent_root = store.candidate_path(noncurrent)
    shutil.copytree(current_candidate / "public", noncurrent_root / "public")
    store.record_transaction(noncurrent_root, noncurrent)

    with (
        patch(
            "nbadb.orchestrate.successor_assurance.validate_successor_terminal_assurance_report",
            return_value=report,
        ),
        pytest.raises(ValueError, match="not the exact current candidate public directory"),
    ):
        KaggleClient._validate_terminal_assurance_report(
            noncurrent_root / "public" / "terminal-assurance-report.json",
            assured_manifest=manifest,
            resource_inventory=resources,
            installed_public_tree_sha256=(promoted.promoted_assurance.installed_public_tree_sha256),
            successor_generation_store=store,
            successor_data_root=noncurrent_root / "public",
            require_successor_current_authority=True,
        )


def test_successor_store_authority_is_used_for_both_full_publication_snapshots() -> None:
    source = inspect.getsource(KaggleClient._upload_claimed)

    assert "successor_generation_store" in inspect.signature(KaggleClient.upload).parameters
    assert source.count("successor_generation_store=successor_generation_store") == 4
    assert source.count("require_successor_current_authority=full_publication") == 2


def test_successor_upload_requires_durable_intent_before_snapshot() -> None:
    source = inspect.getsource(KaggleClient._upload_claimed)
    gate = source.index("require_successor_durable_publication")
    snapshot = source.index("self._snapshot_upload_bundle")

    assert gate < snapshot
    assert 'resource_verification_mode": "exact_api_inventory_and_sha256_full_readback"' in source


def test_successor_upload_requires_store_before_snapshot(tmp_path: Path) -> None:
    from nbadb.core.artifact_identity import SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME
    from nbadb.orchestrate.successor_publication_authority import (
        SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED,
        SuccessorPublicationAuthorityError,
    )
    from tests.unit.orchestrate.test_successor_assurance import _report

    (tmp_path / SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME).write_bytes(_report().canonical_bytes)
    client = KaggleClient()
    with (
        patch.object(client, "_snapshot_upload_bundle") as snapshot,
        pytest.raises(
            SuccessorPublicationAuthorityError,
            match=SUCCESSOR_CURRENT_GENERATION_STORE_REQUIRED,
        ),
    ):
        client._upload_claimed(
            data_dir=tmp_path,
            full_publication=True,
            verify_remote=True,
            require_durable_intent=True,
            publication_ledger=cast("PublicationLedger", object()),
        )

    snapshot.assert_not_called()


def test_successor_store_rejects_leftover_schema_v3_before_independent_branch(
    tmp_path: Path,
) -> None:
    from nbadb.core.artifact_identity import SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME
    from nbadb.orchestrate.successor_generation_store import SuccessorGenerationStore
    from nbadb.orchestrate.successor_publication_authority import (
        SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED,
        SuccessorPublicationAuthorityError,
    )

    store = SuccessorGenerationStore(tmp_path / "successor-store")
    (tmp_path / SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME).write_text(
        json.dumps({"schema_version": 3, "chain_id": "full-baseline"}) + "\n",
        encoding="utf-8",
    )
    client = KaggleClient()
    with (
        patch.object(client, "_snapshot_upload_bundle") as snapshot,
        pytest.raises(
            SuccessorPublicationAuthorityError,
            match=SUCCESSOR_PUBLICATION_AUTHORITY_REQUIRED,
        ),
    ):
        client._upload_claimed(
            data_dir=tmp_path,
            full_publication=True,
            verify_remote=True,
            require_durable_intent=True,
            publication_ledger=cast("PublicationLedger", object()),
            successor_generation_store=store,
        )

    snapshot.assert_not_called()


def test_validate_terminal_report_rejects_leftover_v3_when_store_supplied(
    tmp_path: Path,
) -> None:
    from nbadb.orchestrate.successor_generation_store import SuccessorGenerationStore

    store = SuccessorGenerationStore(tmp_path / "successor-store")
    report_path = tmp_path / "terminal-assurance-report.json"
    report_path.write_text(
        json.dumps({"schema_version": 3, "chain_id": "full-baseline", "source_sha": "a" * 40})
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="leftover full-extraction terminal report"):
        KaggleClient._validate_terminal_assurance_report(
            report_path,
            assured_manifest={"chain_id": "full-baseline", "source_sha": "a" * 40},
            resource_inventory=[],
            installed_public_tree_sha256="0" * 64,
            successor_generation_store=store,
            successor_data_root=tmp_path,
            require_successor_current_authority=True,
        )


def test_successor_upload_rejects_generic_path_before_snapshot(tmp_path: Path) -> None:
    from nbadb.core.artifact_identity import SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME
    from nbadb.orchestrate.successor_publication_authority import (
        SUCCESSOR_DURABLE_PUBLICATION_REQUIRED,
        SuccessorPublicationAuthorityError,
    )
    from tests.unit.orchestrate.test_successor_assurance import _report

    (tmp_path / SUCCESSOR_TERMINAL_ASSURANCE_REPORT_NAME).write_bytes(_report().canonical_bytes)
    client = KaggleClient()
    with (
        patch.object(client, "_snapshot_upload_bundle") as snapshot,
        pytest.raises(
            SuccessorPublicationAuthorityError,
            match=SUCCESSOR_DURABLE_PUBLICATION_REQUIRED,
        ),
    ):
        client._upload_claimed(
            data_dir=tmp_path,
            full_publication=True,
            verify_remote=True,
        )

    snapshot.assert_not_called()


def test_successor_terminal_assurance_v7_admits_actual_dynamic_resource_contract(
    tmp_path: Path,
) -> None:
    from tests.unit.orchestrate.test_successor_assurance import _report

    report = _report()
    report_path = tmp_path / "terminal-assurance-report.json"
    report_path.write_bytes(report.canonical_bytes)
    resources: list[dict[str, Any]] = []
    for resource in report.public_evidence.resources:
        inventory: dict[str, Any] = {
            "path": resource.resource_id,
            "kind": resource.kind,
            "bytes": resource.bytes,
            "sha256": resource.sha256,
        }
        if resource.kind == "directory":
            inventory["files"] = [
                {
                    "path": "part-00000.parquet",
                    "bytes": resource.bytes,
                    "sha256": resource.sha256,
                }
            ]
        resources.append(inventory)
    resources.extend(
        [
            {
                "path": "assured-artifact-manifest.json",
                "kind": "file",
                "bytes": 321,
                "sha256": "f" * 64,
            },
            {
                "path": "terminal-assurance-report.json",
                "kind": "file",
                "bytes": len(report.canonical_bytes),
                "sha256": report.content_sha256,
            },
        ]
    )
    manifest = {
        "chain_id": report.chain_id,
        "source_sha": report.source_sha,
        "coverage_fingerprint": report.coverage_fingerprint,
        "data_tree_fingerprint": "e" * 64,
        "files": KaggleClient._flatten_resource_file_inventory(resources),
    }

    normalized = KaggleClient._validate_terminal_assurance_report(
        report_path,
        assured_manifest=manifest,
        resource_inventory=resources,
        installed_public_tree_sha256="0" * 64,
    )

    assert len(report.public_evidence.resources) == len(resources) - 2
    assert normalized["schema_version"] == 7
    assert normalized["transform_output_count"] == len(report.transform_outputs)
    assert normalized["checkpoint_database_sha256"] == report.database_evidence.duckdb_sha256
    assert normalized["checkpoint_report_sha256"] == report.content_sha256
    assert normalized["inherited_baseline_checkpoint_database_sha256"] == (
        report.baseline.checkpoint_database_sha256
    )
    assert normalized["inherited_baseline_checkpoint_report_sha256"] == (
        report.baseline.checkpoint_report_sha256
    )


def test_successor_v7_publication_becomes_exact_next_baseline(tmp_path: Path) -> None:
    from nbadb.orchestrate.successor_baseline import (
        baseline_identity_from_verified_publication,
    )

    report_path, report_bytes, manifest, resources, report, _identity = (
        _successor_v7_admission_fixture(tmp_path)
    )
    with patch(
        "nbadb.orchestrate.successor_assurance.validate_successor_terminal_assurance_report",
        return_value=report,
    ):
        normalized = KaggleClient._validate_terminal_assurance_report(
            report_path,
            assured_manifest=manifest,
            resource_inventory=resources,
            installed_public_tree_sha256="0" * 64,
        )

    snapshot = {
        "dataset": "wyattowalsh/basketball",
        "fingerprint": "a" * 64,
        "installed_public_tree_sha256": "0" * 64,
        "installed_public_tree_bytes": sum(int(resource["bytes"]) for resource in resources) + 41,
        "resource_bytes": sum(int(resource["bytes"]) for resource in resources),
        "provenance": {
            "chain_id": manifest["chain_id"],
            "source_sha": manifest["source_sha"],
            "coverage_fingerprint": manifest["coverage_fingerprint"],
            "data_tree_fingerprint": manifest["data_tree_fingerprint"],
        },
        "terminal_assurance": normalized,
        "resources": resources,
    }
    next_baseline = baseline_identity_from_verified_publication(
        snapshot,
        remote_dataset_version=239,
        private_baseline_receipt_sha256="b" * 64,
    )

    assert next_baseline.checkpoint_database_sha256 == "1" * 64
    assert next_baseline.checkpoint_database_sha256 != "f" * 64
    assert next_baseline.checkpoint_report_sha256 == hashlib.sha256(report_bytes).hexdigest()
    assert next_baseline.checkpoint_report_sha256 != "0" * 64
    assert next_baseline.assured_manifest_sha256 == "2" * 64
    assert (
        next_baseline.terminal_assurance_report_sha256 == hashlib.sha256(report_bytes).hexdigest()
    )


def test_successor_terminal_assurance_v7_rejects_strict_data_resource_drift(
    tmp_path: Path,
) -> None:
    report_path, _report_bytes, manifest, resources, report, _identity = (
        _successor_v7_admission_fixture(tmp_path)
    )
    resources[1]["sha256"] = "f" * 64

    with (
        patch(
            "nbadb.orchestrate.successor_assurance.validate_successor_terminal_assurance_report",
            return_value=report,
        ),
        pytest.raises(ValueError, match="data resources do not exactly match"),
    ):
        KaggleClient._validate_terminal_assurance_report(
            report_path,
            assured_manifest=manifest,
            resource_inventory=resources,
            installed_public_tree_sha256="0" * 64,
        )


def test_successor_terminal_assurance_v7_rejects_report_control_hash_drift(
    tmp_path: Path,
) -> None:
    report_path, _report_bytes, manifest, resources, report, _identity = (
        _successor_v7_admission_fixture(tmp_path)
    )
    resources[2]["sha256"] = "f" * 64
    manifest["files"][1]["sha256"] = "f" * 64

    with (
        patch(
            "nbadb.orchestrate.successor_assurance.validate_successor_terminal_assurance_report",
            return_value=report,
        ),
        pytest.raises(ValueError, match="report resource hash does not match"),
    ):
        KaggleClient._validate_terminal_assurance_report(
            report_path,
            assured_manifest=manifest,
            resource_inventory=resources,
            installed_public_tree_sha256="0" * 64,
        )


def _successor_download_file(
    contents: dict[str, bytes],
):
    def download(root: Path, version: int, relative_path: str) -> tuple[Path, int]:
        assert version == 238
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents[relative_path])
        return destination, version

    return download


def _verified_public_download_case(
    tmp_path: Path,
) -> tuple[dict[str, bytes], list[dict[str, object]], Path, Path, dict[str, object]]:
    marker = _valid_publication_marker()
    contents = {
        "dataset-metadata.json": b"{}\n",
        "nbadb-publication.json": (json.dumps(marker, sort_keys=True) + "\n").encode(),
        "assured-artifact-manifest.json": b"m" * 13,
        "terminal-assurance-report.json": b"r" * 11,
        "parquet/nested/data.parquet": b"PAR1",
    }
    inventory: list[dict[str, object]] = [
        {"path": path, "bytes": len(content)} for path, content in sorted(contents.items())
    ]
    expected_installed_tree = tmp_path / "expected-verified-public"
    _write_remote_tree(expected_installed_tree, contents)
    installed = measure_installed_public_tree(expected_installed_tree)
    snapshot = _verified_successor_snapshot()
    snapshot["resource_count"] = 2
    snapshot["installed_public_tree_sha256"] = installed.installed_public_tree_sha256
    snapshot["installed_public_tree_bytes"] = installed.byte_count
    return (
        contents,
        inventory,
        tmp_path / "candidate" / "public",
        tmp_path / "receipts" / "baseline.json",
        snapshot,
    )


def test_download_verified_public_baseline_installs_exact_version_and_emits_public_receipt(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)
    with (
        patch.object(
            client,
            "_resolve_remote_dataset_version",
            side_effect=AssertionError("exact verified download must not resolve latest"),
        ) as resolve_latest,
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ) as download,
        patch.object(client, "_require_disk_capacity") as capacity,
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
        patch("kagglehub.dataset_download") as latest_download,
    ):
        installed_path, emitted_receipt = client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
        )

    assert installed_path == target
    assert emitted_receipt == receipt_path
    assert target.is_dir()
    assert download.call_count == len(contents)
    capacity.assert_called_once()
    resolve_latest.assert_not_called()
    latest_download.assert_not_called()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == 1
    assert receipt["kind"] == "nbadb_verified_public_baseline_receipt"
    assert receipt["receipt"]["exact_dataset_handle"] == ("wyattowalsh/basketball/versions/238")
    assert receipt["receipt"]["remote_dataset_version"] == 238
    assert receipt["receipt"]["remote_inventory"]["file_count"] == len(contents)
    assert receipt["receipt"]["remote_inventory"]["content_identity"] == (
        "exact_api_inventory_and_sha256_full_readback"
    )
    assert receipt["receipt"]["durable_reconciliation"] == {
        "checked": False,
        "ledger": None,
        "resolution": None,
    }
    assert "private_baseline_receipt_sha256" not in receipt_path.read_text(encoding="utf-8")
    canonical_body = json.dumps(
        receipt["receipt"],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    assert receipt["receipt_sha256"] == hashlib.sha256(canonical_body).hexdigest()


@pytest.mark.parametrize("invalid_version", [0, -1, True])
def test_verified_public_baseline_rejects_invalid_caller_version_before_side_effects(
    tmp_path: Path,
    invalid_version: int,
) -> None:
    client = KaggleClient()
    target = tmp_path / "missing-parent" / "public"
    with (
        patch.object(client, "_list_remote_dataset_files") as list_files,
        patch.object(client, "_require_disk_capacity") as capacity,
        pytest.raises(RuntimeError, match="did not resolve an exact dataset version"),
    ):
        client.download_verified_public_baseline(
            target,
            dataset_version=invalid_version,
        )

    assert not target.parent.exists()
    list_files.assert_not_called()
    capacity.assert_not_called()


def test_verified_public_baseline_rejects_preversioned_dataset_configuration(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    client._dataset = "wyattowalsh/basketball/versions/237"
    target = tmp_path / "missing-parent" / "public"

    with pytest.raises(ValueError, match="configuration must not contain a version"):
        client.download_verified_public_baseline(target, dataset_version=238)

    assert not target.parent.exists()


def test_verified_public_baseline_excludes_kagglehub_completion_markers(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)
    scratch_inodes: dict[str, int] = {}

    def download_with_sdk_marker(
        root: Path,
        version: int,
        relative_path: str,
    ) -> tuple[Path, int]:
        downloaded, resolved = _successor_download_file(contents)(root, version, relative_path)
        scratch_inodes[relative_path] = downloaded.stat().st_ino
        marker = root / ".complete" / "datasets" / "wyattowalsh" / "basketball" / "238"
        marker.mkdir(parents=True, exist_ok=True)
        (marker / f"{relative_path}.complete").parent.mkdir(parents=True, exist_ok=True)
        (marker / f"{relative_path}.complete").touch()
        return downloaded, resolved

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=download_with_sdk_marker,
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
    ):
        installed, _receipt = client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
        )

    assert installed == target
    assert not (target / ".complete").exists()
    assert sorted(
        path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
    ) == sorted(contents)
    assert all((target / path).stat().st_ino != scratch_inodes[path] for path in contents)


@pytest.mark.parametrize(
    ("inventory", "message"),
    [
        ([{"path": ".complete/metadata", "bytes": 1}], "reserved KaggleHub metadata"),
        ([{"path": "../escape", "bytes": 1}], "normalized relative path"),
        (
            [{"path": "tables/data.parquet", "bytes": 1}] * 2,
            "duplicate path",
        ),
        (
            [{"path": "tables", "bytes": 1}, {"path": "tables/data.parquet", "bytes": 2}],
            "file/prefix collision",
        ),
    ],
    ids=[
        "reserved-sdk-metadata",
        "traversal",
        "duplicate",
        "file-prefix-collision",
    ],
)
def test_verified_public_baseline_rejects_reserved_or_prefix_colliding_inventory(
    inventory: list[dict[str, object]],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        KaggleClient._validate_verified_download_inventory(inventory)


def test_verified_public_baseline_capacity_accounts_for_scratch_and_candidate(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)
    payload_bytes = sum(len(content) for content in contents.values())
    with (
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity") as capacity,
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
    ):
        client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
        )

    capacity.assert_called_once_with(
        target.parent,
        required_bytes=(payload_bytes * 2) + 1_073_741_824,
        operation="verified public baseline download",
    )


def test_verified_public_baseline_copy_preserves_preexisting_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "candidate" / "data.bin"
    source.write_bytes(b"provider")
    destination.parent.mkdir()
    destination.write_bytes(b"foreign")

    with pytest.raises(FileExistsError):
        KaggleClient._copy_verified_download_file(source, destination)

    assert destination.read_bytes() == b"foreign"


def test_verified_public_baseline_copy_rejects_symlink_and_special_source(
    tmp_path: Path,
) -> None:
    regular = tmp_path / "regular.bin"
    symlink = tmp_path / "symlink.bin"
    fifo = tmp_path / "source.fifo"
    regular.write_bytes(b"provider")
    try:
        symlink.symlink_to(regular)
        os.mkfifo(fifo)
    except OSError as exc:
        pytest.skip(f"symlink or FIFO creation unavailable: {exc}")

    with pytest.raises(ValueError, match="regular file"):
        KaggleClient._copy_verified_download_file(symlink, tmp_path / "symlink-copy.bin")
    with pytest.raises(ValueError, match="regular file"):
        KaggleClient._copy_verified_download_file(fifo, tmp_path / "fifo-copy.bin")

    assert not (tmp_path / "symlink-copy.bin").exists()
    assert not (tmp_path / "fifo-copy.bin").exists()


def test_verified_public_baseline_rolls_back_post_install_tree_drift(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)
    installed_public_tree_bytes = snapshot["installed_public_tree_bytes"]
    assert isinstance(installed_public_tree_bytes, int)
    snapshot["installed_public_tree_bytes"] = installed_public_tree_bytes + 1

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
        pytest.raises(RuntimeError, match="changed during atomic installation"),
    ):
        client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
        )

    assert not target.exists()
    assert not receipt_path.exists()
    assert not list(target.parent.glob(".public.verified-public-baseline-*"))


def test_verified_public_baseline_fsyncs_nested_tree_before_promotion(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)
    real_fsync = os.fsync
    fsynced_identities: list[tuple[int, int]] = []

    def record_fsync(descriptor: int) -> None:
        observed = os.fstat(descriptor)
        if stat.S_ISDIR(observed.st_mode):
            fsynced_identities.append((observed.st_dev, observed.st_ino))
        real_fsync(descriptor)

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
        patch("nbadb.kaggle.client.os.fsync", side_effect=record_fsync),
    ):
        client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
        )

    root_stat = target.stat(follow_symlinks=False)
    nested_stat = (target / "parquet" / "nested").stat(follow_symlinks=False)
    root_identity = (root_stat.st_dev, root_stat.st_ino)
    nested_identity = (nested_stat.st_dev, nested_stat.st_ino)
    assert nested_identity in fsynced_identities
    assert root_identity in fsynced_identities
    assert fsynced_identities.index(nested_identity) < fsynced_identities.index(root_identity)


def test_verified_public_baseline_directory_fsync_failure_prevents_publication(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
        patch(
            "nbadb.kaggle.client._fsync_directory_tree",
            side_effect=OSError(errno.EIO, "candidate fsync failed"),
        ),
        pytest.raises(OSError, match="candidate fsync failed"),
    ):
        client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
        )

    assert not target.exists()
    assert not receipt_path.exists()


def test_verified_public_baseline_receipt_fsync_failure_removes_receipt_and_target(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)
    receipt_path.parent.mkdir(parents=True)
    receipt_parent = receipt_path.parent.stat(follow_symlinks=False)
    receipt_parent_identity = (receipt_parent.st_dev, receipt_parent.st_ino)
    real_fsync = os.fsync
    failed = False

    def fail_receipt_parent_once(descriptor: int) -> None:
        nonlocal failed
        observed = os.fstat(descriptor)
        identity = (observed.st_dev, observed.st_ino)
        if not failed and receipt_path.exists() and identity == receipt_parent_identity:
            failed = True
            raise OSError(errno.EIO, "receipt parent fsync failed")
        real_fsync(descriptor)

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
        patch("nbadb.kaggle.client.os.fsync", side_effect=fail_receipt_parent_once),
        pytest.raises(OSError, match="receipt parent fsync failed"),
    ):
        client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
        )

    assert failed is True
    assert not receipt_path.exists()
    assert not target.exists()


def test_verified_public_baseline_receipt_cleanup_retires_exact_inode(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(b"canonical")
    observed = receipt.stat(follow_symlinks=False)
    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        client_module._unlink_named_regular_file_authority(
            parent_descriptor,
            receipt.name,
            expected_identity=(observed.st_dev, observed.st_ino),
            label="test receipt",
        )
    finally:
        os.close(parent_descriptor)

    assert not receipt.exists()


def test_verified_public_baseline_receipt_cleanup_restores_foreign_race(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    receipt = tmp_path / "receipt.json"
    retained_original = tmp_path / "retained-original.json"
    receipt.write_bytes(b"canonical")
    observed = receipt.stat(follow_symlinks=False)
    real_rename = client_module._rename_directory_no_replace
    race_triggered = False

    def swap_before_retirement(
        source_descriptor: int,
        source_name: str,
        target_descriptor: int,
        target_name: str,
    ) -> None:
        nonlocal race_triggered
        if not race_triggered and source_name == receipt.name and target_name == "receipt":
            race_triggered = True
            os.rename(
                source_name,
                retained_original.name,
                src_dir_fd=source_descriptor,
                dst_dir_fd=source_descriptor,
            )
            foreign_descriptor = os.open(
                source_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=source_descriptor,
            )
            try:
                os.write(foreign_descriptor, b"foreign")
                os.fsync(foreign_descriptor)
            finally:
                os.close(foreign_descriptor)
        real_rename(
            source_descriptor,
            source_name,
            target_descriptor,
            target_name,
        )

    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    try:
        with (
            patch(
                "nbadb.kaggle.client._rename_directory_no_replace",
                side_effect=swap_before_retirement,
            ),
            pytest.raises(RuntimeError, match="restored a substituted file"),
        ):
            client_module._unlink_named_regular_file_authority(
                parent_descriptor,
                receipt.name,
                expected_identity=(observed.st_dev, observed.st_ino),
                label="test receipt",
            )
    finally:
        os.close(parent_descriptor)

    assert race_triggered is True
    assert receipt.read_bytes() == b"foreign"
    assert retained_original.read_bytes() == b"canonical"


def test_verified_public_baseline_receipt_success_rejects_named_inode_swap(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    receipt = tmp_path / "receipt.json"
    retained_original = tmp_path / "retained-original.json"
    real_fsync = os.fsync
    receipt_parent_fsync_count = 0

    def swap_during_second_parent_fsync(descriptor: int) -> None:
        nonlocal receipt_parent_fsync_count
        observed = os.fstat(descriptor)
        parent = tmp_path.stat(follow_symlinks=False)
        if stat.S_ISDIR(observed.st_mode) and (observed.st_dev, observed.st_ino) == (
            parent.st_dev,
            parent.st_ino,
        ):
            receipt_parent_fsync_count += 1
            if receipt_parent_fsync_count == 2:
                os.rename(receipt, retained_original)
                receipt.write_bytes(b"foreign")
        real_fsync(descriptor)

    with (
        patch("nbadb.kaggle.client.os.fsync", side_effect=swap_during_second_parent_fsync),
        pytest.raises(
            RuntimeError,
            match="receipt finalization and exact cleanup failed",
        ),
    ):
        client_module.KaggleClient._atomic_write_canonical_json_no_replace(
            receipt,
            {"ok": True},
        )

    assert receipt.read_bytes() == b"foreign"
    assert retained_original.read_bytes() == b'{"ok":true}\n'


def test_verified_public_baseline_receipt_rejects_pre_parent_temp_name_swap_and_retries(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    receipt = tmp_path / "receipt.json"
    retained_original = tmp_path / "retained-original.json"
    foreign_temporary: Path | None = None
    real_open_stable_directory = client_module._open_stable_directory
    race_triggered = False

    def swap_before_parent_admission(path: Path, *, label: str) -> int:
        nonlocal foreign_temporary, race_triggered
        if not race_triggered and label == "verified public baseline receipt parent":
            candidates = list(tmp_path.glob(".receipt.json.*.tmp"))
            assert len(candidates) == 1
            foreign_temporary = candidates[0]
            candidates[0].rename(retained_original)
            candidates[0].write_bytes(b"foreign")
            candidates[0].chmod(0o600)
            race_triggered = True
        return real_open_stable_directory(path, label=label)

    with (
        patch(
            "nbadb.kaggle.client._open_stable_directory",
            side_effect=swap_before_parent_admission,
        ),
        pytest.raises(RuntimeError, match="temporary differs"),
    ):
        client_module.KaggleClient._atomic_write_canonical_json_no_replace(
            receipt,
            {"ok": True},
        )

    assert race_triggered is True
    assert not receipt.exists()
    assert retained_original.read_bytes() == b'{"ok":true}\n'
    assert foreign_temporary is not None
    assert foreign_temporary.read_bytes() == b"foreign"
    assert not list(tmp_path.glob(".*successor-baseline-rollback-*"))

    client_module.KaggleClient._atomic_write_canonical_json_no_replace(
        receipt,
        {"ok": True},
    )

    assert receipt.read_bytes() == b'{"ok":true}\n'
    assert foreign_temporary.read_bytes() == b"foreign"
    assert not list(tmp_path.glob(".*successor-baseline-rollback-*"))


def test_verified_public_baseline_receipt_early_fsync_failure_exactly_retires_temp(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    receipt = tmp_path / "receipt.json"
    real_fsync = os.fsync
    failed = False

    def fail_first_regular_file_fsync(descriptor: int) -> None:
        nonlocal failed
        observed = os.fstat(descriptor)
        if not failed and stat.S_ISREG(observed.st_mode):
            failed = True
            raise OSError(errno.EIO, "retained receipt fsync failed")
        real_fsync(descriptor)

    with (
        patch("nbadb.kaggle.client.os.fsync", side_effect=fail_first_regular_file_fsync),
        pytest.raises(OSError, match="retained receipt fsync failed"),
    ):
        client_module.KaggleClient._atomic_write_canonical_json_no_replace(
            receipt,
            {"ok": True},
        )

    assert failed is True
    assert not receipt.exists()
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))
    assert not list(tmp_path.glob(".*successor-baseline-rollback-*"))

    client_module.KaggleClient._atomic_write_canonical_json_no_replace(
        receipt,
        {"ok": True},
    )
    assert receipt.read_bytes() == b'{"ok":true}\n'


def test_verified_public_baseline_receipt_fchmod_failure_exactly_retires_temp(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    receipt = tmp_path / "receipt.json"
    real_fchmod = os.fchmod
    failed = False

    def fail_first_fchmod(descriptor: int, mode: int) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError(errno.EIO, "retained receipt fchmod failed")
        real_fchmod(descriptor, mode)

    with (
        patch("nbadb.kaggle.client.os.fchmod", side_effect=fail_first_fchmod),
        pytest.raises(OSError, match="retained receipt fchmod failed"),
    ):
        client_module.KaggleClient._atomic_write_canonical_json_no_replace(
            receipt,
            {"ok": True},
        )

    assert failed is True
    assert not receipt.exists()
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))
    assert not list(tmp_path.glob(".*successor-baseline-rollback-*"))

    client_module.KaggleClient._atomic_write_canonical_json_no_replace(
        receipt,
        {"ok": True},
    )
    assert receipt.read_bytes() == b'{"ok":true}\n'


def test_verified_public_baseline_receipt_rejects_retained_inode_content_mutation(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    receipt = tmp_path / "receipt.json"
    retained_descriptor = -1
    real_fsync = os.fsync
    real_link = os.link
    mutated = False

    def capture_retained_descriptor(descriptor: int) -> None:
        nonlocal retained_descriptor
        observed = os.fstat(descriptor)
        if retained_descriptor < 0 and stat.S_ISREG(observed.st_mode):
            retained_descriptor = descriptor
        real_fsync(descriptor)

    def mutate_retained_inode_before_link(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal mutated
        if not mutated and destination == receipt.name:
            assert retained_descriptor >= 0
            if hasattr(os, "pwrite"):
                os.pwrite(retained_descriptor, b"!", 0)
            else:
                os.lseek(retained_descriptor, 0, os.SEEK_SET)
                os.write(retained_descriptor, b"!")
            real_fsync(retained_descriptor)
            mutated = True
        real_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    with (
        patch("nbadb.kaggle.client.os.fsync", side_effect=capture_retained_descriptor),
        patch("nbadb.kaggle.client.os.link", side_effect=mutate_retained_inode_before_link),
        pytest.raises(RuntimeError, match="content changed"),
    ):
        client_module.KaggleClient._atomic_write_canonical_json_no_replace(
            receipt,
            {"ok": True},
        )

    assert mutated is True
    assert not receipt.exists()
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))
    assert not list(tmp_path.glob(".*successor-baseline-rollback-*"))


def test_verified_public_baseline_receipt_rejects_unexpected_extra_hardlink(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    receipt = tmp_path / "receipt.json"
    extra_link = tmp_path / "unexpected-hardlink.json"
    real_link = os.link
    injected = False

    def add_unexpected_link(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal injected
        if not injected and destination == receipt.name:
            assert isinstance(src_dir_fd, int)
            real_link(
                source,
                extra_link.name,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=src_dir_fd,
                follow_symlinks=False,
            )
            injected = True
        real_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    with (
        patch("nbadb.kaggle.client.os.link", side_effect=add_unexpected_link),
        pytest.raises(RuntimeError, match="differs from the admitted file authority"),
    ):
        client_module.KaggleClient._atomic_write_canonical_json_no_replace(
            receipt,
            {"ok": True},
        )

    assert injected is True
    assert not receipt.exists()
    assert extra_link.read_bytes() == b'{"ok":true}\n'
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))
    assert not list(tmp_path.glob(".*successor-baseline-rollback-*"))


@pytest.mark.parametrize("foreign_kind", ["symlink", "fifo"])
def test_verified_public_baseline_receipt_cleanup_restores_nonregular_substitution_bounded(
    tmp_path: Path,
    foreign_kind: str,
) -> None:
    import nbadb.kaggle.client as client_module

    if not hasattr(signal, "setitimer"):
        pytest.skip("bounded POSIX signal timer is unavailable")
    receipt = tmp_path / "receipt.json"
    retained_original = tmp_path / "retained-original.json"
    receipt.write_bytes(b"canonical")
    observed = receipt.stat(follow_symlinks=False)
    real_rename = client_module._rename_directory_no_replace
    race_triggered = False

    def substitute_before_retirement(
        source_descriptor: int,
        source_name: str,
        target_descriptor: int,
        target_name: str,
    ) -> None:
        nonlocal race_triggered
        if not race_triggered and source_name == receipt.name and target_name == "receipt":
            race_triggered = True
            os.rename(
                source_name,
                retained_original.name,
                src_dir_fd=source_descriptor,
                dst_dir_fd=source_descriptor,
            )
            if foreign_kind == "symlink":
                os.symlink(
                    "foreign-target",
                    source_name,
                    dir_fd=source_descriptor,
                )
            else:
                os.mkfifo(source_name, 0o600, dir_fd=source_descriptor)
        real_rename(
            source_descriptor,
            source_name,
            target_descriptor,
            target_name,
        )

    def fail_on_timeout(_signum: int, _frame: object) -> None:
        raise TimeoutError("receipt cleanup blocked on a nonregular substitution")

    parent_descriptor = os.open(tmp_path, os.O_RDONLY)
    prior_handler = signal.getsignal(signal.SIGALRM)
    try:
        signal.signal(signal.SIGALRM, fail_on_timeout)
        signal.setitimer(signal.ITIMER_REAL, 2.0)
        with (
            patch(
                "nbadb.kaggle.client._rename_directory_no_replace",
                side_effect=substitute_before_retirement,
            ),
            pytest.raises(RuntimeError, match="restored a substituted file"),
        ):
            client_module._unlink_named_regular_file_authority(
                parent_descriptor,
                receipt.name,
                expected_identity=(observed.st_dev, observed.st_ino),
                label="test receipt",
            )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, prior_handler)
        os.close(parent_descriptor)

    assert race_triggered is True
    assert retained_original.read_bytes() == b"canonical"
    if foreign_kind == "symlink":
        assert receipt.is_symlink()
        assert os.readlink(receipt) == "foreign-target"
    else:
        assert stat.S_ISFIFO(receipt.stat(follow_symlinks=False).st_mode)
    assert not list(tmp_path.glob(".*successor-baseline-rollback-*"))


def test_verified_public_baseline_receipt_retained_close_failure_is_non_authoritative(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    receipt = tmp_path / "receipt.json"
    retained_descriptor = -1
    real_fsync = os.fsync
    real_close = os.close
    close_failed = False

    def capture_retained_descriptor(descriptor: int) -> None:
        nonlocal retained_descriptor
        observed = os.fstat(descriptor)
        if retained_descriptor < 0 and stat.S_ISREG(observed.st_mode):
            retained_descriptor = descriptor
        real_fsync(descriptor)

    def fail_retained_close_after_close(descriptor: int) -> None:
        nonlocal close_failed
        if not close_failed and descriptor == retained_descriptor:
            close_failed = True
            real_close(descriptor)
            raise OSError(errno.EIO, "retained descriptor close failed")
        real_close(descriptor)

    with (
        patch("nbadb.kaggle.client.os.fsync", side_effect=capture_retained_descriptor),
        patch("nbadb.kaggle.client.os.close", side_effect=fail_retained_close_after_close),
    ):
        client_module.KaggleClient._atomic_write_canonical_json_no_replace(
            receipt,
            {"ok": True},
        )

    assert close_failed is True
    assert receipt.read_bytes() == b'{"ok":true}\n'
    assert not list(tmp_path.glob(".receipt.json.*.tmp"))
    assert not list(tmp_path.glob(".*successor-baseline-rollback-*"))


def test_verified_public_baseline_workspace_cleanup_failure_does_not_reverse_commit(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
        patch.object(
            tempfile.TemporaryDirectory,
            "cleanup",
            side_effect=OSError(errno.EIO, "workspace cleanup failed"),
        ),
    ):
        installed, emitted_receipt = client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
        )

    assert installed == target
    assert emitted_receipt == receipt_path
    assert target.is_dir()
    assert receipt_path.is_file()
    for workspace in target.parent.glob(".public.verified-public-baseline-*"):
        workspace.rmdir()


def test_public_baseline_api_has_no_private_receipt_parameter() -> None:
    signature = inspect.signature(KaggleClient.download_verified_public_baseline)

    assert "private_baseline_receipt_sha256" not in signature.parameters
    assert not hasattr(KaggleClient, "download_successor_baseline")


def test_download_verified_public_baseline_does_not_promote_unresolved_ledger_mismatch(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)
    unresolved = SimpleNamespace(intent_id="unresolved-intent")
    ledger = MagicMock()
    ledger.scan_dataset.return_value = SimpleNamespace(unresolved=(unresolved,))
    with (
        patch.object(
            client,
            "_resolve_remote_dataset_version",
            side_effect=AssertionError("exact verified download must not resolve latest"),
        ) as resolve_latest,
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
        patch.object(client, "_reconcile_durable_publication", return_value=None),
        pytest.raises(RuntimeError, match="does not match the exact verified public baseline"),
    ):
        client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
            publication_ledger=ledger,
            require_durable_reconciliation=True,
        )

    assert not target.exists()
    assert not receipt_path.exists()
    resolve_latest.assert_not_called()
    ledger.scan_dataset.assert_called_once_with("wyattowalsh/basketball")


def test_download_verified_public_baseline_reconciles_matching_unresolved_intent(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents, inventory, target, receipt_path, snapshot = _verified_public_download_case(tmp_path)
    unresolved = SimpleNamespace(intent_id="matching-intent")
    ledger = MagicMock()
    ledger.scan_dataset.side_effect = [
        SimpleNamespace(unresolved=(unresolved,)),
        SimpleNamespace(unresolved=()),
    ]
    resolution = {
        "deployment_id": 101,
        "status_id": 202,
        "intent_id": "matching-intent",
        "resolved_version": 238,
        "publication_marker_sha256": "a" * 64,
        "readback_fingerprint": "b" * 64,
        "resolution_digest": "c" * 64,
        "url": "https://github.example/receipt/202",
    }
    with (
        patch.object(
            client,
            "_resolve_remote_dataset_version",
            side_effect=AssertionError("exact verified download must not resolve latest"),
        ) as resolve_latest,
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
        patch.object(
            client,
            "_reconcile_durable_publication",
            return_value=resolution,
        ) as reconcile,
    ):
        installed, emitted_receipt = client.download_verified_public_baseline(
            target,
            dataset_version=238,
            receipt_path=receipt_path,
            remote_timeout_seconds=30,
            publication_ledger=ledger,
            require_durable_reconciliation=True,
        )

    assert installed == target
    assert emitted_receipt == receipt_path
    resolve_latest.assert_not_called()
    reconcile.assert_called_once()
    assert ledger.scan_dataset.call_count == 2
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["receipt"]["durable_reconciliation"] == {
        "checked": True,
        "ledger": "github_deployment",
        "resolution": resolution,
    }


def _successor_download_case(
    tmp_path: Path,
) -> tuple[dict[str, bytes], list[dict[str, object]], Path, dict[str, object]]:
    contents = {
        "dataset-metadata.json": b"{}\n",
        "nbadb-publication.json": b"{}\n",
        "assured-artifact-manifest.json": b"m" * 13,
        "terminal-assurance-report.json": b"r" * 11,
    }
    inventory: list[dict[str, object]] = [
        {"path": path, "bytes": len(content)} for path, content in sorted(contents.items())
    ]
    expected_installed_tree = tmp_path / "expected-installed-public"
    _write_remote_tree(expected_installed_tree, contents)
    installed = measure_installed_public_tree(expected_installed_tree)
    snapshot = _verified_successor_snapshot()
    snapshot["installed_public_tree_sha256"] = installed.installed_public_tree_sha256
    snapshot["installed_public_tree_bytes"] = installed.byte_count
    return contents, inventory, tmp_path / "candidate" / "public", snapshot


def _run_mocked_successor_download(
    client: KaggleClient,
    *,
    target: Path,
    contents: dict[str, bytes],
    inventory: list[dict[str, object]],
    snapshot: dict[str, object],
) -> BaselineAssuranceIdentity:
    with (
        patch.object(client, "_resolve_remote_dataset_version", side_effect=[238, 238]),
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
    ):
        return client._download_successor_baseline_compat(
            target,
            remote_dataset_version=238,
            private_baseline_receipt_sha256="b" * 64,
        )


def test_download_successor_baseline_installs_only_after_exact_validation(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents = {
        "dataset-metadata.json": b"{}\n",
        "nbadb-publication.json": b"{}\n",
        "assured-artifact-manifest.json": b"m" * 13,
        "terminal-assurance-report.json": b"r" * 11,
    }
    inventory = [
        {"path": path, "bytes": len(content)} for path, content in sorted(contents.items())
    ]
    target = tmp_path / "candidate" / "public"
    expected_installed_tree = tmp_path / "expected-installed-public"
    _write_remote_tree(expected_installed_tree, contents)
    snapshot = _verified_successor_snapshot()
    snapshot["installed_public_tree_sha256"] = measure_installed_public_tree(
        expected_installed_tree
    ).installed_public_tree_sha256
    snapshot["installed_public_tree_bytes"] = measure_installed_public_tree(
        expected_installed_tree
    ).byte_count
    with (
        patch.object(client, "_resolve_remote_dataset_version", side_effect=[238, 238]),
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ) as download,
        patch.object(client, "_require_disk_capacity") as capacity,
        patch.object(client, "_validate_publication_marker") as validate_marker,
        patch.object(client, "_assert_remote_marker_inventory_matches") as validate_inventory,
        patch.object(
            client,
            "_snapshot_upload_bundle",
            return_value=snapshot,
        ) as validate_bundle,
    ):
        identity = client._download_successor_baseline_compat(
            target,
            remote_dataset_version=238,
            private_baseline_receipt_sha256="b" * 64,
        )

    assert target.is_dir()
    installed_files = {
        path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file()
    }
    assert installed_files == set(contents)
    assert download.call_count == len(contents)
    capacity.assert_called_once()
    validate_marker.assert_called_once_with({})
    validate_inventory.assert_called_once()
    validate_bundle.assert_called_once_with(
        validate_bundle.call_args.args[0],
        require_assured=True,
        require_terminal_assurance=True,
    )
    assert identity.remote_dataset_version == 238
    assert identity.private_baseline_receipt_sha256 == "b" * 64


def test_download_successor_baseline_rejects_complete_tree_byte_count_drift(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    contents = {
        "dataset-metadata.json": b"{}\n",
        "nbadb-publication.json": b"{}\n",
        "nba.duckdb": b"duckdb",
    }
    inventory = [
        {"path": path, "bytes": len(content)} for path, content in sorted(contents.items())
    ]
    target = tmp_path / "candidate" / "public"
    expected_installed_tree = tmp_path / "expected-installed-public"
    _write_remote_tree(expected_installed_tree, contents)
    installed = measure_installed_public_tree(expected_installed_tree)
    snapshot = _verified_successor_snapshot()
    snapshot["installed_public_tree_sha256"] = installed.installed_public_tree_sha256
    snapshot["installed_public_tree_bytes"] = installed.byte_count + 1

    with (
        patch.object(client, "_resolve_remote_dataset_version", side_effect=[238, 238]),
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_successor_download_file(contents),
        ),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(client, "_snapshot_upload_bundle", return_value=snapshot),
        pytest.raises(RuntimeError, match="changed during atomic staging"),
    ):
        client._download_successor_baseline_compat(
            target,
            remote_dataset_version=238,
            private_baseline_receipt_sha256="b" * 64,
        )

    assert not target.exists()
    assert not list(target.parent.glob(".public.successor-baseline-*"))


def test_download_successor_baseline_initial_publish_preserves_occupied_target(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    client = KaggleClient()
    contents, inventory, target, snapshot = _successor_download_case(tmp_path)
    real_rename = client_module._rename_directory_no_replace
    rename_calls = 0
    foreign_identity: tuple[int, int] | None = None
    foreign_mode: int | None = None

    def occupy_target_at_publish(
        source_descriptor: int,
        source_name: str,
        target_descriptor: int,
        target_name: str,
    ) -> None:
        nonlocal foreign_identity, foreign_mode, rename_calls
        rename_calls += 1
        assert source_name == "public"
        assert target_name == target.name
        os.mkdir(target_name, mode=0o700, dir_fd=target_descriptor)
        os.chmod(target_name, 0o711, dir_fd=target_descriptor, follow_symlinks=False)
        observed = os.stat(target_name, dir_fd=target_descriptor, follow_symlinks=False)
        foreign_identity = observed.st_dev, observed.st_ino
        foreign_mode = stat.S_IMODE(observed.st_mode)
        real_rename(
            source_descriptor,
            source_name,
            target_descriptor,
            target_name,
        )

    with (
        patch(
            "nbadb.kaggle.client._rename_directory_no_replace",
            side_effect=occupy_target_at_publish,
        ),
        patch(
            "nbadb.orchestrate.successor_baseline.baseline_identity_from_verified_publication"
        ) as identity_builder,
        pytest.raises(OSError) as raised,
    ):
        _run_mocked_successor_download(
            client,
            target=target,
            contents=contents,
            inventory=inventory,
            snapshot=snapshot,
        )

    assert raised.value.errno == errno.EEXIST
    assert rename_calls == 1
    identity_builder.assert_not_called()
    observed_target = target.stat(follow_symlinks=False)
    assert (observed_target.st_dev, observed_target.st_ino) == foreign_identity
    assert stat.S_IMODE(observed_target.st_mode) == foreign_mode == 0o711
    assert not list(target.parent.glob(".public.successor-baseline-*"))

    with pytest.raises(FileExistsError, match="must not already exist"):
        _run_mocked_successor_download(
            client,
            target=target,
            contents=contents,
            inventory=inventory,
            snapshot=snapshot,
        )

    target.rmdir()
    retry_snapshot = _successor_download_case(tmp_path / "retry-evidence")[3]
    identity = _run_mocked_successor_download(
        client,
        target=target,
        contents=contents,
        inventory=inventory,
        snapshot=retry_snapshot,
    )

    assert target.is_dir()
    assert identity.remote_dataset_version == 238


@pytest.mark.parametrize(
    "failure_stage",
    ["fsync", "measurement", "digest", "bytes", "identity"],
)
def test_download_successor_baseline_post_rename_failures_roll_back_and_retry(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    client = KaggleClient()
    contents, inventory, target, snapshot = _successor_download_case(tmp_path)
    original_fsync = os.fsync
    fsync_calls: list[int] = []

    def fail_first_fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        if len(fsync_calls) == 1:
            raise OSError("deterministic parent fsync failure")
        original_fsync(descriptor)

    with ExitStack() as stack:
        if failure_stage == "fsync":
            stack.enter_context(patch("nbadb.kaggle.client.os.fsync", side_effect=fail_first_fsync))
        elif failure_stage == "measurement":
            stack.enter_context(
                patch(
                    "nbadb.kaggle.client.measure_installed_public_tree",
                    side_effect=OSError("deterministic measurement failure"),
                )
            )
        elif failure_stage == "digest":
            snapshot["installed_public_tree_sha256"] = "f" * 64
        elif failure_stage == "bytes":
            installed_public_tree_bytes = snapshot["installed_public_tree_bytes"]
            assert isinstance(installed_public_tree_bytes, int)
            snapshot["installed_public_tree_bytes"] = installed_public_tree_bytes + 1
        else:
            stack.enter_context(
                patch(
                    "nbadb.orchestrate.successor_baseline."
                    "baseline_identity_from_verified_publication",
                    side_effect=ValueError("deterministic identity construction failure"),
                )
            )

        with pytest.raises((OSError, RuntimeError, ValueError)):
            _run_mocked_successor_download(
                client,
                target=target,
                contents=contents,
                inventory=inventory,
                snapshot=snapshot,
            )

    assert not target.exists()
    assert not list(target.parent.glob(".public.successor-baseline-rollback-*"))

    retry_snapshot = _successor_download_case(tmp_path / "retry-evidence")[3]
    identity = _run_mocked_successor_download(
        client,
        target=target,
        contents=contents,
        inventory=inventory,
        snapshot=retry_snapshot,
    )

    assert target.is_dir()
    assert identity.installed_public_tree_bytes == retry_snapshot["installed_public_tree_bytes"]
    if failure_stage == "fsync":
        assert len(fsync_calls) >= 2


@pytest.mark.parametrize("replacement_kind", ["same_inventory", "foreign_inventory"])
def test_download_successor_baseline_rollback_restores_substituted_target_without_deletion(
    tmp_path: Path,
    replacement_kind: str,
) -> None:
    import nbadb.kaggle.client as client_module

    client = KaggleClient()
    contents, inventory, target, snapshot = _successor_download_case(tmp_path)
    snapshot["installed_public_tree_sha256"] = "f" * 64
    real_rename = client_module._rename_directory_no_replace
    observed: dict[str, tuple[int, int]] = {}
    raced = False

    def race_first_rollback_rename(
        source_descriptor: int,
        source_name: str,
        target_descriptor: int,
        target_name: str,
    ) -> None:
        nonlocal raced
        if not raced and source_name == target.name and target_name == "renamed-target":
            raced = True
            admitted_aside = target.parent / "admitted-aside"
            os.rename(target, admitted_aside)
            observed["admitted"] = (
                admitted_aside.stat(follow_symlinks=False).st_dev,
                admitted_aside.stat(follow_symlinks=False).st_ino,
            )
            if replacement_kind == "same_inventory":
                shutil.copytree(admitted_aside, target)
            else:
                target.mkdir()
                (target / "foreign.txt").write_text("foreign target\n", encoding="utf-8")
            replacement = target.stat(follow_symlinks=False)
            observed["replacement"] = replacement.st_dev, replacement.st_ino
        real_rename(
            source_descriptor,
            source_name,
            target_descriptor,
            target_name,
        )

    with (
        patch(
            "nbadb.kaggle.client._rename_directory_no_replace",
            side_effect=race_first_rollback_rename,
        ),
        pytest.raises(RuntimeError, match="exact rollback could not complete"),
    ):
        _run_mocked_successor_download(
            client,
            target=target,
            contents=contents,
            inventory=inventory,
            snapshot=snapshot,
        )

    assert raced
    assert target.is_dir()
    target_stat = target.stat(follow_symlinks=False)
    assert (target_stat.st_dev, target_stat.st_ino) == observed["replacement"]
    admitted_aside = target.parent / "admitted-aside"
    assert admitted_aside.is_dir()
    admitted_stat = admitted_aside.stat(follow_symlinks=False)
    assert (admitted_stat.st_dev, admitted_stat.st_ino) == observed["admitted"]
    if replacement_kind == "same_inventory":
        assert (
            measure_installed_public_tree(target).installed_public_tree_sha256
            == measure_installed_public_tree(admitted_aside).installed_public_tree_sha256
        )
    else:
        assert (target / "foreign.txt").read_text(encoding="utf-8") == "foreign target\n"
    assert not list(target.parent.glob(".public.successor-baseline-rollback-*"))


def test_download_successor_baseline_rollback_retains_foreign_quarantine_when_restore_blocked(
    tmp_path: Path,
) -> None:
    import nbadb.kaggle.client as client_module

    client = KaggleClient()
    contents, inventory, target, snapshot = _successor_download_case(tmp_path)
    snapshot["installed_public_tree_sha256"] = "f" * 64
    real_rename = client_module._rename_directory_no_replace
    rollback_calls = 0

    def race_rollback_restore(
        source_descriptor: int,
        source_name: str,
        target_descriptor: int,
        target_name: str,
    ) -> None:
        nonlocal rollback_calls
        if target_name == "renamed-target":
            rollback_calls += 1
            admitted_aside = target.parent / "admitted-aside"
            os.rename(target, admitted_aside)
            target.mkdir()
            (target / "first-foreign.txt").write_text("first\n", encoding="utf-8")
        elif source_name == "renamed-target":
            rollback_calls += 1
            target.mkdir()
            (target / "newer-target.txt").write_text("newer\n", encoding="utf-8")
        real_rename(
            source_descriptor,
            source_name,
            target_descriptor,
            target_name,
        )

    with (
        patch(
            "nbadb.kaggle.client._rename_directory_no_replace",
            side_effect=race_rollback_restore,
        ),
        pytest.raises(RuntimeError, match="exact rollback could not complete"),
    ):
        _run_mocked_successor_download(
            client,
            target=target,
            contents=contents,
            inventory=inventory,
            snapshot=snapshot,
        )

    assert rollback_calls == 2
    assert (target / "newer-target.txt").read_text(encoding="utf-8") == "newer\n"
    assert (target.parent / "admitted-aside").is_dir()
    quarantines = list(target.parent.glob(".public.successor-baseline-rollback-*"))
    assert len(quarantines) == 1
    assert stat.S_IMODE(quarantines[0].stat(follow_symlinks=False).st_mode) == 0o700
    assert (quarantines[0] / "renamed-target" / "first-foreign.txt").read_text(
        encoding="utf-8"
    ) == "first\n"


@pytest.mark.parametrize("failure_stage", ["download", "remote_drift"])
def test_download_successor_baseline_never_promotes_partial_state(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    client = KaggleClient()
    contents = {
        "dataset-metadata.json": b"{}\n",
        "nbadb-publication.json": b"{}\n",
    }
    inventory = [
        {"path": path, "bytes": len(content)} for path, content in sorted(contents.items())
    ]
    target = tmp_path / "candidate" / "public"
    downloader = _successor_download_file(contents)
    if failure_stage == "download":
        downloader = MagicMock(side_effect=OSError("interrupted"))
    versions = [238, 239] if failure_stage == "remote_drift" else [238]
    with (
        patch.object(client, "_resolve_remote_dataset_version", side_effect=versions),
        patch.object(client, "_list_remote_dataset_files", return_value=inventory),
        patch.object(client, "_download_remote_dataset_file", side_effect=downloader),
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_validate_publication_marker"),
        patch.object(client, "_assert_remote_marker_inventory_matches"),
        patch.object(
            client,
            "_snapshot_upload_bundle",
            return_value=_verified_successor_snapshot(),
        ),
        pytest.raises((OSError, RuntimeError)),
    ):
        client._download_successor_baseline_compat(
            target,
            remote_dataset_version=238,
            private_baseline_receipt_sha256="b" * 64,
        )

    assert not target.exists()
    assert not list(target.parent.glob(".public.successor-baseline-*"))


def test_download_successor_baseline_rejects_existing_target_before_remote_calls(
    tmp_path: Path,
) -> None:
    client = KaggleClient()
    target = tmp_path / "public"
    target.mkdir()
    with (
        patch.object(client, "_resolve_remote_dataset_version") as resolve,
        pytest.raises(FileExistsError, match="must not already exist"),
    ):
        client._download_successor_baseline_compat(
            target,
            remote_dataset_version=238,
            private_baseline_receipt_sha256="b" * 64,
        )
    resolve.assert_not_called()


def test_list_remote_dataset_files_paginates_exact_version() -> None:
    first_page = SimpleNamespace(
        dataset_files=[
            SimpleNamespace(name="dataset-metadata.json", total_bytes=8),
            SimpleNamespace(name="csv/stg_common_all_players.csv", total_bytes=12),
        ],
        error_message="",
        next_page_token="next-page",
    )
    second_page = SimpleNamespace(
        dataset_files=[
            SimpleNamespace(
                name="parquet/stg_common_all_players/stg_common_all_players.parquet",
                total_bytes=16,
            )
        ],
        error_message="",
        next_page_token="",
    )
    api_client = MagicMock()
    api_client.__enter__.return_value = api_client
    list_files = api_client.datasets.dataset_api_client.list_dataset_files
    list_files.side_effect = [first_page, second_page]

    with patch("kagglehub.clients.build_kaggle_client", return_value=api_client):
        inventory = KaggleClient()._list_remote_dataset_files(42)

    assert inventory == [
        {"path": "csv/stg_common_all_players.csv", "bytes": 12},
        {"path": "dataset-metadata.json", "bytes": 8},
        {
            "path": "parquet/stg_common_all_players/stg_common_all_players.parquet",
            "bytes": 16,
        },
    ]
    requests = [call.args[0] for call in list_files.call_args_list]
    assert [request.dataset_version_number for request in requests] == [42, 42]
    assert [request.page_token for request in requests] == ["", "next-page"]
    api_client.__exit__.assert_called_once()


def test_list_remote_dataset_files_rejects_noncanonical_api_path() -> None:
    response = SimpleNamespace(
        dataset_files=[SimpleNamespace(name=" tables/data.parquet", total_bytes=16)],
        error_message="",
        next_page_token="",
    )
    api_client = MagicMock()
    api_client.__enter__.return_value = api_client
    api_client.datasets.dataset_api_client.list_dataset_files.return_value = response

    with (
        patch("kagglehub.clients.build_kaggle_client", return_value=api_client),
        pytest.raises(ValueError, match="noncanonical path"),
    ):
        KaggleClient()._list_remote_dataset_files(42)


def test_verify_remote_bundle_accepts_complete_staging_inventory(tmp_path) -> None:
    files = {
        "dataset-metadata.json": b"metadata",
        "nbadb-publication.json": b"marker",
        "csv/stg_common_all_players.csv": b"person_id\n1\n",
        "parquet/stg_common_all_players/stg_common_all_players.parquet": b"PAR1",
    }
    remote_root = tmp_path / "remote"
    _write_remote_tree(remote_root, files)
    expected_tree = _remote_tree(files)
    api_inventory = [
        {"path": path, "bytes": len(content)} for path, content in sorted(files.items())
    ]
    client = KaggleClient()

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=api_inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_remote_file_downloader(remote_root),
        ),
    ):
        result = client._verify_remote_bundle(expected_tree, version=42)

    assert result["file_count"] == len(files)
    assert result["fingerprint"] == expected_tree["fingerprint"]
    assert result["content_identity"] == "sha256_full_readback"


def test_download_remote_dataset_file_rejects_resolver_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside.csv"
    outside.write_text("id\n1\n", encoding="utf-8")
    download_root = tmp_path / "readback"
    download_root.mkdir()
    client = KaggleClient()

    with (
        patch(
            "kagglehub.registry.dataset_resolver",
            return_value=(str(outside), 42),
        ),
        pytest.raises(ValueError, match="escaped its download root"),
    ):
        client._download_remote_dataset_file(download_root, 42, "csv/table.csv")


def test_download_remote_dataset_file_uses_exact_versioned_resolver_contract(
    tmp_path: Path,
) -> None:
    download_root = tmp_path / "readback"
    downloaded = download_root / "csv" / "table.csv"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_text("id\n1\n", encoding="utf-8")
    client = KaggleClient()

    with patch(
        "kagglehub.registry.dataset_resolver",
        return_value=(str(downloaded), 42),
    ) as resolver:
        result, resolved_version = client._download_remote_dataset_file(
            download_root,
            42,
            "csv/table.csv",
        )

    assert result == downloaded.resolve()
    assert resolved_version == 42
    resolver.assert_called_once()
    handle, relative_path = resolver.call_args.args
    assert str(handle) == "wyattowalsh/basketball/versions/42"
    assert relative_path == "csv/table.csv"
    assert resolver.call_args.kwargs == {
        "output_dir": str(download_root),
        "force_download": True,
    }


def test_download_remote_dataset_file_rejects_wrong_resolved_version(
    tmp_path: Path,
) -> None:
    download_root = tmp_path / "readback"
    downloaded = download_root / "csv" / "table.csv"
    downloaded.parent.mkdir(parents=True)
    downloaded.write_text("id\n1\n", encoding="utf-8")

    with (
        patch(
            "kagglehub.registry.dataset_resolver",
            return_value=(str(downloaded), 43),
        ),
        pytest.raises(RuntimeError, match="resolved the wrong dataset version"),
    ):
        KaggleClient()._download_remote_dataset_file(
            download_root,
            42,
            "csv/table.csv",
        )


def test_snapshot_remote_files_streaming_rejects_deadline_overrun(tmp_path: Path) -> None:
    remote_root = tmp_path / "remote"
    _write_remote_tree(remote_root, {"dataset-metadata.json": b"metadata"})
    client = KaggleClient()

    with (
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_remote_file_downloader(remote_root),
        ) as download,
        patch.object(client, "_require_disk_capacity"),
        patch.object(client, "_monotonic", side_effect=[0.0, 2.0]),
        pytest.raises(TimeoutError, match="remote file download exceeded"),
    ):
        client._snapshot_remote_files_streaming(
            tmp_path / "readback",
            [{"path": "dataset-metadata.json", "bytes": 8}],
            version=42,
            deadline=1.0,
        )

    download.assert_called_once()


def test_verify_remote_bundle_rejects_malformed_expected_tree() -> None:
    client = KaggleClient()

    with (
        patch.object(client, "_list_remote_dataset_files") as list_files,
        pytest.raises(ValueError, match="expected staged file inventory must be a list"),
    ):
        client._verify_remote_bundle({}, version=42)

    list_files.assert_not_called()


def test_verify_remote_bundle_rejects_missing_staging_resource(tmp_path) -> None:
    files = {
        "dataset-metadata.json": b"metadata",
        "nbadb-publication.json": b"marker",
        "csv/stg_common_all_players.csv": b"person_id\n1\n",
    }
    expected_tree = _remote_tree(files)
    api_inventory = [
        {"path": path, "bytes": len(content)}
        for path, content in sorted(files.items())
        if not path.startswith("csv/stg_")
    ]
    client = KaggleClient()

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=api_inventory),
        patch.object(client, "_download_remote_dataset_file") as download,
        pytest.raises(ValueError, match="missing=.*csv/stg_common_all_players.csv"),
    ):
        client._verify_remote_bundle(expected_tree, version=42)

    download.assert_not_called()


def test_verify_remote_bundle_rejects_extra_remote_resource(tmp_path) -> None:
    files = {
        "dataset-metadata.json": b"metadata",
        "nbadb-publication.json": b"marker",
    }
    api_inventory = [
        {"path": path, "bytes": len(content)} for path, content in sorted(files.items())
    ]
    api_inventory.append({"path": "csv/undeclared.csv", "bytes": 7})
    client = KaggleClient()

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=api_inventory),
        patch.object(client, "_download_remote_dataset_file") as download,
        pytest.raises(ValueError, match="extra=.*csv/undeclared.csv"),
    ):
        client._verify_remote_bundle(_remote_tree(files), version=42)

    download.assert_not_called()


def test_verify_remote_bundle_rejects_same_size_content_corruption(tmp_path) -> None:
    expected_files = {
        "dataset-metadata.json": b"metadata",
        "nbadb-publication.json": b"marker",
        "csv/stg_common_all_players.csv": b"person_id\n1\n",
    }
    remote_files = {**expected_files, "csv/stg_common_all_players.csv": b"person_id\n2\n"}
    remote_root = tmp_path / "remote"
    _write_remote_tree(remote_root, remote_files)
    api_inventory = [
        {"path": path, "bytes": len(content)} for path, content in sorted(expected_files.items())
    ]
    client = KaggleClient()

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=api_inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_remote_file_downloader(remote_root),
        ),
        pytest.raises(ValueError, match="sha256=.*csv/stg_common_all_players.csv"),
    ):
        client._verify_remote_bundle(_remote_tree(expected_files), version=42)


def test_verify_remote_bundle_reconciles_marker_attested_staging_content(tmp_path) -> None:
    client = KaggleClient()
    metadata = b"metadata"
    staging = b"person_id\n1\n"
    staging_path = "csv/stg_common_all_players.csv"
    resource = {
        "path": staging_path,
        "kind": "file",
        "bytes": len(staging),
        "sha256": hashlib.sha256(staging).hexdigest(),
    }
    metadata_sha256 = hashlib.sha256(metadata).hexdigest()
    fingerprint_payload = {
        "metadata_sha256": metadata_sha256,
        "resources": [resource],
    }
    bundle_fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    data_files = {
        "dataset-metadata.json": metadata,
        staging_path: staging,
    }
    data_tree = _remote_tree(data_files)
    marker = client._publication_marker_payload(
        preflight={
            "fingerprint": bundle_fingerprint,
            "metadata_sha256": metadata_sha256,
            "resource_count": 1,
            "resource_bytes": len(staging),
            "resources": [resource],
            "provenance": None,
        },
        publish_key="a" * 20,
        data_tree_fingerprint=str(data_tree["fingerprint"]),
    )
    remote_files = {
        **data_files,
        "nbadb-publication.json": client._publication_marker_bytes(marker),
    }
    remote_root = tmp_path / "remote"
    _write_remote_tree(remote_root, remote_files)
    api_inventory = [
        {"path": path, "bytes": len(content)} for path, content in sorted(remote_files.items())
    ]

    with (
        patch.object(client, "_list_remote_dataset_files", return_value=api_inventory),
        patch.object(
            client,
            "_download_remote_dataset_file",
            side_effect=_remote_file_downloader(remote_root),
        ),
    ):
        result = client._verify_remote_bundle(None, expected_marker=marker, version=42)

    assert result["content_identity"] == "sha256_full_readback"


def test_verify_remote_upload_requires_complete_resource_readback() -> None:
    client = KaggleClient()
    marker = _valid_publication_marker()
    expected_tree = _remote_tree({"dataset-metadata.json": b"metadata"})
    resource_verification = {
        "version": 42,
        "file_count": 3,
        "bytes": 24,
        "fingerprint": "f" * 64,
        "api_file_count": 3,
        "content_identity": "sha256_full_readback",
    }

    with (
        patch.object(client, "_download_remote_publication_marker", return_value=(marker, 42)),
        patch.object(client, "_resolve_remote_dataset_version", return_value=42) as version,
        patch.object(
            client,
            "_verify_remote_bundle",
            return_value=resource_verification,
        ) as verify_bundle,
        patch.object(client, "_monotonic", side_effect=[0.0, 1.0, 1.0]),
    ):
        result = client._verify_remote_upload(
            marker,
            expected_tree=expected_tree,
            timeout_seconds=5,
        )

    verify_bundle.assert_called_once_with(
        expected_tree,
        expected_marker=marker,
        version=42,
        deadline=5.0,
    )
    assert version.call_count == 2
    assert result["resource_verification"] == resource_verification
    assert result["resolved_version"] == 42


def test_verify_remote_upload_does_not_retry_local_enospc() -> None:
    client = KaggleClient()
    marker = _valid_publication_marker()
    expected_tree = _remote_tree({"dataset-metadata.json": b"metadata"})
    disk_error = OSError(errno.ENOSPC, "disk full")

    with (
        patch.object(client, "_download_remote_publication_marker", return_value=(marker, 42)),
        patch.object(client, "_resolve_remote_dataset_version", return_value=42),
        patch.object(client, "_verify_remote_bundle", side_effect=disk_error) as verify_bundle,
        patch.object(client, "_sleep") as sleep,
        pytest.raises(OSError, match="disk full"),
    ):
        client._verify_remote_upload(
            marker,
            expected_tree=expected_tree,
            timeout_seconds=30,
        )

    verify_bundle.assert_called_once()
    sleep.assert_not_called()


def test_stage_file_uses_hardlink_without_duplicate_storage(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    destination = tmp_path / "staged" / "nba.sqlite"
    source.write_bytes(b"database")
    inventory = {
        "path": "nba.sqlite",
        "bytes": source.stat().st_size,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }

    KaggleClient()._stage_file_from_inventory(
        source_path=source,
        destination=destination,
        inventory=inventory,
    )

    assert destination.read_bytes() == source.read_bytes()
    assert destination.stat().st_ino == source.stat().st_ino


def test_stage_file_capacity_checks_cross_device_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite"
    destination = tmp_path / "staged" / "nba.sqlite"
    source.write_bytes(b"database")
    inventory = {
        "path": "nba.sqlite",
        "bytes": source.stat().st_size,
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    client = KaggleClient()

    with (
        patch("nbadb.kaggle.client.os.link", side_effect=OSError(errno.EXDEV, "cross-device")),
        patch.object(client, "_require_disk_capacity") as capacity,
    ):
        client._stage_file_from_inventory(
            source_path=source,
            destination=destination,
            inventory=inventory,
        )

    capacity.assert_called_once()
    assert destination.read_bytes() == source.read_bytes()


@patch("nbadb.kaggle.client.get_settings")
def test_publication_preflight_accepts_valid_marker_with_agreeing_exact_version(
    mock_settings: MagicMock,
    tmp_path: Path,
) -> None:
    marker = _valid_publication_marker()
    mock_settings.return_value = NbaDbSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    client = KaggleClient()

    with (
        patch.object(client, "_download_remote_publication_marker", return_value=(marker, 42)),
        patch.object(client, "_resolve_remote_dataset_version", return_value=42),
        patch("kagglehub.dataset_upload") as upload,
    ):
        result = client.publication_preflight()

    assert result == {
        "acceptable": True,
        "dataset": "wyattowalsh/basketball",
        "state": "marker_present",
        "version": 42,
        "publish_key": "a" * 20,
        "bundle_fingerprint": "b" * 64,
    }
    upload.assert_not_called()
    assert not (tmp_path / "logs").exists()


def test_publication_preflight_accepts_marker_specific_404_with_exact_version() -> None:
    client = KaggleClient()

    with (
        patch.object(
            client,
            "_download_remote_publication_marker",
            side_effect=_kaggle_api_http_error(404),
        ),
        patch.object(client, "_resolve_remote_dataset_version", return_value=238) as version,
        patch("kagglehub.dataset_upload") as upload,
    ):
        result = client.publication_preflight()

    assert result == {
        "acceptable": True,
        "dataset": "wyattowalsh/basketball",
        "state": "bootstrap_marker_missing",
        "marker_status_code": 404,
        "version": 238,
    }
    version.assert_called_once_with()
    upload.assert_not_called()


def test_publication_preflight_rejects_dataset_level_404() -> None:
    client = KaggleClient()
    error = _kaggle_api_http_error(
        404,
        url="https://www.kaggle.com/api/v1/datasets/view/wyattowalsh/basketball",
    )

    with (
        patch.object(client, "_download_remote_publication_marker", side_effect=error),
        patch.object(client, "_resolve_remote_dataset_version") as version,
        patch("kagglehub.dataset_upload") as upload,
        pytest.raises(type(error)),
    ):
        client.publication_preflight()

    version.assert_not_called()
    upload.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("preflight timed out"),
        _kaggle_api_http_error(401),
        _kaggle_api_http_error(503),
    ],
)
def test_publication_preflight_fails_closed_on_non_bootstrap_lookup_errors(
    error: Exception,
) -> None:
    client = KaggleClient()

    with (
        patch.object(client, "_download_remote_publication_marker", side_effect=error),
        patch.object(client, "_resolve_remote_dataset_version") as version,
        patch("kagglehub.dataset_upload") as upload,
        pytest.raises(type(error)),
    ):
        client.publication_preflight()

    version.assert_not_called()
    upload.assert_not_called()


def test_publication_preflight_fails_closed_on_ambiguous_versions() -> None:
    client = KaggleClient()

    with (
        patch.object(
            client,
            "_download_remote_publication_marker",
            return_value=(_valid_publication_marker(), 42),
        ),
        patch.object(client, "_resolve_remote_dataset_version", return_value=43),
        patch("kagglehub.dataset_upload") as upload,
        pytest.raises(RuntimeError, match="ambiguous dataset versions"),
    ):
        client.publication_preflight()

    upload.assert_not_called()


def test_publication_preflight_rejects_invalid_marker() -> None:
    client = KaggleClient()
    invalid_marker = {**_valid_publication_marker(), "bundle_fingerprint": "not-a-digest"}

    with (
        patch.object(
            client,
            "_download_remote_publication_marker",
            return_value=(invalid_marker, 42),
        ),
        patch.object(client, "_resolve_remote_dataset_version") as version,
        patch("kagglehub.dataset_upload") as upload,
        pytest.raises(ValueError, match="invalid bundle_fingerprint"),
    ):
        client.publication_preflight()

    version.assert_not_called()
    upload.assert_not_called()


@pytest.mark.parametrize(
    ("corruption", "error_match"),
    [
        ("unsupported_state", "unsupported state"),
        ("dataset_identity", "identity is inconsistent"),
        ("key_identity", "identity is inconsistent"),
        ("publish_key_hex", "publish_key must be 20 lowercase hex"),
        ("fingerprint_hex", "bundle_fingerprint must be lowercase hex"),
        ("empty_status", "nonempty last_status"),
        ("empty_transition_timestamp", "nonempty last_transition_at"),
        ("empty_resolved_timestamp", "nonempty resolved_at"),
        ("missing_unresolved_timestamp", "nonempty first_unresolved_at"),
        ("missing_failed_timestamp", "nonempty failed_at"),
        ("serialization_contract", "serialization contract is invalid"),
        ("resolved_version_zero", "positive resolved_version"),
        ("resolved_version_bool", "positive resolved_version"),
    ],
)
def test_publication_state_rejects_every_corrupted_record_variant(
    tmp_path: Path,
    corruption: str,
    error_match: str,
) -> None:
    settings = NbaDbSettings(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    state = _valid_publication_state()
    datasets = cast("dict[str, object]", state["datasets"])
    dataset_state = cast("dict[str, object]", datasets["wyattowalsh/basketball"])
    publications = cast("dict[str, object]", dataset_state["publications"])
    publish_key = "a" * 20
    record = cast("dict[str, object]", publications[publish_key])

    if corruption == "unsupported_state":
        record["state"] = "pending"
    elif corruption == "dataset_identity":
        datasets["other/dataset"] = datasets.pop("wyattowalsh/basketball")
    elif corruption == "key_identity":
        record["publish_key"] = "c" * 20
    elif corruption == "publish_key_hex":
        uppercase_key = publish_key.upper()
        record["publish_key"] = uppercase_key
        publications[uppercase_key] = publications.pop(publish_key)
    elif corruption == "fingerprint_hex":
        record["bundle_fingerprint"] = str(record["bundle_fingerprint"]).upper()
    elif corruption == "empty_status":
        record["last_status"] = " "
    elif corruption == "empty_transition_timestamp":
        record["last_transition_at"] = ""
    elif corruption == "empty_resolved_timestamp":
        record["resolved_at"] = ""
    elif corruption == "missing_unresolved_timestamp":
        record["state"] = "unresolved"
        record.pop("resolved_at")
        record.pop("resolved_version")
    elif corruption == "missing_failed_timestamp":
        record["state"] = "failed"
        record.pop("resolved_at")
        record.pop("resolved_version")
    elif corruption == "serialization_contract":
        record["serialization"] = {"mechanism": "process_mutex_only"}
    elif corruption == "resolved_version_zero":
        record["resolved_version"] = 0
    elif corruption == "resolved_version_bool":
        record["resolved_version"] = True
    else:  # pragma: no cover - parameter table is exhaustive
        raise AssertionError(corruption)

    with patch("nbadb.kaggle.client.get_settings", return_value=settings):
        client = KaggleClient()
    state_path = client._publication_state_path()
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match=error_match):
        client._read_publication_state()


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        ("Authorization: Bearer bearer-value", "bearer-value"),
        ("api_key=api-value", "api-value"),
        ('{"token": "token-value"}', "token-value"),
        ("secret: secret-value", "secret-value"),
        ("client_secret=client-secret-value", "client-secret-value"),
        ("refresh_token=refresh-token-value", "refresh-token-value"),
        ("password=password-value", "password-value"),
        ("--token flag-value", "flag-value"),
        ("KAGGLE_KEY=kaggle-value", "kaggle-value"),
    ],
)
def test_redacted_error_removes_common_credential_forms(message: str, secret: str) -> None:
    redacted = KaggleClient._redacted_error(RuntimeError(message))

    assert secret not in redacted
    assert "<redacted>" in redacted


@pytest.mark.parametrize(
    "path",
    [
        "/private/var/folders/nbadb-kaggle-readback-x/member",
        "/synthetic/independent/temp-root/member",
        "missing:/synthetic/private/member",
        "uri=file:///synthetic/private/member",
        "uri=file://server/share/private/member",
        "uri=file://[2001:db8::1]/share/private/member",
        "uri=file://[fe80::1%25en0]/share/private/member",
        r"C:\\Users\\runner\\AppData\\Local\\nbadb\\member",
    ],
)
def test_redacted_error_removes_machine_absolute_paths(path: str) -> None:
    redacted = KaggleClient._redacted_error(FileNotFoundError(path))

    assert path not in redacted
    assert "<local-path>" in redacted
    if path.startswith("uri=file://"):
        assert redacted == "FileNotFoundError: uri=<local-path>"


def test_persisted_error_redaction_propagates_through_nested_containers() -> None:
    payload = {
        "errors": ["/synthetic/private/list-member"],
        "error": {"message": "file:///synthetic/private/nested-member"},
        "nested_error": ("/synthetic/private/tuple-member",),
        "ordinary": "/public/semantic/value",
    }

    redacted = KaggleClient._redact_persisted_error_fields(payload)

    assert redacted == {
        "errors": ["<local-path>"],
        "error": {"message": "<local-path>"},
        "nested_error": ["<local-path>"],
        "ordinary": "/public/semantic/value",
    }


@patch("nbadb.kaggle.client.get_settings")
def test_upload_manifest_atomically_redacts_nested_errors_and_documents_lock_scope(
    mock_settings: MagicMock, tmp_path: Path
) -> None:
    mock_settings.return_value = NbaDbSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    client = KaggleClient()

    manifest_path = client._write_upload_manifest(
        data_dir=tmp_path / "data",
        version_notes="test",
        status="failed",
        preflight={"checks": ({"root": str(tmp_path / "independent-staged-root")},)},
        publication={
            "upload_error": (
                "Authorization: Bearer nested-secret",
                "uri=file://[fe80::1%25en0]/share/private/member",
            )
        },
        error=f"api_key=top-level-secret; missing={tmp_path / 'data' / 'missing.bin'}",
    )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert "nested-secret" not in manifest_text
    assert "top-level-secret" not in manifest_text
    assert "file://" not in manifest_text
    assert str(tmp_path) not in manifest_text
    assert "missing=<local-path>" in manifest_text
    assert manifest["publication"]["upload_error"] == [
        "Authorization: Bearer <redacted>",
        "uri=<local-path>",
    ]
    assert manifest["preflight"] == {"checks": [{"root": "<staged-upload-root>"}]}
    assert manifest["serialization"] == {
        "mechanism": "process_mutex_and_advisory_file_lock",
        "scope": "same_process_and_same_host_shared_log_directory",
        "cross_host_supported": False,
        "cross_host_guard": "remote_marker_and_exact_version_reconciliation",
    }
    assert not list(manifest_path.parent.glob(f".{manifest_path.name}.*.tmp"))


@patch("nbadb.kaggle.client.get_settings")
def test_local_upload_claim_rejects_overlapping_same_process_upload(
    mock_settings: MagicMock, tmp_path: Path
) -> None:
    settings = NbaDbSettings(data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    mock_settings.return_value = settings
    first = KaggleClient()
    second = KaggleClient()

    with (
        first._local_upload_claim(),
        patch("kagglehub.dataset_upload") as upload,
        pytest.raises(RuntimeError, match="already active in this process"),
    ):
        second.upload(data_dir=tmp_path / "missing")

    upload.assert_not_called()


def test_posix_advisory_lock_backend_lazily_uses_fcntl() -> None:
    from nbadb.kaggle.client import _advisory_file_lock_backend

    flock = MagicMock()
    fake_fcntl = SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, flock=flock)
    handle = MagicMock()
    handle.fileno.return_value = 17

    with (
        patch("nbadb.kaggle.client.os.name", "posix"),
        patch.dict(sys.modules, {"fcntl": fake_fcntl}),
    ):
        backend = _advisory_file_lock_backend()
        backend.acquire(handle)
        backend.release(handle)

    assert flock.call_args_list[0].args == (17, 3)
    assert flock.call_args_list[1].args == (17, 4)


def test_windows_advisory_lock_backend_lazily_uses_msvcrt() -> None:
    from nbadb.kaggle.client import _advisory_file_lock_backend

    locking = MagicMock()
    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
    handle = MagicMock()
    handle.fileno.return_value = 17
    handle.tell.return_value = 0

    with (
        patch("nbadb.kaggle.client.os.name", "nt"),
        patch.dict(sys.modules, {"msvcrt": fake_msvcrt}),
    ):
        backend = _advisory_file_lock_backend()
        backend.acquire(handle)
        backend.release(handle)

    handle.write.assert_called_once_with(b"\0")
    assert locking.call_args_list[0].args == (17, 1, 1)
    assert locking.call_args_list[1].args == (17, 2, 1)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX fcntl locking")
@patch("nbadb.kaggle.client.get_settings")
def test_local_upload_claim_holds_posix_advisory_file_lock(
    mock_settings: MagicMock, tmp_path: Path
) -> None:
    import fcntl

    mock_settings.return_value = NbaDbSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    client = KaggleClient()

    with client._local_upload_claim():
        lock_path = next((tmp_path / "logs" / "kaggle").glob("kaggle-upload-*.lock"))
        with (
            lock_path.open("a+", encoding="utf-8") as contender,
            pytest.raises(BlockingIOError),
        ):
            fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.skipif(os.name != "nt", reason="requires Windows msvcrt locking")
@patch("nbadb.kaggle.client.get_settings")
def test_local_upload_claim_holds_windows_advisory_file_lock(
    mock_settings: MagicMock, tmp_path: Path
) -> None:
    import msvcrt

    mock_settings.return_value = NbaDbSettings(
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
    )
    client = KaggleClient()

    with client._local_upload_claim():
        lock_path = next((tmp_path / "logs" / "kaggle").glob("kaggle-upload-*.lock"))
        with lock_path.open("r+b") as contender:
            contender.seek(0)
            locking = vars(msvcrt)["locking"]
            lk_nblck = vars(msvcrt)["LK_NBLCK"]
            with pytest.raises(OSError):
                locking(contender.fileno(), lk_nblck, 1)
