#!/usr/bin/env python3
# ruff: noqa: E501
"""Run exact full-extraction handoff operations from the pinned source checkout."""

from __future__ import annotations

import argparse
import subprocess
from typing import Final

RESOLVE_RESUME_SOURCE_COMMITTED_MANIFEST_SCRIPT: Final = r"""mkdir -p "$RUNNER_TEMP/workflow-provenance"
python .github/scripts/workflow_source_provenance.py attest-run \
  --repository "$GITHUB_REPOSITORY" \
  --run-id "$RESUME_SOURCE_RUN_ID" \
  --source-sha "$WORKFLOW_SOURCE_SHA" \
  --trusted-branch "$WORKFLOW_SOURCE_REF" \
  --workflow-path .github/workflows/full-extraction.yml \
  --required-state completed \
  --output "$RUNNER_TEMP/workflow-provenance/resume-source-owner.json"
python .github/scripts/workflow_source_provenance.py recheck-run \
  --attestation "$RUNNER_TEMP/workflow-provenance/resume-source-owner.json" \
  --required-state completed \
  --output "$RUNNER_TEMP/workflow-provenance/resume-source-owner-recheck.json"
OWNER_RECHECK_PATH="$RUNNER_TEMP/workflow-provenance/resume-source-owner-recheck.json" python - <<'PY'
# RESUME_SOURCE_COMMITTED_MANIFEST_RESOLVER
import json
import os
import re
import subprocess
import time
from pathlib import Path

def gh_json(arguments: list[str]) -> object:
    raw = subprocess.check_output(
        ["gh", "api", *arguments],
        text=True,
    )
    return json.loads(raw)

source_run_id = os.environ["RESUME_SOURCE_RUN_ID"]
if re.fullmatch(r"[1-9][0-9]*", source_run_id) is None:
    raise SystemExit("resume source run ID must be a positive integer")
repository = os.environ["GITHUB_REPOSITORY"].strip()
workflow_source_sha = os.environ["WORKFLOW_SOURCE_SHA"].strip().lower()
if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
    raise SystemExit("GitHub repository identity is invalid")
if re.fullmatch(r"[0-9a-f]{40}", workflow_source_sha) is None:
    raise SystemExit("pinned workflow source SHA is invalid")

owner_snapshot = json.loads(
    Path(os.environ["OWNER_RECHECK_PATH"]).read_text(encoding="utf-8")
)
owner_claim = (
    owner_snapshot.get("run")
    if isinstance(owner_snapshot, dict)
    else None
)
semantic_source = (
    owner_snapshot.get("semantic_source")
    if isinstance(owner_snapshot, dict)
    else None
)
workflow_claim = (
    owner_snapshot.get("workflow")
    if isinstance(owner_snapshot, dict)
    else None
)
expected_run_url = (
    f"{os.environ['GITHUB_API_URL'].rstrip('/')}/repos/{repository}"
    f"/actions/runs/{source_run_id}"
)
if (
    not isinstance(owner_snapshot, dict)
    or type(owner_snapshot.get("schema_version")) is not int
    or owner_snapshot.get("schema_version") != 1
    or owner_snapshot.get("repository") != repository
    or not isinstance(owner_claim, dict)
    or type(owner_claim.get("id")) is not int
    or owner_claim.get("id") != int(source_run_id)
    or owner_claim.get("url") != expected_run_url
    or owner_claim.get("event") != "workflow_dispatch"
    or not isinstance(owner_claim.get("head_branch"), str)
    or not owner_claim.get("head_branch")
    or re.fullmatch(
        r"[0-9a-f]{40}",
        str(owner_claim.get("head_sha") or "").lower(),
    )
    is None
    or owner_claim.get("path")
    != ".github/workflows/full-extraction.yml"
    or type(owner_claim.get("attempt")) is not int
    or owner_claim.get("attempt") != 1
    or type(owner_claim.get("workflow_id")) is not int
    or owner_claim.get("workflow_id") < 1
    or owner_claim.get("status") != "completed"
    or owner_claim.get("conclusion")
    not in {"cancelled", "failure", "success", "timed_out"}
    or not isinstance(semantic_source, dict)
    or str(semantic_source.get("sha") or "").lower()
    != workflow_source_sha
    or semantic_source.get("relation")
    not in {"identical", "ancestor"}
    or (semantic_source.get("relation") == "identical")
    != (
        str(semantic_source.get("sha") or "").lower()
        == str(owner_claim.get("head_sha") or "").lower()
    )
    or not isinstance(workflow_claim, dict)
    or workflow_claim.get("path")
    != ".github/workflows/full-extraction.yml"
    or re.fullmatch(
        r"[0-9a-f]{40}",
        str(workflow_claim.get("blob_sha") or "").lower(),
    )
    is None
    or re.fullmatch(
        r"[0-9a-f]{64}",
        str(workflow_claim.get("sha256") or "").lower(),
    )
    is None
    or type(workflow_claim.get("size_in_bytes")) is not int
    or workflow_claim.get("size_in_bytes") < 1
):
    raise SystemExit("resume source owner recheck snapshot is invalid")

owner_run = gh_json(
    [
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        f"/repos/{repository}/actions/runs/{source_run_id}",
    ]
)
if not isinstance(owner_run, dict):
    raise SystemExit("resume source workflow run must be an object")
owner_head_sha = str(owner_run.get("head_sha") or "").lower()
run_attempt = owner_run.get("run_attempt")
workflow_id = owner_run.get("workflow_id")
owner_repository = owner_run.get("repository")
if (
    type(owner_run.get("id")) is not int
    or str(owner_run.get("id")) != source_run_id
    or owner_run.get("url") != owner_claim.get("url")
    or not isinstance(owner_repository, dict)
    or owner_repository.get("full_name") != repository
    or type(run_attempt) is not int
    or run_attempt != owner_claim.get("attempt")
    or run_attempt != 1
    or owner_head_sha != str(owner_claim.get("head_sha") or "").lower()
    or owner_run.get("status") != owner_claim.get("status")
    or owner_run.get("conclusion") != owner_claim.get("conclusion")
    or owner_run.get("event") != owner_claim.get("event")
    or owner_run.get("head_branch") != owner_claim.get("head_branch")
    or owner_run.get("path") != owner_claim.get("path")
    or type(workflow_id) is not int
    or workflow_id != owner_claim.get("workflow_id")
):
    raise SystemExit(
        "resume source owner run changed after provenance recheck"
    )

def normalized_artifact(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise SystemExit(
            "resume source artifact inventory entry must be an object"
        )
    artifact_id = raw.get("id")
    artifact_name = raw.get("name")
    artifact_digest = str(raw.get("digest") or "").lower()
    artifact_size = raw.get("size_in_bytes")
    workflow_run = raw.get("workflow_run")
    expected_archive_url = (
        f"{os.environ['GITHUB_API_URL'].rstrip('/')}/repos/{repository}"
        f"/actions/artifacts/{artifact_id}/zip"
    )
    if (
        isinstance(artifact_id, bool)
        or not isinstance(artifact_id, int)
        or artifact_id < 1
        or not isinstance(artifact_name, str)
        or not artifact_name
        or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest) is None
        or isinstance(artifact_size, bool)
        or not isinstance(artifact_size, int)
        or artifact_size < 1
        or type(raw.get("expired")) is not bool
        or raw.get("archive_download_url") != expected_archive_url
        or not isinstance(workflow_run, dict)
        or str(workflow_run.get("id") or "") != source_run_id
        or str(workflow_run.get("head_sha") or "").lower()
        != owner_head_sha
    ):
        raise SystemExit(
            "resume source artifact REST identity is malformed"
        )
    return {
        "archive_download_url": expected_archive_url,
        "digest": artifact_digest,
        "expired": raw["expired"],
        "id": artifact_id,
        "name": artifact_name,
        "size_in_bytes": artifact_size,
        "workflow_run": {
            "head_sha": owner_head_sha,
            "id": int(source_run_id),
        },
    }

def artifact_inventory_snapshot() -> dict[str, object]:
    pages = gh_json(
        [
            "--method",
            "GET",
            "--paginate",
            "--slurp",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2026-03-10",
            f"/repos/{repository}/actions/runs/{source_run_id}/artifacts",
            "-f",
            "per_page=100",
        ]
    )
    if not isinstance(pages, list) or not pages:
        raise SystemExit(
            "resume source artifact inventory must contain pages"
        )
    expected_total: int | None = None
    artifact_ids: set[int] = set()
    artifacts: list[dict[str, object]] = []
    for page in pages:
        if not isinstance(page, dict):
            raise SystemExit(
                "resume source artifact inventory page must be an object"
            )
        page_total = page.get("total_count")
        entries = page.get("artifacts")
        if (
            isinstance(page_total, bool)
            or not isinstance(page_total, int)
            or page_total < 0
            or not isinstance(entries, list)
        ):
            raise SystemExit(
                "resume source artifact inventory page is malformed"
            )
        if expected_total is None:
            expected_total = page_total
        elif expected_total != page_total:
            raise SystemExit(
                "resume source artifact inventory total changed during pagination"
            )
        for entry in entries:
            artifact = normalized_artifact(entry)
            artifact_id = int(artifact["id"])
            if artifact_id in artifact_ids:
                raise SystemExit(
                    "resume source artifact inventory repeated an artifact ID"
                )
            artifact_ids.add(artifact_id)
            artifacts.append(artifact)
    if expected_total != len(artifacts):
        raise SystemExit(
            "resume source artifact inventory count does not match total_count"
        )
    return {
        "artifacts": sorted(
            artifacts,
            key=lambda artifact: int(artifact["id"]),
        ),
        "total_count": expected_total,
    }

raw_interval = (
    os.environ.get(
        "RESUME_MANIFEST_RECEIPT_POLL_INTERVAL_SECONDS",
        "",
    ).strip()
    or "2"
)
try:
    poll_interval = float(raw_interval)
except ValueError as exc:
    raise SystemExit(
        "resume manifest receipt poll interval must be numeric"
    ) from exc
if poll_interval < 0 or poll_interval > 30:
    raise SystemExit(
        "resume manifest receipt poll interval must be between 0 and 30 seconds"
    )
observations: list[dict[str, object]] = []
for observation_index in range(3):
    observations.append(artifact_inventory_snapshot())
    if observation_index < 2 and poll_interval:
        time.sleep(poll_interval)
if observations[-2] != observations[-1]:
    raise SystemExit(
        "resume source artifact inventory did not stabilize across "
        "the final two observations"
    )
artifacts = observations[-1]["artifacts"]
assert isinstance(artifacts, list)

prefix = f"full-extraction-next-manifest-{os.environ['CHAIN_ID']}-"
run_marker = f"-run-{source_run_id}-attempt-"
canonical_name = f"full-extraction-manifest-{os.environ['CHAIN_ID']}"
pattern = re.compile(
    (
        rf"^{re.escape(prefix)}iter-[1-9][0-9]*-"
        rf"run-{re.escape(source_run_id)}-"
        r"attempt-(?P<attempt>[1-9][0-9]*)$"
    )
)
matches_by_attempt: dict[int, list[dict[str, object]]] = {}
canonical_matches: list[dict[str, object]] = []
for artifact in artifacts:
    assert isinstance(artifact, dict)
    artifact_name = str(artifact.get("name") or "")
    if artifact_name == canonical_name and artifact.get("expired") is not True:
        canonical_matches.append(artifact)
        continue
    match = pattern.fullmatch(artifact_name)
    if match is not None:
        attempt = int(match.group("attempt"))
        if attempt > run_attempt:
            raise SystemExit(
                "resume source committed-manifest attempt exceeds "
                "the owner run attempt"
            )
        matches_by_attempt.setdefault(attempt, []).append(artifact)
    elif artifact_name.startswith(prefix) and run_marker in artifact_name:
        raise SystemExit(
            "resume source committed-manifest artifact name is malformed"
        )
if len(canonical_matches) > 1:
    raise SystemExit(
        "resume source has ambiguous canonical manifest artifacts"
    )
duplicate_attempts = sorted(
    attempt
    for attempt, matches in matches_by_attempt.items()
    if len(matches) != 1
)
if duplicate_attempts:
    raise SystemExit(
        "resume source has ambiguous immutable committed next-manifest "
        f"artifacts for attempt {duplicate_attempts[0]}"
    )

if matches_by_attempt:
    selected_attempt = max(matches_by_attempt)
    artifact = matches_by_attempt[selected_attempt][0]
    resolution = "committed"
elif len(canonical_matches) == 1:
    selected_attempt = run_attempt
    artifact = canonical_matches[0]
    resolution = "canonical"
else:
    raise SystemExit(
        "resume source run has no exact committed or canonical manifest artifact"
    )

artifact_id = artifact.get("id")
artifact_name = str(artifact.get("name") or "")
artifact_digest = str(artifact.get("digest") or "").lower()
artifact_size = artifact.get("size_in_bytes")
if artifact.get("expired") is not False:
    raise SystemExit(
        "resume source committed-manifest artifact provenance is invalid"
    )
direct_artifact = normalized_artifact(
    gh_json(
        [
            "--method",
            "GET",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2026-03-10",
            f"/repos/{repository}/actions/artifacts/{artifact_id}",
        ]
    )
)
if direct_artifact != artifact:
    raise SystemExit(
        "selected resume source manifest changed before exact-ID download"
    )
final_owner_run = gh_json(
    [
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        f"/repos/{repository}/actions/runs/{source_run_id}",
    ]
)
if final_owner_run != owner_run:
    raise SystemExit(
        "resume source owner run changed after exact artifact selection"
    )
with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as handle:
    handle.write(f"resolution={resolution}\n")
    handle.write(f"artifact_name={artifact_name}\n")
    handle.write(f"artifact_id={artifact_id}\n")
    handle.write(f"artifact_digest={artifact_digest}\n")
    handle.write(f"artifact_size_bytes={artifact_size}\n")
    handle.write(
        f"artifact_archive_url={artifact['archive_download_url']}\n"
    )
    handle.write(f"source_run_id={source_run_id}\n")
    handle.write(f"source_run_head_sha={owner_head_sha}\n")
    handle.write(f"source_run_attempt={run_attempt}\n")
    handle.write(f"source_run_status={owner_run['status']}\n")
    handle.write(f"source_run_conclusion={owner_run['conclusion']}\n")
    handle.write(f"source_workflow_id={workflow_id}\n")
PY

"""

BUILD_LANE_MANIFEST_SCRIPT: Final = r"""mkdir -p artifacts/full-extraction
effective_matrix_batch_size="$MATRIX_BATCH_SIZE"
echo "::notice::Planning under exact operation authority recorded at $OPERATION_AUTHORITY_PATH"
args=(
  plan
  --operation-authority-path "$OPERATION_AUTHORITY_PATH"
  --chain-id "$CHAIN_ID"
  --workflow-source-sha "$WORKFLOW_SOURCE_SHA"
  --iteration "$ITERATION"
  --max-matrix-lanes "$effective_matrix_batch_size"
  --vpn-slot-count "$VPN_PARALLELISM"
  --output-path artifacts/full-extraction/manifest.json
)
if [ -n "$INPUT_LANE_MANIFEST_JSON" ]; then
  manifest_chars="$(python - <<'PY'
import os
print(len(os.environ.get("INPUT_LANE_MANIFEST_JSON", "")))
PY
)"
  if [ "$manifest_chars" -gt 60000 ]; then
    echo "::error::lane_manifest_json is ${manifest_chars} chars; use lane_manifest_run_id/lane_manifest_artifact_name artifact handoff"
    exit 1
  fi
  args+=(--lane-manifest-json "$INPUT_LANE_MANIFEST_JSON")
elif [ -n "$LANE_MANIFEST_RUN_ID" ] || [ -n "$LANE_MANIFEST_ARTIFACT_NAME" ]; then
  if [ -z "$LANE_MANIFEST_RUN_ID" ] || [ -z "$LANE_MANIFEST_ARTIFACT_NAME" ]; then
    echo "::error::lane_manifest_run_id and lane_manifest_artifact_name must be provided together"
    exit 1
  fi
  if [ -z "$REQUESTED_CHAIN_ID" ]; then
    echo "::error::lane_manifest_run_id requires chain_id so workflow concurrency and discovery artifacts retain the original chain identity"
    exit 1
  fi
  mkdir -p "$RUNNER_TEMP/lane-manifest-input"
  if [ -z "$LANE_MANIFEST_ARTIFACT_ID" ] && [ -z "$LANE_MANIFEST_ARTIFACT_DIGEST" ]; then
    echo "::warning::Using bounded legacy run/name manifest handoff without an immutable receipt"
    mkdir -p "$RUNNER_TEMP/workflow-provenance"
    python .github/scripts/workflow_source_provenance.py attest-run \
      --repository "$GITHUB_REPOSITORY" \
      --run-id "$LANE_MANIFEST_RUN_ID" \
      --source-sha "$WORKFLOW_SOURCE_SHA" \
      --trusted-branch "$WORKFLOW_SOURCE_REF" \
      --workflow-path .github/workflows/full-extraction.yml \
      --required-state active-or-completed \
      --output "$RUNNER_TEMP/workflow-provenance/legacy-manifest-owner.json"
    legacy_receipt="$RUNNER_TEMP/lane-manifest-input/legacy-receipt.json"
    LEGACY_RECEIPT_PATH="$legacy_receipt" \
      OWNER_ATTESTATION_PATH="$RUNNER_TEMP/workflow-provenance/legacy-manifest-owner.json" \
      python .github/scripts/resolve_legacy_manifest_handoff.py resolve
    legacy_artifact_id="$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["id"])' "$legacy_receipt")"
    legacy_archive="$RUNNER_TEMP/lane-manifest-input/legacy-manifest.zip"
    gh api \
      --method GET \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2026-03-10" \
      "/repos/${GITHUB_REPOSITORY}/actions/artifacts/${legacy_artifact_id}/zip" \
      > "$legacy_archive"
    LEGACY_ARCHIVE_PATH="$legacy_archive" \
      LEGACY_RECEIPT_PATH="$legacy_receipt" \
      LEGACY_OUTPUT_DIR="$RUNNER_TEMP/lane-manifest-input" \
      python .github/scripts/resolve_legacy_manifest_handoff.py extract
  elif [ -z "$LANE_MANIFEST_ARTIFACT_ID" ] || [ -z "$LANE_MANIFEST_ARTIFACT_DIGEST" ]; then
    echo "::error::lane_manifest_artifact_id and lane_manifest_artifact_digest must be provided together"
    exit 1
  fi
  mapfile -t manifest_candidates < <(
    find "$RUNNER_TEMP/lane-manifest-input" \
      \( -name next-manifest.json -o -name manifest.json \) \
      -type f -print
  )
  if [ "${#manifest_candidates[@]}" -ne 1 ] || [ -L "${manifest_candidates[0]:-}" ]; then
    echo "::error::Manifest artifact $LANE_MANIFEST_ARTIFACT_NAME from run $LANE_MANIFEST_RUN_ID must contain exactly one regular manifest.json or next-manifest.json"
    find "$RUNNER_TEMP/lane-manifest-input" -maxdepth 4 -type f -print || true
    exit 1
  fi
  manifest_path="${manifest_candidates[0]}"
  MANIFEST_PATH="$manifest_path" \
    ARTIFACT_NAME="$LANE_MANIFEST_ARTIFACT_NAME" \
    REQUESTED_CHAIN_ID="$REQUESTED_CHAIN_ID" \
    python - <<'PY'
# MANUAL_HANDOFF_CHAIN_VERIFIER
import json
import os
import re
from pathlib import Path

manifest = json.loads(
    Path(os.environ["MANIFEST_PATH"]).read_text(encoding="utf-8")
)
requested = os.environ["REQUESTED_CHAIN_ID"]
expected_source_sha = os.environ["WORKFLOW_SOURCE_SHA"].lower()
artifact_name = os.environ["ARTIFACT_NAME"]
chain_state = manifest.get("chain_state", {})
manifest_ids = {
    str(value).strip()
    for value in (
        manifest.get("chain_id"),
        chain_state.get("chain_id") if isinstance(chain_state, dict) else None,
    )
    if str(value or "").strip()
}
mismatched_ids = sorted(value for value in manifest_ids if value != requested)
if mismatched_ids:
    print(
        "::error::Manifest chain identity does not match requested chain_id "
        f"{requested!r}: {mismatched_ids}"
    )
    raise SystemExit(1)

manifest_source_sha = str(manifest.get("workflow_source_sha") or "").lower()
if manifest_source_sha != expected_source_sha:
    print(
        "::error::Manifest source SHA does not match the pinned workflow source "
        f"{expected_source_sha!r}: {manifest_source_sha or '<missing>'!r}"
    )
    raise SystemExit(1)

initial_name = f"full-extraction-manifest-{requested}"
legacy_chained_name = re.fullmatch(
    rf"full-extraction-next-manifest-{re.escape(requested)}-iter-[1-9][0-9]*",
    artifact_name,
)
receipt_chained_name = re.fullmatch(
    (
        rf"full-extraction-next-manifest-{re.escape(requested)}-"
        r"iter-[1-9][0-9]*-run-[1-9][0-9]*-attempt-[1-9][0-9]*"
    ),
    artifact_name,
)
chained_name = legacy_chained_name or receipt_chained_name
standard_name = artifact_name.startswith(
    ("full-extraction-manifest-", "full-extraction-next-manifest-")
)
if standard_name and artifact_name != initial_name and chained_name is None:
    print(
        "::error::Manifest artifact name does not match requested chain_id "
        f"{requested!r}: {artifact_name!r}"
    )
    raise SystemExit(1)
if not manifest_ids and artifact_name != initial_name and chained_name is None:
    print(
        "::error::Unable to verify original chain identity from the manifest "
        f"or artifact name {artifact_name!r}"
    )
    raise SystemExit(1)
print(f"Verified manual manifest handoff for chain {requested}")
PY
  cp "$manifest_path" artifacts/full-extraction/input-manifest.json
  args+=(--lane-manifest-path artifacts/full-extraction/input-manifest.json)
elif [ -n "$RESUME_SOURCE_RUN_ID" ]; then
  if [ -z "$REQUESTED_CHAIN_ID" ]; then
    echo "::error::resume_source_run_id requires chain_id so source artifacts can be resolved; use the original chain id, usually the source run id"
    exit 1
  fi
  mkdir -p "$RUNNER_TEMP/resume-source/metadata"
  source_manifest="$RUNNER_TEMP/resume-source/resolved-manifest.json"
  if [ ! -f "$source_manifest" ]; then
    echo "::error::Verified resume source manifest is unavailable"
    exit 1
  fi
  metadata_receipts="$RUNNER_TEMP/resume-source/metadata-artifact-receipts.json"
  python .github/scripts/workflow_source_provenance.py \
    resolve-artifacts-by-prefix \
    --attestation "$RUNNER_TEMP/workflow-provenance/resume-source-owner-recheck.json" \
    --artifact-name-prefix "extraction-lane-metadata-${CHAIN_ID}-" \
    --poll-interval-seconds 0 \
    --output "$metadata_receipts"
  metadata_download="$RUNNER_TEMP/resume-source/metadata-download.json"
  python .github/scripts/workflow_source_provenance.py download-artifact-bundle \
    --attestation "$RUNNER_TEMP/workflow-provenance/resume-source-owner-recheck.json" \
    --receipt-bundle "$metadata_receipts" \
    --output-dir "$RUNNER_TEMP/resume-source/metadata" \
    --output "$metadata_download"
  metadata_count="$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["downloaded_count"])' "$metadata_download")"
  if [ "$metadata_count" = "0" ]; then
    echo "::notice::Resume source run $RESUME_SOURCE_RUN_ID has no lane metadata artifacts; recovery will re-plan from the manifest"
  fi
  resume_args=(
    resume
    --operation-authority-path "$OPERATION_AUTHORITY_PATH"
    --lane-manifest-path "$source_manifest"
    --metadata-dir "$RUNNER_TEMP/resume-source/metadata"
    --completed-artifact-run-id "$RESUME_SOURCE_RUN_ID"
    --chunk-profile "$CHUNK_PROFILE"
    --iteration "$ITERATION"
    --max-matrix-lanes "$effective_matrix_batch_size"
    --vpn-slot-count "$VPN_PARALLELISM"
    --allow-missing-attempted-metadata
    --output-path artifacts/full-extraction/resume-source-manifest.json
  )
  if [ "$RETRY_PIPELINE_FAILURES" = "true" ]; then
    resume_args+=(--allow-pipeline-failures)
  fi
  uv run python -m nbadb.orchestrate.full_extraction_control "${resume_args[@]}" \
    > artifacts/full-extraction/resume-source-manifest.stdout.json
  uv run python -m nbadb.orchestrate.full_extraction_control audit \
    --metadata-dir "$RUNNER_TEMP/resume-source/metadata" \
    --output-path artifacts/full-extraction/resume-source-audit.json \
    > artifacts/full-extraction/resume-source-audit.stdout.json
  args+=(--lane-manifest-path artifacts/full-extraction/resume-source-manifest.json)
else
  args+=(--support-matrix-path artifacts/endpoint-coverage/endpoint-support-matrix.json)
  if [ -z "$ASSURANCE_ADMISSION_PATH" ] || \
     [ ! -f "$ASSURANCE_ADMISSION_PATH" ] || \
     [ -L "$ASSURANCE_ADMISSION_PATH" ]; then
    echo "::error::Fresh planning requires the exact regular assurance admission member"
    exit 1
  fi
  args+=(--assurance-admission-path "$ASSURANCE_ADMISSION_PATH")
  args+=(--chunk-profile "$CHUNK_PROFILE")
fi
[ -n "$BACKFILL_PATTERNS" ]  && args+=(--backfill-patterns "$BACKFILL_PATTERNS")
[ -n "$BACKFILL_ENDPOINTS" ] && args+=(--backfill-endpoints "$BACKFILL_ENDPOINTS")

uv run python -m nbadb.orchestrate.full_extraction_control "${args[@]}" > artifacts/full-extraction/manifest.stdout.json

if [ -n "$RESUME_SOURCE_RUN_ID" ]; then
  SOURCE_MANIFEST_PATH=artifacts/full-extraction/resume-source-input-manifest.json \
    RESUME_MANIFEST_PATH=artifacts/full-extraction/resume-source-manifest.json \
    RESUME_AUDIT_PATH=artifacts/full-extraction/resume-source-audit.json \
    FINAL_MANIFEST_PATH=artifacts/full-extraction/manifest.json \
    uv run python - <<'PY'
# RESUME_SOURCE_PENDING_CONTRACT_BLOCKED_EVIDENCE
import json
import os
from pathlib import Path

from nbadb.orchestrate.full_extraction_control import (
    _canonical_contract_blocked_audit_row,
    _hash_payload,
)

def canonical_rows(
    raw_rows: object,
    *,
    label: str,
) -> list[dict[str, object]]:
    if not isinstance(raw_rows, list):
        raise SystemExit(f"{label} blocked evidence must be a list")
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict):
            raise SystemExit(f"{label} blocked evidence rows must be objects")
        lane_id = str(raw_row.get("lane_id") or "").strip()
        if not lane_id or lane_id in seen:
            raise SystemExit(f"{label} blocked lane IDs must be unique")
        canonical_input = dict(raw_row)
        canonical_input["lane_kind"] = raw_row.get("kind")
        try:
            row = _canonical_contract_blocked_audit_row(
                lane_id,
                canonical_input,
            )
        except ValueError as exc:
            raise SystemExit(
                f"{label} blocked evidence is invalid for {lane_id}: {exc}"
            ) from exc
        if _hash_payload(row) != _hash_payload(raw_row):
            raise SystemExit(
                f"{label} blocked evidence is not canonical for {lane_id}"
            )
        seen.add(lane_id)
        rows.append(row)
    return sorted(rows, key=lambda row: str(row["lane_id"]))

def bundle(rows: list[dict[str, object]]) -> dict[str, object]:
    return {"schema_version": 1, "contract_blocked_lanes": rows}

source_manifest = json.loads(
    Path(os.environ["SOURCE_MANIFEST_PATH"]).read_text(encoding="utf-8")
)
resume_manifest = json.loads(
    Path(os.environ["RESUME_MANIFEST_PATH"]).read_text(encoding="utf-8")
)
audit = json.loads(
    Path(os.environ["RESUME_AUDIT_PATH"]).read_text(encoding="utf-8")
)
final_path = Path(os.environ["FINAL_MANIFEST_PATH"])
final_manifest = json.loads(final_path.read_text(encoding="utf-8"))
if not all(
    isinstance(value, dict)
    for value in (source_manifest, resume_manifest, audit, final_manifest)
):
    raise SystemExit("resume source pending-evidence inputs must be objects")

raw_source_lanes = source_manifest.get("lanes")
if not isinstance(raw_source_lanes, list):
    raise SystemExit("resume source manifest lanes must be a list")
source_lanes: dict[str, dict[str, object]] = {}
for lane in raw_source_lanes:
    if not isinstance(lane, dict):
        raise SystemExit("resume source manifest lanes must be objects")
    lane_id = str(lane.get("lane_id") or "").strip()
    if not lane_id or lane_id in source_lanes:
        raise SystemExit("resume source manifest lane IDs must be unique")
    source_lanes[lane_id] = lane

scope_fields = (
    ("kind", "lane_kind"),
    ("endpoints", "endpoints"),
    ("patterns", "patterns"),
    ("season_start", "season_start"),
    ("season_end", "season_end"),
    ("season_types", "season_types"),
    ("context_measures", "context_measures"),
    ("coverage_units_hash", "coverage_units_hash"),
)

def require_source_scope(row: dict[str, object], *, label: str) -> None:
    lane_id = str(row["lane_id"])
    lane = source_lanes.get(lane_id)
    if lane is None:
        raise SystemExit(f"{label} blocked evidence is outside source manifest: {lane_id}")
    for row_field, lane_field in scope_fields:
        if row.get(row_field) != lane.get(lane_field):
            raise SystemExit(
                f"{label} blocked evidence scope does not match source manifest "
                f"for {lane_id}: {row_field}"
            )

audit_rows = canonical_rows(
    audit.get("contract_blocked_lanes", []),
    label="resume source audit",
)
pending_by_id: dict[str, dict[str, object]] = {}
for lane_id, lane in source_lanes.items():
    canonical_input = dict(lane)
    canonical_input["lane_kind"] = lane.get("lane_kind")
    try:
        row = _canonical_contract_blocked_audit_row(
            lane_id,
            canonical_input,
        )
    except ValueError:
        continue
    require_source_scope(row, label="derived resume source")
    pending_by_id[lane_id] = row
for row in audit_rows:
    require_source_scope(row, label="resume source audit")
    lane_id = str(row["lane_id"])
    prior = pending_by_id.get(lane_id)
    if prior is not None and _hash_payload(prior) != _hash_payload(row):
        raise SystemExit(f"resume source blocked evidence changed for {lane_id}")
    pending_by_id[lane_id] = row

resume_summary = resume_manifest.get("resume_summary")
if not isinstance(resume_summary, dict):
    raise SystemExit("resume source manifest lacks resume_summary")
expected_count = int(resume_summary.get("contract_blocked_lane_count", -1))
if expected_count != len(pending_by_id):
    raise SystemExit(
        "resume source contract-blocked count does not match validated evidence"
    )

chain_state = final_manifest.get("chain_state")
if not isinstance(chain_state, dict):
    raise SystemExit("final resume source manifest chain_state must be an object")
committed_rows = canonical_rows(
    chain_state.get("contract_blocked_evidence", []),
    label="resume source committed chain-state",
)
committed_digest = str(
    chain_state.get("contract_blocked_evidence_sha256") or ""
)
if committed_rows or committed_digest:
    if _hash_payload(bundle(committed_rows)) != committed_digest:
        raise SystemExit(
            "resume source committed blocked evidence digest does not match"
        )
committed_by_id = {str(row["lane_id"]): row for row in committed_rows}
existing_pending_rows = canonical_rows(
    chain_state.get("pending_contract_blocked_evidence", []),
    label="resume source existing pending chain-state",
)
existing_pending_digest = str(
    chain_state.get("pending_contract_blocked_evidence_sha256") or ""
)
if existing_pending_rows:
    if _hash_payload(bundle(existing_pending_rows)) != existing_pending_digest:
        raise SystemExit(
            "resume source existing pending blocked evidence digest does not match"
        )
elif existing_pending_digest:
    raise SystemExit(
        "resume source existing pending blocked evidence digest has no rows"
    )
combined_pending_by_id = {
    str(row["lane_id"]): row for row in existing_pending_rows
}
for lane_id, row in pending_by_id.items():
    existing = combined_pending_by_id.get(lane_id)
    if existing is not None and _hash_payload(existing) != _hash_payload(row):
        raise SystemExit(
            f"resume source pending blocked evidence changed for {lane_id}"
        )
    combined_pending_by_id[lane_id] = row
pending_rows: list[dict[str, object]] = []
for lane_id in sorted(combined_pending_by_id):
    row = combined_pending_by_id[lane_id]
    committed = committed_by_id.get(lane_id)
    if committed is not None:
        if _hash_payload(committed) != _hash_payload(row):
            raise SystemExit(
                f"resume source blocked evidence conflicts with ancestry for {lane_id}"
            )
        continue
    pending_rows.append(row)

pending_bundle = bundle(pending_rows)
chain_state["pending_contract_blocked_evidence"] = pending_rows
chain_state["pending_contract_blocked_evidence_sha256"] = (
    _hash_payload(pending_bundle) if pending_rows else ""
)
final_path.write_text(
    json.dumps(final_manifest, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
fi

"""

RESOLVE_PRIOR_DISCOVERY_ARTIFACT_RECEIPT_SCRIPT: Final = r"""mkdir -p "$RUNNER_TEMP/workflow-provenance"
python .github/scripts/workflow_source_provenance.py attest-run \
  --repository "$GITHUB_REPOSITORY" \
  --run-id "$MANIFEST_SOURCE_RUN_ID" \
  --source-sha "$WORKFLOW_SOURCE_SHA" \
  --trusted-branch "$WORKFLOW_SOURCE_REF" \
  --workflow-path .github/workflows/full-extraction.yml \
  --required-state completed \
  --output "$RUNNER_TEMP/workflow-provenance/discovery-source-owner.json"
python .github/scripts/workflow_source_provenance.py recheck-run \
  --attestation "$RUNNER_TEMP/workflow-provenance/discovery-source-owner.json" \
  --required-state completed \
  --output "$RUNNER_TEMP/workflow-provenance/discovery-source-owner-recheck.json"
OWNER_RECHECK_PATH="$RUNNER_TEMP/workflow-provenance/discovery-source-owner-recheck.json" python - <<'PY'
# DISCOVERY_ARTIFACT_RECEIPT_RESOLVER
import json
import os
import re
import subprocess
import time
from pathlib import Path

def gh_json(arguments: list[str]) -> object:
    raw = subprocess.check_output(["gh", "api", *arguments], text=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"GitHub discovery receipt response is not valid JSON: {exc}"
        ) from exc

def normalized_artifact(
    artifact: object,
    *,
    repository: str,
) -> dict[str, object]:
    if not isinstance(artifact, dict):
        raise SystemExit(
            "discovery artifact inventory entries must be objects"
        )
    artifact_id = artifact.get("id")
    name = artifact.get("name")
    digest = str(artifact.get("digest") or "").lower()
    size = artifact.get("size_in_bytes")
    expired = artifact.get("expired")
    workflow_run = artifact.get("workflow_run")
    if (
        isinstance(artifact_id, bool)
        or not isinstance(artifact_id, int)
        or artifact_id < 1
        or not isinstance(name, str)
        or not name
        or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or not isinstance(expired, bool)
        or not isinstance(workflow_run, dict)
    ):
        raise SystemExit("discovery artifact inventory entry is malformed")
    workflow_run_id = workflow_run.get("id")
    workflow_head_sha = str(workflow_run.get("head_sha") or "").lower()
    expected_archive_url = (
        f"{os.environ['GITHUB_API_URL'].rstrip('/')}/repos/{repository}/"
        f"actions/artifacts/{artifact_id}/zip"
    )
    if (
        isinstance(workflow_run_id, bool)
        or not isinstance(workflow_run_id, int)
        or workflow_run_id < 1
        or re.fullmatch(r"[0-9a-f]{40}", workflow_head_sha) is None
        or artifact.get("archive_download_url") != expected_archive_url
    ):
        raise SystemExit(
            "discovery artifact REST identity is malformed"
        )
    return {
        "archive_download_url": expected_archive_url,
        "digest": digest,
        "expired": expired,
        "id": artifact_id,
        "name": name,
        "size_in_bytes": size,
        "workflow_run": {
            "head_sha": workflow_head_sha,
            "id": workflow_run_id,
        },
    }

def artifact_inventory_snapshot(
    *,
    repository: str,
    source_run_id: str,
) -> dict[str, object]:
    pages = gh_json(
        [
            "--method",
            "GET",
            "--paginate",
            "--slurp",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2026-03-10",
            f"/repos/{repository}/actions/runs/{source_run_id}/artifacts",
            "-f",
            "per_page=100",
        ]
    )
    if not isinstance(pages, list) or not pages:
        raise SystemExit(
            "discovery artifact inventory must contain pages"
        )

    artifacts: list[dict[str, object]] = []
    expected_total: int | None = None
    artifact_ids: set[int] = set()
    for page in pages:
        if not isinstance(page, dict):
            raise SystemExit(
                "discovery artifact inventory pages must be objects"
            )
        total_count = page.get("total_count")
        entries = page.get("artifacts")
        if (
            isinstance(total_count, bool)
            or not isinstance(total_count, int)
            or total_count < 0
            or not isinstance(entries, list)
        ):
            raise SystemExit(
                "discovery artifact inventory page is malformed"
            )
        if expected_total is None:
            expected_total = total_count
        elif expected_total != total_count:
            raise SystemExit(
                "discovery artifact inventory total changed during pagination"
            )
        for entry in entries:
            artifact = normalized_artifact(
                entry,
                repository=repository,
            )
            artifact_id = int(artifact["id"])
            if artifact_id in artifact_ids:
                raise SystemExit(
                    "discovery artifact inventory repeated an artifact ID"
                )
            artifact_ids.add(artifact_id)
            artifacts.append(artifact)
    if expected_total != len(artifacts):
        raise SystemExit(
            "discovery artifact inventory count does not match total_count"
        )
    return {
        "artifacts": sorted(
            artifacts,
            key=lambda artifact: int(artifact["id"]),
        ),
        "total_count": expected_total,
    }

source_run_id = os.environ["MANIFEST_SOURCE_RUN_ID"].strip()
current_run_id = os.environ["CURRENT_RUN_ID"].strip()
repository = os.environ["GITHUB_REPOSITORY"].strip()
workflow_source_sha = os.environ["WORKFLOW_SOURCE_SHA"].strip().lower()
if re.fullmatch(r"[1-9][0-9]*", source_run_id) is None:
    raise SystemExit("discovery source run ID must be a positive integer")
if re.fullmatch(r"[1-9][0-9]*", current_run_id) is None:
    raise SystemExit("current workflow run ID must be a positive integer")
if source_run_id == current_run_id:
    raise SystemExit(
        "discovery recovery requires a distinct source workflow run; "
        "prior attempts of the current run are not a recovery boundary"
    )
if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
    raise SystemExit("GitHub repository identity is invalid")
if re.fullmatch(r"[0-9a-f]{40}", workflow_source_sha) is None:
    raise SystemExit("pinned workflow source SHA is invalid")

owner_snapshot = json.loads(
    Path(os.environ["OWNER_RECHECK_PATH"]).read_text(encoding="utf-8")
)
owner_claim = (
    owner_snapshot.get("run")
    if isinstance(owner_snapshot, dict)
    else None
)
semantic_source = (
    owner_snapshot.get("semantic_source")
    if isinstance(owner_snapshot, dict)
    else None
)
workflow_claim = (
    owner_snapshot.get("workflow")
    if isinstance(owner_snapshot, dict)
    else None
)
expected_run_url = (
    f"{os.environ['GITHUB_API_URL'].rstrip('/')}/repos/{repository}"
    f"/actions/runs/{source_run_id}"
)
if (
    not isinstance(owner_snapshot, dict)
    or type(owner_snapshot.get("schema_version")) is not int
    or owner_snapshot.get("schema_version") != 1
    or owner_snapshot.get("repository") != repository
    or not isinstance(owner_claim, dict)
    or type(owner_claim.get("id")) is not int
    or owner_claim.get("id") != int(source_run_id)
    or owner_claim.get("url") != expected_run_url
    or owner_claim.get("event") != "workflow_dispatch"
    or not isinstance(owner_claim.get("head_branch"), str)
    or not owner_claim.get("head_branch")
    or re.fullmatch(
        r"[0-9a-f]{40}",
        str(owner_claim.get("head_sha") or "").lower(),
    )
    is None
    or owner_claim.get("path")
    != ".github/workflows/full-extraction.yml"
    or type(owner_claim.get("attempt")) is not int
    or owner_claim.get("attempt") != 1
    or type(owner_claim.get("workflow_id")) is not int
    or owner_claim.get("workflow_id") < 1
    or owner_claim.get("status") != "completed"
    or owner_claim.get("conclusion")
    not in {"cancelled", "failure", "success", "timed_out"}
    or not isinstance(semantic_source, dict)
    or str(semantic_source.get("sha") or "").lower()
    != workflow_source_sha
    or semantic_source.get("relation")
    not in {"identical", "ancestor"}
    or (semantic_source.get("relation") == "identical")
    != (
        str(semantic_source.get("sha") or "").lower()
        == str(owner_claim.get("head_sha") or "").lower()
    )
    or not isinstance(workflow_claim, dict)
    or workflow_claim.get("path")
    != ".github/workflows/full-extraction.yml"
    or re.fullmatch(
        r"[0-9a-f]{40}",
        str(workflow_claim.get("blob_sha") or "").lower(),
    )
    is None
    or re.fullmatch(
        r"[0-9a-f]{64}",
        str(workflow_claim.get("sha256") or "").lower(),
    )
    is None
    or type(workflow_claim.get("size_in_bytes")) is not int
    or workflow_claim.get("size_in_bytes") < 1
):
    raise SystemExit("discovery source owner recheck snapshot is invalid")

owner_run = gh_json(
    [
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        f"/repos/{repository}/actions/runs/{source_run_id}",
    ]
)
if not isinstance(owner_run, dict):
    raise SystemExit("discovery source workflow run must be an object")
source_attempt = owner_run.get("run_attempt")
owner_head_sha = str(owner_run.get("head_sha") or "").lower()
workflow_id = owner_run.get("workflow_id")
owner_repository = owner_run.get("repository")
if (
    type(owner_run.get("id")) is not int
    or str(owner_run.get("id")) != source_run_id
    or owner_run.get("url") != owner_claim.get("url")
    or not isinstance(owner_repository, dict)
    or owner_repository.get("full_name") != repository
    or type(source_attempt) is not int
    or source_attempt != owner_claim.get("attempt")
    or source_attempt != 1
    or owner_head_sha != str(owner_claim.get("head_sha") or "").lower()
    or owner_run.get("status") != owner_claim.get("status")
    or owner_run.get("conclusion") != owner_claim.get("conclusion")
    or owner_run.get("event") != owner_claim.get("event")
    or owner_run.get("head_branch") != owner_claim.get("head_branch")
    or owner_run.get("path") != owner_claim.get("path")
    or type(workflow_id) is not int
    or workflow_id != owner_claim.get("workflow_id")
):
    raise SystemExit(
        "discovery source owner run changed after provenance recheck"
    )

raw_interval = (
    os.environ.get("DISCOVERY_RECEIPT_POLL_INTERVAL_SECONDS", "").strip()
    or "2"
)
try:
    poll_interval = float(raw_interval)
except ValueError as exc:
    raise SystemExit(
        "discovery receipt poll interval must be numeric"
    ) from exc
if poll_interval < 0 or poll_interval > 30:
    raise SystemExit(
        "discovery receipt poll interval must be between 0 and 30 seconds"
    )
observations: list[dict[str, object]] = []
for observation_index in range(3):
    observations.append(
        artifact_inventory_snapshot(
            repository=repository,
            source_run_id=source_run_id,
        )
    )
    if observation_index < 2 and poll_interval:
        time.sleep(poll_interval)
if observations[-2] != observations[-1]:
    raise SystemExit(
        "discovery artifact inventory did not stabilize across "
        "the final two observations"
    )
artifacts = observations[-1]["artifacts"]
assert isinstance(artifacts, list)

canonical_name = os.environ["DISCOVERY_ARTIFACT_NAME"]
recovery_prefix = os.environ["DISCOVERY_RECOVERY_PREFIX"]
recovery_name = (
    f"{recovery_prefix}-run-{source_run_id}-attempt-{source_attempt}"
)
source_recovery_prefix = f"{recovery_prefix}-run-{source_run_id}-attempt-"
canonical_matches: list[dict[str, object]] = []
recovery_matches: list[dict[str, object]] = []
for artifact in artifacts:
    artifact_name = artifact.get("name")
    if not isinstance(artifact_name, str) or not artifact_name:
        raise SystemExit("discovery artifact inventory name is invalid")
    if artifact_name == canonical_name:
        if artifact.get("expired") is not True:
            canonical_matches.append(artifact)
        continue
    if artifact_name.startswith(source_recovery_prefix):
        match = re.fullmatch(
            rf"{re.escape(source_recovery_prefix)}(?P<attempt>[1-9][0-9]*)",
            artifact_name,
        )
        if match is None:
            raise SystemExit(
                "source discovery recovery artifact name is malformed"
            )
        artifact_attempt = int(match.group("attempt"))
        if artifact_attempt > source_attempt:
            raise SystemExit(
                "source discovery recovery artifact attempt exceeds "
                "the workflow run attempt"
            )
        if artifact_name == recovery_name and artifact.get("expired") is not True:
            recovery_matches.append(artifact)

if len(canonical_matches) > 1:
    raise SystemExit(
        "discovery source has ambiguous unexpired canonical artifacts"
    )
if len(recovery_matches) > 1:
    raise SystemExit(
        "discovery source has ambiguous unexpired current-attempt recovery artifacts"
    )
if canonical_matches:
    selected = canonical_matches[0]
    source_kind = "canonical"
    expected_name = canonical_name
elif recovery_matches:
    selected = recovery_matches[0]
    source_kind = "recovery"
    expected_name = recovery_name
else:
    raise SystemExit(
        "distinct discovery source run has no exact canonical or "
        "current-attempt recovery artifact"
    )

artifact_id = selected["id"]
artifact_digest = str(selected.get("digest") or "").lower()
workflow_run = selected.get("workflow_run")
if (
    selected.get("name") != expected_name
    or selected.get("expired") is not False
    or not isinstance(workflow_run, dict)
    or str(workflow_run.get("id") or "") != source_run_id
    or str(workflow_run.get("head_sha") or "").lower()
    != owner_head_sha
):
    raise SystemExit(
        "discovery artifact REST identity does not match its source run"
    )

direct_artifact = normalized_artifact(
    gh_json(
        [
            "--method",
            "GET",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2026-03-10",
            f"/repos/{repository}/actions/artifacts/{artifact_id}",
        ]
    ),
    repository=repository,
)
if direct_artifact != selected:
    raise SystemExit(
        "selected discovery artifact changed before exact-ID download"
    )
final_owner_run = gh_json(
    [
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        f"/repos/{repository}/actions/runs/{source_run_id}",
    ]
)
if final_owner_run != owner_run:
    raise SystemExit(
        "discovery source owner run changed after exact artifact selection"
    )

with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as handle:
    handle.write(f"artifact_id={artifact_id}\n")
    handle.write(f"artifact_name={expected_name}\n")
    handle.write(f"artifact_digest={artifact_digest}\n")
    handle.write(f"source_kind={source_kind}\n")
    handle.write(f"source_run_id={source_run_id}\n")
print(
    f"Resolved exact {source_kind} discovery artifact {artifact_id} "
    f"from source run {source_run_id}"
)
PY

"""

RESOLVE_EXACT_SOURCE_CHECKPOINT_RECEIPT_SCRIPT: Final = r"""set -euo pipefail
if ! [[ "$SOURCE_RUN_ID" =~ ^[1-9][0-9]*$ ]]; then
  echo "::error::resume_source_run_id must be a numeric run ID"
  exit 1
fi
if ! [[ "$SOURCE_RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]]; then
  echo "::error::resume_source_run_attempt must be positive"
  exit 1
fi
mapfile -t plan_manifests < <(find plan-artifact -name resume-source-input-manifest.json -type f -print)
if [ "${#plan_manifests[@]}" -ne 1 ]; then
  echo "::error::zero-active replay requires exactly one source manifest"
  exit 1
fi

PLAN_MANIFEST_PATH="${plan_manifests[0]}" python - <<'PY'
# TERMINAL_REPLAY_ARTIFACT_RESOLVER
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
W2_RELATIONS = (
    "raw_nba_api_live_lossless_node",
    "raw_nba_api_result_cell",
    "raw_nba_api_route_field_landing",
    "raw_nba_api_stats_lossless_record",
    "raw_nba_api_value_representation",
    "raw_nba_api_w2_operation",
)
def canonical_sha256(payload: object) -> str:
    raw = json.dumps(
        payload, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(raw).hexdigest()
def require_exact_keys(
    payload: object, expected: set[str], label: str
) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != expected:
        raise SystemExit(f"{label} has a foreign field shape")
    return payload
def require_sha256(value: object, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise SystemExit(f"{label} is not SHA-256")
    return value
def require_count(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise SystemExit(f"{label} is not a count")
    return value
def validate_w2_authority(build: object) -> dict[str, object]:
    exact_build = require_exact_keys(
        build,
        {"database_sha256", "report_sha256", "w2_authority"},
        "checkpoint build",
    )
    authority = require_exact_keys(
        exact_build["w2_authority"],
        {
            "w2_database_authority",
            "w2_database_authority_sha256",
            "w2_expected_call_count",
            "w2_expected_call_inventory_sha256",
            "w2_database_authority_closed",
            "w2_authority_identity_sha256",
        },
        "checkpoint W2",
    )
    receipt = require_exact_keys(
        authority["w2_database_authority"],
        {
            "schema_version",
            "kind",
            "receipt_sha256",
            "w2_required_logical_call_count",
            "w2_source_call_admission_inventory_sha256",
            "raw_authority_v2_bundle_count",
            "raw_authority_v2_bundle_inventory_sha256",
            "raw_authority_v2_persistence_receipt_inventory_sha256",
            "w2_publication_receipt_count",
            "w2_publication_receipt_inventory_sha256",
            "w2_exact_six_schema_inventory_sha256",
            "w2_relation_row_counts",
            "w2_relation_row_count",
            "w2_relation_inventory_sha256",
        },
        "W2 receipt",
    )
    if (
        type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != 1
        or receipt["kind"]
        != "nbadb_w2_database_authority_receipt_v1"
    ):
        raise SystemExit("W2 receipt is foreign")
    for field_name, value in receipt.items():
        if field_name.endswith("_sha256"):
            require_sha256(value, field_name)
    required_count = require_count(
        receipt["w2_required_logical_call_count"],
        "w2_required_logical_call_count",
    )
    raw_bundle_count = require_count(
        receipt["raw_authority_v2_bundle_count"],
        "raw_authority_v2_bundle_count",
    )
    publication_count = require_count(
        receipt["w2_publication_receipt_count"],
        "w2_publication_receipt_count",
    )
    relation_count = require_count(
        receipt["w2_relation_row_count"],
        "w2_relation_row_count",
    )
    relation_rows = receipt["w2_relation_row_counts"]
    if type(relation_rows) is not list or len(relation_rows) != 6:
        raise SystemExit("W2 receipt lacks exact-six relations")
    names: list[str] = []
    row_counts: dict[str, int] = {}
    for row in relation_rows:
        exact_row = require_exact_keys(
            row,
            {"row_count", "table_name"},
            "W2 relation row",
        )
        table_name = exact_row["table_name"]
        if type(table_name) is not str:
            raise SystemExit("W2 relation name is invalid")
        names.append(table_name)
        row_counts[table_name] = require_count(
            exact_row["row_count"],
            "W2 relation row_count",
        )
    if tuple(names) != W2_RELATIONS or len(row_counts) != 6:
        raise SystemExit("W2 relation inventory is foreign")
    if (
        relation_count != sum(row_counts.values())
        or required_count != raw_bundle_count
        or required_count != publication_count
        or row_counts["raw_nba_api_w2_operation"]
        != publication_count
    ):
        raise SystemExit("W2 receipt algebra is invalid")
    receipt_sha256 = require_sha256(
        receipt["receipt_sha256"],
        "W2 receipt_sha256",
    )
    if canonical_sha256(
        {
            key: value
            for key, value in receipt.items()
            if key != "receipt_sha256"
        }
    ) != receipt_sha256:
        raise SystemExit("W2 receipt digest is invalid")
    expected_call_count = require_count(
        authority["w2_expected_call_count"],
        "w2_expected_call_count",
    )
    require_sha256(
        authority["w2_expected_call_inventory_sha256"],
        "w2_expected_call_inventory_sha256",
    )
    if (
        authority["w2_database_authority_sha256"] != receipt_sha256
        or expected_call_count != required_count
        or authority["w2_database_authority_closed"] is not True
    ):
        raise SystemExit("checkpoint W2 is not closed")
    identity_sha256 = require_sha256(
        authority["w2_authority_identity_sha256"],
        "w2_authority_identity_sha256",
    )
    if canonical_sha256(
        {
            key: value
            for key, value in authority.items()
            if key != "w2_authority_identity_sha256"
        }
    ) != identity_sha256:
        raise SystemExit("checkpoint W2 identity is invalid")
    return authority
manifest = json.loads(
    Path(os.environ["PLAN_MANIFEST_PATH"]).read_text(encoding="utf-8")
)
if not isinstance(manifest, dict):
    raise SystemExit("zero-active replay plan manifest must be an object")
chain_id = os.environ["CHAIN_ID"]
source_sha = os.environ["WORKFLOW_SOURCE_SHA"].lower()
source_run_id = os.environ["SOURCE_RUN_ID"]
state = manifest.get("chain_state")
if not isinstance(state, dict):
    raise SystemExit("zero-active replay plan chain_state must be an object")
if "latest_checkpoint_transaction" not in state:
    print(
        "::notice::No committed source checkpoint transaction exists; "
        "rebuilding from attested complete-lane artifacts"
    )
    raise SystemExit(0)
transaction = state["latest_checkpoint_transaction"]
if type(transaction) is not dict:
    raise SystemExit(
        "zero-active replay requires a committed checkpoint transaction"
    )
require_exact_keys(
    transaction,
    {
        "schema_version",
        "state",
        "identity",
        "artifact_name",
        "build",
        "receipt",
    },
    "committed checkpoint transaction",
)
if (
    type(transaction["schema_version"]) is not int
    or transaction["schema_version"] != 3
    or transaction["state"] != "committed"
):
    raise SystemExit(
        "zero-active replay requires a schema-v3 committed checkpoint transaction"
    )
identity = transaction.get("identity")
coverage = identity.get("coverage") if isinstance(identity, dict) else None
build = transaction.get("build")
receipt = transaction.get("receipt")
if (
    not isinstance(identity, dict)
    or not isinstance(coverage, dict)
    or not isinstance(build, dict)
    or not isinstance(receipt, dict)
):
    raise SystemExit("committed checkpoint transaction is incomplete")
require_exact_keys(
    identity,
    {"chain_id", "source_sha", "generation", "coverage"},
    "committed checkpoint identity",
)
require_exact_keys(
    coverage,
    {"coverage_fingerprint", "lane_inventory_sha256", "lanes"},
    "committed checkpoint coverage",
)
require_exact_keys(
    receipt,
    {
        "artifact_id",
        "artifact_run_id",
        "artifact_run_attempt",
        "artifact_name",
        "artifact_digest",
        "artifact_size_bytes",
        "database_sha256",
        "report_sha256",
        "chain_id",
        "source_sha",
        "generation",
        "coverage_fingerprint",
        "lane_inventory_sha256",
        "w2_authority_identity_sha256",
    },
    "committed checkpoint receipt",
)
w2_authority = validate_w2_authority(build)
generation = identity.get("generation")
coverage_fingerprint = str(
    coverage.get("coverage_fingerprint") or ""
).lower()
artifact_name = str(transaction.get("artifact_name") or "")
database_sha256 = str(build.get("database_sha256") or "").lower()
report_sha256 = str(build.get("report_sha256") or "").lower()
artifact_id = receipt.get("artifact_id")
artifact_run_id = receipt.get("artifact_run_id")
artifact_run_attempt = receipt.get("artifact_run_attempt")
artifact_digest = str(receipt.get("artifact_digest") or "").lower()
artifact_size = receipt.get("artifact_size_bytes")
expected_name = (
    f"full-extraction-checkpoint-{chain_id}-iter-{generation}"
)
if (
    str(identity.get("chain_id") or "") != chain_id
    or str(identity.get("source_sha") or "").lower() != source_sha
    or isinstance(generation, bool)
    or not isinstance(generation, int)
    or generation < 1
    or artifact_name != expected_name
    or re.fullmatch(r"[0-9a-f]{64}", coverage_fingerprint) is None
    or re.fullmatch(r"[0-9a-f]{64}", database_sha256) is None
    or re.fullmatch(r"[0-9a-f]{64}", report_sha256) is None
):
    raise SystemExit("committed checkpoint transaction identity is invalid")
lanes = coverage.get("lanes")
if not isinstance(lanes, list):
    raise SystemExit("committed checkpoint lane inventory must be a list")
canonical_lanes: list[dict[str, str]] = []
seen_lane_ids: set[str] = set()
for lane in lanes:
    if not isinstance(lane, dict) or set(lane) != {
        "lane_id",
        "coverage_units_hash",
    }:
        raise SystemExit("committed checkpoint lane inventory is malformed")
    lane_id = str(lane.get("lane_id") or "")
    lane_hash = str(lane.get("coverage_units_hash") or "").lower()
    if (
        not lane_id
        or lane_id in seen_lane_ids
        or re.fullmatch(r"[0-9a-f]{64}", lane_hash) is None
    ):
        raise SystemExit("committed checkpoint lane inventory is invalid")
    seen_lane_ids.add(lane_id)
    canonical_lanes.append(
        {"lane_id": lane_id, "coverage_units_hash": lane_hash}
    )
canonical_lanes.sort(key=lambda lane: lane["lane_id"])
lane_inventory_sha256 = hashlib.sha256(
    json.dumps(
        canonical_lanes,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()
if (
    str(coverage.get("lane_inventory_sha256") or "").lower()
    != lane_inventory_sha256
):
    raise SystemExit("committed checkpoint lane inventory digest is invalid")
if (
    isinstance(artifact_id, bool)
    or not isinstance(artifact_id, int)
    or artifact_id < 1
    or isinstance(artifact_run_id, bool)
    or not isinstance(artifact_run_id, int)
    or str(artifact_run_id) != source_run_id
    or isinstance(artifact_run_attempt, bool)
    or not isinstance(artifact_run_attempt, int)
    or str(artifact_run_attempt) != os.environ["SOURCE_RUN_ATTEMPT"]
    or re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest) is None
    or isinstance(artifact_size, bool)
    or not isinstance(artifact_size, int)
    or artifact_size < 1
    or str(receipt.get("artifact_name") or "") != artifact_name
    or str(receipt.get("database_sha256") or "").lower()
    != database_sha256
    or str(receipt.get("report_sha256") or "").lower() != report_sha256
    or str(receipt.get("chain_id") or "") != chain_id
    or str(receipt.get("source_sha") or "").lower() != source_sha
    or receipt.get("generation") != generation
    or str(receipt.get("coverage_fingerprint") or "").lower()
    != coverage_fingerprint
    or str(receipt.get("lane_inventory_sha256") or "").lower()
    != lane_inventory_sha256
    or str(
        receipt.get("w2_authority_identity_sha256") or ""
    ).lower()
    != str(
        w2_authority.get("w2_authority_identity_sha256") or ""
    ).lower()
):
    raise SystemExit("committed checkpoint artifact receipt is invalid")
owner_snapshot = json.loads(
    Path(os.environ["OWNER_RECHECK_PATH"]).read_text(encoding="utf-8")
)
owner_claim = (
    owner_snapshot.get("run")
    if isinstance(owner_snapshot, dict)
    else None
)
semantic_source = (
    owner_snapshot.get("semantic_source")
    if isinstance(owner_snapshot, dict)
    else None
)
workflow_claim = (
    owner_snapshot.get("workflow")
    if isinstance(owner_snapshot, dict)
    else None
)
expected_owner_url = (
    f"{os.environ['GITHUB_API_URL'].rstrip('/')}/repos/"
    f"{os.environ['GITHUB_REPOSITORY']}/actions/runs/{source_run_id}"
)
if (
    not isinstance(owner_snapshot, dict)
    or type(owner_snapshot.get("schema_version")) is not int
    or owner_snapshot.get("schema_version") != 1
    or owner_snapshot.get("repository")
    != os.environ["GITHUB_REPOSITORY"]
    or not isinstance(owner_claim, dict)
    or type(owner_claim.get("id")) is not int
    or owner_claim.get("id") != int(source_run_id)
    or owner_claim.get("url") != expected_owner_url
    or owner_claim.get("event") != "workflow_dispatch"
    or not isinstance(owner_claim.get("head_branch"), str)
    or not owner_claim.get("head_branch")
    or re.fullmatch(
        r"[0-9a-f]{40}",
        str(owner_claim.get("head_sha") or "").lower(),
    )
    is None
    or owner_claim.get("path")
    != ".github/workflows/full-extraction.yml"
    or type(owner_claim.get("attempt")) is not int
    or owner_claim.get("attempt") != 1
    or type(owner_claim.get("workflow_id")) is not int
    or owner_claim.get("workflow_id") < 1
    or owner_claim.get("status") != "completed"
    or owner_claim.get("conclusion")
    not in {"cancelled", "failure", "success", "timed_out"}
    or not isinstance(semantic_source, dict)
    or str(semantic_source.get("sha") or "").lower() != source_sha
    or semantic_source.get("relation")
    not in {"identical", "ancestor"}
    or (semantic_source.get("relation") == "identical")
    != (
        str(semantic_source.get("sha") or "").lower()
        == str(owner_claim.get("head_sha") or "").lower()
    )
    or not isinstance(workflow_claim, dict)
    or workflow_claim.get("path")
    != ".github/workflows/full-extraction.yml"
    or re.fullmatch(
        r"[0-9a-f]{40}",
        str(workflow_claim.get("blob_sha") or "").lower(),
    )
    is None
    or re.fullmatch(
        r"[0-9a-f]{64}",
        str(workflow_claim.get("sha256") or "").lower(),
    )
    is None
    or type(workflow_claim.get("size_in_bytes")) is not int
    or workflow_claim.get("size_in_bytes") < 1
):
    raise SystemExit("source checkpoint owner recheck snapshot is invalid")
run_raw = subprocess.check_output(
    [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        (
            f"/repos/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/runs/{source_run_id}"
        ),
    ],
    text=True,
)
owner_run = json.loads(run_raw)
owner_head_sha = str(owner_run.get("head_sha") or "").lower()
owner_repository = owner_run.get("repository")
if (
    type(owner_run.get("id")) is not int
    or str(owner_run.get("id")) != source_run_id
    or owner_run.get("url") != owner_claim.get("url")
    or not isinstance(owner_repository, dict)
    or owner_repository.get("full_name")
    != os.environ["GITHUB_REPOSITORY"]
    or type(owner_run.get("run_attempt")) is not int
    or owner_run.get("run_attempt") != owner_claim.get("attempt")
    or owner_run.get("run_attempt") != 1
    or owner_head_sha
    != str(owner_claim.get("head_sha") or "").lower()
    or owner_run.get("status") != owner_claim.get("status")
    or owner_run.get("conclusion") != owner_claim.get("conclusion")
    or owner_run.get("event") != owner_claim.get("event")
    or owner_run.get("head_branch") != owner_claim.get("head_branch")
    or owner_run.get("path") != owner_claim.get("path")
    or type(owner_run.get("workflow_id")) is not int
    or owner_run.get("workflow_id") != owner_claim.get("workflow_id")
):
    raise SystemExit(
        "source checkpoint owner changed after provenance recheck"
    )
raw = subprocess.check_output(
    [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        (
            f"/repos/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/artifacts/{artifact_id}"
        ),
    ],
    text=True,
)
artifact = json.loads(raw)
workflow_run = artifact.get("workflow_run")
rest_artifact_id = artifact.get("id")
rest_artifact_size = artifact.get("size_in_bytes")
expected_archive_url = (
    f"{os.environ['GITHUB_API_URL'].rstrip('/')}/repos/"
    f"{os.environ['GITHUB_REPOSITORY']}/actions/artifacts/"
    f"{artifact_id}/zip"
)
if (
    isinstance(rest_artifact_id, bool)
    or not isinstance(rest_artifact_id, int)
    or rest_artifact_id != artifact_id
    or artifact.get("name") != artifact_name
    or artifact.get("digest") != artifact_digest
    or artifact.get("archive_download_url") != expected_archive_url
    or isinstance(rest_artifact_size, bool)
    or not isinstance(rest_artifact_size, int)
    or rest_artifact_size != artifact_size
    or artifact.get("expired") is not False
    or not isinstance(workflow_run, dict)
    or str(workflow_run.get("id") or "") != source_run_id
    or str(workflow_run.get("head_sha") or "").lower()
    != owner_head_sha
):
    raise SystemExit(
        "source checkpoint REST identity does not match its committed receipt"
    )
final_run_raw = subprocess.check_output(
    [
        "gh",
        "api",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        (
            f"/repos/{os.environ['GITHUB_REPOSITORY']}"
            f"/actions/runs/{source_run_id}"
        ),
    ],
    text=True,
)
if json.loads(final_run_raw) != owner_run:
    raise SystemExit(
        "source checkpoint owner changed after exact artifact selection"
    )
with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as handle:
    handle.write(f"artifact_name={artifact_name}\n")
    handle.write(f"artifact_id={artifact_id}\n")
    handle.write(f"artifact_digest={artifact_digest}\n")
    handle.write(f"artifact_size_bytes={artifact_size}\n")
    handle.write(f"source_run_id={source_run_id}\n")
    handle.write(f"checkpoint_generation={generation}\n")
    handle.write(f"coverage_fingerprint={coverage_fingerprint}\n")
    handle.write(f"database_sha256={database_sha256}\n")
    handle.write(f"report_sha256={report_sha256}\n")
    handle.write(
        "w2_authority_identity_sha256="
        f"{w2_authority['w2_authority_identity_sha256']}\n"
    )
    handle.write(
        "w2_database_authority_sha256="
        f"{w2_authority['w2_database_authority_sha256']}\n"
    )
    handle.write(
        "w2_expected_call_count="
        f"{w2_authority['w2_expected_call_count']}\n"
    )
    handle.write(
        "w2_expected_call_inventory_sha256="
        f"{w2_authority['w2_expected_call_inventory_sha256']}\n"
    )
    handle.write("w2_database_authority_closed=true\n")
PY
"""

ATTEST_TERMINAL_REPLAY_INPUTS_SCRIPT: Final = r"""set -euo pipefail
mkdir -p terminal-replay-inputs/checkpoint artifacts/full-extraction
mapfile -t plan_manifests < <(find plan-artifact -name manifest.json -type f -print)
mapfile -t trust_manifests < <(find plan-artifact -name resume-source-input-manifest.json -type f -print)
mapfile -t checkpoint_manifests < <(find source-checkpoint -name checkpoint-manifest.json -type f -print)
mapfile -t checkpoint_reports < <(find source-checkpoint -name checkpoint-report.json -type f -print)
mapfile -t checkpoint_databases < <(find source-checkpoint -name nba.duckdb -type f -print)
mapfile -t checkpoint_transactions < <(find source-checkpoint -name checkpoint-transaction.json -type f -print)
if [ "${#plan_manifests[@]}" -ne 1 ] || \
   [ "${#trust_manifests[@]}" -ne 1 ] || \
   [ "${#checkpoint_manifests[@]}" -ne 1 ] || \
   [ "${#checkpoint_reports[@]}" -ne 1 ] || \
   [ "${#checkpoint_databases[@]}" -ne 1 ] || \
   [ "${#checkpoint_transactions[@]}" -ne 1 ]; then
  echo "::error::Terminal replay inputs are incomplete"
  find plan-artifact source-checkpoint \
    -maxdepth 6 -type f -print || true
  exit 1
fi
plan_manifest_path="${plan_manifests[0]}"
trust_manifest_path="${trust_manifests[0]}"
checkpoint_manifest="${checkpoint_manifests[0]}"
checkpoint_report="${checkpoint_reports[0]}"
checkpoint_database="${checkpoint_databases[0]}"
checkpoint_transaction="${checkpoint_transactions[0]}"

PLAN_MANIFEST_PATH="$plan_manifest_path" \
  TRUST_MANIFEST_PATH="$trust_manifest_path" \
  CHECKPOINT_MANIFEST_PATH="$checkpoint_manifest" \
  CHECKPOINT_REPORT_PATH="$checkpoint_report" \
  CHECKPOINT_DATABASE_PATH="$checkpoint_database" \
  CHECKPOINT_TRANSACTION_PATH="$checkpoint_transaction" \
  python - <<'PY'
# TERMINAL_REPLAY_ATTESTATION
import hashlib
import json
import os
import re
from pathlib import Path

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
W2_AUTHORITY_KEYS = {
    "w2_database_authority",
    "w2_database_authority_sha256",
    "w2_expected_call_count",
    "w2_expected_call_inventory_sha256",
    "w2_database_authority_closed",
    "w2_authority_identity_sha256",
}
W2_RECEIPT_KEYS = {
    "schema_version",
    "kind",
    "receipt_sha256",
    "w2_required_logical_call_count",
    "w2_source_call_admission_inventory_sha256",
    "raw_authority_v2_bundle_count",
    "raw_authority_v2_bundle_inventory_sha256",
    "raw_authority_v2_persistence_receipt_inventory_sha256",
    "w2_publication_receipt_count",
    "w2_publication_receipt_inventory_sha256",
    "w2_exact_six_schema_inventory_sha256",
    "w2_relation_row_counts",
    "w2_relation_row_count",
    "w2_relation_inventory_sha256",
}

class ReplayW2Error(ValueError):
    pass

def canonical_sha256(payload: object) -> str:
    raw = json.dumps(
        payload, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(raw).hexdigest()

def require_exact_keys(
    payload: object, expected: set[str], label: str
) -> dict[str, object]:
    if type(payload) is not dict or set(payload) != expected:
        raise ReplayW2Error(f"{label} has a foreign field shape")
    return payload

def require_sha256(value: object, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise ReplayW2Error(f"{label} is not SHA-256")
    return value

def validate_w2_authority(
    build: object, *, label: str
) -> dict[str, object]:
    exact_build = require_exact_keys(
        build,
        {"database_sha256", "report_sha256", "w2_authority"},
        f"{label} build",
    )
    authority = require_exact_keys(
        exact_build["w2_authority"], W2_AUTHORITY_KEYS, f"{label} W2"
    )
    receipt = require_exact_keys(
        authority["w2_database_authority"],
        W2_RECEIPT_KEYS,
        f"{label} W2 receipt",
    )
    if (
        receipt["schema_version"] != 1
        or receipt["kind"]
        != "nbadb_w2_database_authority_receipt_v1"
    ):
        raise ReplayW2Error(f"{label} W2 receipt is foreign")
    for field, value in receipt.items():
        if field.endswith("_sha256"):
            require_sha256(value, field)
    receipt_sha = receipt["receipt_sha256"]
    receipt_identity = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    if canonical_sha256(receipt_identity) != receipt_sha:
        raise ReplayW2Error(f"{label} W2 receipt digest is invalid")
    count = authority["w2_expected_call_count"]
    if (
        type(count) is not int
        or count < 0
        or count != receipt["w2_required_logical_call_count"]
        or authority["w2_database_authority_sha256"] != receipt_sha
        or authority["w2_database_authority_closed"] is not True
    ):
        raise ReplayW2Error(f"{label} W2 is not closed")
    require_sha256(
        authority["w2_expected_call_inventory_sha256"], "W2 inventory"
    )
    identity_sha = require_sha256(
        authority["w2_authority_identity_sha256"], "W2 identity"
    )
    identity = {
        key: value
        for key, value in authority.items()
        if key != "w2_authority_identity_sha256"
    }
    if canonical_sha256(identity) != identity_sha:
        raise ReplayW2Error(f"{label} W2 identity is invalid")
    return authority

plan_manifest_path = Path(os.environ["PLAN_MANIFEST_PATH"])
trust_manifest_path = Path(os.environ["TRUST_MANIFEST_PATH"])
checkpoint_manifest_path = Path(os.environ["CHECKPOINT_MANIFEST_PATH"])
report_path = Path(os.environ["CHECKPOINT_REPORT_PATH"])
database_path = Path(os.environ["CHECKPOINT_DATABASE_PATH"])
candidate_transaction_path = Path(
    os.environ["CHECKPOINT_TRANSACTION_PATH"]
)
plan_manifest = json.loads(plan_manifest_path.read_text(encoding="utf-8"))
trust_manifest = json.loads(
    trust_manifest_path.read_text(encoding="utf-8")
)
checkpoint_manifest = json.loads(
    checkpoint_manifest_path.read_text(encoding="utf-8")
)
report = json.loads(report_path.read_text(encoding="utf-8"))
candidate_transaction = json.loads(
    candidate_transaction_path.read_text(encoding="utf-8")
)
expected_generation = int(os.environ["EXPECTED_CHECKPOINT_GENERATION"])
expected_coverage = os.environ["EXPECTED_COVERAGE_FINGERPRINT"].lower()
expected_database_sha256 = os.environ["EXPECTED_DATABASE_SHA256"].lower()
expected_report_sha256 = os.environ["EXPECTED_REPORT_SHA256"].lower()
expected_w2_authority_identity_sha256 = os.environ[
    "EXPECTED_W2_AUTHORITY_IDENTITY_SHA256"
].lower()
expected_w2_database_authority_sha256 = os.environ[
    "EXPECTED_W2_DATABASE_AUTHORITY_SHA256"
].lower()
expected_w2_expected_call_inventory_sha256 = os.environ[
    "EXPECTED_W2_EXPECTED_CALL_INVENTORY_SHA256"
].lower()
expected_w2_closed = os.environ[
    "EXPECTED_W2_DATABASE_AUTHORITY_CLOSED"
]
try:
    expected_w2_expected_call_count = int(
        os.environ["EXPECTED_W2_EXPECTED_CALL_COUNT"]
    )
except (TypeError, ValueError):
    expected_w2_expected_call_count = -1

failures: list[str] = []
if not isinstance(plan_manifest, dict):
    failures.append("zero-active replay plan manifest is invalid")
    plan_manifest = {}
if not isinstance(trust_manifest, dict):
    failures.append("zero-active replay trust manifest is invalid")
    trust_manifest = {}
trust_state = trust_manifest.get("chain_state")
if not isinstance(trust_state, dict):
    failures.append("zero-active replay trust chain_state is invalid")
    trust_state = {}
if (
    str(trust_manifest.get("chain_id") or "")
    != os.environ["CHAIN_ID"]
    or str(trust_manifest.get("workflow_source_sha") or "").lower()
    != os.environ["WORKFLOW_SOURCE_SHA"].lower()
):
    failures.append("zero-active replay trust manifest identity does not match")
committed_transaction = trust_state.get("latest_checkpoint_transaction")
if not isinstance(committed_transaction, dict):
    failures.append(
        "zero-active replay trust manifest lacks a committed checkpoint transaction"
    )
    committed_transaction = {}
committed_w2_authority: dict[str, object] = {}
try:
    require_exact_keys(
        committed_transaction,
        {
            "schema_version",
            "state",
            "identity",
            "artifact_name",
            "build",
            "receipt",
        },
        "committed checkpoint transaction",
    )
    if (
        type(committed_transaction["schema_version"]) is not int
        or committed_transaction["schema_version"] != 3
        or committed_transaction["state"] != "committed"
    ):
        raise ReplayW2Error(
            "committed checkpoint transaction is not exact schema v2"
        )
    committed_w2_authority = validate_w2_authority(
        committed_transaction["build"],
        label="committed checkpoint",
    )
except (KeyError, ReplayW2Error) as exc:
    failures.append(str(exc))
committed_identity = committed_transaction.get("identity")
committed_build = committed_transaction.get("build")
committed_receipt = committed_transaction.get("receipt")
if not isinstance(committed_identity, dict):
    failures.append("committed checkpoint identity is invalid")
    committed_identity = {}
if not isinstance(committed_build, dict):
    failures.append("committed checkpoint build is invalid")
    committed_build = {}
if not isinstance(committed_receipt, dict):
    failures.append("committed checkpoint receipt is invalid")
    committed_receipt = {}
committed_coverage = committed_identity.get("coverage")
if not isinstance(committed_coverage, dict):
    failures.append("committed checkpoint coverage is invalid")
    committed_coverage = {}
if (
    committed_transaction.get("schema_version") != 3
    or committed_transaction.get("state") != "committed"
):
    failures.append("zero-active replay transaction is not committed")
if (
    str(committed_identity.get("chain_id") or "")
    != os.environ["CHAIN_ID"]
    or str(committed_identity.get("source_sha") or "").lower()
    != os.environ["WORKFLOW_SOURCE_SHA"].lower()
    or committed_identity.get("generation") != expected_generation
    or str(committed_coverage.get("coverage_fingerprint") or "").lower()
    != expected_coverage
    or str(committed_transaction.get("artifact_name") or "")
    != os.environ["SOURCE_CHECKPOINT_ARTIFACT"]
    or str(committed_build.get("database_sha256") or "").lower()
    != expected_database_sha256
    or str(committed_build.get("report_sha256") or "").lower()
    != expected_report_sha256
):
    failures.append(
        "zero-active replay committed transaction identity does not match"
    )
if (
    require_sha256(
        expected_w2_authority_identity_sha256,
        "expected W2 authority identity SHA-256",
    )
    != committed_w2_authority.get("w2_authority_identity_sha256")
    or require_sha256(
        expected_w2_database_authority_sha256,
        "expected W2 database authority SHA-256",
    )
    != committed_w2_authority.get("w2_database_authority_sha256")
    or expected_w2_expected_call_count < 0
    or expected_w2_expected_call_count
    != committed_w2_authority.get("w2_expected_call_count")
    or require_sha256(
        expected_w2_expected_call_inventory_sha256,
        "expected W2 call inventory SHA-256",
    )
    != committed_w2_authority.get(
        "w2_expected_call_inventory_sha256"
    )
    or expected_w2_closed != "true"
    or committed_w2_authority.get(
        "w2_database_authority_closed"
    )
    is not True
):
    failures.append(
        "zero-active replay W2 resolver outputs do not match the committed trust root"
    )
if (
    str(committed_receipt.get("artifact_run_id") or "")
    != os.environ["SOURCE_RUN_ID"]
    or str(committed_receipt.get("artifact_run_attempt") or "")
    != os.environ["SOURCE_RUN_ATTEMPT"]
    or str(committed_receipt.get("artifact_name") or "")
    != os.environ["SOURCE_CHECKPOINT_ARTIFACT"]
    or str(committed_receipt.get("database_sha256") or "").lower()
    != expected_database_sha256
    or str(committed_receipt.get("report_sha256") or "").lower()
    != expected_report_sha256
    or str(committed_receipt.get("chain_id") or "")
    != os.environ["CHAIN_ID"]
    or str(committed_receipt.get("source_sha") or "").lower()
    != os.environ["WORKFLOW_SOURCE_SHA"].lower()
    or committed_receipt.get("generation") != expected_generation
    or str(
        committed_receipt.get("coverage_fingerprint") or ""
    ).lower()
    != expected_coverage
    or str(
        committed_receipt.get("lane_inventory_sha256") or ""
    ).lower()
    != str(
        committed_coverage.get("lane_inventory_sha256") or ""
    ).lower()
    or str(
        committed_receipt.get("w2_authority_identity_sha256") or ""
    ).lower()
    != expected_w2_authority_identity_sha256
):
    failures.append(
        "zero-active replay committed receipt does not match"
    )
if not isinstance(checkpoint_manifest, dict):
    failures.append("source checkpoint manifest is invalid")
    checkpoint_manifest = {}
if not isinstance(candidate_transaction, dict):
    failures.append("source checkpoint transaction is invalid")
    candidate_transaction = {}
candidate_w2_authority: dict[str, object] = {}
try:
    require_exact_keys(
        candidate_transaction,
        {
            "schema_version",
            "state",
            "identity",
            "artifact_name",
            "build",
        },
        "source checkpoint built transaction",
    )
    if (
        type(candidate_transaction["schema_version"]) is not int
        or candidate_transaction["schema_version"] != 3
        or candidate_transaction["state"] != "built"
    ):
        raise ReplayW2Error(
            "source checkpoint transaction is not exact schema-v3 built state"
        )
    candidate_w2_authority = validate_w2_authority(
        candidate_transaction["build"],
        label="source checkpoint built",
    )
except (KeyError, ReplayW2Error) as exc:
    failures.append(str(exc))
if (
    candidate_transaction.get("schema_version") != 3
    or candidate_transaction.get("state") != "built"
    or "receipt" in candidate_transaction
    or candidate_transaction.get("identity") != committed_identity
    or candidate_transaction.get("artifact_name")
    != committed_transaction.get("artifact_name")
    or candidate_transaction.get("build") != committed_build
    or candidate_w2_authority != committed_w2_authority
):
    failures.append(
        "source checkpoint built transaction does not match the committed trust root"
    )
report_w2_authority = {
    "w2_database_authority": report.get("w2_database_authority"),
    "w2_database_authority_sha256": report.get(
        "w2_database_authority_sha256"
    ),
    "w2_expected_call_count": report.get("w2_expected_call_count"),
    "w2_expected_call_inventory_sha256": report.get(
        "w2_expected_call_inventory_sha256"
    ),
    "w2_database_authority_closed": report.get(
        "w2_database_authority_closed"
    ),
}
committed_w2_report_identity = {
    key: value
    for key, value in committed_w2_authority.items()
    if key != "w2_authority_identity_sha256"
}
if report_w2_authority != committed_w2_report_identity:
    failures.append(
        "source checkpoint report W2 authority does not match the committed trust root"
    )
if int(plan_manifest.get("lane_count", 0)) <= 0:
    failures.append("zero-active replay manifest has no lanes")
if int(plan_manifest.get("active_lane_count", -1)) != 0:
    failures.append("zero-active replay manifest has active lanes")
if int(plan_manifest.get("matrix_lane_count", -1)) != 0:
    failures.append("zero-active replay manifest has matrix lanes")
if int(checkpoint_manifest.get("lane_count", 0)) <= 0:
    failures.append("source checkpoint manifest has no lanes")
if report.get("terminal_ready") is not True:
    failures.append("source checkpoint is not terminal-ready")
if int(report.get("active_lane_count", -1)) != 0:
    failures.append("source checkpoint still has active lanes")
if str(report.get("chain_id") or "") != os.environ["CHAIN_ID"]:
    failures.append("source checkpoint chain identity does not match")
if str(checkpoint_manifest.get("chain_id") or "") != os.environ["CHAIN_ID"]:
    failures.append("source checkpoint manifest chain identity does not match")
if str(report.get("run_id") or "") != os.environ["SOURCE_RUN_ID"]:
    failures.append("source checkpoint run identity does not match")
if (
    str(report.get("artifact_name") or "")
    != os.environ["SOURCE_CHECKPOINT_ARTIFACT"]
):
    failures.append("source checkpoint artifact identity does not match")
if (
    str(report.get("source_sha") or "").lower()
    != os.environ["WORKFLOW_SOURCE_SHA"].lower()
):
    failures.append("source checkpoint source SHA does not match")
if (
    str(checkpoint_manifest.get("workflow_source_sha") or "").lower()
    != os.environ["WORKFLOW_SOURCE_SHA"].lower()
):
    failures.append("source checkpoint manifest source SHA does not match")
if int(report.get("checkpoint_generation", 0)) != expected_generation:
    failures.append("source checkpoint generation does not match its artifact name")
if (
    not expected_coverage
    or str(report.get("coverage_fingerprint") or "").lower()
    != expected_coverage
):
    failures.append("source checkpoint coverage fingerprint does not match")
if (
    str(plan_manifest.get("coverage_fingerprint") or "").lower()
    != expected_coverage
):
    failures.append("zero-active replay coverage does not match source checkpoint")
if int(report.get("complete_lane_count", 0)) <= 0:
    failures.append("source checkpoint contains no completed lanes")

manifest_lane_hashes = {
    str(lane.get("lane_id") or ""): str(lane.get("coverage_units_hash") or "")
    for lane in checkpoint_manifest.get("lanes", [])
    if isinstance(lane, dict)
}
report_lane_hashes = {
    str(lane_id): str(coverage_hash)
    for lane_id, coverage_hash in dict(
        report.get("included_lane_coverage_hashes", {})
    ).items()
}
committed_lane_hashes = {
    str(lane.get("lane_id") or ""): str(
        lane.get("coverage_units_hash") or ""
    )
    for lane in committed_coverage.get("lanes", [])
    if isinstance(lane, dict)
}
mismatched_lane_hashes = sorted(
    set(manifest_lane_hashes)
    ^ set(report_lane_hashes)
    | set(manifest_lane_hashes)
    ^ set(committed_lane_hashes)
) + sorted(
    lane_id for lane_id, coverage_hash in manifest_lane_hashes.items()
    if (
        not lane_id
        or not coverage_hash
        or report_lane_hashes.get(lane_id) != coverage_hash
        or committed_lane_hashes.get(lane_id) != coverage_hash
    )
)
if mismatched_lane_hashes:
    failures.append(
        "source checkpoint lane coverage hashes do not match: "
        + ", ".join(mismatched_lane_hashes)
    )
if report.get("current_lane_attestation_failures"):
    failures.append("source checkpoint records lane attestation failures")

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

if (
    str(report.get("database_sha256") or "").lower()
    != expected_database_sha256
    or sha256(database_path) != expected_database_sha256
):
    failures.append("source checkpoint database SHA-256 does not match")
if sha256(report_path) != expected_report_sha256:
    failures.append("source checkpoint report SHA-256 does not match")

if failures:
    for failure in failures:
        print(f"::error::{failure}")
    raise SystemExit(1)
PY

cp "$checkpoint_manifest" terminal-replay-inputs/terminal-manifest.json
cp "$checkpoint_report" terminal-replay-inputs/checkpoint/checkpoint-report.json
cp "$checkpoint_database" terminal-replay-inputs/checkpoint/nba.duckdb
artifact_name="full-extraction-terminal-replay-${ACTIVE_CHAIN_ID}-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
{
  echo "artifact_name=$artifact_name"
  echo "checkpoint_generation=${EXPECTED_CHECKPOINT_GENERATION}"
} >> "$GITHUB_OUTPUT"

"""

COMMANDS: Final = {
    "resolve-resume-source-committed-manifest": RESOLVE_RESUME_SOURCE_COMMITTED_MANIFEST_SCRIPT,
    "build-lane-manifest": BUILD_LANE_MANIFEST_SCRIPT,
    "resolve-prior-discovery-artifact-receipt": RESOLVE_PRIOR_DISCOVERY_ARTIFACT_RECEIPT_SCRIPT,
    "resolve-exact-source-checkpoint-receipt": RESOLVE_EXACT_SOURCE_CHECKPOINT_RECEIPT_SCRIPT,
    "attest-terminal-replay-inputs": ATTEST_TERMINAL_REPLAY_INPUTS_SCRIPT,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=tuple(COMMANDS))
    return parser


def main(argv: list[str] | None = None) -> int:
    command = _parser().parse_args(argv).command
    return subprocess.run(
        ["bash", "-e", "-c", COMMANDS[command]],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
