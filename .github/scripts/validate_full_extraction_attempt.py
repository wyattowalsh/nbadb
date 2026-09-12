#!/usr/bin/env python3
"""Fail-closed admission gate for every independently rerunnable extraction job."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from collections.abc import Mapping

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_GITHUB_API_VERSION = "2026-03-10"
_POSITIVE_INT_RE = re.compile(r"[1-9][0-9]*")
_REPLACEABLE_CONCLUSIONS = frozenset({"action_required", "cancelled", "failure", "timed_out"})
_WORKFLOW_FILE = "full-extraction.yml"
_WORKFLOW_PATH = ".github/workflows/full-extraction.yml"


class _WorkflowRun(TypedDict):
    conclusion: str | None
    display_title: str
    event: str
    html_url: str | None
    id: int
    status: str


class _WorkflowInventory(TypedDict):
    runs: list[_WorkflowRun]
    total_count: int


def _value(env: Mapping[str, str], name: str) -> str:
    return env.get(name, "").strip()


def _positive_integer(value: str, *, label: str) -> int:
    if _POSITIVE_INT_RE.fullmatch(value) is None:
        raise SystemExit(f"{label} must be a positive integer")
    return int(value)


def validate_source_mode(env: Mapping[str, str]) -> tuple[int, int, str]:
    """Validate the attempt and mutually exclusive manifest source mode."""

    current_run_id = _positive_integer(
        _value(env, "GITHUB_RUN_ID"),
        label="current workflow run ID",
    )
    current_attempt = _positive_integer(
        _value(env, "GITHUB_RUN_ATTEMPT"),
        label="current workflow run attempt",
    )
    chain_id = _value(env, "FULL_EXTRACTION_CHAIN_INPUT")
    inline_manifest_present = _value(
        env,
        "FULL_EXTRACTION_LANE_MANIFEST_JSON_PRESENT",
    ).lower()
    if inline_manifest_present not in {"false", "true"}:
        raise SystemExit("lane_manifest_json presence must be exactly true or false")
    inline_manifest = inline_manifest_present == "true"
    lane_run_id = _value(env, "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID")
    artifact_name = _value(env, "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME")
    artifact_id = _value(env, "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_ID")
    artifact_digest = _value(env, "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_DIGEST").lower()
    resume_run_id = _value(env, "FULL_EXTRACTION_RESUME_SOURCE_RUN_ID")
    resume_run_attempt = _value(env, "FULL_EXTRACTION_RESUME_SOURCE_RUN_ATTEMPT")
    resume_artifact_name = _value(env, "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_NAME")
    resume_artifact_id = _value(env, "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_ID")
    resume_artifact_digest = _value(
        env,
        "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_DIGEST",
    ).lower()
    artifact_fields = (artifact_name, artifact_id, artifact_digest)
    resume_fields = (
        resume_run_id,
        resume_run_attempt,
        resume_artifact_name,
        resume_artifact_id,
        resume_artifact_digest,
    )

    if lane_run_id and resume_run_id:
        raise SystemExit("lane_manifest_run_id and resume_source_run_id are mutually exclusive")
    if inline_manifest and (lane_run_id or resume_run_id or any(artifact_fields)):
        raise SystemExit(
            "lane_manifest_json cannot be combined with a source run or lane artifact metadata"
        )
    if inline_manifest and any(resume_fields):
        raise SystemExit(
            "lane_manifest_json cannot be combined with resume source artifact metadata"
        )
    if resume_run_id and any(artifact_fields):
        raise SystemExit("resume_source_run_id cannot be combined with lane artifact metadata")
    if any(resume_fields) and not all(resume_fields):
        raise SystemExit(
            "resume source inputs are all-or-none: run id, run attempt, manifest artifact "
            "name, artifact id, and artifact digest must be provided together"
        )
    if resume_run_id:
        if _POSITIVE_INT_RE.fullmatch(resume_run_attempt) is None:
            raise SystemExit("resume_source_run_attempt must be a positive integer")
        if _POSITIVE_INT_RE.fullmatch(resume_artifact_id) is None:
            raise SystemExit("resume_source_manifest_artifact_id must be a positive integer")
        if _DIGEST_RE.fullmatch(resume_artifact_digest) is None:
            raise SystemExit(
                "resume_source_manifest_artifact_digest must be sha256:<64 lowercase hex>"
            )
    if not lane_run_id and any(artifact_fields):
        raise SystemExit("lane artifact metadata requires lane_manifest_run_id")
    if bool(artifact_id) != bool(artifact_digest):
        raise SystemExit(
            "lane_manifest_artifact_id and lane_manifest_artifact_digest must be provided together"
        )
    if artifact_digest and not artifact_digest.startswith("sha256:"):
        artifact_digest = f"sha256:{artifact_digest}"

    source_run_id: int | None = None
    if lane_run_id:
        source_run_id = _positive_integer(
            lane_run_id,
            label="lane_manifest_run_id",
        )
        if not artifact_name:
            raise SystemExit("lane_manifest_run_id requires lane_manifest_artifact_name")
        if artifact_id:
            _positive_integer(
                artifact_id,
                label="lane_manifest_artifact_id",
            )
            if _DIGEST_RE.fullmatch(artifact_digest) is None:
                raise SystemExit("lane_manifest_artifact_digest must be sha256:<64 lowercase hex>")
        mode = "lane_source"
    elif resume_run_id:
        source_run_id = _positive_integer(
            resume_run_id,
            label="resume_source_run_id",
        )
        mode = "continue"
    elif inline_manifest:
        mode = "inline"
    else:
        mode = "fresh"

    if source_run_id is not None:
        if source_run_id == current_run_id:
            raise SystemExit(
                "full-extraction source run must differ from the current workflow run ID"
            )
        if not chain_id:
            raise SystemExit("lane or resume source mode requires an explicit chain_id")

    operation = _value(env, "FULL_EXTRACTION_OPERATION")
    if operation not in {"targeted_smoke", "extract", "continue"}:
        raise SystemExit("operation must be exactly targeted_smoke, extract, or continue")
    if operation == "continue" and mode != "continue":
        raise SystemExit("operation=continue requires the exact five-field resume source")
    if operation != "continue" and mode == "continue":
        raise SystemExit("resume source inputs require operation=continue")

    print(
        "Full-extraction attempt source contract passed: "
        f"run={current_run_id} attempt={current_attempt} mode={mode}"
    )
    return current_run_id, current_attempt, mode


def _gh_json(arguments: list[str]) -> Any:
    try:
        raw = subprocess.check_output(
            ["gh", "api", *arguments],
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"GitHub workflow inventory request failed with exit code {exc.returncode}"
        ) from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"GitHub workflow inventory is not valid JSON: {exc}") from exc


def _normalize_run_inventory(pages: Any) -> _WorkflowInventory:
    if not isinstance(pages, list) or not pages:
        raise SystemExit("workflow run inventory must contain pages")

    total_count: int | None = None
    run_ids: set[int] = set()
    runs: list[_WorkflowRun] = []
    for page in pages:
        if not isinstance(page, dict):
            raise SystemExit("workflow run inventory pages must be objects")
        page_total = page.get("total_count")
        entries = page.get("workflow_runs")
        if (
            isinstance(page_total, bool)
            or not isinstance(page_total, int)
            or page_total < 0
            or not isinstance(entries, list)
        ):
            raise SystemExit("workflow run inventory page is malformed")
        if total_count is None:
            total_count = page_total
        elif total_count != page_total:
            raise SystemExit("workflow run inventory total_count changed during pagination")

        for entry in entries:
            if not isinstance(entry, dict):
                raise SystemExit("workflow run inventory entries must be objects")
            run_id = entry.get("id")
            title = entry.get("display_title")
            status = entry.get("status")
            conclusion = entry.get("conclusion")
            event = entry.get("event")
            html_url = entry.get("html_url")
            if (
                isinstance(run_id, bool)
                or not isinstance(run_id, int)
                or run_id < 1
                or not isinstance(title, str)
                or not title
                or not isinstance(status, str)
                or not status
                or (conclusion is not None and not isinstance(conclusion, str))
                or not isinstance(event, str)
                or not event
                or (html_url is not None and not isinstance(html_url, str))
            ):
                raise SystemExit("workflow run inventory entry is malformed")
            if run_id in run_ids:
                raise SystemExit("workflow run inventory repeated a workflow run ID")
            run_ids.add(run_id)
            runs.append(
                {
                    "conclusion": conclusion,
                    "display_title": title,
                    "event": event,
                    "html_url": html_url,
                    "id": run_id,
                    "status": status,
                }
            )

    assert total_count is not None
    if total_count != len(runs):
        raise SystemExit("workflow run inventory row count does not match total_count")
    return {
        "runs": sorted(runs, key=lambda run: int(run["id"])),
        "total_count": total_count,
    }


def _poll_interval(env: Mapping[str, str]) -> float:
    raw = _value(env, "FULL_EXTRACTION_ATTEMPT_GATE_POLL_INTERVAL_SECONDS") or "2"
    try:
        interval = float(raw)
    except ValueError as exc:
        raise SystemExit("attempt gate poll interval must be a number") from exc
    if interval < 0 or interval > 30:
        raise SystemExit("attempt gate poll interval must be between 0 and 30 seconds")
    return interval


def enforce_duplicate_admission(
    env: Mapping[str, str],
    *,
    current_run_id: int,
) -> None:
    """Require a stable exact-title run inventory before admitting this job."""

    repository = _value(env, "GITHUB_REPOSITORY")
    expected_run_name = _value(env, "FULL_EXTRACTION_EXPECTED_RUN_NAME")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
        raise SystemExit("GitHub repository identity is invalid")
    if not expected_run_name or any(ord(character) < 32 for character in expected_run_name):
        raise SystemExit("expected workflow run name is invalid")

    endpoint = f"/repos/{repository}/actions/workflows/{_WORKFLOW_FILE}/runs"
    observations: list[_WorkflowInventory] = []
    interval = _poll_interval(env)
    for observation_index in range(3):
        pages = _gh_json(
            [
                "--method",
                "GET",
                "--paginate",
                "--slurp",
                "-H",
                "Accept: application/vnd.github+json",
                "-H",
                f"X-GitHub-Api-Version: {_GITHUB_API_VERSION}",
                endpoint,
                "-f",
                "per_page=100",
            ]
        )
        observations.append(_normalize_run_inventory(pages))
        if observation_index < 2 and interval:
            time.sleep(interval)

    if observations[-2] != observations[-1]:
        raise SystemExit(
            "workflow run inventory did not stabilize across the final two observations"
        )

    final_runs = observations[-1]["runs"]
    current_matches = [run for run in final_runs if run["id"] == current_run_id]
    if len(current_matches) != 1:
        raise SystemExit("workflow run inventory does not contain exactly one current workflow run")
    current = current_matches[0]
    if (
        current["event"] != "workflow_dispatch"
        or current["display_title"] != expected_run_name
        or current["status"] not in {"queued", "in_progress"}
        or current["conclusion"] is not None
    ):
        raise SystemExit("current workflow run inventory identity is invalid")

    blockers: list[_WorkflowRun] = []
    for run in final_runs:
        if (
            run["event"] != "workflow_dispatch"
            or run["display_title"] != expected_run_name
            or run["id"] == current_run_id
        ):
            continue
        if run["status"] != "completed" or run["conclusion"] not in _REPLACEABLE_CONCLUSIONS:
            blockers.append(run)

    if blockers:
        identities = ", ".join(
            (f"{run['id']}:{run['status']}:{run['conclusion']}:{run['html_url']}")
            for run in blockers
        )
        raise SystemExit(
            f"refusing duplicate full-extraction workflow run for {expected_run_name}: {identities}"
        )
    print(f"Duplicate workflow admission passed for {expected_run_name}")


def main() -> None:
    role = _value(os.environ, "FULL_EXTRACTION_ATTEMPT_GATE_ROLE")
    if role not in {
        "dispatch_reconcile",
        "partial",
        "primary",
        "publication_reconcile",
    }:
        raise SystemExit(
            "attempt gate role must be dispatch_reconcile, primary, partial, "
            "or publication_reconcile"
        )
    current_run_id, current_attempt, _mode = validate_source_mode(os.environ)
    if current_attempt > 1 and role in {"partial", "primary"}:
        raise SystemExit(
            "full and partial workflow reruns are unsafe after attempt artifacts "
            "are replaced; dispatch a new receipt-bound workflow run"
        )
    if role == "primary" or current_attempt > 1:
        enforce_duplicate_admission(
            os.environ,
            current_run_id=current_run_id,
        )
    else:
        print("Duplicate workflow admission delegated to the primary attempt-1 guard")


if __name__ == "__main__":
    main()
