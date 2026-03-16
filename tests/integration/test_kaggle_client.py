from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from nbadb.core.config import NbaDbSettings, get_settings

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear lru_cache on get_settings so mocks take effect."""
    get_settings.cache_clear()


class TestKaggleClientDownload:
    @patch("nbadb.kaggle.client.get_settings")
    def test_download_copies_to_data_dir(self, mock_settings: MagicMock, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        mock_settings.return_value = NbaDbSettings(
            data_dir=data_dir, log_dir=tmp_path / "logs"
        )
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


class TestKaggleClientUpload:
    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_calls_kagglehub_with_correct_args(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with patch("kagglehub.dataset_upload") as mock_up:
            client.upload(data_dir=data_dir, version_notes="test upload")
            mock_up.assert_called_once_with(
                handle="wyattowalsh/basketball",
                local_dataset_dir=str(data_dir),
                version_notes="test upload",
            )

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_uses_settings_data_dir_by_default(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with patch("kagglehub.dataset_upload") as mock_up:
            client.upload()
            mock_up.assert_called_once()
            assert mock_up.call_args.kwargs["local_dataset_dir"] == str(data_dir)

    @patch("nbadb.kaggle.client.get_settings")
    def test_upload_raises_on_missing_dir(self, mock_settings: MagicMock, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        mock_settings.return_value = NbaDbSettings(data_dir=missing, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        with pytest.raises(FileNotFoundError, match="does not exist"):
            client.upload(data_dir=missing)


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
        assert len(data["resources"]) == 55

    @patch("nbadb.kaggle.client.get_settings")
    def test_ensure_metadata_creates_parent_dirs(
        self, mock_settings: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "deep" / "nested" / "data"
        mock_settings.return_value = NbaDbSettings(data_dir=data_dir, log_dir=tmp_path / "logs")
        from nbadb.kaggle.client import KaggleClient

        client = KaggleClient()
        result = client.ensure_metadata(data_dir=data_dir)
        assert result.exists()
