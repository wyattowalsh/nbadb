from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, cast

from loguru import logger

from nbadb.core.config import get_settings
from nbadb.core.types import validate_sql_identifier


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
        copied_names: set[str] = set()
        for src_file in download_path.iterdir():
            if src_file.is_file():
                shutil.copy2(src_file, dest / src_file.name)
                copied_names.add(src_file.name)
                size_mb = src_file.stat().st_size / 1_048_576
                logger.info(f"  copied file: {src_file.name} ({size_mb:.1f} MB)")
                copied += 1
            elif src_file.is_dir():
                dst_sub = dest / src_file.name
                if dst_sub.exists():
                    shutil.rmtree(dst_sub)
                shutil.copytree(src_file, dst_sub)
                logger.info(f"  copied dir: {src_file.name}/")
                copied += 1
        logger.info(f"Copied {copied} items from Kaggle cache to {dest}")

        self._sync_duckdb_after_download(dest, copied_names=copied_names)

        return dest

    @staticmethod
    def _sync_duckdb_after_download(dest: Path, *, copied_names: set[str]) -> None:
        """Ensure DuckDB reflects the freshly downloaded bundle."""
        duckdb_path = dest / "nba.duckdb"
        sqlite_path = dest / "nba.sqlite"
        if "nba.duckdb" in copied_names or "nba.sqlite" not in copied_names:
            return
        if duckdb_path.exists():
            logger.info("Replacing stale local nba.duckdb from freshly downloaded nba.sqlite")
            duckdb_path.unlink()
        KaggleClient._seed_duckdb_from_sqlite(sqlite_path, duckdb_path)

    @staticmethod
    def _seed_duckdb_from_sqlite(sqlite_path: Path, duckdb_path: Path) -> None:
        """Import all tables from SQLite into a new DuckDB file."""
        import duckdb

        logger.info(f"Seeding DuckDB from {sqlite_path.name}...")
        conn = duckdb.connect(str(duckdb_path))
        try:
            conn.execute("INSTALL sqlite; LOAD sqlite;")
            # Use parameterized path to prevent single-quote injection
            safe_path = str(sqlite_path).replace("'", "''")
            conn.execute(f"ATTACH '{safe_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")
            tables = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_db.sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            total_rows = 0
            for table in tables:
                validate_sql_identifier(table)
                # Quote identifiers to prevent SQL injection from table names
                quoted = f'"{table}"'
                conn.execute(
                    f"CREATE TABLE IF NOT EXISTS {quoted} AS SELECT * FROM sqlite_db.{quoted}"
                )
                row_count = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
                if row_count is None:
                    msg = f"Failed to read row count for table {table}"
                    raise RuntimeError(msg)
                rows = row_count[0]
                total_rows += rows
                logger.debug(f"  seeded {table}: {rows:,} rows")
            conn.execute("DETACH sqlite_db")
            logger.info(f"Seeded DuckDB: {len(tables)} tables, {total_rows:,} rows total")
        finally:
            conn.close()

    def upload(
        self,
        data_dir: Path | None = None,
        version_notes: str = "Automated update via nbadb",
        verify_remote: bool = False,
    ) -> Path:
        """Upload dataset to Kaggle after validating the local upload bundle."""
        import kagglehub

        upload_dir = data_dir or self._settings.data_dir
        if not upload_dir.exists():
            msg = f"Data directory does not exist: {upload_dir}"
            raise FileNotFoundError(msg)
        if not upload_dir.is_dir():
            msg = f"Data path is not a directory: {upload_dir}"
            raise NotADirectoryError(msg)

        preflight = self._snapshot_upload_bundle(upload_dir)
        with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-upload-") as temp_dir:
            staged_dir = Path(temp_dir) / "dataset"
            staged_dir.mkdir(parents=True)
            try:
                staged = self._stage_upload_bundle(upload_dir, staged_dir, preflight)
            except Exception as exc:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="staging_failed",
                    preflight=preflight,
                    error=self._redacted_error(exc),
                )
                raise
            expected_staged = self._expected_staged_tree_snapshot(preflight, staged_dir)
            preflight["staged"] = staged
            preflight["expected_staged"] = expected_staged
            if staged["fingerprint"] != expected_staged["fingerprint"]:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="staged_pre_upload_mismatch",
                    preflight=preflight,
                    post_upload=staged,
                )
                msg = "Kaggle staged upload bundle does not match the validated preflight inventory"
                raise RuntimeError(msg)

            try:
                source_before_upload = self._snapshot_upload_bundle(upload_dir)
            except Exception as exc:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="source_validation_failed_before_upload",
                    preflight=preflight,
                    post_upload=staged,
                    error=self._redacted_error(exc),
                )
                raise
            preflight["source_before_upload"] = source_before_upload
            if source_before_upload["fingerprint"] != preflight["fingerprint"]:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="source_changed_before_upload",
                    preflight=preflight,
                    post_upload=staged,
                )
                msg = "Kaggle upload source bundle changed before upload"
                raise RuntimeError(msg)

            manifest_path = self._write_upload_manifest(
                data_dir=upload_dir,
                staged_dir=staged_dir,
                version_notes=version_notes,
                status="preflight_passed",
                preflight=preflight,
            )
            try:
                kagglehub.dataset_upload(
                    handle=self._dataset,
                    local_dataset_dir=str(staged_dir),
                    version_notes=version_notes,
                )
            except Exception as exc:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="upload_failed",
                    preflight=preflight,
                    error=self._redacted_error(exc),
                )
                raise

            post_upload = self._snapshot_tree(staged_dir)
            if post_upload["fingerprint"] != staged["fingerprint"]:
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="post_upload_mismatch_remote_may_exist",
                    preflight=preflight,
                    post_upload=post_upload,
                )
                msg = (
                    "Kaggle upload bundle changed during upload; the remote Kaggle "
                    "version may already have been created"
                )
                raise RuntimeError(msg)

            remote_readback = None
            if verify_remote:
                try:
                    remote_readback = self._verify_remote_upload(expected_staged)
                except Exception as exc:
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="remote_readback_failed",
                        preflight=preflight,
                        post_upload=post_upload,
                        error=self._redacted_error(exc),
                    )
                    raise

            manifest_path = self._write_upload_manifest(
                data_dir=upload_dir,
                staged_dir=staged_dir,
                version_notes=version_notes,
                status="uploaded_remote_verified" if verify_remote else "uploaded",
                preflight=preflight,
                post_upload=post_upload,
                remote_readback=remote_readback,
            )
        logger.info(f"Uploaded dataset from {upload_dir}")
        logger.info(f"Wrote Kaggle upload manifest to {manifest_path}")
        return manifest_path

    def ensure_metadata(self, data_dir: Path | None = None) -> Path:
        """Ensure dataset-metadata.json exists in data dir."""
        from nbadb.kaggle.metadata import generate_metadata

        resolved_data_dir = data_dir or self._settings.data_dir
        target = resolved_data_dir / "dataset-metadata.json"
        generate_metadata(target, data_dir=resolved_data_dir)
        return target

    def _snapshot_upload_bundle(self, data_dir: Path) -> dict[str, Any]:
        metadata_path = data_dir / "dataset-metadata.json"
        if not metadata_path.is_file():
            msg = f"Kaggle metadata file does not exist: {metadata_path}"
            raise FileNotFoundError(msg)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            msg = f"Kaggle metadata file is not valid JSON: {metadata_path}"
            raise ValueError(msg) from exc
        if metadata.get("id") != self._dataset:
            msg = (
                "Kaggle metadata dataset id does not match configured dataset: "
                f"{metadata.get('id')!r} != {self._dataset!r}"
            )
            raise ValueError(msg)

        resources = metadata.get("resources")
        if not isinstance(resources, list):
            msg = "Kaggle metadata resources must be a list"
            raise ValueError(msg)
        if not resources:
            msg = "Kaggle upload bundle has no declared data resources"
            raise ValueError(msg)

        resource_inventory: list[dict[str, Any]] = []
        seen_paths: set[str] = set()
        seen_resolved_paths: set[Path] = set()
        data_root = data_dir.resolve()
        for index, resource in enumerate(resources):
            if not isinstance(resource, dict):
                msg = f"Kaggle resource entry {index} must be an object"
                raise ValueError(msg)
            resource = cast("dict[str, Any]", resource)
            raw_path = resource.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                msg = f"Kaggle resource entry {index} is missing a non-empty path"
                raise ValueError(msg)
            normalized_path = self._normalize_resource_path(raw_path)
            if normalized_path in seen_paths:
                msg = f"Kaggle metadata declares duplicate resource path: {normalized_path}"
                raise ValueError(msg)
            overlapping_path = next(
                (
                    seen_path
                    for seen_path in seen_paths
                    if self._resource_paths_overlap(normalized_path, seen_path)
                ),
                None,
            )
            if overlapping_path is not None:
                msg = (
                    "Kaggle metadata declares overlapping resource paths: "
                    f"{normalized_path} and {overlapping_path}"
                )
                raise ValueError(msg)
            seen_paths.add(normalized_path)
            resource_path = Path(normalized_path)
            source_resource_path = data_root / resource_path
            if source_resource_path.is_symlink():
                msg = f"Kaggle resource path must not be a symlink: {normalized_path}"
                raise ValueError(msg)
            resolved_resource_path = (data_root / resource_path).resolve()
            try:
                resolved_resource_path.relative_to(data_root)
            except ValueError as exc:
                msg = f"Kaggle resource path escapes data directory: {raw_path}"
                raise ValueError(msg) from exc
            if resolved_resource_path in seen_resolved_paths:
                msg = f"Kaggle metadata declares duplicate resolved resource: {normalized_path}"
                raise ValueError(msg)
            seen_resolved_paths.add(resolved_resource_path)
            if resolved_resource_path.is_file():
                database_validation = self._database_validation_for_resource(
                    resolved_resource_path,
                    normalized_path,
                )
                parquet_validation = self._parquet_validation_for_resource(
                    resolved_resource_path,
                    normalized_path,
                )
                inventory: dict[str, Any] = {
                    "path": normalized_path,
                    "source_path": str(resolved_resource_path),
                    "kind": "file",
                    "bytes": resolved_resource_path.stat().st_size,
                    "sha256": self._file_sha256(resolved_resource_path),
                }
                if database_validation is not None:
                    inventory["database_validation"] = database_validation
                if parquet_validation is not None:
                    inventory["parquet_validation"] = parquet_validation
                resource_inventory.append(inventory)
                continue
            if resolved_resource_path.is_dir():
                directory_inventory = self._directory_inventory(resolved_resource_path)
                self._validate_directory_resource_inventory(
                    normalized_path,
                    directory_inventory,
                    resolved_resource_path,
                )
                resource_inventory.append(
                    {
                        "path": normalized_path,
                        "source_path": str(resolved_resource_path),
                        "kind": "directory",
                        "bytes": directory_inventory["bytes"],
                        "file_count": directory_inventory["file_count"],
                        "sha256": directory_inventory["fingerprint"],
                        "files": directory_inventory["files"],
                    }
                )
                continue
            if not resolved_resource_path.exists():
                msg = f"Kaggle resource path does not exist: {raw_path}"
                raise FileNotFoundError(msg)
            msg = f"Kaggle resource path is not a file or directory: {raw_path}"
            raise ValueError(msg)

        self._validate_database_resource_parity(resource_inventory)
        metadata_bytes = metadata_path.read_bytes()
        fingerprint_payload = {
            "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
            "resources": sorted(resource_inventory, key=lambda resource: resource["path"]),
        }
        fingerprint_source = json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "dataset": self._dataset,
            "metadata_path": str(metadata_path),
            "metadata_bytes": len(metadata_bytes),
            "metadata_sha256": fingerprint_payload["metadata_sha256"],
            "resource_count": len(resource_inventory),
            "resource_bytes": sum(resource["bytes"] for resource in resource_inventory),
            "resources": fingerprint_payload["resources"],
            "fingerprint": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        }

    def _stage_upload_bundle(
        self,
        source_dir: Path,
        staged_dir: Path,
        preflight: dict[str, Any],
    ) -> dict[str, Any]:
        self._stage_file_from_inventory(
            source_path=source_dir / "dataset-metadata.json",
            destination=staged_dir / "dataset-metadata.json",
            inventory={
                "path": "dataset-metadata.json",
                "bytes": preflight["metadata_bytes"],
                "sha256": preflight["metadata_sha256"],
            },
        )
        staged_paths: set[str] = {"dataset-metadata.json"}
        for resource in preflight["resources"]:
            relative_path = resource["path"]
            if relative_path in staged_paths:
                msg = f"Kaggle staged bundle path collision: {relative_path}"
                raise ValueError(msg)
            staged_paths.add(relative_path)
            source_path = Path(resource["source_path"])
            destination = staged_dir / relative_path
            if resource["kind"] == "file":
                self._stage_file_from_inventory(
                    source_path=source_path,
                    destination=destination,
                    inventory=resource,
                )
            elif resource["kind"] == "directory":
                for file_inventory in resource["files"]:
                    child_relative_path = file_inventory["path"]
                    staged_child_path = f"{relative_path}/{child_relative_path}"
                    self._stage_file_from_inventory(
                        source_path=source_path / child_relative_path,
                        destination=staged_dir / staged_child_path,
                        inventory={
                            "path": staged_child_path,
                            "bytes": file_inventory["bytes"],
                            "sha256": file_inventory["sha256"],
                        },
                    )
            else:
                msg = f"Unsupported Kaggle resource kind: {resource['kind']}"
                raise ValueError(msg)
        return self._snapshot_tree(staged_dir)

    def _write_upload_manifest(
        self,
        *,
        data_dir: Path,
        staged_dir: Path | None = None,
        version_notes: str,
        status: str,
        preflight: dict[str, Any],
        post_upload: dict[str, Any] | None = None,
        remote_readback: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Path:
        manifest_dir = self._settings.log_dir / "kaggle"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "kaggle-upload-manifest.json"
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": status,
            "dataset": self._dataset,
            "data_dir": str(data_dir),
            "staged_dir": str(staged_dir) if staged_dir is not None else None,
            "version_notes": version_notes,
            "preflight": preflight,
        }
        if post_upload is not None:
            manifest["post_upload"] = post_upload
        if remote_readback is not None:
            manifest["remote_readback"] = remote_readback
        if error is not None:
            manifest["error"] = error
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest_path

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _normalize_resource_path(raw_path: str) -> str:
        if "\\" in raw_path:
            msg = f"Kaggle resource path must use POSIX separators: {raw_path}"
            raise ValueError(msg)
        path = PurePosixPath(raw_path.strip())
        if path.is_absolute():
            msg = f"Kaggle resource path must be relative: {raw_path}"
            raise ValueError(msg)
        if not path.parts or any(part in ("", ".", "..") for part in path.parts):
            msg = f"Kaggle resource path must be a normalized relative path: {raw_path}"
            raise ValueError(msg)
        return path.as_posix()

    @staticmethod
    def _resource_paths_overlap(first_path: str, second_path: str) -> bool:
        return first_path.startswith(f"{second_path}/") or second_path.startswith(f"{first_path}/")

    @staticmethod
    def _validate_directory_resource_inventory(
        resource_path: str,
        directory_inventory: dict[str, Any],
        directory_path: Path,
    ) -> None:
        if int(directory_inventory.get("file_count", 0)) == 0:
            msg = f"Kaggle directory resource is empty: {resource_path}"
            raise ValueError(msg)
        for file_inventory in directory_inventory["files"]:
            relative_path = file_inventory["path"]
            parts = PurePosixPath(relative_path).parts
            if any(part.startswith(".") for part in parts):
                msg = (
                    "Kaggle resource directory contains hidden or ignored path: "
                    f"{resource_path}/{relative_path}"
                )
                raise ValueError(msg)
            if PurePosixPath(relative_path).suffix != ".parquet":
                msg = (
                    "Kaggle directory resources may only contain parquet files: "
                    f"{resource_path}/{relative_path}"
                )
                raise ValueError(msg)
            file_inventory["parquet_validation"] = KaggleClient._validate_parquet_file(
                directory_path / relative_path,
                f"{resource_path}/{relative_path}",
            )

    def _directory_inventory(self, path: Path) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        total_bytes = 0
        for child in sorted(path.rglob("*")):
            if child.is_symlink():
                msg = f"Kaggle resource directory contains symlink: {child}"
                raise ValueError(msg)
            if not child.is_file():
                continue
            relative_path = child.relative_to(path).as_posix()
            size = child.stat().st_size
            total_bytes += size
            files.append(
                {
                    "path": relative_path,
                    "bytes": size,
                    "sha256": self._file_sha256(child),
                }
            )
        fingerprint_source = json.dumps(files, sort_keys=True, separators=(",", ":"))
        return {
            "bytes": total_bytes,
            "file_count": len(files),
            "files": files,
            "fingerprint": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        }

    def _stage_file_from_inventory(
        self,
        *,
        source_path: Path,
        destination: Path,
        inventory: dict[str, Any],
    ) -> None:
        relative_path = inventory["path"]
        self._assert_file_matches_inventory(
            source_path,
            inventory,
            relative_path=relative_path,
            mismatch_message="Kaggle resource file changed before staging",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        self._assert_file_matches_inventory(
            destination,
            inventory,
            relative_path=relative_path,
            mismatch_message="Kaggle staged file does not match preflight inventory",
        )

    def _assert_file_matches_inventory(
        self,
        path: Path,
        inventory: dict[str, Any],
        *,
        relative_path: str,
        mismatch_message: str,
    ) -> None:
        if path.is_symlink():
            msg = f"Kaggle file inventory path must not be a symlink: {relative_path}"
            raise ValueError(msg)
        if not path.is_file():
            msg = f"Kaggle file inventory path does not exist: {relative_path}"
            raise FileNotFoundError(msg)
        size = path.stat().st_size
        digest = self._file_sha256(path)
        if size != inventory["bytes"] or digest != inventory["sha256"]:
            msg = f"{mismatch_message}: {relative_path}"
            raise ValueError(msg)

    @staticmethod
    def _expected_staged_tree_snapshot(
        preflight: dict[str, Any],
        root: Path,
    ) -> dict[str, Any]:
        files: list[dict[str, Any]] = [
            {
                "path": "dataset-metadata.json",
                "bytes": preflight["metadata_bytes"],
                "sha256": preflight["metadata_sha256"],
            }
        ]
        for resource in preflight["resources"]:
            if resource["kind"] == "file":
                files.append(
                    {
                        "path": resource["path"],
                        "bytes": resource["bytes"],
                        "sha256": resource["sha256"],
                    }
                )
                continue
            if resource["kind"] == "directory":
                for file_inventory in resource["files"]:
                    files.append(
                        {
                            "path": f"{resource['path']}/{file_inventory['path']}",
                            "bytes": file_inventory["bytes"],
                            "sha256": file_inventory["sha256"],
                        }
                    )
        files = sorted(files, key=lambda file_inventory: file_inventory["path"])
        fingerprint_source = json.dumps(files, sort_keys=True, separators=(",", ":"))
        return {
            "root": str(root),
            "file_count": len(files),
            "bytes": sum(file_inventory["bytes"] for file_inventory in files),
            "files": files,
            "fingerprint": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        }

    def _snapshot_tree(self, root: Path) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        total_bytes = 0
        for child in sorted(root.rglob("*")):
            if child.is_symlink():
                msg = f"Kaggle staged bundle contains symlink: {child}"
                raise ValueError(msg)
            if not child.is_file():
                continue
            relative_path = child.relative_to(root).as_posix()
            size = child.stat().st_size
            total_bytes += size
            files.append(
                {
                    "path": relative_path,
                    "bytes": size,
                    "sha256": self._file_sha256(child),
                }
            )
        fingerprint_source = json.dumps(files, sort_keys=True, separators=(",", ":"))
        return {
            "root": str(root),
            "file_count": len(files),
            "bytes": total_bytes,
            "files": files,
            "fingerprint": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _database_validation_for_resource(path: Path, resource_path: str) -> dict[str, Any] | None:
        suffix = PurePosixPath(resource_path).suffix.lower()
        if suffix in {".sqlite", ".sqlite3", ".db"}:
            return KaggleClient._validate_sqlite_database(path, resource_path)
        if suffix == ".duckdb":
            return KaggleClient._validate_duckdb_database(path, resource_path)
        return None

    @staticmethod
    def _parquet_validation_for_resource(path: Path, resource_path: str) -> dict[str, Any] | None:
        suffix = PurePosixPath(resource_path).suffix.lower()
        if suffix == ".parquet":
            return KaggleClient._validate_parquet_file(path, resource_path)
        return None

    @staticmethod
    def _validate_parquet_file(path: Path, resource_path: str) -> dict[str, Any]:
        import pyarrow.parquet as pq

        try:
            metadata = pq.read_metadata(path)
            arrow_schema = metadata.schema.to_arrow_schema()
        except Exception as exc:
            msg = f"Kaggle Parquet resource metadata validation failed: {resource_path}"
            raise ValueError(msg) from exc
        return {
            "engine": "parquet",
            "row_count": int(metadata.num_rows),
            "column_count": int(metadata.num_columns),
            "row_group_count": int(metadata.num_row_groups),
            "columns": list(arrow_schema.names),
        }

    @staticmethod
    def _validate_sqlite_database(path: Path, resource_path: str) -> dict[str, Any]:
        import sqlite3

        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.DatabaseError as exc:
            msg = f"Kaggle SQLite resource is not readable: {resource_path}"
            raise ValueError(msg) from exc
        try:
            quick_check = conn.execute("PRAGMA quick_check").fetchone()
            if quick_check is None or str(quick_check[0]).lower() != "ok":
                msg = f"Kaggle SQLite resource failed quick_check: {resource_path}"
                raise ValueError(msg)
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_rows:
                msg = f"Kaggle SQLite resource failed foreign_key_check: {resource_path}"
                raise ValueError(msg)
            table_names = [
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                ).fetchall()
            ]
            public_table_names = sorted(
                table_name for table_name in table_names if not table_name.startswith("_")
            )
            excluded_internal_tables = sorted(
                table_name for table_name in table_names if table_name.startswith("_")
            )
            if not public_table_names:
                msg = f"Kaggle SQLite resource contains no public user tables: {resource_path}"
                raise ValueError(msg)
            row_counts: dict[str, int] = {}
            for table_name in public_table_names:
                validate_sql_identifier(table_name)
                quoted = f'"{table_name}"'
                row = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
                row_counts[table_name] = int(row[0]) if row is not None else 0
        except sqlite3.DatabaseError as exc:
            msg = f"Kaggle SQLite resource integrity validation failed: {resource_path}"
            raise ValueError(msg) from exc
        finally:
            conn.close()
        return {
            "engine": "sqlite",
            "quick_check": "ok",
            "foreign_key_check_error_count": 0,
            "table_count": len(public_table_names),
            "row_count": sum(row_counts.values()),
            "tables": row_counts,
            "excluded_internal_table_count": len(excluded_internal_tables),
            "excluded_internal_tables": excluded_internal_tables,
        }

    @staticmethod
    def _validate_duckdb_database(path: Path, resource_path: str) -> dict[str, Any]:
        import duckdb

        from nbadb.core.db import get_user_tables

        try:
            conn = duckdb.connect(str(path), read_only=True)
        except duckdb.Error as exc:
            msg = f"Kaggle DuckDB resource is not readable: {resource_path}"
            raise ValueError(msg) from exc
        try:
            all_table_names = sorted(
                str(row[0])
                for row in conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            )
            table_names = get_user_tables(conn)
            excluded_internal_tables = sorted(
                table_name for table_name in all_table_names if table_name.startswith("_")
            )
            if not table_names:
                msg = f"Kaggle DuckDB resource contains no public user tables: {resource_path}"
                raise ValueError(msg)
            row_counts: dict[str, int] = {}
            for table_name in table_names:
                validate_sql_identifier(table_name)
                quoted = f'"{table_name}"'
                row = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
                row_counts[table_name] = int(row[0]) if row is not None else 0
        except duckdb.Error as exc:
            msg = f"Kaggle DuckDB resource integrity validation failed: {resource_path}"
            raise ValueError(msg) from exc
        finally:
            conn.close()
        return {
            "engine": "duckdb",
            "table_count": len(table_names),
            "row_count": sum(row_counts.values()),
            "tables": row_counts,
            "excluded_internal_table_count": len(excluded_internal_tables),
            "excluded_internal_tables": excluded_internal_tables,
        }

    @staticmethod
    def _validate_database_resource_parity(resources: list[dict[str, Any]]) -> None:
        database_resources = [
            resource
            for resource in resources
            if isinstance(resource.get("database_validation"), dict)
        ]
        sqlite_resource = next(
            (
                resource
                for resource in database_resources
                if resource["database_validation"].get("engine") == "sqlite"
            ),
            None,
        )
        duckdb_resource = next(
            (
                resource
                for resource in database_resources
                if resource["database_validation"].get("engine") == "duckdb"
            ),
            None,
        )
        if sqlite_resource is None or duckdb_resource is None:
            return
        sqlite_tables = sqlite_resource["database_validation"]["tables"]
        duckdb_tables = duckdb_resource["database_validation"]["tables"]
        sqlite_table_names = set(sqlite_tables)
        duckdb_table_names = set(duckdb_tables)
        missing_from_sqlite = sorted(duckdb_table_names - sqlite_table_names)
        missing_from_duckdb = sorted(sqlite_table_names - duckdb_table_names)
        if missing_from_sqlite or missing_from_duckdb:
            msg = (
                "Kaggle SQLite and DuckDB resources are missing public tables: "
                f"{sqlite_resource['path']} vs {duckdb_resource['path']}; "
                f"missing_from_sqlite={missing_from_sqlite}; "
                f"missing_from_duckdb={missing_from_duckdb}"
            )
            raise ValueError(msg)
        row_count_diffs = {
            table_name: {
                "sqlite": sqlite_tables[table_name],
                "duckdb": duckdb_tables[table_name],
            }
            for table_name in sorted(sqlite_table_names)
            if sqlite_tables[table_name] != duckdb_tables[table_name]
        }
        if row_count_diffs:
            msg = (
                "Kaggle SQLite and DuckDB resources have mismatched public table row counts: "
                f"{sqlite_resource['path']} vs {duckdb_resource['path']}; "
                f"differences={row_count_diffs}"
            )
            raise ValueError(msg)

    def _verify_remote_upload(self, expected_staged: dict[str, Any]) -> dict[str, Any]:
        import kagglehub

        with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-readback-") as temp_dir:
            download_root = Path(temp_dir)
            try:
                downloaded = kagglehub.dataset_download(
                    self._dataset,
                    output_dir=str(download_root),
                    force_download=True,
                )
            except TypeError:
                try:
                    downloaded = kagglehub.dataset_download(
                        self._dataset,
                        path=str(download_root),
                        force_download=True,
                    )
                except TypeError:
                    downloaded = kagglehub.dataset_download(self._dataset)
            remote_path = Path(downloaded)
            remote_snapshot = self._snapshot_tree(remote_path)
            if remote_snapshot["fingerprint"] != expected_staged["fingerprint"]:
                msg = "Kaggle remote readback bundle does not match uploaded staged inventory"
                raise RuntimeError(msg)
            return remote_snapshot

    @staticmethod
    def _redacted_error(exc: Exception) -> str:
        message = str(exc)
        home = str(Path.home())
        if home and home in message:
            message = message.replace(home, "~")
        message = re.sub(r"(?i)(kaggle[_-]?(?:key|token|secret)=)[^\s]+", r"\1<redacted>", message)
        return f"{type(exc).__name__}: {message}"
