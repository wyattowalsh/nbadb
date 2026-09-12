from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import quote, urlencode

_API_VERSION = "2026-03-10"
_EXECUTED_CONCLUSIONS = {"cancelled", "failure", "success", "timed_out"}
_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_ARTIFACT_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")


class ProvenanceError(RuntimeError):
    """Raised when a workflow-run provenance claim cannot be proven exactly."""


def _positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProvenanceError(f"{field} must be a positive integer")
    return value


def _poll_interval(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, float | int)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ProvenanceError("artifact inventory poll interval is invalid")
    return float(value)


def _gh_json(path: str, *, fields: dict[str, str] | None = None) -> object:
    command = [
        "gh",
        "api",
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        f"X-GitHub-Api-Version: {_API_VERSION}",
        path,
    ]
    for key, value in sorted((fields or {}).items()):
        command.extend(["-f", f"{key}={value}"])
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ProvenanceError("GitHub API request failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProvenanceError("GitHub API response is not valid JSON") from exc


def _stream_gh_archive(path: str, destination: Path) -> None:
    with destination.open("xb") as output:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "GET",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                f"X-GitHub-Api-Version: {_API_VERSION}",
                path,
            ],
            check=False,
            stdout=output,
            stderr=subprocess.PIPE,
        )
    if result.returncode != 0:
        destination.unlink(missing_ok=True)
        raise ProvenanceError("GitHub artifact download failed")


def _validate_state(run: dict[str, Any], *, required_state: str) -> None:
    status = run.get("status")
    conclusion = run.get("conclusion")
    active = status in {"queued", "in_progress"} and conclusion is None
    completed = status == "completed" and conclusion in _EXECUTED_CONCLUSIONS
    if not active and not completed:
        raise ProvenanceError("workflow run status and conclusion are invalid")
    if required_state == "completed" and not completed:
        raise ProvenanceError("workflow run is not completed")
    if required_state == "successful" and not (status == "completed" and conclusion == "success"):
        raise ProvenanceError("workflow run did not complete successfully")


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise ProvenanceError(f"{label} is malformed")
    return cast("dict[str, Any]", payload)


def recheck_attested_run(
    attestation: dict[str, Any],
    *,
    required_state: str | None = None,
) -> dict[str, Any]:
    """Re-read an attested owner run and reject any identity or state drift."""
    repository = attestation.get("repository")
    run_claim = attestation.get("run")
    semantic_source = attestation.get("semantic_source")
    workflow_claim = attestation.get("workflow")
    if (
        type(attestation.get("schema_version")) is not int
        or attestation.get("schema_version") != 1
        or not isinstance(repository, str)
        or _REPOSITORY_RE.fullmatch(repository) is None
        or not isinstance(run_claim, dict)
        or not isinstance(semantic_source, dict)
        or not isinstance(workflow_claim, dict)
    ):
        raise ProvenanceError("workflow provenance attestation is malformed")
    run_id = _positive_integer(run_claim.get("id"), field="attested run ID")
    workflow_id = _positive_integer(run_claim.get("workflow_id"), field="attested workflow ID")
    attempt = _positive_integer(run_claim.get("attempt"), field="attested run attempt")
    head_sha = str(run_claim.get("head_sha") or "").lower()
    source_sha = str(semantic_source.get("sha") or "").lower()
    workflow_path = str(run_claim.get("path") or "")
    expected_url = (
        f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com').rstrip('/')}"
        f"/repos/{repository}/actions/runs/{run_id}"
    )
    if (
        attempt != 1
        or _SHA_RE.fullmatch(head_sha) is None
        or _SHA_RE.fullmatch(source_sha) is None
        or semantic_source.get("relation") not in {"identical", "ancestor"}
        or workflow_claim.get("path") != workflow_path
        or run_claim.get("url") != expected_url
        or run_claim.get("event") != "workflow_dispatch"
        or not str(run_claim.get("head_branch") or "")
        or _SHA_RE.fullmatch(str(workflow_claim.get("blob_sha") or "").lower()) is None
        or re.fullmatch(r"[0-9a-f]{64}", str(workflow_claim.get("sha256") or "").lower()) is None
        or isinstance(workflow_claim.get("size_in_bytes"), bool)
        or not isinstance(workflow_claim.get("size_in_bytes"), int)
        or workflow_claim["size_in_bytes"] < 1
        or (semantic_source.get("relation") == "identical") != (source_sha == head_sha)
    ):
        raise ProvenanceError("workflow provenance attestation identity is invalid")

    raw = _gh_json(f"/repos/{repository}/actions/runs/{run_id}")
    if not isinstance(raw, dict):
        raise ProvenanceError("workflow run response is malformed")
    run = cast("dict[str, Any]", raw)
    run_repository = run.get("repository")
    if (
        type(run.get("id")) is not int
        or run.get("id") != run_id
        or run.get("url") != expected_url
        or not isinstance(run_repository, dict)
        or run_repository.get("full_name") != repository
        or run.get("event") != run_claim.get("event")
        or run.get("head_branch") != run_claim.get("head_branch")
        or str(run.get("head_sha") or "").lower() != head_sha
        or run.get("path") != workflow_path
        or type(run.get("workflow_id")) is not int
        or run.get("workflow_id") != workflow_id
        or type(run.get("run_attempt")) is not int
        or run.get("run_attempt") != 1
        or run.get("status") != run_claim.get("status")
        or run.get("conclusion") != run_claim.get("conclusion")
    ):
        raise ProvenanceError("workflow run changed after provenance attestation")
    effective_required_state = required_state or "active-or-completed"
    if effective_required_state not in {
        "active-or-completed",
        "completed",
        "successful",
    }:
        raise ProvenanceError("required workflow state is invalid")
    _validate_state(run, required_state=effective_required_state)
    return run


def _normalize_artifact(
    raw: object,
    *,
    artifact_name: str,
    owner_head_sha: str,
    repository: str,
    run_id: int,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ProvenanceError("artifact identity is malformed")
    artifact_id = raw.get("id")
    digest = str(raw.get("digest") or "").lower()
    size = raw.get("size_in_bytes")
    workflow_run = raw.get("workflow_run")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    expected_archive_url = f"{api_url}/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    if (
        isinstance(artifact_id, bool)
        or not isinstance(artifact_id, int)
        or artifact_id < 1
        or raw.get("name") != artifact_name
        or _ARTIFACT_DIGEST_RE.fullmatch(digest) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or raw.get("expired") is not False
        or raw.get("archive_download_url") != expected_archive_url
        or not isinstance(workflow_run, dict)
        or type(workflow_run.get("id")) is not int
        or workflow_run.get("id") != run_id
        or str(workflow_run.get("head_sha") or "").lower() != owner_head_sha
    ):
        raise ProvenanceError("artifact identity is malformed")
    return {
        "archive_download_url": expected_archive_url,
        "digest": digest,
        "expired": False,
        "id": artifact_id,
        "name": artifact_name,
        "size_in_bytes": size,
        "workflow_run_id": run_id,
        "workflow_run_sha": owner_head_sha,
    }


def _artifact_inventory_identity(
    raw: object,
    *,
    repository: str,
    run_id: int,
) -> dict[str, object]:
    """Normalize every inventory row without requiring unrelated artifacts to be usable."""
    if not isinstance(raw, dict):
        raise ProvenanceError("artifact inventory is malformed")
    artifact_id = _positive_integer(raw.get("id"), field="artifact inventory ID")
    name = raw.get("name")
    size = raw.get("size_in_bytes")
    expired = raw.get("expired")
    digest = raw.get("digest")
    workflow_run = raw.get("workflow_run")
    workflow_head_sha = (
        str(workflow_run.get("head_sha") or "").lower() if isinstance(workflow_run, dict) else ""
    )
    expected_archive_url = (
        f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com').rstrip('/')}"
        f"/repos/{repository}/actions/artifacts/{artifact_id}/zip"
    )
    if (
        not isinstance(name, str)
        or not name
        or type(size) is not int
        or size < 0
        or not isinstance(expired, bool)
        or (digest is not None and not isinstance(digest, str))
        or raw.get("archive_download_url") != expected_archive_url
        or not isinstance(workflow_run, dict)
        or type(workflow_run.get("id")) is not int
        or workflow_run.get("id") != run_id
        or _SHA_RE.fullmatch(workflow_head_sha) is None
    ):
        raise ProvenanceError("artifact inventory is malformed")
    return {
        "archive_download_url": expected_archive_url,
        "digest": str(digest or "").lower(),
        "expired": expired,
        "id": artifact_id,
        "name": name,
        "size_in_bytes": size,
        "workflow_run_id": run_id,
        "workflow_run_sha": workflow_head_sha,
    }


def _artifact_inventory(
    *,
    artifact_name: str,
    owner_head_sha: str,
    repository: str,
    run_id: int,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    total_count: int | None = None
    page = 1
    while total_count is None or len(records) < total_count:
        query = urlencode({"name": artifact_name, "page": page, "per_page": 100})
        raw = _gh_json(f"/repos/{repository}/actions/runs/{run_id}/artifacts?{query}")
        if not isinstance(raw, dict):
            raise ProvenanceError("artifact inventory is malformed")
        page_total = raw.get("total_count")
        artifacts = raw.get("artifacts")
        if (
            isinstance(page_total, bool)
            or not isinstance(page_total, int)
            or page_total < 0
            or not isinstance(artifacts, list)
            or (total_count is not None and page_total != total_count)
        ):
            raise ProvenanceError("artifact inventory is malformed")
        total_count = page_total
        records.extend(
            _normalize_artifact(
                artifact,
                artifact_name=artifact_name,
                owner_head_sha=owner_head_sha,
                repository=repository,
                run_id=run_id,
            )
            for artifact in artifacts
        )
        if not artifacts:
            break
        page += 1
    if total_count is None or len(records) != total_count:
        raise ProvenanceError("artifact inventory count mismatch")
    ids = [cast("int", record["id"]) for record in records]
    if len(ids) != len(set(ids)):
        raise ProvenanceError("artifact inventory contains duplicate IDs")
    return sorted(records, key=lambda record: cast("int", record["id"]))


def _artifact_inventory_by_prefix(
    *,
    artifact_name_prefix: str,
    owner_head_sha: str,
    repository: str,
    run_id: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    full_inventory: list[dict[str, object]] = []
    all_ids: list[int] = []
    total_count: int | None = None
    page = 1
    while total_count is None or len(all_ids) < total_count:
        query = urlencode({"page": page, "per_page": 100})
        raw = _gh_json(f"/repos/{repository}/actions/runs/{run_id}/artifacts?{query}")
        if not isinstance(raw, dict):
            raise ProvenanceError("artifact inventory is malformed")
        page_total = raw.get("total_count")
        artifacts = raw.get("artifacts")
        if (
            isinstance(page_total, bool)
            or not isinstance(page_total, int)
            or page_total < 0
            or not isinstance(artifacts, list)
            or (total_count is not None and page_total != total_count)
        ):
            raise ProvenanceError("artifact inventory is malformed")
        total_count = page_total
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise ProvenanceError("artifact inventory is malformed")
            artifact_id = _positive_integer(artifact.get("id"), field="artifact inventory ID")
            all_ids.append(artifact_id)
            name = artifact.get("name")
            if not isinstance(name, str) or not name:
                raise ProvenanceError("artifact inventory is malformed")
            full_inventory.append(
                _artifact_inventory_identity(
                    artifact,
                    repository=repository,
                    run_id=run_id,
                )
            )
            if name.startswith(artifact_name_prefix):
                normalized = _normalize_artifact(
                    artifact,
                    artifact_name=name,
                    owner_head_sha=owner_head_sha,
                    repository=repository,
                    run_id=run_id,
                )
                records.append(normalized)
        if not artifacts:
            break
        page += 1
    if total_count is None or len(all_ids) != total_count:
        raise ProvenanceError("artifact inventory count mismatch")
    if len(all_ids) != len(set(all_ids)):
        raise ProvenanceError("artifact inventory contains duplicate IDs")
    names = [cast("str", record["name"]) for record in records]
    if len(names) != len(set(names)):
        raise ProvenanceError("artifact inventory contains duplicate names")
    return (
        sorted(records, key=lambda record: cast("int", record["id"])),
        sorted(full_inventory, key=lambda record: cast("int", record["id"])),
    )


def resolve_attested_artifacts_by_prefix(
    *,
    attestation: dict[str, Any],
    artifact_name_prefix: str,
    poll_interval_seconds: float = 1.0,
) -> dict[str, object]:
    if not artifact_name_prefix or artifact_name_prefix.strip() != artifact_name_prefix:
        raise ProvenanceError("artifact name prefix is invalid")
    poll_interval_seconds = _poll_interval(poll_interval_seconds)
    run = recheck_attested_run(attestation)
    repository = cast("str", attestation["repository"])
    run_claim = cast("dict[str, Any]", attestation["run"])
    run_id = cast("int", run_claim["id"])
    owner_head_sha = str(run["head_sha"]).lower()
    observations: list[tuple[list[dict[str, object]], list[dict[str, object]]]] = []
    for observation_index in range(3):
        observations.append(
            _artifact_inventory_by_prefix(
                artifact_name_prefix=artifact_name_prefix,
                owner_head_sha=owner_head_sha,
                repository=repository,
                run_id=run_id,
            )
        )
        if observation_index < 2 and poll_interval_seconds:
            time.sleep(poll_interval_seconds)
    if observations[-2][1] != observations[-1][1]:
        raise ProvenanceError("artifact inventory did not stabilize")
    selected_records = observations[-1][0]
    for selected in selected_records:
        direct = _normalize_artifact(
            _gh_json(f"/repos/{repository}/actions/artifacts/{selected['id']}"),
            artifact_name=cast("str", selected["name"]),
            owner_head_sha=owner_head_sha,
            repository=repository,
            run_id=run_id,
        )
        if direct != selected:
            raise ProvenanceError("artifact changed before exact-ID download")
    recheck_attested_run(attestation)
    return {"artifacts": selected_records, "schema_version": 1}


def resolve_attested_artifact(
    *,
    attestation: dict[str, Any],
    artifact_name: str,
    poll_interval_seconds: float = 1.0,
) -> dict[str, object]:
    if not artifact_name or artifact_name.strip() != artifact_name:
        raise ProvenanceError("artifact name is invalid")
    poll_interval_seconds = _poll_interval(poll_interval_seconds)
    run = recheck_attested_run(attestation)
    repository = cast("str", attestation["repository"])
    run_claim = cast("dict[str, Any]", attestation["run"])
    run_id = cast("int", run_claim["id"])
    owner_head_sha = str(run["head_sha"]).lower()
    observations: list[list[dict[str, object]]] = []
    for observation_index in range(3):
        observations.append(
            _artifact_inventory(
                artifact_name=artifact_name,
                owner_head_sha=owner_head_sha,
                repository=repository,
                run_id=run_id,
            )
        )
        if observation_index < 2 and poll_interval_seconds:
            time.sleep(poll_interval_seconds)
    if observations[-2] != observations[-1]:
        raise ProvenanceError("artifact inventory did not stabilize")
    if len(observations[-1]) != 1:
        raise ProvenanceError("artifact name is absent or ambiguous")
    selected = observations[-1][0]
    direct = _normalize_artifact(
        _gh_json(f"/repos/{repository}/actions/artifacts/{selected['id']}"),
        artifact_name=artifact_name,
        owner_head_sha=owner_head_sha,
        repository=repository,
        run_id=run_id,
    )
    if direct != selected:
        raise ProvenanceError("artifact changed before exact-ID download")
    recheck_attested_run(attestation)
    return direct


def download_attested_artifact(
    *,
    attestation: dict[str, Any],
    receipt: dict[str, Any],
    output_dir: Path,
) -> None:
    """Recheck an exact receipt, hash its archive, and extract only safe regular files."""
    run = recheck_attested_run(attestation)
    repository = cast("str", attestation["repository"])
    run_claim = cast("dict[str, Any]", attestation["run"])
    run_id = cast("int", run_claim["id"])
    artifact_id = _positive_integer(receipt.get("id"), field="artifact receipt ID")
    artifact_name = str(receipt.get("name") or "")
    direct = _normalize_artifact(
        _gh_json(f"/repos/{repository}/actions/artifacts/{artifact_id}"),
        artifact_name=artifact_name,
        owner_head_sha=str(run["head_sha"]).lower(),
        repository=repository,
        run_id=run_id,
    )
    if direct != receipt:
        raise ProvenanceError("artifact receipt changed before exact-ID download")
    recheck_attested_run(attestation)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output_dir.parent,
        prefix=".artifact-",
        suffix=".zip",
        delete=False,
    ) as archive_handle:
        archive_path = Path(archive_handle.name)
    archive_path.unlink()
    try:
        _stream_gh_archive(
            f"/repos/{repository}/actions/artifacts/{artifact_id}/zip",
            archive_path,
        )
        if archive_path.stat().st_size != direct["size_in_bytes"]:
            raise ProvenanceError("artifact archive size does not match its receipt")
        digest = hashlib.sha256()
        with archive_path.open("rb") as archive_stream:
            for chunk in iter(lambda: archive_stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if f"sha256:{digest.hexdigest()}" != direct["digest"]:
            raise ProvenanceError("artifact archive digest does not match its receipt")
        try:
            archive = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile as exc:
            raise ProvenanceError("artifact archive is not a valid ZIP") from exc
        with archive:
            members: list[tuple[zipfile.ZipInfo, PurePosixPath, bool]] = []
            member_kinds: dict[PurePosixPath, str] = {}
            for member in archive.infolist():
                member_path = PurePosixPath(member.filename)
                mode = member.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                is_directory = member.is_dir()
                unsafe = (
                    not member.filename
                    or member_path.is_absolute()
                    or not member_path.parts
                    or str(member_path) in {"", "."}
                    or ".." in member_path.parts
                    or "\\" in member.filename
                    or member_path in member_kinds
                    or stat.S_ISLNK(mode)
                    or (is_directory and file_type not in {0, stat.S_IFDIR})
                    or (not is_directory and file_type not in {0, stat.S_IFREG})
                )
                if unsafe:
                    raise ProvenanceError("artifact archive contains an unsafe member")
                member_kinds[member_path] = "directory" if is_directory else "file"
                members.append((member, member_path, is_directory))
            if not members:
                raise ProvenanceError("artifact archive is empty")

            for member_path in member_kinds:
                for parent in member_path.parents:
                    if str(parent) == ".":
                        break
                    if member_kinds.get(parent) == "file":
                        raise ProvenanceError("artifact archive contains a file-parent collision")

            if output_dir.is_symlink():
                raise ProvenanceError("artifact output directory is a symlink")
            output_root = output_dir.resolve()
            targets: list[tuple[zipfile.ZipInfo, Path, bool]] = []
            for member, member_path, is_directory in members:
                target = output_dir.joinpath(*member_path.parts)
                cursor = output_dir
                if cursor.is_symlink():
                    raise ProvenanceError("artifact output directory is a symlink")
                for part in member_path.parts:
                    cursor /= part
                    if cursor.is_symlink():
                        raise ProvenanceError("artifact archive destination contains a symlink")
                    if cursor != target and cursor.exists() and not cursor.is_dir():
                        raise ProvenanceError(
                            "artifact archive destination parent is not a directory"
                        )
                resolved_target = target.resolve()
                if output_root not in {resolved_target, *resolved_target.parents}:
                    raise ProvenanceError("artifact archive member escapes output directory")
                if is_directory:
                    if target.exists() and not target.is_dir():
                        raise ProvenanceError("artifact archive destination collision")
                elif target.exists():
                    raise ProvenanceError("artifact archive destination collision")
                targets.append((member, target, is_directory))

            output_dir.mkdir(parents=True, exist_ok=True)
            for member, target, is_directory in targets:
                if is_directory:
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("xb") as destination:
                    while chunk := source.read(1024 * 1024):
                        destination.write(chunk)
    finally:
        archive_path.unlink(missing_ok=True)


def download_attested_artifact_bundle(
    *,
    attestation: dict[str, Any],
    bundle: dict[str, Any],
    output_dir: Path,
) -> int:
    artifacts = bundle.get("artifacts")
    if (
        type(bundle.get("schema_version")) is not int
        or bundle.get("schema_version") != 1
        or not isinstance(artifacts, list)
    ):
        raise ProvenanceError("artifact receipt bundle is malformed")
    names: set[str] = set()
    for receipt in artifacts:
        if not isinstance(receipt, dict):
            raise ProvenanceError("artifact receipt bundle entry is malformed")
        name = receipt.get("name")
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or "/" in name
            or "\\" in name
            or name in {".", ".."}
        ):
            raise ProvenanceError("artifact receipt bundle name is invalid")
        names.add(name)
        download_attested_artifact(
            attestation=attestation,
            receipt=receipt,
            output_dir=output_dir / name,
        )
    return len(artifacts)


def verify_current_artifact(
    *,
    repository: str,
    run_id: int,
    run_attempt: int,
    head_sha: str,
    trusted_branch: str,
    workflow_path: str,
    artifact_id: int,
    artifact_name: str,
    artifact_digest: str,
    producer_run_attempt: int | None = None,
    producer_artifact_name: str | None = None,
    reconciliation_role: str | None = None,
) -> dict[str, object]:
    run_id = _positive_integer(run_id, field="current run ID")
    run_attempt = _positive_integer(run_attempt, field="current run attempt")
    producer_run_attempt = _positive_integer(
        run_attempt if producer_run_attempt is None else producer_run_attempt,
        field="artifact producer run attempt",
    )
    artifact_id = _positive_integer(artifact_id, field="current artifact ID")
    if reconciliation_role is not None:
        if reconciliation_role != "publication_reconcile":
            raise ProvenanceError("artifact reconciliation role is invalid")
        if producer_run_attempt != 1:
            raise ProvenanceError("reconciliation artifact producer run attempt must be one")
        if not producer_artifact_name or artifact_name != producer_artifact_name:
            raise ProvenanceError(
                "reconciliation artifact name is not bound to its attempt-one producer"
            )
    elif run_attempt != 1 or producer_run_attempt != 1 or producer_artifact_name is not None:
        raise ProvenanceError("current workflow run attempt must be one")
    head_sha = head_sha.strip().lower()
    if _REPOSITORY_RE.fullmatch(repository) is None or _SHA_RE.fullmatch(head_sha) is None:
        raise ProvenanceError("current workflow identity is invalid")
    digest_hex = artifact_digest.strip().lower().removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", digest_hex) is None:
        raise ProvenanceError("current artifact upload digest is invalid")
    expected_artifact_digest = f"sha256:{digest_hex}"
    expected_run_url = (
        f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com').rstrip('/')}"
        f"/repos/{repository}/actions/runs/{run_id}"
    )

    def current_run_identity(raw: object) -> dict[str, object]:
        if not isinstance(raw, dict):
            raise ProvenanceError("current workflow run response is malformed")
        run_repository = raw.get("repository")
        workflow_id = raw.get("workflow_id")
        if (
            type(raw.get("id")) is not int
            or raw.get("id") != run_id
            or raw.get("url") != expected_run_url
            or not isinstance(run_repository, dict)
            or run_repository.get("full_name") != repository
            or raw.get("event") != "workflow_dispatch"
            or raw.get("head_branch") != trusted_branch
            or str(raw.get("head_sha") or "").lower() != head_sha
            or raw.get("path") != workflow_path
            or type(raw.get("run_attempt")) is not int
            or raw.get("run_attempt") != run_attempt
            or isinstance(workflow_id, bool)
            or not isinstance(workflow_id, int)
            or workflow_id < 1
        ):
            raise ProvenanceError("current workflow run identity is invalid")
        _validate_state(cast("dict[str, Any]", raw), required_state="active-or-completed")
        return {
            "conclusion": raw.get("conclusion"),
            "event": raw.get("event"),
            "head_branch": raw.get("head_branch"),
            "head_sha": str(raw.get("head_sha") or "").lower(),
            "id": raw.get("id"),
            "path": raw.get("path"),
            "repository": repository,
            "run_attempt": raw.get("run_attempt"),
            "status": raw.get("status"),
            "url": raw.get("url"),
            "workflow_id": workflow_id,
        }

    initial_run_identity = current_run_identity(
        _gh_json(f"/repos/{repository}/actions/runs/{run_id}")
    )
    artifact = _normalize_artifact(
        _gh_json(f"/repos/{repository}/actions/artifacts/{artifact_id}"),
        artifact_name=artifact_name,
        owner_head_sha=head_sha,
        repository=repository,
        run_id=run_id,
    )
    if artifact["id"] != artifact_id or artifact["digest"] != expected_artifact_digest:
        raise ProvenanceError("current artifact does not match its upload receipt")
    final_run_identity = current_run_identity(
        _gh_json(f"/repos/{repository}/actions/runs/{run_id}")
    )
    if final_run_identity != initial_run_identity:
        raise ProvenanceError("current workflow run changed after artifact receipt")
    if reconciliation_role is None:
        return artifact
    return {
        **artifact,
        "producer_run_attempt": producer_run_attempt,
        "reconciliation_role": reconciliation_role,
        "verified_owner_run_attempt": run_attempt,
    }


def _decode_workflow_content(
    raw: object,
    *,
    workflow_path: str,
    ref: str,
) -> tuple[bytes, str]:
    if not isinstance(raw, dict):
        raise ProvenanceError(f"workflow content at {ref} is malformed")
    content = raw.get("content")
    blob_sha = str(raw.get("sha") or "").lower()
    size = raw.get("size")
    if (
        raw.get("type") != "file"
        or raw.get("path") != workflow_path
        or raw.get("encoding") != "base64"
        or not isinstance(content, str)
        or _SHA_RE.fullmatch(blob_sha) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
    ):
        raise ProvenanceError(f"workflow content at {ref} is malformed")
    try:
        encoded = "".join(content.split()).encode("ascii")
        workflow_bytes = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ProvenanceError(f"workflow content at {ref} is not valid base64") from exc
    git_blob = hashlib.sha1(  # noqa: S324 - Git object identity is SHA-1 in this repo.
        f"blob {len(workflow_bytes)}\0".encode() + workflow_bytes
    ).hexdigest()
    if not workflow_bytes or len(workflow_bytes) != size or git_blob != blob_sha:
        raise ProvenanceError(f"workflow content at {ref} failed blob validation")
    return workflow_bytes, blob_sha


def attest_run(
    *,
    repository: str,
    run_id: int,
    source_sha: str,
    trusted_branch: str,
    workflow_path: str,
    required_state: str,
) -> dict[str, object]:
    run_id = _positive_integer(run_id, field="run ID")
    repository = repository.strip()
    source_sha = source_sha.strip().lower()
    trusted_branch = trusted_branch.strip()
    if _REPOSITORY_RE.fullmatch(repository) is None:
        raise ProvenanceError("repository identity is invalid")
    if _SHA_RE.fullmatch(source_sha) is None:
        raise ProvenanceError("semantic workflow source SHA is invalid")
    if (
        not trusted_branch
        or trusted_branch.startswith("-")
        or ".." in trusted_branch
        or any(character.isspace() for character in trusted_branch)
    ):
        raise ProvenanceError("trusted workflow branch is invalid")
    if not workflow_path.startswith(".github/workflows/") or not workflow_path.endswith(
        (".yml", ".yaml")
    ):
        raise ProvenanceError("workflow path is invalid")
    if required_state not in {"active-or-completed", "completed", "successful"}:
        raise ProvenanceError("required workflow state is invalid")
    if not os.environ.get("GH_TOKEN", "").strip():
        raise ProvenanceError("GH_TOKEN is required")

    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    expected_run_url = f"{api_url}/repos/{repository}/actions/runs/{run_id}"
    run = _gh_json(f"/repos/{repository}/actions/runs/{run_id}")
    if not isinstance(run, dict):
        raise ProvenanceError("workflow run response is malformed")
    run = cast("dict[str, Any]", run)
    owner_head_sha = str(run.get("head_sha") or "").lower()
    workflow_id = _positive_integer(run.get("workflow_id"), field="workflow ID")
    run_attempt = _positive_integer(run.get("run_attempt"), field="run attempt")
    run_repository = run.get("repository")
    if (
        type(run.get("id")) is not int
        or run.get("id") != run_id
        or run.get("url") != expected_run_url
        or not isinstance(run_repository, dict)
        or run_repository.get("full_name") != repository
        or run.get("event") != "workflow_dispatch"
        or run.get("path") != workflow_path
        or run.get("head_branch") != trusted_branch
        or _SHA_RE.fullmatch(owner_head_sha) is None
        or run_attempt != 1
    ):
        raise ProvenanceError("workflow run identity is invalid")
    _validate_state(run, required_state=required_state)

    workflow = _gh_json(f"/repos/{repository}/actions/workflows/{workflow_id}")
    if (
        not isinstance(workflow, dict)
        or type(workflow.get("id")) is not int
        or workflow.get("id") != workflow_id
        or workflow.get("path") != workflow_path
    ):
        raise ProvenanceError("workflow definition identity is invalid")

    if owner_head_sha == source_sha:
        relation = "identical"
    else:
        comparison = _gh_json(f"/repos/{repository}/compare/{source_sha}...{owner_head_sha}")
        if not isinstance(comparison, dict):
            raise ProvenanceError("workflow source ancestry response is malformed")
        base_commit = comparison.get("base_commit")
        merge_base_commit = comparison.get("merge_base_commit")
        ahead_by = comparison.get("ahead_by")
        behind_by = comparison.get("behind_by")
        if (
            comparison.get("status") != "ahead"
            or not isinstance(base_commit, dict)
            or str(base_commit.get("sha") or "").lower() != source_sha
            or not isinstance(merge_base_commit, dict)
            or str(merge_base_commit.get("sha") or "").lower() != source_sha
            or isinstance(behind_by, bool)
            or behind_by != 0
            or isinstance(ahead_by, bool)
            or not isinstance(ahead_by, int)
            or ahead_by < 1
        ):
            raise ProvenanceError("owner run head does not descend from workflow source")
        relation = "ancestor"

    encoded_path = quote(workflow_path, safe="/")
    source_content = _gh_json(
        f"/repos/{repository}/contents/{encoded_path}",
        fields={"ref": source_sha},
    )
    owner_content = _gh_json(
        f"/repos/{repository}/contents/{encoded_path}",
        fields={"ref": owner_head_sha},
    )
    source_bytes, source_blob_sha = _decode_workflow_content(
        source_content,
        workflow_path=workflow_path,
        ref=source_sha,
    )
    owner_bytes, owner_blob_sha = _decode_workflow_content(
        owner_content,
        workflow_path=workflow_path,
        ref=owner_head_sha,
    )
    if source_bytes != owner_bytes or source_blob_sha != owner_blob_sha:
        raise ProvenanceError("workflow definition differs between source and owner run")

    return {
        "repository": repository,
        "run": {
            "attempt": run_attempt,
            "conclusion": run.get("conclusion"),
            "event": "workflow_dispatch",
            "head_branch": trusted_branch,
            "head_sha": owner_head_sha,
            "id": run_id,
            "path": workflow_path,
            "status": run.get("status"),
            "url": expected_run_url,
            "workflow_id": workflow_id,
        },
        "schema_version": 1,
        "semantic_source": {
            "relation": relation,
            "sha": source_sha,
        },
        "workflow": {
            "blob_sha": source_blob_sha,
            "path": workflow_path,
            "sha256": hashlib.sha256(source_bytes).hexdigest(),
            "size_in_bytes": len(source_bytes),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Attest semantic workflow source provenance for an exact Actions run."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    attest = subparsers.add_parser("attest-run")
    attest.add_argument("--repository", required=True)
    attest.add_argument("--run-id", required=True, type=int)
    attest.add_argument("--source-sha", required=True)
    attest.add_argument("--trusted-branch", required=True)
    attest.add_argument("--workflow-path", required=True)
    attest.add_argument(
        "--required-state",
        choices=("active-or-completed", "completed", "successful"),
        default="completed",
    )
    attest.add_argument("--output", required=True, type=Path)
    recheck = subparsers.add_parser("recheck-run")
    recheck.add_argument("--attestation", required=True, type=Path)
    recheck.add_argument(
        "--required-state",
        choices=("active-or-completed", "completed", "successful"),
    )
    recheck.add_argument("--output", required=True, type=Path)
    resolve = subparsers.add_parser("resolve-artifact")
    resolve.add_argument("--attestation", required=True, type=Path)
    resolve.add_argument("--artifact-name", required=True)
    resolve.add_argument("--poll-interval-seconds", type=float, default=1.0)
    resolve.add_argument("--output", required=True, type=Path)
    resolve_prefix = subparsers.add_parser("resolve-artifacts-by-prefix")
    resolve_prefix.add_argument("--attestation", required=True, type=Path)
    resolve_prefix.add_argument("--artifact-name-prefix", required=True)
    resolve_prefix.add_argument("--poll-interval-seconds", type=float, default=1.0)
    resolve_prefix.add_argument("--output", required=True, type=Path)
    download = subparsers.add_parser("download-artifact")
    download.add_argument("--attestation", required=True, type=Path)
    download.add_argument("--receipt", required=True, type=Path)
    download.add_argument("--output-dir", required=True, type=Path)
    download.add_argument("--output", required=True, type=Path)
    download_bundle = subparsers.add_parser("download-artifact-bundle")
    download_bundle.add_argument("--attestation", required=True, type=Path)
    download_bundle.add_argument("--receipt-bundle", required=True, type=Path)
    download_bundle.add_argument("--output-dir", required=True, type=Path)
    download_bundle.add_argument("--output", required=True, type=Path)
    current = subparsers.add_parser("verify-current-artifact")
    current.add_argument("--repository", required=True)
    current.add_argument("--run-id", required=True, type=int)
    current.add_argument("--run-attempt", required=True, type=int)
    current.add_argument("--head-sha", required=True)
    current.add_argument("--trusted-branch", required=True)
    current.add_argument("--workflow-path", required=True)
    current.add_argument("--artifact-id", required=True, type=int)
    current.add_argument("--artifact-name", required=True)
    current.add_argument("--artifact-digest", required=True)
    current.add_argument("--producer-run-attempt", type=int)
    current.add_argument("--producer-artifact-name")
    current.add_argument("--reconciliation-role", choices=("publication_reconcile",))
    current.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "attest-run":
            payload: dict[str, object] = attest_run(
                repository=args.repository,
                run_id=args.run_id,
                source_sha=args.source_sha,
                trusted_branch=args.trusted_branch,
                workflow_path=args.workflow_path,
                required_state=args.required_state,
            )
        elif args.command == "recheck-run":
            attestation = _load_json_object(
                args.attestation,
                label="workflow provenance attestation",
            )
            recheck_attested_run(
                attestation,
                required_state=args.required_state,
            )
            # Preserve the complete, already-validated schema-v1 snapshot so
            # every downstream consumer can bind its final REST read to the
            # exact owner identity that was rechecked here.
            payload = attestation
        elif args.command == "resolve-artifact":
            payload = resolve_attested_artifact(
                attestation=_load_json_object(
                    args.attestation,
                    label="workflow provenance attestation",
                ),
                artifact_name=args.artifact_name,
                poll_interval_seconds=args.poll_interval_seconds,
            )
        elif args.command == "resolve-artifacts-by-prefix":
            payload = resolve_attested_artifacts_by_prefix(
                attestation=_load_json_object(
                    args.attestation,
                    label="workflow provenance attestation",
                ),
                artifact_name_prefix=args.artifact_name_prefix,
                poll_interval_seconds=args.poll_interval_seconds,
            )
        elif args.command == "download-artifact":
            download_attested_artifact(
                attestation=_load_json_object(
                    args.attestation,
                    label="workflow provenance attestation",
                ),
                receipt=_load_json_object(args.receipt, label="artifact receipt"),
                output_dir=args.output_dir,
            )
            payload = {"schema_version": 1, "status": "downloaded"}
        elif args.command == "download-artifact-bundle":
            downloaded_count = download_attested_artifact_bundle(
                attestation=_load_json_object(
                    args.attestation,
                    label="workflow provenance attestation",
                ),
                bundle=_load_json_object(args.receipt_bundle, label="artifact receipt bundle"),
                output_dir=args.output_dir,
            )
            payload = {
                "downloaded_count": downloaded_count,
                "schema_version": 1,
                "status": "downloaded",
            }
        elif args.command == "verify-current-artifact":
            payload = verify_current_artifact(
                repository=args.repository,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                head_sha=args.head_sha,
                trusted_branch=args.trusted_branch,
                workflow_path=args.workflow_path,
                artifact_id=args.artifact_id,
                artifact_name=args.artifact_name,
                artifact_digest=args.artifact_digest,
                producer_run_attempt=args.producer_run_attempt,
                producer_artifact_name=args.producer_artifact_name,
                reconciliation_role=args.reconciliation_role,
            )
        else:  # pragma: no cover - argparse enforces the command set.
            raise ProvenanceError("unsupported provenance command")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ProvenanceError) as exc:
        raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
