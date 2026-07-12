from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from nbadb.core.config import NbaDbSettings
from nbadb.kaggle.client import KaggleClient

if TYPE_CHECKING:
    from pathlib import Path


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
    datasets = state["datasets"]
    assert isinstance(datasets, dict)
    dataset_state = datasets["wyattowalsh/basketball"]
    assert isinstance(dataset_state, dict)
    publications = dataset_state["publications"]
    assert isinstance(publications, dict)
    publish_key = "a" * 20
    record = publications[publish_key]
    assert isinstance(record, dict)

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
        preflight={},
        publication={"upload_error": "Authorization: Bearer nested-secret"},
        error="api_key=top-level-secret",
    )

    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert "nested-secret" not in manifest_text
    assert "top-level-secret" not in manifest_text
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
            with pytest.raises(OSError):
                msvcrt.locking(contender.fileno(), msvcrt.LK_NBLCK, 1)
