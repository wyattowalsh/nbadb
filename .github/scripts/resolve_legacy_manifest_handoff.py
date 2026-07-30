from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode

_API_VERSION = "2026-03-10"
_WORKFLOW_PATH = ".github/workflows/full-extraction.yml"
_EXECUTED_CONCLUSIONS = {"cancelled", "failure", "success", "timed_out"}


def _gh_json(path: str) -> object:
    raw = subprocess.check_output(
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
        text=True,
    )
    return json.loads(raw)


def _normalize_artifact(
    raw: object,
    *,
    artifact_name: str,
    owner_head_sha: str,
    repository: str,
    run_id: str,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise SystemExit("legacy lane-manifest artifact identity is malformed")
    artifact_id = raw.get("id")
    size = raw.get("size_in_bytes")
    expired = raw.get("expired")
    digest_value = raw.get("digest")
    digest = str(digest_value).lower() if digest_value is not None and digest_value != "" else ""
    workflow_run = raw.get("workflow_run")
    expected_archive_url = (
        f"{os.environ['GITHUB_API_URL'].rstrip('/')}/repos/{repository}"
        f"/actions/artifacts/{artifact_id}/zip"
    )
    if (
        isinstance(artifact_id, bool)
        or not isinstance(artifact_id, int)
        or artifact_id < 1
        or raw.get("name") != artifact_name
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or not isinstance(expired, bool)
        or (digest and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None)
        or raw.get("archive_download_url") != expected_archive_url
        or not isinstance(workflow_run, dict)
        or str(workflow_run.get("id") or "") != run_id
        or str(workflow_run.get("head_sha") or "").lower() != owner_head_sha
    ):
        raise SystemExit("legacy lane-manifest artifact identity is malformed")
    return {
        "archive_download_url": expected_archive_url,
        "digest": digest,
        "expired": expired,
        "id": artifact_id,
        "name": artifact_name,
        "size_in_bytes": size,
        "workflow_run_id": int(run_id),
        "workflow_run_sha": owner_head_sha,
    }


def _artifact_inventory(
    *,
    artifact_name: str,
    owner_head_sha: str,
    repository: str,
    run_id: str,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    total_count: int | None = None
    page = 1
    while total_count is None or len(records) < total_count:
        query = urlencode({"name": artifact_name, "page": page, "per_page": 100})
        payload = _gh_json(f"/repos/{repository}/actions/runs/{run_id}/artifacts?{query}")
        if not isinstance(payload, dict):
            raise SystemExit("legacy lane-manifest artifact inventory is malformed")
        page_total = payload.get("total_count")
        artifacts = payload.get("artifacts")
        if (
            isinstance(page_total, bool)
            or not isinstance(page_total, int)
            or page_total < 0
            or not isinstance(artifacts, list)
            or (total_count is not None and page_total != total_count)
        ):
            raise SystemExit("legacy lane-manifest artifact inventory is malformed")
        total_count = page_total
        records.extend(
            _normalize_artifact(
                item,
                artifact_name=artifact_name,
                owner_head_sha=owner_head_sha,
                repository=repository,
                run_id=run_id,
            )
            for item in artifacts
        )
        if not artifacts:
            break
        page += 1
    if total_count is None or len(records) != total_count:
        raise SystemExit("legacy lane-manifest artifact inventory count mismatch")

    def artifact_id(record: dict[str, object]) -> int:
        value = record["id"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise AssertionError("normalized artifact ID is not an integer")
        return value

    ids = [artifact_id(record) for record in records]
    if len(ids) != len(set(ids)):
        raise SystemExit("legacy lane-manifest artifact inventory has duplicate IDs")
    return sorted(records, key=artifact_id)


def resolve() -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    run_id = os.environ["LANE_MANIFEST_RUN_ID"]
    artifact_name = os.environ["LANE_MANIFEST_ARTIFACT_NAME"]
    workflow_source_sha = os.environ["WORKFLOW_SOURCE_SHA"].strip().lower()
    if re.fullmatch(r"[1-9][0-9]*", run_id) is None:
        raise SystemExit("legacy lane-manifest run ID must be a positive integer")
    if not artifact_name:
        raise SystemExit("legacy lane-manifest artifact name is required")
    if re.fullmatch(r"[0-9a-f]{40}", workflow_source_sha) is None:
        raise SystemExit("pinned workflow source SHA is invalid")

    owner_run = _gh_json(f"/repos/{repository}/actions/runs/{run_id}")
    if not isinstance(owner_run, dict):
        raise SystemExit("legacy lane-manifest owner run response is malformed")
    owner_head_sha = str(owner_run.get("head_sha") or "").lower()
    owner_attempt = owner_run.get("run_attempt")
    owner_status = owner_run.get("status")
    owner_conclusion = owner_run.get("conclusion")
    workflow_id = owner_run.get("workflow_id")
    valid_owner_state = (
        owner_status in {"queued", "in_progress"} and owner_conclusion is None
    ) or (owner_status == "completed" and owner_conclusion in _EXECUTED_CONCLUSIONS)
    if (
        str(owner_run.get("id") or "") != run_id
        or owner_head_sha != workflow_source_sha
        or isinstance(owner_attempt, bool)
        or not isinstance(owner_attempt, int)
        or owner_attempt < 1
        or not valid_owner_state
        or owner_run.get("event") != "workflow_dispatch"
        or owner_run.get("path") != _WORKFLOW_PATH
        or isinstance(workflow_id, bool)
        or not isinstance(workflow_id, int)
        or workflow_id < 1
    ):
        raise SystemExit("legacy lane-manifest owner run identity is invalid")

    poll_interval = float(os.environ.get("LEGACY_MANIFEST_RECEIPT_POLL_INTERVAL_SECONDS", "1"))
    if not math.isfinite(poll_interval) or poll_interval < 0:
        raise SystemExit("legacy lane-manifest poll interval is invalid")
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
        if observation_index < 2 and poll_interval > 0:
            time.sleep(poll_interval)
    if observations[-2] != observations[-1]:
        raise SystemExit("legacy lane-manifest artifact inventory did not stabilize")
    candidates = [record for record in observations[-1] if record["expired"] is False]
    if len(candidates) != 1:
        raise SystemExit("legacy lane-manifest artifact name is absent or ambiguous")
    selected = candidates[0]
    direct = _normalize_artifact(
        _gh_json(f"/repos/{repository}/actions/artifacts/{selected['id']}"),
        artifact_name=artifact_name,
        owner_head_sha=owner_head_sha,
        repository=repository,
        run_id=run_id,
    )
    if direct != selected:
        raise SystemExit("legacy lane-manifest artifact changed before exact-ID download")
    Path(os.environ["LEGACY_RECEIPT_PATH"]).write_text(
        json.dumps(direct, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_receipt(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("legacy lane-manifest receipt is unreadable") from exc
    if not isinstance(payload, dict):
        raise SystemExit("legacy lane-manifest receipt is malformed")
    return payload


def extract() -> None:
    archive_path = Path(os.environ["LEGACY_ARCHIVE_PATH"])
    output_dir = Path(os.environ["LEGACY_OUTPUT_DIR"])
    receipt = _load_receipt(Path(os.environ["LEGACY_RECEIPT_PATH"]))
    expected_manifest_name = (
        "next-manifest.json"
        if str(receipt.get("name") or "").startswith("full-extraction-next-manifest-")
        else "manifest.json"
    )
    digest = str(receipt.get("digest") or "")
    archive_digest = f"sha256:{hashlib.sha256(archive_path.read_bytes()).hexdigest()}"
    if digest and archive_digest != digest:
        raise SystemExit("legacy lane-manifest archive digest does not match REST identity")

    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SystemExit("legacy lane-manifest archive is not a valid ZIP") from exc
    with archive:
        candidates: list[zipfile.ZipInfo] = []
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (
                path.is_absolute()
                or ".." in path.parts
                or stat.S_ISLNK(mode)
                or (not member.is_dir() and stat.S_IFMT(mode) not in {0, stat.S_IFREG})
            ):
                raise SystemExit("legacy lane-manifest archive contains an unsafe member")
            if not member.is_dir() and path.name == expected_manifest_name:
                candidates.append(member)
        if len(candidates) != 1:
            raise SystemExit("legacy lane-manifest archive must contain exactly one manifest")
        selected = candidates[0]
        destination = output_dir / PurePosixPath(selected.filename).name
        destination.write_bytes(archive.read(selected))


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LEGACY_MANIFEST_HANDOFF_MODE", "")
    if mode == "resolve":
        resolve()
    elif mode == "extract":
        extract()
    else:
        raise SystemExit("expected mode: resolve or extract")


if __name__ == "__main__":
    main()
