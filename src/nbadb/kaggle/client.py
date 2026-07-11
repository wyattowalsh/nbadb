from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import BinaryIO, Protocol

    class _FcntlModule(Protocol):
        LOCK_EX: int
        LOCK_NB: int
        LOCK_UN: int

        def flock(self, file_descriptor: int, operation: int) -> None: ...

    class _MsvcrtModule(Protocol):
        LK_NBLCK: int
        LK_UNLCK: int

        def locking(self, file_descriptor: int, mode: int, byte_count: int) -> None: ...


from loguru import logger

from nbadb.core.config import get_settings
from nbadb.core.types import validate_sql_identifier

PUBLICATION_MARKER_NAME = "nbadb-publication.json"
PUBLICATION_STATE_NAME = "kaggle-publication-state.json"
UPLOAD_SERIALIZATION_CONTRACT = {
    "mechanism": "process_mutex_and_advisory_file_lock",
    "scope": "same_process_and_same_host_shared_log_directory",
    "cross_host_supported": False,
    "cross_host_guard": "remote_marker_and_exact_version_reconciliation",
}
_PUBLICATION_RECORD_STATES = frozenset({"failed", "resolved", "unresolved"})

_PROCESS_UPLOAD_LOCK = threading.Lock()
_AUTHORIZATION_BEARER_RE = re.compile(
    r"(?i)(\bauthorization\b[\"']?\s*(?::|=)?\s*[\"']?bearer\s+)([^\"'\s,;}]+)"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|kaggle[_-]?(?:key|token|secret)|"
    r"(?:[a-z0-9]+[_-])?(?:token|secret|password))\b[\"']?\s*(?:=|:)\s*)"
    r"([\"']?)([^\"'\s&,;}\]]+)([\"']?)"
)
_SECRET_FLAG_RE = re.compile(
    r"(?i)((?:--)(?:api[_-]?key|(?:[a-z0-9]+[_-])?(?:token|secret|password))\s+)"
    r"([\"']?)([^\"'\s,;}]+)([\"']?)"
)


class KagglePublicationPendingError(RuntimeError):
    def __init__(self, message: str, publication: dict[str, Any]) -> None:
        self.publication = publication
        super().__init__(message)


class _PosixAdvisoryFileLock:
    @staticmethod
    def acquire(handle: BinaryIO) -> None:
        fcntl = cast("_FcntlModule", importlib.import_module("fcntl"))

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def release(handle: BinaryIO) -> None:
        fcntl = cast("_FcntlModule", importlib.import_module("fcntl"))

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class _WindowsAdvisoryFileLock:
    @staticmethod
    def acquire(handle: BinaryIO) -> None:
        msvcrt = cast("_MsvcrtModule", importlib.import_module("msvcrt"))

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError("The advisory lock is already held") from exc

    @staticmethod
    def release(handle: BinaryIO) -> None:
        msvcrt = cast("_MsvcrtModule", importlib.import_module("msvcrt"))

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _advisory_file_lock_backend() -> type[_PosixAdvisoryFileLock] | type[_WindowsAdvisoryFileLock]:
    if os.name == "posix":
        return _PosixAdvisoryFileLock
    if os.name == "nt":
        return _WindowsAdvisoryFileLock
    msg = f"Kaggle advisory file locking is unsupported on os.name={os.name!r}"
    raise RuntimeError(msg)


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

    def publication_preflight(self) -> dict[str, Any]:
        """Read and classify exact remote publication evidence without uploading."""
        try:
            with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-preflight-") as temp_dir:
                marker, marker_version = self._download_remote_publication_marker(Path(temp_dir))
        except Exception as exc:
            if not self._is_publication_marker_not_found(exc):
                raise
            version = self._resolve_remote_dataset_version()
            return {
                "acceptable": True,
                "dataset": self._dataset,
                "state": "bootstrap_marker_missing",
                "marker_status_code": int(HTTPStatus.NOT_FOUND),
                "version": version,
            }

        self._validate_publication_marker(marker)
        metadata_version = self._resolve_remote_dataset_version()
        if marker_version != metadata_version:
            msg = (
                "Kaggle publication preflight resolved ambiguous dataset versions: "
                f"marker={marker_version}, metadata={metadata_version}"
            )
            raise RuntimeError(msg)
        return {
            "acceptable": True,
            "dataset": self._dataset,
            "state": "marker_present",
            "version": marker_version,
            "publish_key": marker["publish_key"],
            "bundle_fingerprint": marker["bundle_fingerprint"],
        }

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
        remote_timeout_seconds: float = 900.0,
        remote_poll_interval_seconds: float = 15.0,
    ) -> Path:
        """Upload with same-host serialization and remote publication reconciliation.

        The advisory file claim coordinates processes that share this client's local
        log directory. Kaggle has no conditional version-upload API, so separate hosts
        remain coordinated only by the marker and exact-version checks.
        """
        with self._local_upload_claim():
            return self._upload_claimed(
                data_dir=data_dir,
                version_notes=version_notes,
                verify_remote=verify_remote,
                remote_timeout_seconds=remote_timeout_seconds,
                remote_poll_interval_seconds=remote_poll_interval_seconds,
            )

    def _upload_claimed(
        self,
        data_dir: Path | None = None,
        version_notes: str = "Automated update via nbadb",
        verify_remote: bool = False,
        remote_timeout_seconds: float = 900.0,
        remote_poll_interval_seconds: float = 15.0,
    ) -> Path:
        """Validate and upload a bundle while the local upload claim is held."""
        import kagglehub

        upload_dir = data_dir or self._settings.data_dir
        if not upload_dir.exists():
            msg = f"Data directory does not exist: {upload_dir}"
            raise FileNotFoundError(msg)
        if not upload_dir.is_dir():
            msg = f"Data path is not a directory: {upload_dir}"
            raise NotADirectoryError(msg)
        if remote_timeout_seconds < 0:
            msg = "remote_timeout_seconds must be >= 0"
            raise ValueError(msg)
        if remote_poll_interval_seconds <= 0:
            msg = "remote_poll_interval_seconds must be > 0"
            raise ValueError(msg)

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
            expected_data_tree = self._expected_staged_tree_snapshot(preflight, staged_dir)
            preflight["staged"] = staged
            publish_key = hashlib.sha256(
                f"{self._dataset}:{preflight['fingerprint']}".encode()
            ).hexdigest()[:20]
            publication_marker = self._publication_marker_payload(
                preflight=preflight,
                publish_key=publish_key,
                data_tree_fingerprint=expected_data_tree["fingerprint"],
            )
            self._write_publication_marker(staged_dir, publication_marker)
            staged = self._snapshot_tree(staged_dir)
            expected_staged = self._expected_staged_tree_snapshot(
                preflight,
                staged_dir,
                publication_marker=publication_marker,
            )
            preflight["staged"] = staged
            preflight["expected_staged"] = expected_staged
            publication: dict[str, Any] = {
                "publish_key": publish_key,
                "expected_fingerprint": expected_staged["fingerprint"],
                "expected_bundle_fingerprint": preflight["fingerprint"],
                "verification_mode": "publication_marker",
                "upload_attempts": 0,
                "verification_attempts": 0,
                "observations": [],
                "result": "pending",
            }
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

            try:
                prior_unresolved = self._prior_unresolved_publication(publish_key=publish_key)
            except Exception as exc:
                publication["local_state"] = {
                    "state": "reconciliation_failed",
                    "error": self._redacted_error(exc),
                }
                publication["result"] = "local_state_reconciliation_failed"
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="local_state_reconciliation_failed",
                    preflight=preflight,
                    post_upload=staged,
                    publication=publication,
                    error=self._redacted_error(exc),
                )
                raise

            if prior_unresolved is not None and not verify_remote:
                publication["prior_unresolved_publication"] = prior_unresolved
                publication["result"] = "publication_reconciliation_required"
                msg = (
                    "Kaggle has a prior unresolved upload attempt; remote verification is "
                    "required before another upload"
                )
                pending = KagglePublicationPendingError(msg, publication)
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="publication_reconciliation_required",
                    preflight=preflight,
                    post_upload=staged,
                    publication=publication,
                    error=self._redacted_error(pending),
                )
                raise pending

            bootstrap_baseline_version: int | None = None
            if verify_remote:
                try:
                    with tempfile.TemporaryDirectory(
                        prefix="nbadb-kaggle-baseline-"
                    ) as baseline_dir:
                        baseline_marker, baseline_version = (
                            self._download_remote_publication_marker(Path(baseline_dir))
                        )
                except Exception as exc:
                    if not self._is_publication_marker_not_found(exc):
                        publication["baseline"] = {
                            "state": "reconciliation_failed",
                            "error": self._redacted_error(exc),
                        }
                        publication["result"] = "baseline_reconciliation_failed"
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="baseline_reconciliation_failed",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(exc),
                        )
                        raise

                    try:
                        baseline_version = self._resolve_remote_dataset_version()
                    except Exception as bootstrap_exc:
                        publication["baseline"] = {
                            "state": "bootstrap_version_resolution_failed",
                            "marker_status_code": int(HTTPStatus.NOT_FOUND),
                            "error": self._redacted_error(bootstrap_exc),
                        }
                        publication["result"] = "baseline_reconciliation_failed"
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="baseline_reconciliation_failed",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(bootstrap_exc),
                        )
                        raise

                    publication["baseline"] = {
                        "state": "bootstrap_marker_missing",
                        "marker_status_code": int(HTTPStatus.NOT_FOUND),
                        "version": baseline_version,
                        "matches_expected": False,
                        "upload_allowed": prior_unresolved is None,
                    }
                    if prior_unresolved is not None:
                        publication["prior_unresolved_publication"] = prior_unresolved
                        publication["result"] = "bootstrap_reconciliation_required"
                        msg = (
                            "Kaggle has a prior unresolved upload attempt and the remote "
                            "publication marker is absent; refusing another upload"
                        )
                        pending = KagglePublicationPendingError(msg, publication)
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="bootstrap_reconciliation_required",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(pending),
                        )
                        raise pending from exc
                    bootstrap_baseline_version = baseline_version
                else:
                    baseline_matches = self._publication_marker_matches(
                        baseline_marker,
                        expected=publication_marker,
                    )
                    prior_matches = prior_unresolved is not None and (
                        self._publication_marker_matches_record(
                            baseline_marker,
                            record=prior_unresolved,
                        )
                    )
                    publication["baseline"] = {
                        "state": "marker_present",
                        "publish_key": baseline_marker.get("publish_key"),
                        "bundle_fingerprint": baseline_marker.get("bundle_fingerprint"),
                        "version": baseline_version,
                        "matches_expected": baseline_matches,
                        "upload_allowed": prior_unresolved is None,
                    }
                    if prior_unresolved is not None and not prior_matches:
                        publication["prior_unresolved_publication"] = prior_unresolved
                        publication["result"] = "publication_reconciliation_required"
                        msg = (
                            "Kaggle has a prior unresolved upload attempt and the remote "
                            "publication marker does not resolve that exact record; refusing "
                            "another upload"
                        )
                        pending = KagglePublicationPendingError(msg, publication)
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="publication_reconciliation_required",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(pending),
                        )
                        raise pending
                    if (
                        prior_unresolved is not None
                        and prior_unresolved.get("publish_key") != publish_key
                    ):
                        publication["prior_unresolved_publication"] = prior_unresolved
                        publication["prior_unresolved_reconciliation"] = {
                            "state": "resolved",
                            "status": "reconciled_prior_remote",
                            "resolved_version": baseline_version,
                        }
                        self._transition_publication_state(
                            prior_unresolved,
                            state_name="resolved",
                            status="reconciled_prior_remote",
                            resolved_version=baseline_version,
                        )
                        prior_unresolved = None
                    publication["baseline"]["upload_allowed"] = (
                        prior_unresolved is None or baseline_matches
                    )
                    if baseline_matches:
                        publication.update(
                            {
                                "result": "reconciled_existing_remote",
                                "resolved_version": baseline_version,
                                "verification_attempts": 1,
                            }
                        )
                        self._transition_publication_state(
                            publication,
                            state_name="resolved",
                            status="reconciled_existing_remote",
                            resolved_version=baseline_version,
                        )
                        manifest_path = self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="reconciled_existing_remote",
                            preflight=preflight,
                            post_upload=staged,
                            remote_readback={
                                **baseline_marker,
                                "verification_mode": "publication_marker",
                                "verification_attempts": 1,
                                "verification_elapsed_seconds": 0.0,
                                "resolved_version": baseline_version,
                            },
                            publication=publication,
                        )
                        logger.info("Kaggle already exposes the staged bundle; upload skipped")
                        return manifest_path
                    if prior_unresolved is not None:
                        publication["prior_unresolved_publication"] = prior_unresolved
                        publication["result"] = "publication_reconciliation_required"
                        msg = (
                            "Kaggle has a prior unresolved upload attempt and the remote "
                            "publication marker is present but nonmatching; refusing another upload"
                        )
                        pending = KagglePublicationPendingError(msg, publication)
                        self._write_upload_manifest(
                            data_dir=upload_dir,
                            staged_dir=staged_dir,
                            version_notes=version_notes,
                            status="publication_reconciliation_required",
                            preflight=preflight,
                            post_upload=staged,
                            publication=publication,
                            error=self._redacted_error(pending),
                        )
                        raise pending

            manifest_path = self._write_upload_manifest(
                data_dir=upload_dir,
                staged_dir=staged_dir,
                version_notes=version_notes,
                status="preflight_passed",
                preflight=preflight,
                publication=publication,
            )
            if bootstrap_baseline_version is not None:
                try:
                    bootstrap_recheck = self._reconcile_bootstrap_before_upload(
                        expected_marker=publication_marker,
                        baseline_version=bootstrap_baseline_version,
                    )
                except Exception as exc:
                    publication["bootstrap_pre_upload"] = {
                        "state": "reconciliation_failed",
                        "baseline_version": bootstrap_baseline_version,
                        "error": self._redacted_error(exc),
                    }
                    publication["result"] = "bootstrap_pre_upload_reconciliation_failed"
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="bootstrap_pre_upload_reconciliation_failed",
                        preflight=preflight,
                        post_upload=staged,
                        publication=publication,
                        error=self._redacted_error(exc),
                    )
                    raise
                publication["bootstrap_pre_upload"] = bootstrap_recheck
                if (
                    bootstrap_recheck["state"] == "marker_present"
                    and bootstrap_recheck["upload_allowed"]
                ):
                    resolved_version = self._require_exact_dataset_version(
                        bootstrap_recheck["marker_version"],
                        source="bootstrap pre-upload marker",
                    )
                    remote_marker = cast("dict[str, Any]", bootstrap_recheck["marker"])
                    publication.update(
                        {
                            "result": "reconciled_existing_remote",
                            "resolved_version": resolved_version,
                            "verification_attempts": 1,
                        }
                    )
                    self._transition_publication_state(
                        publication,
                        state_name="resolved",
                        status="reconciled_existing_remote",
                        resolved_version=resolved_version,
                    )
                    manifest_path = self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="reconciled_existing_remote",
                        preflight=preflight,
                        post_upload=staged,
                        remote_readback={
                            **remote_marker,
                            "verification_mode": "publication_marker",
                            "verification_attempts": 1,
                            "verification_elapsed_seconds": 0.0,
                            "resolved_version": resolved_version,
                        },
                        publication=publication,
                    )
                    logger.info("Kaggle bootstrap recheck found the staged bundle; upload skipped")
                    return manifest_path
                if not bootstrap_recheck["upload_allowed"]:
                    publication["result"] = "bootstrap_pre_upload_reconciliation_required"
                    msg = (
                        "Kaggle remote publication evidence changed or became ambiguous after "
                        "the marker-specific 404; refusing upload"
                    )
                    pending = KagglePublicationPendingError(msg, publication)
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="bootstrap_pre_upload_reconciliation_required",
                        preflight=preflight,
                        post_upload=staged,
                        publication=publication,
                        error=self._redacted_error(pending),
                    )
                    raise pending

            upload_error: Exception | None = None
            try:
                publication["upload_attempts"] = 1
                self._transition_publication_state(
                    publication,
                    state_name="unresolved",
                    status="upload_attempt_started",
                )
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="upload_attempt_started",
                    preflight=preflight,
                    post_upload=staged,
                    publication=publication,
                )
                kagglehub.dataset_upload(
                    handle=self._dataset,
                    local_dataset_dir=str(staged_dir),
                    version_notes=version_notes,
                )
            except Exception as exc:
                upload_error = exc
                publication["upload_error"] = self._redacted_error(exc)
                publication["result"] = "upload_ambiguous"
                self._transition_publication_state(
                    publication,
                    state_name="unresolved",
                    status="upload_ambiguous",
                    error=self._redacted_error(exc),
                )
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="upload_ambiguous_reconciling" if verify_remote else "upload_ambiguous",
                    preflight=preflight,
                    publication=publication,
                    error=self._redacted_error(exc),
                )
                if not verify_remote:
                    raise

            post_upload = self._snapshot_tree(staged_dir)
            if post_upload["fingerprint"] != staged["fingerprint"]:
                self._transition_publication_state(
                    publication,
                    state_name="unresolved",
                    status="post_upload_mismatch_remote_may_exist",
                )
                self._write_upload_manifest(
                    data_dir=upload_dir,
                    staged_dir=staged_dir,
                    version_notes=version_notes,
                    status="post_upload_mismatch_remote_may_exist",
                    preflight=preflight,
                    post_upload=post_upload,
                    publication=publication,
                )
                msg = (
                    "Kaggle upload bundle changed during upload; the remote Kaggle "
                    "version may already have been created"
                )
                raise RuntimeError(msg)

            remote_readback = None
            if verify_remote:
                try:
                    remote_readback = self._verify_remote_upload(
                        publication_marker,
                        timeout_seconds=remote_timeout_seconds,
                        poll_interval_seconds=remote_poll_interval_seconds,
                        publication=publication,
                    )
                except KagglePublicationPendingError as exc:
                    publication = exc.publication
                    publication["result"] = "publication_reconciliation_required"
                    self._transition_publication_state(
                        publication,
                        state_name="unresolved",
                        status="publication_reconciliation_required",
                        error=self._redacted_error(exc),
                    )
                    self._write_upload_manifest(
                        data_dir=upload_dir,
                        staged_dir=staged_dir,
                        version_notes=version_notes,
                        status="publication_reconciliation_required",
                        preflight=preflight,
                        post_upload=post_upload,
                        publication=publication,
                        error=self._redacted_error(exc),
                    )
                    raise
                publication["result"] = (
                    "reconciled_after_upload_error" if upload_error is not None else "verified"
                )
                self._transition_publication_state(
                    publication,
                    state_name="resolved",
                    status="uploaded_remote_verified",
                    resolved_version=publication.get("resolved_version"),
                )
            else:
                publication["result"] = "uploaded_unverified"
                self._transition_publication_state(
                    publication,
                    state_name="unresolved",
                    status="uploaded_unverified",
                )

            manifest_path = self._write_upload_manifest(
                data_dir=upload_dir,
                staged_dir=staged_dir,
                version_notes=version_notes,
                status="uploaded_remote_verified" if verify_remote else "uploaded",
                preflight=preflight,
                post_upload=post_upload,
                remote_readback=remote_readback,
                publication=publication,
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

    @contextmanager
    def _local_upload_claim(self) -> Iterator[None]:
        """Claim this host/log root; separate hosts still require remote reconciliation."""
        if not _PROCESS_UPLOAD_LOCK.acquire(blocking=False):
            msg = "Another Kaggle upload is already active in this process"
            raise RuntimeError(msg)

        lock_handle = None
        lock_backend = None
        file_claimed = False
        try:
            lock_dir = self._settings.log_dir / "kaggle"
            lock_dir.mkdir(parents=True, exist_ok=True)
            dataset_key = hashlib.sha256(self._dataset.encode("utf-8")).hexdigest()[:16]
            lock_path = lock_dir / f"kaggle-upload-{dataset_key}.lock"
            lock_path.touch(exist_ok=True)
            lock_handle = lock_path.open("r+b")
            lock_backend = _advisory_file_lock_backend()
            try:
                lock_backend.acquire(lock_handle)
            except BlockingIOError as exc:
                msg = (
                    "Another Kaggle upload is already active on this host for the shared "
                    "log directory"
                )
                raise RuntimeError(msg) from exc
            file_claimed = True
            lock_handle.seek(0)
            lock_handle.write(
                (
                    json.dumps(
                        {
                            "dataset": self._dataset,
                            "process_id": os.getpid(),
                            "claimed_at": datetime.now(UTC).isoformat(),
                            "serialization": UPLOAD_SERIALIZATION_CONTRACT,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
            )
            lock_handle.truncate()
            lock_handle.flush()
            os.fsync(lock_handle.fileno())
            yield
        finally:
            try:
                if lock_handle is not None:
                    try:
                        if file_claimed and lock_backend is not None:
                            lock_backend.release(lock_handle)
                    finally:
                        lock_handle.close()
            finally:
                _PROCESS_UPLOAD_LOCK.release()

    def _publication_state_path(self) -> Path:
        return self._settings.log_dir / "kaggle" / PUBLICATION_STATE_NAME

    @staticmethod
    def _is_lowercase_hex(value: Any, *, length: int) -> bool:
        return (
            isinstance(value, str)
            and len(value) == length
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _require_nonempty_record_string(
        record: dict[str, Any],
        field: str,
        *,
        context: str,
    ) -> None:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            msg = f"Kaggle publication record {context} must have a nonempty {field}"
            raise RuntimeError(msg)

    @classmethod
    def _validate_publication_record(
        cls,
        *,
        dataset_key: str,
        stored_key: str,
        record: dict[str, Any],
    ) -> None:
        if record.get("dataset") != dataset_key or record.get("publish_key") != stored_key:
            msg = "Kaggle publication record identity is inconsistent"
            raise RuntimeError(msg)
        if not cls._is_lowercase_hex(stored_key, length=20):
            msg = "Kaggle publication record publish_key must be 20 lowercase hex characters"
            raise RuntimeError(msg)
        if not cls._is_lowercase_hex(record.get("bundle_fingerprint"), length=64):
            msg = "Kaggle publication record bundle_fingerprint must be lowercase hex"
            raise RuntimeError(msg)

        state_name = record.get("state")
        if state_name not in _PUBLICATION_RECORD_STATES:
            msg = "Kaggle publication record has an unsupported state"
            raise RuntimeError(msg)
        context = f"{dataset_key}/{stored_key}"
        cls._require_nonempty_record_string(record, "last_status", context=context)
        cls._require_nonempty_record_string(record, "last_transition_at", context=context)
        if record.get("serialization") != UPLOAD_SERIALIZATION_CONTRACT:
            msg = "Kaggle publication record serialization contract is invalid"
            raise RuntimeError(msg)

        state_timestamp_fields = {
            "failed": "failed_at",
            "resolved": "resolved_at",
            "unresolved": "first_unresolved_at",
        }
        cls._require_nonempty_record_string(
            record,
            state_timestamp_fields[cast("str", state_name)],
            context=context,
        )
        for timestamp_field in state_timestamp_fields.values():
            if timestamp_field in record:
                cls._require_nonempty_record_string(
                    record,
                    timestamp_field,
                    context=context,
                )
        if state_name == "resolved":
            resolved_version = record.get("resolved_version")
            if (
                not isinstance(resolved_version, int)
                or isinstance(resolved_version, bool)
                or resolved_version <= 0
            ):
                msg = "Kaggle resolved publication record requires a positive resolved_version"
                raise RuntimeError(msg)

    @classmethod
    def _validate_publication_state(cls, state: dict[str, Any]) -> None:
        datasets = state.get("datasets")
        if not isinstance(datasets, dict):
            msg = "Kaggle publication state datasets must be an object"
            raise RuntimeError(msg)
        for dataset_key, dataset_state in datasets.items():
            if not isinstance(dataset_key, str) or not dataset_key.strip():
                msg = "Kaggle publication state dataset key must be nonempty"
                raise RuntimeError(msg)
            if not isinstance(dataset_state, dict):
                msg = "Kaggle publication dataset state must be an object"
                raise RuntimeError(msg)
            publications = dataset_state.get("publications")
            if not isinstance(publications, dict):
                msg = "Kaggle publication records must be an object"
                raise RuntimeError(msg)
            for stored_key, raw_record in publications.items():
                if not isinstance(stored_key, str) or not isinstance(raw_record, dict):
                    msg = "Kaggle publication record must be an object with a string key"
                    raise RuntimeError(msg)
                cls._validate_publication_record(
                    dataset_key=dataset_key,
                    stored_key=stored_key,
                    record=cast("dict[str, Any]", raw_record),
                )

    def _read_publication_state(self) -> dict[str, Any]:
        state_path = self._publication_state_path()
        if not state_path.is_file():
            return {"schema_version": 1, "datasets": {}}
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = "Kaggle publication state cannot be read safely"
            raise RuntimeError(msg) from exc
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            msg = "Kaggle publication state has an unsupported schema"
            raise RuntimeError(msg)
        validated_state = cast("dict[str, Any]", state)
        self._validate_publication_state(validated_state)
        return validated_state

    def _prior_unresolved_publication(self, *, publish_key: str) -> dict[str, Any] | None:
        state = self._read_publication_state()
        dataset_state = state["datasets"].get(self._dataset)
        if dataset_state is None:
            return None
        if not isinstance(dataset_state, dict):
            msg = "Kaggle publication dataset state must be an object"
            raise RuntimeError(msg)
        publications = dataset_state.get("publications")
        if not isinstance(publications, dict):
            msg = "Kaggle publication records must be an object"
            raise RuntimeError(msg)
        unresolved: list[dict[str, Any]] = []
        for raw_record in publications.values():
            record = cast("dict[str, Any]", raw_record)
            if record.get("state") == "unresolved":
                unresolved.append(record)
        if len(unresolved) > 1:
            keys = sorted(str(record.get("publish_key") or "") for record in unresolved)
            msg = "Kaggle publication state has multiple unresolved dataset uploads: " + ", ".join(
                keys
            )
            raise RuntimeError(msg)
        if not unresolved:
            return None
        record = unresolved[0]
        if record.get("publish_key") != publish_key:
            logger.warning(
                "Kaggle dataset has an unresolved publication for a different bundle: {}",
                record.get("publish_key"),
            )
        return record

    def _transition_publication_state(
        self,
        publication: dict[str, Any],
        *,
        state_name: str,
        status: str,
        resolved_version: int | None = None,
        error: str | None = None,
    ) -> None:
        if state_name not in _PUBLICATION_RECORD_STATES:
            msg = f"Unsupported Kaggle publication state transition: {state_name}"
            raise RuntimeError(msg)
        publish_key = publication.get("publish_key")
        bundle_fingerprint = publication.get("expected_bundle_fingerprint") or publication.get(
            "bundle_fingerprint"
        )
        if not isinstance(publish_key, str) or not isinstance(bundle_fingerprint, str):
            msg = "Kaggle publication transition requires exact local identity"
            raise RuntimeError(msg)

        state = self._read_publication_state()
        datasets = state["datasets"]
        dataset_state = datasets.setdefault(self._dataset, {"publications": {}})
        if not isinstance(dataset_state, dict):
            msg = "Kaggle publication dataset state must be an object"
            raise RuntimeError(msg)
        publications = dataset_state.setdefault("publications", {})
        if not isinstance(publications, dict):
            msg = "Kaggle publication records must be an object"
            raise RuntimeError(msg)
        existing = publications.get(publish_key)
        if existing is not None and not isinstance(existing, dict):
            msg = "Kaggle publication record must be an object"
            raise RuntimeError(msg)

        transitioned_at = datetime.now(UTC).isoformat()
        record: dict[str, Any] = {
            **(existing or {}),
            "dataset": self._dataset,
            "publish_key": publish_key,
            "bundle_fingerprint": bundle_fingerprint,
            "state": state_name,
            "last_status": status,
            "last_transition_at": transitioned_at,
            "serialization": UPLOAD_SERIALIZATION_CONTRACT,
        }
        if state_name == "unresolved":
            record.setdefault("first_unresolved_at", transitioned_at)
            record["baseline"] = publication.get("baseline")
            record["result"] = publication.get("result")
        elif state_name == "resolved":
            record["resolved_at"] = transitioned_at
            record["resolved_version"] = self._require_exact_dataset_version(
                resolved_version,
                source="publication state resolution",
            )
        else:
            record["failed_at"] = transitioned_at
        if error is not None:
            record["error"] = self._redact_sensitive_text(error)
        publications[publish_key] = record
        state["updated_at"] = transitioned_at
        self._validate_publication_state(state)
        self._atomic_write_json(self._publication_state_path(), state)

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
        identity_resources = [
            {
                "path": resource["path"],
                "kind": resource["kind"],
                "bytes": resource["bytes"],
                "sha256": resource["sha256"],
                **(
                    {
                        "file_count": resource["file_count"],
                        "files": resource["files"],
                    }
                    if resource["kind"] == "directory"
                    else {}
                ),
            }
            for resource in resource_inventory
        ]
        fingerprint_payload = {
            "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
            "resources": sorted(identity_resources, key=lambda resource: resource["path"]),
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
            "resources": sorted(resource_inventory, key=lambda resource: resource["path"]),
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
        publication: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Path:
        manifest_dir = self._settings.log_dir / "kaggle"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "kaggle-upload-manifest.json"
        manifest: dict[str, Any] = {
            "schema_version": 2,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": status,
            "dataset": self._dataset,
            "data_dir": str(data_dir),
            "staged_dir": str(staged_dir) if staged_dir is not None else None,
            "version_notes": version_notes,
            "preflight": preflight,
            "serialization": UPLOAD_SERIALIZATION_CONTRACT,
        }
        if post_upload is not None:
            manifest["post_upload"] = post_upload
        if remote_readback is not None:
            manifest["remote_readback"] = remote_readback
        if publication is not None:
            manifest["publication"] = publication
        if error is not None:
            manifest["error"] = error
        sanitized = self._redact_persisted_error_fields(manifest)
        self._atomic_write_json(manifest_path, cast("dict[str, Any]", sanitized))
        return manifest_path

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise

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
        *,
        publication_marker: dict[str, Any] | None = None,
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
        if publication_marker is not None:
            marker_bytes = KaggleClient._publication_marker_bytes(publication_marker)
            files.append(
                {
                    "path": PUBLICATION_MARKER_NAME,
                    "bytes": len(marker_bytes),
                    "sha256": hashlib.sha256(marker_bytes).hexdigest(),
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

    def _publication_marker_payload(
        self,
        *,
        preflight: dict[str, Any],
        publish_key: str,
        data_tree_fingerprint: str,
    ) -> dict[str, Any]:
        resources = [
            {
                "path": resource["path"],
                "kind": resource["kind"],
                "bytes": resource["bytes"],
                "sha256": resource["sha256"],
                **(
                    {"file_count": resource["file_count"]}
                    if resource["kind"] == "directory"
                    else {}
                ),
            }
            for resource in preflight["resources"]
        ]
        return {
            "schema_version": 1,
            "dataset": self._dataset,
            "publish_key": publish_key,
            "bundle_fingerprint": preflight["fingerprint"],
            "data_tree_fingerprint": data_tree_fingerprint,
            "metadata_sha256": preflight["metadata_sha256"],
            "resource_count": preflight["resource_count"],
            "resource_bytes": preflight["resource_bytes"],
            "resources": resources,
        }

    @staticmethod
    def _publication_marker_bytes(marker: dict[str, Any]) -> bytes:
        return (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8")

    @classmethod
    def _write_publication_marker(cls, staged_dir: Path, marker: dict[str, Any]) -> Path:
        marker_path = staged_dir / PUBLICATION_MARKER_NAME
        marker_path.write_bytes(cls._publication_marker_bytes(marker))
        return marker_path

    @staticmethod
    def _publication_marker_matches(
        observed: dict[str, Any],
        *,
        expected: dict[str, Any],
    ) -> bool:
        identity_fields = (
            "schema_version",
            "dataset",
            "publish_key",
            "bundle_fingerprint",
            "data_tree_fingerprint",
            "metadata_sha256",
            "resource_count",
            "resource_bytes",
            "resources",
        )
        return all(observed.get(field) == expected.get(field) for field in identity_fields)

    @staticmethod
    def _publication_marker_matches_record(
        marker: dict[str, Any],
        *,
        record: dict[str, Any],
    ) -> bool:
        return all(
            marker.get(field) == record.get(field)
            for field in ("dataset", "publish_key", "bundle_fingerprint")
        )

    def _validate_publication_marker(self, marker: dict[str, Any]) -> None:
        if marker.get("schema_version") != 1:
            msg = "Kaggle remote publication marker has an unsupported schema"
            raise ValueError(msg)
        if marker.get("dataset") != self._dataset:
            msg = "Kaggle remote publication marker dataset does not match configuration"
            raise ValueError(msg)
        digest_fields = {
            "bundle_fingerprint": 64,
            "data_tree_fingerprint": 64,
            "metadata_sha256": 64,
            "publish_key": 20,
        }
        for field, length in digest_fields.items():
            value = marker.get(field)
            if (
                not isinstance(value, str)
                or len(value) != length
                or any(character not in "0123456789abcdef" for character in value)
            ):
                msg = f"Kaggle remote publication marker has invalid {field}"
                raise ValueError(msg)
        resources = marker.get("resources")
        if not isinstance(resources, list):
            msg = "Kaggle remote publication marker resources must be a list"
            raise ValueError(msg)
        resource_count = marker.get("resource_count")
        resource_bytes = marker.get("resource_bytes")
        if (
            not isinstance(resource_count, int)
            or isinstance(resource_count, bool)
            or resource_count <= 0
            or resource_count != len(resources)
        ):
            msg = "Kaggle remote publication marker resource count is inconsistent"
            raise ValueError(msg)
        if (
            not isinstance(resource_bytes, int)
            or isinstance(resource_bytes, bool)
            or resource_bytes < 0
        ):
            msg = "Kaggle remote publication marker resource bytes are invalid"
            raise ValueError(msg)
        observed_bytes = 0
        seen_paths: set[str] = set()
        for resource in resources:
            if not isinstance(resource, dict):
                msg = "Kaggle remote publication marker resource must be an object"
                raise ValueError(msg)
            path = resource.get("path")
            kind = resource.get("kind")
            byte_count = resource.get("bytes")
            digest = resource.get("sha256")
            if not isinstance(path, str) or self._normalize_resource_path(path) != path:
                msg = "Kaggle remote publication marker resource path is invalid"
                raise ValueError(msg)
            if path in seen_paths:
                msg = "Kaggle remote publication marker has duplicate resource paths"
                raise ValueError(msg)
            seen_paths.add(path)
            if kind not in {"file", "directory"}:
                msg = "Kaggle remote publication marker resource kind is invalid"
                raise ValueError(msg)
            if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
                msg = "Kaggle remote publication marker resource bytes are invalid"
                raise ValueError(msg)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                msg = "Kaggle remote publication marker resource digest is invalid"
                raise ValueError(msg)
            if kind == "directory":
                file_count = resource.get("file_count")
                if (
                    not isinstance(file_count, int)
                    or isinstance(file_count, bool)
                    or file_count <= 0
                ):
                    msg = "Kaggle remote publication marker directory file count is invalid"
                    raise ValueError(msg)
            observed_bytes += byte_count
        if observed_bytes != resource_bytes:
            msg = "Kaggle remote publication marker resource bytes are inconsistent"
            raise ValueError(msg)

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

    @staticmethod
    def _monotonic() -> float:
        return time.monotonic()

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(seconds)

    @staticmethod
    def _is_publication_marker_not_found(exc: Exception) -> bool:
        from kagglehub.exceptions import KaggleApiHTTPError

        response = getattr(exc, "response", None)
        if (
            not isinstance(exc, KaggleApiHTTPError)
            or response is None
            or response.status_code != HTTPStatus.NOT_FOUND
        ):
            return False
        request = getattr(response, "request", None)
        request_locations = (
            getattr(response, "url", ""),
            getattr(request, "url", ""),
            getattr(request, "body", ""),
        )
        return any(PUBLICATION_MARKER_NAME in str(location) for location in request_locations)

    @staticmethod
    def _require_exact_dataset_version(version: Any, *, source: str) -> int:
        if not isinstance(version, int) or isinstance(version, bool) or version <= 0:
            msg = f"Kaggle {source} did not resolve an exact dataset version"
            raise RuntimeError(msg)
        return version

    def _resolve_remote_dataset_version(self) -> int:
        from kagglehub.clients import build_kaggle_client
        from kagglehub.exceptions import handle_call
        from kagglehub.handle import parse_dataset_handle
        from kagglesdk.datasets.types.dataset_api_service import ApiGetDatasetRequest

        handle = parse_dataset_handle(self._dataset)
        request = ApiGetDatasetRequest()
        request.owner_slug = handle.owner
        request.dataset_slug = handle.dataset
        with build_kaggle_client() as api_client:
            dataset = handle_call(
                lambda: api_client.datasets.dataset_api_client.get_dataset(request),
                handle,
            )
        return self._require_exact_dataset_version(
            dataset.current_version_number,
            source="dataset metadata API",
        )

    def _reconcile_bootstrap_before_upload(
        self,
        *,
        expected_marker: dict[str, Any],
        baseline_version: int,
    ) -> dict[str, Any]:
        """Recheck the marker and exact metadata version just before an upload call."""
        try:
            with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-bootstrap-recheck-") as temp_dir:
                marker, marker_version = self._download_remote_publication_marker(Path(temp_dir))
        except Exception as exc:
            if not self._is_publication_marker_not_found(exc):
                raise
            metadata_version = self._resolve_remote_dataset_version()
            return {
                "state": "marker_missing",
                "marker_status_code": int(HTTPStatus.NOT_FOUND),
                "baseline_version": baseline_version,
                "metadata_version": metadata_version,
                "version_unchanged": metadata_version == baseline_version,
                "upload_allowed": metadata_version == baseline_version,
            }

        metadata_version = self._resolve_remote_dataset_version()
        marker_matches = self._publication_marker_matches(marker, expected=expected_marker)
        return {
            "state": "marker_present",
            "marker": marker,
            "publish_key": marker.get("publish_key"),
            "bundle_fingerprint": marker.get("bundle_fingerprint"),
            "baseline_version": baseline_version,
            "marker_version": marker_version,
            "metadata_version": metadata_version,
            "versions_agree": marker_version == metadata_version,
            "matches_expected": marker_matches,
            "upload_allowed": marker_version == metadata_version and marker_matches,
        }

    def _download_remote_publication_marker(
        self,
        download_root: Path,
    ) -> tuple[dict[str, Any], int]:
        from kagglehub import registry
        from kagglehub.handle import parse_dataset_handle

        downloaded, version = registry.dataset_resolver(
            parse_dataset_handle(self._dataset),
            PUBLICATION_MARKER_NAME,
            output_dir=str(download_root),
            force_download=True,
        )
        version = self._require_exact_dataset_version(
            version,
            source="remote publication marker",
        )
        remote_path = Path(downloaded)
        marker_path = (
            remote_path if remote_path.is_file() else remote_path / PUBLICATION_MARKER_NAME
        )
        if not marker_path.is_file():
            candidates = list(remote_path.rglob(PUBLICATION_MARKER_NAME))
            if len(candidates) != 1:
                msg = "Kaggle remote publication marker is missing or ambiguous"
                raise FileNotFoundError(msg)
            marker_path = candidates[0]
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            msg = "Kaggle remote publication marker is not valid JSON"
            raise ValueError(msg) from exc
        if not isinstance(marker, dict):
            msg = "Kaggle remote publication marker must be a JSON object"
            raise ValueError(msg)
        self._validate_publication_marker(marker)
        return marker, version

    def _verify_remote_upload(
        self,
        expected_marker: dict[str, Any],
        *,
        timeout_seconds: float = 900.0,
        poll_interval_seconds: float = 15.0,
        publication: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if publication is None:
            publication = {}
        observations = list(publication.get("observations") or [])
        started = self._monotonic()
        attempt = 0
        while True:
            attempt += 1
            observation: dict[str, Any] = {"attempt": attempt}
            try:
                with tempfile.TemporaryDirectory(prefix="nbadb-kaggle-readback-") as temp_dir:
                    remote_marker, version = self._download_remote_publication_marker(
                        Path(temp_dir)
                    )
            except Exception as exc:
                observation["error"] = self._redacted_error(exc)
            else:
                marker_matches = self._publication_marker_matches(
                    remote_marker,
                    expected=expected_marker,
                )
                observation.update(
                    {
                        "publish_key": remote_marker.get("publish_key"),
                        "bundle_fingerprint": remote_marker.get("bundle_fingerprint"),
                        "matches_expected": marker_matches,
                        "version": version,
                    }
                )
                if observation["matches_expected"]:
                    elapsed = max(0.0, self._monotonic() - started)
                    observations.append(observation)
                    publication.update(
                        {
                            "verification_attempts": attempt,
                            "verification_elapsed_seconds": round(elapsed, 3),
                            "resolved_version": version,
                            "observations": observations,
                        }
                    )
                    return {
                        **remote_marker,
                        "verification_mode": "publication_marker",
                        "verification_attempts": attempt,
                        "verification_elapsed_seconds": round(elapsed, 3),
                        "resolved_version": version,
                    }
            observations.append(observation)
            elapsed = max(0.0, self._monotonic() - started)
            publication.update(
                {
                    "verification_attempts": attempt,
                    "verification_elapsed_seconds": round(elapsed, 3),
                    "observations": observations,
                }
            )
            if elapsed >= timeout_seconds:
                msg = "Kaggle publication did not expose the expected bundle before the deadline"
                raise KagglePublicationPendingError(msg, publication)
            self._sleep(min(poll_interval_seconds, timeout_seconds - elapsed))

    @staticmethod
    def _redact_sensitive_text(message: str) -> str:
        home = str(Path.home())
        if home and home in message:
            message = message.replace(home, "~")
        message = _AUTHORIZATION_BEARER_RE.sub(r"\1<redacted>", message)
        message = _SECRET_ASSIGNMENT_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(4)}",
            message,
        )
        return _SECRET_FLAG_RE.sub(
            lambda match: f"{match.group(1)}{match.group(2)}<redacted>{match.group(4)}",
            message,
        )

    @classmethod
    def _redact_persisted_error_fields(cls, value: Any, *, field_name: str = "") -> Any:
        if isinstance(value, dict):
            return {
                key: cls._redact_persisted_error_fields(item, field_name=str(key))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact_persisted_error_fields(item) for item in value]
        if isinstance(value, str) and "error" in field_name.lower():
            return cls._redact_sensitive_text(value)
        return value

    @classmethod
    def _redacted_error(cls, exc: Exception) -> str:
        return f"{type(exc).__name__}: {cls._redact_sensitive_text(str(exc))}"
