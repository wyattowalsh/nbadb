from __future__ import annotations

from pathlib import Path

from loguru import logger

from nbadb.core.config import get_settings


class KaggleClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._dataset = self._settings.kaggle_dataset

    def download(self, target_dir: Path | None = None) -> Path:
        """Download latest dataset from Kaggle."""
        import kagglehub
        path = kagglehub.dataset_download(self._dataset)
        download_path = Path(path)
        logger.info(f"Downloaded dataset to {download_path}")
        return download_path

    def upload(
        self,
        data_dir: Path | None = None,
        version_notes: str = "Automated update via nbadb",
    ) -> None:
        """Upload dataset to Kaggle."""
        import kagglehub
        upload_dir = data_dir or self._settings.data_dir
        if not upload_dir.exists():
            msg = f"Data directory does not exist: {upload_dir}"
            raise FileNotFoundError(msg)
        kagglehub.dataset_upload(
            handle=self._dataset,
            local_dataset_dir=str(upload_dir),
            version_notes=version_notes,
        )
        logger.info(f"Uploaded dataset from {upload_dir}")

    def ensure_metadata(self, data_dir: Path | None = None) -> Path:
        """Ensure dataset-metadata.json exists in data dir."""
        from nbadb.kaggle.metadata import generate_metadata
        target = (data_dir or self._settings.data_dir) / "dataset-metadata.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        generate_metadata(target)
        return target
