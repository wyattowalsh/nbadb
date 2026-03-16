from __future__ import annotations

from pathlib import Path

from loguru import logger

from nbadb.core.config import get_settings


class KaggleClient:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._dataset = self._settings.kaggle_dataset

    def download(self, target_dir: Path | None = None) -> Path:
        """Download latest dataset from Kaggle and copy to data dir."""
        import shutil

        import kagglehub

        path = kagglehub.dataset_download(self._dataset)
        download_path = Path(path)
        logger.info(f"Downloaded dataset to {download_path}")

        dest = Path(target_dir) if target_dir else self._settings.data_dir
        dest.mkdir(parents=True, exist_ok=True)

        # Copy downloaded files into the working data directory
        copied = 0
        for src_file in download_path.iterdir():
            if src_file.is_file():
                shutil.copy2(src_file, dest / src_file.name)
                copied += 1
            elif src_file.is_dir():
                dst_sub = dest / src_file.name
                if dst_sub.exists():
                    shutil.rmtree(dst_sub)
                shutil.copytree(src_file, dst_sub)
                copied += 1
        logger.info(f"Copied {copied} items from Kaggle cache to {dest}")
        return dest

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
