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
                logger.info(f"  copied file: {src_file.name} ({src_file.stat().st_size / 1_048_576:.1f} MB)")
                copied += 1
            elif src_file.is_dir():
                dst_sub = dest / src_file.name
                if dst_sub.exists():
                    shutil.rmtree(dst_sub)
                shutil.copytree(src_file, dst_sub)
                logger.info(f"  copied dir: {src_file.name}/")
                copied += 1
        logger.info(f"Copied {copied} items from Kaggle cache to {dest}")

        # Seed DuckDB from SQLite if no DuckDB was downloaded
        duckdb_path = dest / "nba.duckdb"
        sqlite_path = dest / "nba.sqlite"
        if sqlite_path.exists() and not duckdb_path.exists():
            self._seed_duckdb_from_sqlite(sqlite_path, duckdb_path)

        return dest

    @staticmethod
    def _seed_duckdb_from_sqlite(sqlite_path: Path, duckdb_path: Path) -> None:
        """Import all tables from SQLite into a new DuckDB file."""
        import duckdb

        logger.info(f"Seeding DuckDB from {sqlite_path.name}...")
        conn = duckdb.connect(str(duckdb_path))
        try:
            conn.execute("INSTALL sqlite; LOAD sqlite;")
            conn.execute(
                f"ATTACH '{sqlite_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)"
            )
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_db.sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            total_rows = 0
            for table in tables:
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM sqlite_db.{table}"
                )
                rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                total_rows += rows
                logger.debug(f"  seeded {table}: {rows:,} rows")
            conn.execute("DETACH sqlite_db")
            logger.info(
                f"Seeded DuckDB: {len(tables)} tables, {total_rows:,} rows total"
            )
        finally:
            conn.close()

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
