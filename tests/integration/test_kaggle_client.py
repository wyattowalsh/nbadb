from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nbadb.core.config import NbaDbSettings, get_settings


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
            assert not (staged_dir / "private-not-declared.txt").exists()

        with patch("kagglehub.dataset_upload", side_effect=inspect_staged_upload) as mock_up:
            manifest_path = client.upload(data_dir=data_dir, version_notes="test upload")
            mock_up.assert_called_once()
            assert mock_up.call_args.kwargs["handle"] == "wyattowalsh/basketball"
            assert mock_up.call_args.kwargs["version_notes"] == "test upload"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "uploaded"
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
        assert manifest["post_upload"]["file_count"] == 3

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

        def mutate_then_stage(*args: object, **kwargs: object) -> object:
            resource_path = data_dir / "nba.sqlite"
            resource_path.unlink()
            try:
                resource_path.symlink_to(outside_path)
            except OSError as exc:
                pytest.skip(f"symlink creation unavailable: {exc}")
            return original_stage(*args, **kwargs)

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

        def mutate_after_stage(*args: object, **kwargs: object) -> object:
            staged = original_stage(*args, **kwargs)
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
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        def capture_upload(**kwargs: object) -> None:
            shutil.copytree(Path(str(kwargs["local_dataset_dir"])), uploaded_dir)

        client = KaggleClient()
        with (
            patch("kagglehub.dataset_upload", side_effect=capture_upload),
            patch("kagglehub.dataset_download", return_value=str(uploaded_dir)) as mock_download,
        ):
            manifest_path = client.upload(data_dir=data_dir, verify_remote=True)

        mock_download.assert_called_once()
        assert mock_download.call_args.args == ("wyattowalsh/basketball",)
        assert mock_download.call_args.kwargs["force_download"] is True
        assert "output_dir" in mock_download.call_args.kwargs
        assert "path" not in mock_download.call_args.kwargs
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "uploaded_remote_verified"
        assert (
            manifest["remote_readback"]["fingerprint"]
            == manifest["preflight"]["staged"]["fingerprint"]
        )

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_verify_remote_falls_back_for_older_kagglehub_download_shapes(
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
            patch("kagglehub.dataset_upload", side_effect=capture_upload),
            patch(
                "kagglehub.dataset_download",
                side_effect=[
                    TypeError("output_dir unsupported"),
                    TypeError("path unsupported"),
                    str(uploaded_dir),
                ],
            ) as mock_download,
        ):
            manifest_path = client.upload(data_dir=data_dir, verify_remote=True)

        assert mock_download.call_count == 3
        first_call, second_call, third_call = mock_download.call_args_list
        assert first_call.args == ("wyattowalsh/basketball",)
        assert first_call.kwargs["force_download"] is True
        assert "output_dir" in first_call.kwargs
        assert "path" not in first_call.kwargs
        assert second_call.args == ("wyattowalsh/basketball",)
        assert second_call.kwargs["force_download"] is True
        assert "path" in second_call.kwargs
        assert "output_dir" not in second_call.kwargs
        assert third_call.args == ("wyattowalsh/basketball",)
        assert third_call.kwargs == {}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["status"] == "uploaded_remote_verified"


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
