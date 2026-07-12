from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from nbadb.core.artifact_identity import build_assured_artifact_manifest
from nbadb.core.config import NbaDbSettings, get_settings

if TYPE_CHECKING:
    from typing import Any


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear lru_cache on get_settings so mocks take effect."""
    get_settings.cache_clear()


class TestKaggleClientDownload:
    @patch("nbadb.kaggle.client.get_settings")
    def test_download_copies_to_data_dir(self, mock_settings: MagicMock, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        download_dir = tmp_path / "downloaded"
        download_dir.mkdir()
        # Simulate kagglehub cached files
        (download_dir / "nba.duckdb").write_text("fake")
        (download_dir / "nba.sqlite").write_text("fake")

        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with patch("kagglehub.dataset_download", return_value=str(download_dir)) as mock_dl:
            result = client.download()
            mock_dl.assert_called_once_with("wyattowalsh/basketball")
            assert result == data_dir
            assert (data_dir / "nba.duckdb").exists()
            assert (data_dir / "nba.sqlite").exists()

    @patch("nbadb.kaggle.client.get_settings")
    def test_download_passes_dataset_handle(self, mock_settings: MagicMock, tmp_path: Path) -> None:
        mock_settings.return_value = NbaDbSettings(
            data_dir=tmp_path / "data",
            log_dir=tmp_path / "logs",
            kaggle_dataset="custom/dataset",
        )
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with patch("kagglehub.dataset_download", return_value=str(tmp_path)) as mock_dl:
            client.download()
            mock_dl.assert_called_once_with("custom/dataset")


def _write_upload_bundle(
    data_dir: Path,
    *,
    dataset_id: str = "wyattowalsh/basketball",
    resource_path: str = "nba.sqlite",
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    resource = data_dir / resource_path
    resource.parent.mkdir(parents=True, exist_ok=True)
    if resource.suffix == ".sqlite":
        _write_sqlite_database(resource)
    elif resource.suffix == ".duckdb":
        _write_duckdb_database(resource)
    elif resource.suffix == ".parquet":
        _write_parquet_file(resource, [{"player_id": 1, "player_name": "Test Player"}])
    else:
        resource.write_text("sqlite-preview", encoding="utf-8")
    _write_upload_metadata(
        data_dir,
        dataset_id=dataset_id,
        resources=[
            {
                "path": resource_path,
                "name": "SQLite Database",
            }
        ],
    )


def _write_upload_metadata(
    data_dir: Path,
    *,
    resources: list[dict[str, object]],
    dataset_id: str = "wyattowalsh/basketball",
) -> None:
    (data_dir / "dataset-metadata.json").write_text(
        json.dumps(
            {
                "id": dataset_id,
                "resources": resources,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _add_assured_provenance(data_dir: Path) -> dict[str, str]:
    provenance = {
        "chain_id": "full-20260711",
        "source_sha": "a" * 40,
        "coverage_fingerprint": "b" * 64,
    }
    manifest_path = build_assured_artifact_manifest(data_dir, **provenance)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata_path = data_dir / "dataset-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["resources"].append(
        {
            "path": manifest_path.name,
            "name": "Assured Artifact Provenance",
        }
    )
    metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
    return {
        **provenance,
        "data_tree_fingerprint": manifest["data_tree_fingerprint"],
    }


def _valid_stale_publication_marker() -> dict[str, object]:
    return {
        "schema_version": 1,
        "dataset": "wyattowalsh/basketball",
        "publish_key": "0" * 20,
        "bundle_fingerprint": "1" * 64,
        "data_tree_fingerprint": "2" * 64,
        "metadata_sha256": "3" * 64,
        "resource_count": 1,
        "resource_bytes": 0,
        "resources": [
            {
                "path": "stale.sqlite",
                "kind": "file",
                "bytes": 0,
                "sha256": "4" * 64,
            }
        ],
    }


def _write_stale_publication_marker(directory: Path) -> None:
    directory.mkdir(parents=True)
    (directory / "nbadb-publication.json").write_text(
        json.dumps(_valid_stale_publication_marker()) + "\n",
        encoding="utf-8",
    )


def _kaggle_api_http_error(status_code: int) -> Exception:
    import requests
    from kagglehub.exceptions import KaggleApiHTTPError

    response = requests.Response()
    response.status_code = status_code
    response.url = "https://www.kaggle.com/api/v1/datasets/download/test/nbadb-publication.json"
    return KaggleApiHTTPError(f"HTTP {status_code}", response=response)


def _write_sqlite_database(
    path: Path,
    *,
    table_rows: dict[str, int] | None = None,
    internal_tables: tuple[str, ...] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_by_table = table_rows or {"dim_player": 1}
    conn = sqlite3.connect(path)
    try:
        for table_name, row_count in rows_by_table.items():
            conn.execute(f'CREATE TABLE "{table_name}" (id INTEGER PRIMARY KEY, name TEXT)')
            for index in range(row_count):
                conn.execute(
                    f'INSERT INTO "{table_name}" VALUES (?, ?)',
                    (index + 1, f"{table_name} {index + 1}"),
                )
        for table_name in internal_tables:
            conn.execute(f'CREATE TABLE "{table_name}" (id INTEGER PRIMARY KEY)')
            conn.execute(f'INSERT INTO "{table_name}" VALUES (1)')
        conn.commit()
    finally:
        conn.close()


def _write_duckdb_database(
    path: Path,
    *,
    table_rows: dict[str, int] | None = None,
    internal_tables: tuple[str, ...] = (),
) -> None:
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    rows_by_table = table_rows or {"dim_player": 1}
    conn = duckdb.connect(str(path))
    try:
        for table_name, row_count in rows_by_table.items():
            conn.execute(f'CREATE TABLE "{table_name}" (id INTEGER, name VARCHAR)')
            for index in range(row_count):
                conn.execute(
                    f'INSERT INTO "{table_name}" VALUES (?, ?)',
                    (index + 1, f"{table_name} {index + 1}"),
                )
        for table_name in internal_tables:
            conn.execute(f'CREATE TABLE "{table_name}" (id INTEGER)')
            conn.execute(f'INSERT INTO "{table_name}" VALUES (1)')
    finally:
        conn.close()


def _write_parquet_file(path: Path, rows: list[dict[str, object]]) -> None:
    import polars as pl

    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(path)


class TestKaggleClientUpload:
    @patch("nbadb.kaggle.client.get_settings")
    def test_assured_bundle_binds_provenance_to_publication_marker(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        provenance = _add_assured_provenance(data_dir)
        mock_settings.return_value = NbaDbSettings(
            data_dir=data_dir,
            log_dir=tmp_path / "logs",
        )
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        preflight = client._snapshot_upload_bundle(data_dir)
        staged_dir = tmp_path / "staged"
        client._stage_upload_bundle(data_dir, staged_dir, preflight)
        staged_tree = client._expected_staged_tree_snapshot(preflight, staged_dir)
        marker = client._publication_marker_payload(
            preflight=preflight,
            publish_key="c" * 20,
            data_tree_fingerprint=staged_tree["fingerprint"],
        )

        assert preflight["provenance"] == provenance
        assert marker["schema_version"] == 2
        assert marker["provenance"] == provenance
        client._validate_publication_marker(marker)

        boolean_schema_marker = {**marker, "schema_version": True}
        with pytest.raises(ValueError, match="unsupported schema"):
            client._validate_publication_marker(boolean_schema_marker)

        marker["provenance"]["source_sha"] = "A" * 40
        with pytest.raises(ValueError, match="provenance source_sha is invalid"):
            client._validate_publication_marker(marker)

    @patch("nbadb.kaggle.client.get_settings")
    def test_assured_bundle_rejects_inventory_tampering(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        _add_assured_provenance(data_dir)
        (data_dir / "undeclared-after-assurance.txt").write_text("tampered", encoding="utf-8")
        mock_settings.return_value = NbaDbSettings(
            data_dir=data_dir,
            log_dir=tmp_path / "logs",
        )
        from nbadb.kaggle.client import KaggleClient

        with pytest.raises(ValueError, match="contents do not match"):
            KaggleClient()._snapshot_upload_bundle(data_dir)

    @patch("nbadb.kaggle.client.get_settings")
    def test_assured_bundle_rejects_preexisting_undeclared_file(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        (data_dir / "undeclared-before-assurance.bin").write_bytes(b"not published")
        _add_assured_provenance(data_dir)
        mock_settings.return_value = NbaDbSettings(
            data_dir=data_dir,
            log_dir=tmp_path / "logs",
        )
        from nbadb.kaggle.client import KaggleClient

        with pytest.raises(ValueError, match="does not exactly match declared"):
            KaggleClient()._snapshot_upload_bundle(data_dir)

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_calls_kagglehub_with_correct_args(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        (data_dir / "private-not-declared.txt").write_text("do not upload", encoding="utf-8")

        def inspect_staged_upload(**kwargs: object) -> None:
            staged_dir = Path(str(kwargs["local_dataset_dir"]))
            assert staged_dir != data_dir
            assert (staged_dir / "dataset-metadata.json").is_file()
            assert (staged_dir / "nba.sqlite").is_file()
            assert (staged_dir / "nbadb-publication.json").is_file()
            assert not (staged_dir / "private-not-declared.txt").exists()

        with patch("kagglehub.dataset_upload", side_effect=inspect_staged_upload) as mock_up:
            manifest_path = client.upload(data_dir=data_dir, version_notes="test upload")
            mock_up.assert_called_once()
            assert mock_up.call_args.kwargs["handle"] == "wyattowalsh/basketball"
            assert mock_up.call_args.kwargs["version_notes"] == "test upload"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "uploaded"
        assert manifest["publication"]["result"] == "uploaded_unverified"
        assert manifest["preflight"]["resource_count"] == 1
        assert manifest["preflight"]["resources"][0]["database_validation"] == {
            "engine": "sqlite",
            "quick_check": "ok",
            "foreign_key_check_error_count": 0,
            "table_count": 1,
            "row_count": 1,
            "tables": {"dim_player": 1},
            "excluded_internal_table_count": 0,
            "excluded_internal_tables": [],
        }
        assert (
            manifest["post_upload"]["fingerprint"] == manifest["preflight"]["staged"]["fingerprint"]
        )

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_uses_settings_data_dir_by_default(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with patch("kagglehub.dataset_upload") as mock_up:
            client.upload()
            mock_up.assert_called_once()
            assert mock_up.call_args.kwargs["local_dataset_dir"] != str(data_dir)

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_raises_on_missing_dir(self, mock_settings: MagicMock, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        mock_settings.return_value = NbaDbSettings(data_dir=missing, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with pytest.raises(FileNotFoundError, match="does not exist"):
            client.upload(data_dir=missing)

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_metadata_only_bundle(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "dataset-metadata.json").write_text(
            json.dumps({"id": "wyattowalsh/basketball", "resources": []}) + "\n",
            encoding="utf-8",
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="no declared data resources"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_metadata_id_mismatch(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir, dataset_id="other/dataset")
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="does not match configured dataset"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_invalid_sqlite_resource(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "nba.sqlite").write_text("not a sqlite database", encoding="utf-8")
        (data_dir / "dataset-metadata.json").write_text(
            json.dumps(
                {
                    "id": "wyattowalsh/basketball",
                    "resources": [{"path": "nba.sqlite"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="SQLite resource integrity validation failed"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_resource_path_traversal(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (tmp_path / "outside.sqlite").write_text("outside", encoding="utf-8")
        (data_dir / "dataset-metadata.json").write_text(
            json.dumps(
                {
                    "id": "wyattowalsh/basketball",
                    "resources": [{"path": "../outside.sqlite"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="normalized relative path"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_accepts_partitioned_parquet_directory(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        partition_dir = data_dir / "parquet" / "fact_player_game"
        partition_dir.mkdir(parents=True)
        _write_parquet_file(
            partition_dir / "season=2024-25" / "part-0.parquet",
            [{"player_id": 1, "points": 12}],
        )
        _write_parquet_file(
            partition_dir / "season=2025-26" / "part-0.parquet",
            [{"player_id": 2, "points": 18}],
        )
        (data_dir / "undeclared.txt").write_text("private", encoding="utf-8")
        _write_upload_metadata(
            data_dir,
            resources=[
                {
                    "path": "parquet/fact_player_game",
                    "name": "fact_player_game parquet",
                }
            ],
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        def inspect_staged_upload(**kwargs: object) -> None:
            staged_dir = Path(str(kwargs["local_dataset_dir"]))
            staged_partition = staged_dir / "parquet" / "fact_player_game"
            assert (staged_partition / "season=2024-25" / "part-0.parquet").is_file()
            assert (staged_partition / "season=2025-26" / "part-0.parquet").is_file()
            assert not (staged_dir / "undeclared.txt").exists()

        client = KaggleClient()
        with patch("kagglehub.dataset_upload", side_effect=inspect_staged_upload):
            manifest_path = client.upload(data_dir=data_dir)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        resource = manifest["preflight"]["resources"][0]
        assert resource["kind"] == "directory"
        assert resource["file_count"] == 2
        assert resource["files"][0]["parquet_validation"] == {
            "engine": "parquet",
            "row_count": 1,
            "column_count": 2,
            "row_group_count": 1,
            "columns": ["player_id", "points"],
        }
        assert manifest["post_upload"]["file_count"] == 4
        assert any(
            file["path"] == "nbadb-publication.json" for file in manifest["post_upload"]["files"]
        )

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_corrupt_parquet_resource(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        parquet_path = data_dir / "parquet" / "fact_player_game" / "part-0.parquet"
        parquet_path.parent.mkdir(parents=True)
        parquet_path.write_bytes(b"not parquet")
        _write_upload_metadata(
            data_dir,
            resources=[{"path": "parquet/fact_player_game"}],
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="Parquet resource metadata validation failed"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_empty_directory_resource(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        (data_dir / "parquet" / "empty").mkdir(parents=True)
        (data_dir / "dataset-metadata.json").write_text(
            json.dumps(
                {
                    "id": "wyattowalsh/basketball",
                    "resources": [{"path": "parquet/empty"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="directory resource is empty"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_unexpected_file_inside_partitioned_parquet_directory(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        partition_dir = data_dir / "parquet" / "fact_player_game"
        partition_dir.mkdir(parents=True)
        _write_parquet_file(
            partition_dir / "season=2024-25" / "part-0.parquet",
            [{"player_id": 1, "points": 12}],
        )
        (partition_dir / ".env").write_text("private", encoding="utf-8")
        (data_dir / "dataset-metadata.json").write_text(
            json.dumps(
                {
                    "id": "wyattowalsh/basketball",
                    "resources": [{"path": "parquet/fact_player_game"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="hidden or ignored path"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_symlink_resource_path(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "target.sqlite").write_text("sqlite-preview", encoding="utf-8")
        link_path = data_dir / "nba.sqlite"
        try:
            link_path.symlink_to(data_dir / "target.sqlite")
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        (data_dir / "dataset-metadata.json").write_text(
            json.dumps(
                {
                    "id": "wyattowalsh/basketball",
                    "resources": [{"path": "nba.sqlite"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="must not be a symlink"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_source_symlink_mutation_before_staging(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        outside_path = tmp_path / "outside.txt"
        outside_path.write_text("outside", encoding="utf-8")
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        original_stage = client._stage_upload_bundle

        def mutate_then_stage(
            source_dir: Path,
            staged_dir: Path,
            preflight: dict[str, Any],
        ) -> dict[str, Any]:
            resource_path = data_dir / "nba.sqlite"
            resource_path.unlink()
            try:
                resource_path.symlink_to(outside_path)
            except OSError as exc:
                pytest.skip(f"symlink creation unavailable: {exc}")
            return original_stage(source_dir, staged_dir, preflight)

        with (
            patch.object(client, "_stage_upload_bundle", side_effect=mutate_then_stage),
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="must not be a symlink"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "staging_failed"

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_source_mutation_after_staging_before_upload(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        original_stage = client._stage_upload_bundle

        def mutate_after_stage(
            source_dir: Path,
            staged_dir: Path,
            preflight: dict[str, Any],
        ) -> dict[str, Any]:
            staged = original_stage(source_dir, staged_dir, preflight)
            (data_dir / "nba.sqlite").write_text("changed", encoding="utf-8")
            return staged

        with (
            patch.object(client, "_stage_upload_bundle", side_effect=mutate_after_stage),
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="SQLite resource integrity validation failed"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "source_validation_failed_before_upload"

    @patch("nbadb.kaggle.client.get_settings")
    def test_bundle_and_publication_identity_are_independent_of_local_root(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        first_dir = tmp_path / "first" / "data"
        second_dir = tmp_path / "elsewhere" / "data"
        _write_upload_bundle(first_dir)
        shutil.copytree(first_dir, second_dir)
        mock_settings.return_value = NbaDbSettings(
            data_dir=first_dir,
            log_dir=tmp_path / "logs",
        )
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        first = client._snapshot_upload_bundle(first_dir)
        second = client._snapshot_upload_bundle(second_dir)

        assert first["resources"][0]["source_path"] != second["resources"][0]["source_path"]
        assert first["fingerprint"] == second["fingerprint"]
        first_publish_key = hashlib.sha256(
            f"wyattowalsh/basketball:{first['fingerprint']}".encode()
        ).hexdigest()[:20]
        second_publish_key = hashlib.sha256(
            f"wyattowalsh/basketball:{second['fingerprint']}".encode()
        ).hexdigest()[:20]
        first_tree = client._expected_staged_tree_snapshot(first, tmp_path / "stage-one")
        second_tree = client._expected_staged_tree_snapshot(second, tmp_path / "stage-two")
        first_marker = client._publication_marker_payload(
            preflight=first,
            publish_key=first_publish_key,
            data_tree_fingerprint=first_tree["fingerprint"],
        )
        second_marker = client._publication_marker_payload(
            preflight=second,
            publish_key=second_publish_key,
            data_tree_fingerprint=second_tree["fingerprint"],
        )

        assert first_publish_key == second_publish_key
        assert first_tree["fingerprint"] == second_tree["fingerprint"]
        assert first_marker == second_marker

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_overlapping_resource_paths(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        partition_dir = data_dir / "parquet" / "fact_player_game"
        partition_dir.mkdir(parents=True)
        _write_parquet_file(partition_dir / "part-0.parquet", [{"player_id": 1}])
        (data_dir / "dataset-metadata.json").write_text(
            json.dumps(
                {
                    "id": "wyattowalsh/basketball",
                    "resources": [
                        {"path": "parquet/fact_player_game"},
                        {"path": "parquet/fact_player_game/part-0.parquet"},
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="overlapping resource paths"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_symlink_inside_directory_resource(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        partition_dir = data_dir / "parquet" / "fact_player_game"
        partition_dir.mkdir(parents=True)
        target_path = partition_dir / "part-0.parquet"
        _write_parquet_file(target_path, [{"player_id": 1}])
        try:
            (partition_dir / "part-link.parquet").symlink_to(target_path)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")
        (data_dir / "dataset-metadata.json").write_text(
            json.dumps(
                {
                    "id": "wyattowalsh/basketball",
                    "resources": [{"path": "parquet/fact_player_game"}],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="directory contains symlink"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_bundle_mutation_during_upload(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        def mutate_bundle(**kwargs: object) -> None:
            staged_dir = Path(str(kwargs["local_dataset_dir"]))
            (staged_dir / "nba.sqlite").write_text("changed", encoding="utf-8")

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload", side_effect=mutate_bundle),
            pytest.raises(
                RuntimeError, match="remote Kaggle version may already have been created"
            ),
        ):
            client.upload(data_dir=data_dir)

        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "post_upload_mismatch_remote_may_exist"

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_validates_database_parity_using_public_tables_only(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _write_sqlite_database(
            data_dir / "nba.sqlite",
            table_rows={"dim_player": 1},
            internal_tables=("_pipeline_watermarks",),
        )
        _write_duckdb_database(
            data_dir / "nba.duckdb",
            table_rows={"dim_player": 1},
            internal_tables=("_pipeline_watermarks", "_extraction_journal"),
        )
        _write_upload_metadata(
            data_dir,
            resources=[
                {"path": "nba.sqlite", "name": "SQLite Database"},
                {"path": "nba.duckdb", "name": "DuckDB Database"},
            ],
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with patch("kagglehub.dataset_upload"):
            manifest_path = client.upload(data_dir=data_dir)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        validations = {
            resource["path"]: resource["database_validation"]
            for resource in manifest["preflight"]["resources"]
        }
        assert validations["nba.sqlite"]["tables"] == {"dim_player": 1}
        assert validations["nba.sqlite"]["excluded_internal_tables"] == ["_pipeline_watermarks"]
        assert validations["nba.duckdb"]["tables"] == {"dim_player": 1}
        assert validations["nba.duckdb"]["excluded_internal_tables"] == [
            "_extraction_journal",
            "_pipeline_watermarks",
        ]

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_database_parity_missing_public_tables(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _write_sqlite_database(data_dir / "nba.sqlite", table_rows={"dim_player": 1})
        _write_duckdb_database(data_dir / "nba.duckdb", table_rows={"dim_team": 1})
        _write_upload_metadata(
            data_dir,
            resources=[
                {"path": "nba.sqlite", "name": "SQLite Database"},
                {"path": "nba.duckdb", "name": "DuckDB Database"},
            ],
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="missing public tables"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_database_parity_row_count_differences(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        _write_sqlite_database(data_dir / "nba.sqlite", table_rows={"dim_player": 1})
        _write_duckdb_database(data_dir / "nba.duckdb", table_rows={"dim_player": 2})
        _write_upload_metadata(
            data_dir,
            resources=[
                {"path": "nba.sqlite", "name": "SQLite Database"},
                {"path": "nba.duckdb", "name": "DuckDB Database"},
            ],
        )
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_up,
            pytest.raises(ValueError, match="mismatched public table row counts"),
        ):
            client.upload(data_dir=data_dir)

        mock_up.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_verify_remote_records_readback(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        uploaded_dir = tmp_path / "uploaded"
        stale_dir = tmp_path / "stale"
        _write_stale_publication_marker(stale_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        def capture_upload(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), uploaded_dir)

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload", side_effect=capture_upload),
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[(str(stale_dir), 11), (str(uploaded_dir), 12)],
            ) as mock_resolver,
            patch.object(client, "_resolve_remote_dataset_version", return_value=12),
        ):
            manifest_path = client.upload(data_dir=data_dir, verify_remote=True)

        assert mock_resolver.call_count == 2
        assert all(
            str(call.args[0]) == "wyattowalsh/basketball" for call in mock_resolver.call_args_list
        )
        assert all(
            call.args[1] == "nbadb-publication.json" for call in mock_resolver.call_args_list
        )
        assert all(call.kwargs["force_download"] is True for call in mock_resolver.call_args_list)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "uploaded_remote_verified"
        assert (
            manifest["remote_readback"]["bundle_fingerprint"]
            == manifest["preflight"]["fingerprint"]
        )
        assert manifest["remote_readback"]["verification_mode"] == "publication_marker"
        assert manifest["remote_readback"]["resolved_version"] == 12
        assert manifest["publication"]["baseline"]["version"] == 11
        assert manifest["publication"]["resolved_version"] == 12
        assert manifest["publication"]["upload_attempts"] == 1
        assert manifest["publication"]["verification_attempts"] == 1

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_verify_remote_downloads_only_publication_marker(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        uploaded_dir = tmp_path / "uploaded"
        stale_dir = tmp_path / "stale"
        _write_stale_publication_marker(stale_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        def capture_upload(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), uploaded_dir)

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload", side_effect=capture_upload),
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[(str(stale_dir), 20), (str(uploaded_dir), 21)],
            ) as mock_resolver,
            patch.object(client, "_resolve_remote_dataset_version", return_value=21),
        ):
            manifest_path = client.upload(data_dir=data_dir, verify_remote=True)

        assert mock_resolver.call_count == 2
        for call in mock_resolver.call_args_list:
            assert str(call.args[0]) == "wyattowalsh/basketball"
            assert call.args[1] == "nbadb-publication.json"
            assert call.kwargs["force_download"] is True
            assert "output_dir" in call.kwargs
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "uploaded_remote_verified"

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_matching_remote_marker_skips_duplicate_upload(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        remote_dir = tmp_path / "remote"
        remote_dir.mkdir()
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        preflight = client._snapshot_upload_bundle(data_dir)
        client._stage_upload_bundle(data_dir, remote_dir, preflight)
        data_tree = client._expected_staged_tree_snapshot(preflight, remote_dir)
        publish_key = hashlib.sha256(
            f"wyattowalsh/basketball:{preflight['fingerprint']}".encode()
        ).hexdigest()[:20]
        marker = client._publication_marker_payload(
            preflight=preflight,
            publish_key=publish_key,
            data_tree_fingerprint=data_tree["fingerprint"],
        )
        client._write_publication_marker(remote_dir, marker)

        with (
            patch("kagglehub.dataset_upload") as mock_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                return_value=(str(remote_dir), 31),
            ),
            patch.object(client, "_resolve_remote_dataset_version", return_value=31),
        ):
            manifest_path = client.upload(data_dir=data_dir, verify_remote=True)

        mock_upload.assert_not_called()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "reconciled_existing_remote"
        assert manifest["publication"]["result"] == "reconciled_existing_remote"
        assert manifest["publication"]["resolved_version"] == 31
        assert manifest["publication"]["upload_attempts"] == 0
        state_path = tmp_path / "logs" / "kaggle" / "kaggle-publication-state.json"
        records = json.loads(state_path.read_text(encoding="utf-8"))["datasets"][
            "wyattowalsh/basketball"
        ]["publications"]
        assert records[publish_key]["state"] == "resolved"
        assert records[publish_key]["last_status"] == "reconciled_existing_remote"
        assert records[publish_key]["resolved_version"] == 31

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_matching_marker_from_noncurrent_version(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        remote_dir = tmp_path / "remote"
        _write_upload_bundle(data_dir)
        remote_dir.mkdir()
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        preflight = client._snapshot_upload_bundle(data_dir)
        client._stage_upload_bundle(data_dir, remote_dir, preflight)
        data_tree = client._expected_staged_tree_snapshot(preflight, remote_dir)
        publish_key = hashlib.sha256(
            f"wyattowalsh/basketball:{preflight['fingerprint']}".encode()
        ).hexdigest()[:20]
        marker = client._publication_marker_payload(
            preflight=preflight,
            publish_key=publish_key,
            data_tree_fingerprint=data_tree["fingerprint"],
        )
        client._write_publication_marker(remote_dir, marker)

        with (
            patch("kagglehub.dataset_upload") as upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                return_value=(str(remote_dir), 7),
            ),
            patch.object(client, "_resolve_remote_dataset_version", return_value=8),
            pytest.raises(RuntimeError, match="not from the current dataset version"),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        upload.assert_not_called()
        manifest = json.loads(
            (tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["status"] == "baseline_reconciliation_failed"
        assert manifest["publication"]["baseline"]["version"] == 7
        assert manifest["publication"]["baseline"]["metadata_version"] == 8
        assert manifest["publication"]["baseline"]["versions_agree"] is False

    @patch("nbadb.kaggle.client.get_settings")
    def test_remote_verification_rejects_matching_marker_from_noncurrent_version(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient, KagglePublicationPendingError

        client = KaggleClient()
        preflight = client._snapshot_upload_bundle(data_dir)
        marker = client._publication_marker_payload(
            preflight=preflight,
            publish_key="d" * 20,
            data_tree_fingerprint="e" * 64,
        )
        publication: dict[str, Any] = {}

        with (
            patch.object(
                client,
                "_download_remote_publication_marker",
                return_value=(marker, 7),
            ),
            patch.object(client, "_resolve_remote_dataset_version", return_value=8),
            pytest.raises(KagglePublicationPendingError),
        ):
            client._verify_remote_upload(
                marker,
                timeout_seconds=0,
                publication=publication,
            )

        assert publication["verification_attempts"] == 1
        observation = publication["observations"][0]
        assert observation["matches_expected"] is True
        assert observation["version"] == 7
        assert observation["metadata_version"] == 8
        assert observation["versions_agree"] is False

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_marker_404_bootstraps_from_exact_current_version_once(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        uploaded_dir = tmp_path / "uploaded"
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        def capture_upload(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), uploaded_dir)

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload", side_effect=capture_upload) as mock_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[
                    _kaggle_api_http_error(404),
                    _kaggle_api_http_error(404),
                    (str(uploaded_dir), 239),
                ],
            ),
            patch.object(
                client,
                "_resolve_remote_dataset_version",
                side_effect=[238, 238, 239],
            ) as version,
        ):
            manifest_path = client.upload(data_dir=data_dir, verify_remote=True)

        mock_upload.assert_called_once()
        assert version.call_count == 3
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "uploaded_remote_verified"
        assert manifest["publication"]["baseline"] == {
            "state": "bootstrap_marker_missing",
            "marker_status_code": 404,
            "version": 238,
            "matches_expected": False,
            "upload_allowed": True,
        }
        assert manifest["publication"]["bootstrap_pre_upload"] == {
            "state": "marker_missing",
            "marker_status_code": 404,
            "baseline_version": 238,
            "metadata_version": 238,
            "version_unchanged": True,
            "upload_allowed": True,
        }
        assert manifest["publication"]["resolved_version"] == 239
        assert manifest["publication"]["upload_attempts"] == 1

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_baseline_timeout_does_not_upload(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=TimeoutError("baseline lookup unavailable"),
            ),
            patch.object(client, "_resolve_remote_dataset_version") as version,
            pytest.raises(TimeoutError, match="baseline lookup unavailable"),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        mock_upload.assert_not_called()
        version.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "baseline_reconciliation_failed"
        assert manifest["publication"]["result"] == "baseline_reconciliation_failed"
        assert manifest["publication"]["upload_attempts"] == 0
        assert manifest["publication"]["baseline"] == {
            "state": "reconciliation_failed",
            "error": "TimeoutError: baseline lookup unavailable",
        }

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_baseline_401_does_not_upload(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from kagglehub.exceptions import KaggleApiHTTPError

        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=_kaggle_api_http_error(401),
            ),
            patch.object(client, "_resolve_remote_dataset_version") as version,
            pytest.raises(KaggleApiHTTPError, match="HTTP 401"),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        mock_upload.assert_not_called()
        version.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "baseline_reconciliation_failed"
        assert manifest["publication"]["upload_attempts"] == 0
        assert manifest["publication"]["baseline"]["state"] == "reconciliation_failed"

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_rejects_downloaded_malformed_publication_marker_before_upload(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        remote_dir = tmp_path / "remote"
        _write_upload_bundle(data_dir)
        remote_dir.mkdir()
        malformed_marker = {
            **_valid_stale_publication_marker(),
            "bundle_fingerprint": "not-a-digest",
        }
        (remote_dir / "nbadb-publication.json").write_text(
            json.dumps(malformed_marker) + "\n",
            encoding="utf-8",
        )
        mock_settings.return_value = NbaDbSettings(
            data_dir=data_dir,
            log_dir=tmp_path / "logs",
        )
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                return_value=(str(remote_dir), 61),
            ),
            pytest.raises(ValueError, match="invalid bundle_fingerprint"),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        upload.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "baseline_reconciliation_failed"
        assert manifest["publication"]["baseline"]["state"] == "reconciliation_failed"

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_prior_unresolved_missing_marker_does_not_retry_after_version_change(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient, KagglePublicationPendingError

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as first_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[
                    _kaggle_api_http_error(404),
                    _kaggle_api_http_error(404),
                    _kaggle_api_http_error(404),
                ],
            ),
            patch.object(client, "_resolve_remote_dataset_version", return_value=238),
            pytest.raises(KagglePublicationPendingError),
        ):
            client.upload(
                data_dir=data_dir,
                verify_remote=True,
                remote_timeout_seconds=0,
            )

        first_upload.assert_called_once()
        with (
            patch("kagglehub.dataset_upload") as retry_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=_kaggle_api_http_error(404),
            ),
            patch.object(client, "_resolve_remote_dataset_version", return_value=239),
            pytest.raises(
                KagglePublicationPendingError,
                match="prior unresolved upload attempt",
            ),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        retry_upload.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "bootstrap_reconciliation_required"
        assert manifest["publication"]["baseline"]["version"] == 239
        assert manifest["publication"]["baseline"]["upload_allowed"] is False
        prior = manifest["publication"]["prior_unresolved_publication"]
        assert prior["state"] == "unresolved"
        assert prior["last_status"] == "publication_reconciliation_required"
        assert prior["baseline"]["version"] == 238
        assert prior["publish_key"] == manifest["publication"]["publish_key"]

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_prior_unresolved_blocks_second_invocation_with_stale_marker(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        stale_dir = tmp_path / "stale"
        _write_upload_bundle(data_dir)
        _write_stale_publication_marker(stale_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient, KagglePublicationPendingError

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as first_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[(str(stale_dir), 60), (str(stale_dir), 60)],
            ),
            pytest.raises(KagglePublicationPendingError),
        ):
            client.upload(
                data_dir=data_dir,
                verify_remote=True,
                remote_timeout_seconds=0,
            )

        first_upload.assert_called_once()
        with (
            patch("kagglehub.dataset_upload") as second_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                return_value=(str(stale_dir), 60),
            ),
            pytest.raises(
                KagglePublicationPendingError,
                match="does not resolve that exact record",
            ),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        second_upload.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "publication_reconciliation_required"
        assert manifest["publication"]["baseline"]["state"] == "marker_present"
        assert manifest["publication"]["baseline"]["matches_expected"] is False
        assert manifest["publication"]["baseline"]["upload_allowed"] is False
        assert manifest["publication"]["prior_unresolved_publication"]["state"] == "unresolved"

    @patch("nbadb.kaggle.client.get_settings")
    def test_unresolved_evidence_survives_metadata_timeout_and_blocks_third_upload(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient, KagglePublicationPendingError

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as first_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[
                    _kaggle_api_http_error(404),
                    _kaggle_api_http_error(404),
                    _kaggle_api_http_error(404),
                ],
            ),
            patch.object(
                client,
                "_resolve_remote_dataset_version",
                side_effect=[238, 238],
            ),
            pytest.raises(KagglePublicationPendingError),
        ):
            client.upload(
                data_dir=data_dir,
                verify_remote=True,
                remote_timeout_seconds=0,
            )

        first_upload.assert_called_once()
        with (
            patch("kagglehub.dataset_upload") as second_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=_kaggle_api_http_error(404),
            ),
            patch.object(
                client,
                "_resolve_remote_dataset_version",
                side_effect=TimeoutError("metadata unavailable api_key=do-not-persist"),
            ),
            pytest.raises(TimeoutError, match="metadata unavailable"),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        second_upload.assert_not_called()
        state_path = tmp_path / "logs" / "kaggle" / "kaggle-publication-state.json"
        state_text = state_path.read_text(encoding="utf-8")
        state = json.loads(state_text)
        publication_records = state["datasets"]["wyattowalsh/basketball"]["publications"]
        assert len(publication_records) == 1
        assert next(iter(publication_records.values()))["state"] == "unresolved"
        assert "do-not-persist" not in state_text
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        timeout_manifest_text = manifest_path.read_text(encoding="utf-8")
        timeout_manifest = json.loads(timeout_manifest_text)
        assert timeout_manifest["status"] == "baseline_reconciliation_failed"
        assert "do-not-persist" not in timeout_manifest_text

        with (
            patch("kagglehub.dataset_upload") as third_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=_kaggle_api_http_error(404),
            ),
            patch.object(client, "_resolve_remote_dataset_version", return_value=238),
            pytest.raises(KagglePublicationPendingError, match="prior unresolved upload attempt"),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        third_upload.assert_not_called()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "bootstrap_reconciliation_required"
        assert manifest["publication"]["upload_attempts"] == 0

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_post_404_version_change_before_upload_fails_closed(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient, KagglePublicationPendingError

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[
                    _kaggle_api_http_error(404),
                    _kaggle_api_http_error(404),
                ],
            ),
            patch.object(
                client,
                "_resolve_remote_dataset_version",
                side_effect=[238, 239],
            ),
            pytest.raises(KagglePublicationPendingError, match="changed or became ambiguous"),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        upload.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "bootstrap_pre_upload_reconciliation_required"
        assert manifest["publication"]["upload_attempts"] == 0
        assert manifest["publication"]["bootstrap_pre_upload"] == {
            "state": "marker_missing",
            "marker_status_code": 404,
            "baseline_version": 238,
            "metadata_version": 239,
            "version_unchanged": False,
            "upload_allowed": False,
        }
        assert not (tmp_path / "logs" / "kaggle" / "kaggle-publication-state.json").exists()

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_verify_remote_polls_stale_latest_until_match(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        stale_dir = tmp_path / "stale"
        _write_stale_publication_marker(stale_dir)
        uploaded_dir = tmp_path / "cache" / "versions" / "999"
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        def capture_upload(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), uploaded_dir)

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload", side_effect=capture_upload) as mock_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[
                    (str(stale_dir), 5),
                    (str(stale_dir), 5),
                    (str(uploaded_dir), 7),
                ],
            ) as mock_resolver,
            patch.object(client, "_sleep") as mock_sleep,
            patch.object(client, "_resolve_remote_dataset_version", return_value=7),
        ):
            manifest_path = client.upload(
                data_dir=data_dir,
                verify_remote=True,
                remote_timeout_seconds=30,
                remote_poll_interval_seconds=1,
            )

        mock_upload.assert_called_once()
        assert mock_resolver.call_count == 3
        mock_sleep.assert_called_once_with(1)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["publication"]["verification_attempts"] == 2
        assert manifest["publication"]["resolved_version"] == 7

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_ambiguous_transport_error_reconciles_without_second_upload(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        stale_dir = tmp_path / "stale"
        _write_stale_publication_marker(stale_dir)
        uploaded_dir = tmp_path / "uploaded"
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        def accepted_then_timed_out(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), uploaded_dir)
            raise TimeoutError("ambiguous response")

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload", side_effect=accepted_then_timed_out) as mock_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[(str(stale_dir), 40), (str(uploaded_dir), 41)],
            ),
            patch.object(client, "_resolve_remote_dataset_version", return_value=41),
        ):
            manifest_path = client.upload(data_dir=data_dir, verify_remote=True)

        mock_upload.assert_called_once()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "uploaded_remote_verified"
        assert manifest["publication"]["result"] == "reconciled_after_upload_error"
        assert manifest["publication"]["resolved_version"] == 41
        assert manifest["publication"]["upload_attempts"] == 1
        state_path = tmp_path / "logs" / "kaggle" / "kaggle-publication-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        publication_records = state["datasets"]["wyattowalsh/basketball"]["publications"]
        record = publication_records[manifest["publication"]["publish_key"]]
        assert record["state"] == "resolved"
        assert record["resolved_version"] == 41

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_ambiguous_application_error_still_reconciles_remote(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        stale_dir = tmp_path / "stale"
        _write_stale_publication_marker(stale_dir)
        uploaded_dir = tmp_path / "uploaded"
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        def accepted_then_raised(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), uploaded_dir)
            raise RuntimeError("unexpected upload response shape")

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload", side_effect=accepted_then_raised) as mock_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[(str(stale_dir), 42), (str(uploaded_dir), 43)],
            ),
            patch.object(client, "_resolve_remote_dataset_version", return_value=43),
        ):
            manifest_path = client.upload(data_dir=data_dir, verify_remote=True)

        mock_upload.assert_called_once()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "uploaded_remote_verified"
        assert manifest["publication"]["result"] == "reconciled_after_upload_error"
        assert manifest["publication"]["resolved_version"] == 43

    @patch("nbadb.kaggle.client.get_settings")
    def test_unverified_upload_exception_remains_unresolved_and_blocks_retry(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient, KagglePublicationPendingError

        client = KaggleClient()
        with (
            patch(
                "kagglehub.dataset_upload",
                side_effect=RuntimeError("unknown post-submit failure"),
            ) as first_upload,
            pytest.raises(RuntimeError, match="unknown post-submit failure"),
        ):
            client.upload(data_dir=data_dir, verify_remote=False)

        first_upload.assert_called_once()
        state_path = tmp_path / "logs" / "kaggle" / "kaggle-publication-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        records = state["datasets"]["wyattowalsh/basketball"]["publications"]
        assert next(iter(records.values()))["state"] == "unresolved"

        with (
            patch("kagglehub.dataset_upload") as retry_upload,
            pytest.raises(KagglePublicationPendingError, match="prior unresolved upload attempt"),
        ):
            client.upload(data_dir=data_dir, verify_remote=False)

        retry_upload.assert_not_called()

    @patch("nbadb.kaggle.client.get_settings")
    def test_unresolved_dataset_upload_blocks_a_different_bundle(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient, KagglePublicationPendingError

        client = KaggleClient()
        first_snapshot = client._snapshot_upload_bundle(data_dir)
        first_publish_key = hashlib.sha256(
            f"wyattowalsh/basketball:{first_snapshot['fingerprint']}".encode()
        ).hexdigest()[:20]
        client._transition_publication_state(
            {
                "publish_key": first_publish_key,
                "expected_bundle_fingerprint": first_snapshot["fingerprint"],
            },
            state_name="unresolved",
            status="upload_ambiguous",
        )

        conn = sqlite3.connect(data_dir / "nba.sqlite")
        try:
            conn.execute("INSERT INTO dim_player VALUES (2, 'Changed Player')")
            conn.commit()
        finally:
            conn.close()

        with (
            patch("kagglehub.dataset_upload") as upload,
            pytest.raises(KagglePublicationPendingError, match="prior unresolved upload attempt"),
        ):
            client.upload(data_dir=data_dir, verify_remote=False)

        upload.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["publication"]["publish_key"] != first_publish_key
        assert manifest["publication"]["prior_unresolved_publication"]["publish_key"] == (
            first_publish_key
        )

    @patch("nbadb.kaggle.client.get_settings")
    def test_remote_current_bundle_cannot_clear_different_prior_unresolved_record(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        remote_current = tmp_path / "remote-current"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(
            data_dir=data_dir,
            log_dir=tmp_path / "logs",
        )
        from nbadb.kaggle.client import KaggleClient, KagglePublicationPendingError

        client = KaggleClient()
        prior_snapshot = client._snapshot_upload_bundle(data_dir)
        prior_publish_key = hashlib.sha256(
            f"wyattowalsh/basketball:{prior_snapshot['fingerprint']}".encode()
        ).hexdigest()[:20]
        client._transition_publication_state(
            {
                "publish_key": prior_publish_key,
                "expected_bundle_fingerprint": prior_snapshot["fingerprint"],
            },
            state_name="unresolved",
            status="upload_ambiguous",
        )

        conn = sqlite3.connect(data_dir / "nba.sqlite")
        try:
            conn.execute("INSERT INTO dim_player VALUES (2, 'Current Bundle Player')")
            conn.commit()
        finally:
            conn.close()

        current_snapshot = client._snapshot_upload_bundle(data_dir)
        current_publish_key = hashlib.sha256(
            f"wyattowalsh/basketball:{current_snapshot['fingerprint']}".encode()
        ).hexdigest()[:20]
        remote_current.mkdir()
        client._stage_upload_bundle(data_dir, remote_current, current_snapshot)
        current_tree = client._expected_staged_tree_snapshot(current_snapshot, remote_current)
        current_marker = client._publication_marker_payload(
            preflight=current_snapshot,
            publish_key=current_publish_key,
            data_tree_fingerprint=current_tree["fingerprint"],
        )
        client._write_publication_marker(remote_current, current_marker)

        with (
            patch("kagglehub.dataset_upload") as upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                return_value=(str(remote_current), 80),
            ),
            pytest.raises(
                KagglePublicationPendingError,
                match="does not resolve that exact record",
            ),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        upload.assert_not_called()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "publication_reconciliation_required"
        assert manifest["publication"]["baseline"]["matches_expected"] is True
        assert manifest["publication"]["baseline"]["upload_allowed"] is False
        assert manifest["publication"]["prior_unresolved_publication"]["publish_key"] == (
            prior_publish_key
        )
        state_path = tmp_path / "logs" / "kaggle" / "kaggle-publication-state.json"
        records = json.loads(state_path.read_text(encoding="utf-8"))["datasets"][
            "wyattowalsh/basketball"
        ]["publications"]
        assert set(records) == {prior_publish_key}
        assert records[prior_publish_key]["state"] == "unresolved"

    @patch("nbadb.kaggle.client.get_settings")
    def test_changed_bundle_resolves_prior_remote_before_new_upload(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        first_remote = tmp_path / "remote-a"
        second_remote = tmp_path / "remote-b"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()

        def capture_first(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), first_remote)

        with patch("kagglehub.dataset_upload", side_effect=capture_first):
            first_manifest_path = client.upload(data_dir=data_dir, verify_remote=False)
        first_manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
        first_publish_key = first_manifest["publication"]["publish_key"]

        conn = sqlite3.connect(data_dir / "nba.sqlite")
        try:
            conn.execute("INSERT INTO dim_player VALUES (2, 'Changed Player')")
            conn.commit()
        finally:
            conn.close()

        def capture_second(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), second_remote)

        with (
            patch("kagglehub.dataset_upload", side_effect=capture_second) as upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                side_effect=[(str(first_remote), 70), (str(second_remote), 71)],
            ),
            patch.object(client, "_resolve_remote_dataset_version", side_effect=[70, 71]),
        ):
            second_manifest_path = client.upload(data_dir=data_dir, verify_remote=True)

        upload.assert_called_once()
        second_manifest = json.loads(second_manifest_path.read_text(encoding="utf-8"))
        assert second_manifest["status"] == "uploaded_remote_verified"
        assert second_manifest["publication"]["publish_key"] != first_publish_key
        assert second_manifest["publication"]["prior_unresolved_reconciliation"] == {
            "state": "resolved",
            "status": "reconciled_prior_remote",
            "resolved_version": 70,
        }
        state_path = tmp_path / "logs" / "kaggle" / "kaggle-publication-state.json"
        records = json.loads(state_path.read_text(encoding="utf-8"))["datasets"][
            "wyattowalsh/basketball"
        ]["publications"]
        assert records[first_publish_key]["state"] == "resolved"
        assert records[first_publish_key]["resolved_version"] == 70
        assert records[second_manifest["publication"]["publish_key"]]["state"] == "resolved"
        assert records[second_manifest["publication"]["publish_key"]]["resolved_version"] == 71

    @patch("nbadb.kaggle.client.get_settings")
    def test_changed_bundle_does_not_resolve_prior_marker_from_noncurrent_version(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        first_remote = tmp_path / "remote-a"
        _write_upload_bundle(data_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()

        def capture_first(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), first_remote)

        with patch("kagglehub.dataset_upload", side_effect=capture_first):
            first_manifest_path = client.upload(data_dir=data_dir, verify_remote=False)
        first_manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
        first_publish_key = first_manifest["publication"]["publish_key"]

        conn = sqlite3.connect(data_dir / "nba.sqlite")
        try:
            conn.execute("INSERT INTO dim_player VALUES (2, 'Changed Player')")
            conn.commit()
        finally:
            conn.close()

        with (
            patch("kagglehub.dataset_upload") as upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                return_value=(str(first_remote), 70),
            ),
            patch.object(client, "_resolve_remote_dataset_version", return_value=71),
            pytest.raises(RuntimeError, match="not from the current dataset version"),
        ):
            client.upload(data_dir=data_dir, verify_remote=True)

        upload.assert_not_called()
        manifest = json.loads(
            (tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert manifest["status"] == "baseline_reconciliation_failed"
        assert manifest["publication"]["baseline"]["version"] == 70
        assert manifest["publication"]["baseline"]["metadata_version"] == 71
        assert manifest["publication"]["baseline"]["versions_agree"] is False
        records = json.loads(
            (tmp_path / "logs" / "kaggle" / "kaggle-publication-state.json").read_text(
                encoding="utf-8"
            )
        )["datasets"]["wyattowalsh/basketball"]["publications"]
        assert records[first_publish_key]["state"] == "unresolved"

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_remote_timeout_records_reconciliation_required(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        _write_upload_bundle(data_dir)
        stale_dir = tmp_path / "stale"
        _write_stale_publication_marker(stale_dir)
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient, KagglePublicationPendingError

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload") as mock_upload,
            patch(
                "kagglehub.registry.dataset_resolver",
                return_value=(str(stale_dir), 50),
            ),
            pytest.raises(KagglePublicationPendingError),
        ):
            client.upload(
                data_dir=data_dir,
                verify_remote=True,
                remote_timeout_seconds=0,
            )

        mock_upload.assert_called_once()
        manifest_path = tmp_path / "logs" / "kaggle" / "kaggle-upload-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "publication_reconciliation_required"
        assert manifest["publication"]["upload_attempts"] == 1
        assert manifest["publication"]["verification_attempts"] == 1


class TestKaggleClientEnsureMetadata:
    @patch("nbadb.kaggle.client.get_settings")
    def test_ensure_metadata_creates_file(self, mock_settings: MagicMock, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        result = client.ensure_metadata(data_dir=data_dir)
        assert result.exists()
        assert result.name == "dataset-metadata.json"

    @patch("nbadb.kaggle.client.get_settings")
    def test_ensure_metadata_content_is_valid(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        result = client.ensure_metadata(data_dir=data_dir)
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["id"] == "wyattowalsh/basketball"
        assert len(data["resources"]) == 0

    @patch("nbadb.kaggle.client.get_settings")
    def test_ensure_metadata_rejects_missing_data_dir(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "deep" / "nested" / "data"
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with pytest.raises(FileNotFoundError, match="Metadata data_dir does not exist"):
            client.ensure_metadata(data_dir=data_dir)
