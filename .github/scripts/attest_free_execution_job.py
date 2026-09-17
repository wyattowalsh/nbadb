#!/usr/bin/env python3
"""Attest the live GitHub Actions job for Full Extraction provider work.

This is job/run/workflow-byte identity, not strictly-free billing admission and
not FreeExecutionAdmissionV1.admitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, NoReturn, cast
from urllib.parse import quote

_API_VERSION = "2026-03-10"
_WORKFLOW_PATH = ".github/workflows/full-extraction.yml"
_MAX_WORKFLOW_BYTES = 512_000
_MAX_JOB_PAGES = 12
_JOB_POLL_ATTEMPTS = 6
_JOB_POLL_SECONDS = 2.0
_OPERATIONS = frozenset({"targeted_smoke", "extract", "continue"})
_COLLECT_JOB = "plan"
_AUTHORIZE_JOBS = {
    "discovery_seed": Path("artifacts/discovery/free-execution-authorization.json"),
    "extract": Path("artifacts/extraction/free-execution-authorization.json"),
    "merge": Path("artifacts/live-snapshot/free-execution-authorization.json"),
}
_PAYLOAD_KEYS = (
    "schema_version",
    "repository",
    "source_sha",
    "head_sha",
    "workflow_path",
    "workflow_sha256",
    "run_id",
    "run_attempt",
    "logical_job_id",
    "actual_job_id",
    "runner_name",
    "operation",
    "lane_id",
    "nonce_sha256",
    "job_url",
    "evaluated_at",
    "collector_status",
    "operation_authority_status",
    "provider_calls_allowed",
    "storage_mutations_allowed",
    "mutations_authorized",
)
_FORBIDDEN_PAYLOAD_KEYS = frozenset({"authorization", "credential", "password", "secret", "token"})
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _fail(message: str) -> NoReturn:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if type(value) is not str or not value or value.strip() != value:
        _fail(f"{name} is missing")
    return value


def _require_positive_int(raw: str, *, field: str) -> int:
    if not raw.isdigit() or int(raw) < 1:
        _fail(f"{field} must be a positive integer")
    return int(raw)


def _require_sha(raw: str, *, field: str) -> str:
    value = raw.strip().lower()
    if _SHA_RE.fullmatch(value) is None:
        _fail(f"{field} must be a 40-character lowercase commit SHA")
    return value


def _canonical_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _open_nofollow(path: Path, flags: int, mode: int = 0o600) -> int:
    return os.open(path, flags | _NOFOLLOW, mode)


def _read_workflow_bytes() -> bytes:
    path = Path(_WORKFLOW_PATH)
    try:
        fd = _open_nofollow(path, os.O_RDONLY)
    except OSError:
        _fail("workflow file must be a bounded regular file")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size < 1 or info.st_size > _MAX_WORKFLOW_BYTES:
            _fail("workflow file must be a bounded regular file")
        body = os.read(fd, _MAX_WORKFLOW_BYTES + 1)
    finally:
        os.close(fd)
    if len(body) > _MAX_WORKFLOW_BYTES:
        _fail("workflow file must be a bounded regular file")
    return body


def _gh_json(path: str) -> object:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        _fail("GH_TOKEN is missing")
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
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        _fail("GitHub API request failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        _fail("GitHub API response is not valid JSON")


def _require_mapping(value: object, *, field: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(f"{field} must be an object")
    return cast("dict[str, Any]", value)


def _job_name_matches(name: object, logical_job_id: str) -> bool:
    if type(name) is not str or not name:
        return False
    return name == logical_job_id or name.startswith(f"{logical_job_id} (")


def _select_live_job(
    *,
    repository: str,
    run_id: int,
    run_attempt: int,
    logical_job_id: str,
) -> dict[str, Any]:
    encoded_repo = quote(repository, safe="/")
    selected: dict[str, Any] | None = None
    for _attempt in range(_JOB_POLL_ATTEMPTS):
        candidates: list[dict[str, Any]] = []
        seen = 0
        total_count: int | None = None
        for page in range(1, _MAX_JOB_PAGES + 1):
            payload = _require_mapping(
                _gh_json(
                    f"/repos/{encoded_repo}/actions/runs/{run_id}/attempts/"
                    f"{run_attempt}/jobs?per_page=100&page={page}"
                ),
                field="jobs inventory",
            )
            page_total = payload.get("total_count")
            if type(page_total) is not int or page_total < 0:
                _fail("jobs inventory total_count is invalid")
            if total_count is None:
                total_count = page_total
            elif page_total != total_count:
                _fail("jobs inventory total_count drifted")
            jobs = payload.get("jobs")
            if type(jobs) is not list:
                _fail("jobs inventory is invalid")
            seen += len(jobs)
            for raw in jobs:
                job = _require_mapping(raw, field="job")
                if (
                    job.get("run_attempt") == run_attempt
                    and job.get("status") == "in_progress"
                    and _job_name_matches(job.get("name"), logical_job_id)
                ):
                    candidates.append(job)
            if seen >= total_count or not jobs:
                break
        else:
            _fail("jobs inventory exceeded page budget")
        if len(candidates) > 1:
            _fail("live job identity is ambiguous")
        if len(candidates) == 1:
            selected = candidates[0]
            break
        if _attempt + 1 < _JOB_POLL_ATTEMPTS:
            time.sleep(_JOB_POLL_SECONDS)
    if selected is None:
        _fail("live job identity is missing")
    return selected


def _attest_job() -> dict[str, object]:
    repository = _require_env("GITHUB_REPOSITORY")
    if _REPOSITORY_RE.fullmatch(repository) is None:
        _fail("GITHUB_REPOSITORY must be owner/name")
    run_id = _require_positive_int(_require_env("GITHUB_RUN_ID"), field="GITHUB_RUN_ID")
    run_attempt = _require_positive_int(
        _require_env("GITHUB_RUN_ATTEMPT"), field="GITHUB_RUN_ATTEMPT"
    )
    logical_job_id = _require_env("GITHUB_JOB")
    head_sha = _require_sha(_require_env("GITHUB_SHA"), field="GITHUB_SHA")
    source_sha = _require_sha(_require_env("WORKFLOW_SOURCE_SHA"), field="WORKFLOW_SOURCE_SHA")
    api_url = _require_env("GITHUB_API_URL").rstrip("/")
    runner_name = _require_env("RUNNER_NAME")
    operation = _require_env("FULL_EXTRACTION_OPERATION")
    if operation not in _OPERATIONS:
        _fail("FULL_EXTRACTION_OPERATION is invalid")
    workflow_bytes = _read_workflow_bytes()
    workflow_sha256 = hashlib.sha256(workflow_bytes).hexdigest()
    encoded_repo = quote(repository, safe="/")
    run = _require_mapping(
        _gh_json(f"/repos/{encoded_repo}/actions/runs/{run_id}"),
        field="workflow run",
    )
    run_repository = _require_mapping(run.get("repository"), field="run repository")
    if (
        run.get("id") != run_id
        or run.get("run_attempt") != run_attempt
        or run.get("event") != "workflow_dispatch"
        or run.get("path") != _WORKFLOW_PATH
        or run_repository.get("full_name") != repository
        or run.get("url") != f"{api_url}/repos/{repository}/actions/runs/{run_id}"
    ):
        _fail("workflow run identity does not match this execution")
    listed = _select_live_job(
        repository=repository,
        run_id=run_id,
        run_attempt=run_attempt,
        logical_job_id=logical_job_id,
    )
    actual_job_id = listed.get("id")
    if type(actual_job_id) is not int or actual_job_id < 1:
        _fail("actual job id is invalid")
    job = _require_mapping(
        _gh_json(f"/repos/{encoded_repo}/actions/jobs/{actual_job_id}"),
        field="job",
    )
    job_url = f"{api_url}/repos/{repository}/actions/jobs/{actual_job_id}"
    started_at = job.get("started_at")
    if type(started_at) is not str or not started_at:
        _fail("job started_at is missing")
    if (
        job.get("id") != actual_job_id
        or job.get("run_id") != run_id
        or job.get("run_attempt") != run_attempt
        or job.get("head_sha") != head_sha
        or job.get("runner_name") != runner_name
        or job.get("url") != job_url
        or job.get("run_url") != f"{api_url}/repos/{repository}/actions/runs/{run_id}"
        or not _job_name_matches(job.get("name"), logical_job_id)
    ):
        _fail("job identity does not match this execution")
    lane_id = os.environ.get("LANE_ID", "")
    if logical_job_id == "extract":
        if type(lane_id) is not str or not lane_id or lane_id.strip() != lane_id:
            _fail("LANE_ID is required for extract")
    elif lane_id:
        _fail("LANE_ID must be empty outside extract")
    nonce = hashlib.sha256(
        "|".join(
            (
                repository,
                str(run_id),
                str(run_attempt),
                str(actual_job_id),
                logical_job_id,
                workflow_sha256,
                operation,
                lane_id,
            )
        ).encode("utf-8")
    ).hexdigest()
    payload: dict[str, object] = {
        "schema_version": 1,
        "repository": repository,
        "source_sha": source_sha,
        "head_sha": head_sha,
        "workflow_path": _WORKFLOW_PATH,
        "workflow_sha256": workflow_sha256,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "logical_job_id": logical_job_id,
        "actual_job_id": actual_job_id,
        "runner_name": runner_name,
        "operation": operation,
        "lane_id": lane_id,
        "nonce_sha256": nonce,
        "job_url": job_url,
        "evaluated_at": started_at,
        "collector_status": "admitted",
        "operation_authority_status": "validated",
        "provider_calls_allowed": True,
        "storage_mutations_allowed": True,
        "mutations_authorized": True,
    }
    if frozenset(payload) != frozenset(_PAYLOAD_KEYS):
        _fail("authorization payload fields are invalid")
    if frozenset(payload) & _FORBIDDEN_PAYLOAD_KEYS:
        _fail("authorization payload contains a forbidden key")
    return payload


def _require_admitted_collector_env() -> None:
    expected = {
        "OPERATION_AUTHORITY_STATUS": "validated",
        "COLLECTOR_STATUS": "admitted",
        "COLLECTOR_AUTHENTICATED": "true",
        "RUNTIME_CONTEXT_STATUS": "authenticated",
        "STORAGE_MUTATIONS_ALLOWED": "true",
        "PROVIDER_CALLS_ALLOWED": "true",
        "MUTATIONS_AUTHORIZED": "true",
    }
    for name, value in expected.items():
        if os.environ.get(name) != value:
            _fail("operation authority or collector outputs are not admitted")


def _expected_output_path(logical_job_id: str) -> Path:
    try:
        return _AUTHORIZE_JOBS[logical_job_id]
    except KeyError:
        _fail("this job cannot write provider authorization")


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    if path != _expected_output_path(str(payload["logical_job_id"])):
        _fail("authorization output path is not allowed for this job")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _canonical_bytes(payload)
    if path.exists() or path.is_symlink():
        if path.is_symlink():
            _fail("authorization file must not be a symlink")
        try:
            fd = _open_nofollow(path, os.O_RDONLY)
        except OSError:
            _fail("authorization file is unreadable")
        try:
            existing = os.read(fd, len(body) + 1)
        finally:
            os.close(fd)
        if existing != body:
            _fail("authorization file differs from the attested payload")
        return
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = _open_nofollow(path, flags, 0o600)
    except OSError:
        _fail("authorization file could not be created exclusively")
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_payload(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        _fail("authorization file must not be a symlink")
    try:
        fd = _open_nofollow(path, os.O_RDONLY)
    except OSError:
        _fail("authorization file is missing")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size < 1 or info.st_size > 16_384:
            _fail("authorization file must be a bounded regular file")
        raw = os.read(fd, 16_385)
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _fail("authorization file is not valid JSON")
    if type(payload) is not dict:
        _fail("authorization file must be an object")
    typed = cast("dict[str, Any]", payload)
    if frozenset(typed) != frozenset(_PAYLOAD_KEYS):
        _fail("authorization file fields are invalid")
    if frozenset(typed) & _FORBIDDEN_PAYLOAD_KEYS:
        _fail("authorization file contains a forbidden key")
    return typed


def collect() -> None:
    if _require_env("GITHUB_JOB") != _COLLECT_JOB:
        _fail("collect is only allowed from the plan job")
    _attest_job()
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        _fail("GITHUB_OUTPUT is missing")
    with Path(output).open("a", encoding="utf-8") as handle:
        handle.write("status=admitted\n")
        handle.write("authenticated=true\n")
        handle.write("runtime-context-status=authenticated\n")
        handle.write("storage-mutations-allowed=true\n")
        handle.write("provider-calls-allowed=true\n")
        handle.write("mutations-authorized=true\n")


def authorize(*, output: str) -> None:
    _require_admitted_collector_env()
    logical_job_id = _require_env("GITHUB_JOB")
    path = Path(output)
    if path != _expected_output_path(logical_job_id):
        _fail("authorization output path is not allowed for this job")
    payload = _attest_job()
    _write_payload(path, payload)


def verify(*, input_path: str) -> None:
    _require_admitted_collector_env()
    logical_job_id = _require_env("GITHUB_JOB")
    path = Path(input_path)
    if path != _expected_output_path(logical_job_id):
        _fail("authorization input path is not allowed for this job")
    existing = _read_payload(path)
    expected = _attest_job()
    if existing != expected:
        _fail("authorization file does not match the attested job")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="attest_free_execution_job.py")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect")
    authorize_parser = sub.add_parser("authorize")
    authorize_parser.add_argument("--output", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    if args.command == "collect":
        collect()
    elif args.command == "authorize":
        authorize(output=args.output)
    else:
        verify(input_path=args.input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
