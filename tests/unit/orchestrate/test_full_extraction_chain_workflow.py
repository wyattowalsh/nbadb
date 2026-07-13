from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import textwrap
import types
import zipfile

import pytest

from nbadb.orchestrate.full_extraction_control import (
    FullExtractionLane,
    _canonical_contract_blocked_audit_row,
    _coverage_hash_for_lane,
    manifest_payload,
)
from nbadb.orchestrate.full_extraction_control import (
    main as full_extraction_main,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "full-extraction.yml"
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_DAILY_PATH = _REPO_ROOT / ".github" / "workflows" / "daily-update.yml"
_MONTHLY_PATH = _REPO_ROOT / ".github" / "workflows" / "monthly-update.yml"
_REFRESH_METADATA_ACTION_PATH = (
    _REPO_ROOT / ".github" / "actions" / "refresh-metadata" / "action.yml"
)
_DISCOVERY_SEED_PATH = _REPO_ROOT / ".github" / "scripts" / "seed_discovery_artifacts.py"
_REQUIRED_EXTRACTION_SCRIPTS = (
    _REPO_ROOT / ".github" / "scripts" / "probe_discovery_transport.py",
    _REPO_ROOT / ".github" / "scripts" / "verify_discovery_bundle.py",
)


def _workflow_text() -> str:
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block(workflow: str, job_name: str) -> str:
    jobs = workflow.split("\njobs:\n", 1)[1]
    marker = f"  {job_name}:\n"
    start = jobs.index(marker)
    remainder = jobs[start + len(marker) :]
    next_job = re.search(r"(?m)^  [a-z][a-z0-9_-]*:\n", remainder)
    end = start + len(marker) + (next_job.start() if next_job else len(remainder))
    return jobs[start:end]


def _step_block(job: str, step_name: str) -> str:
    marker = f"      - name: {step_name}\n"
    start = job.index(marker)
    remainder = job[start + len(marker) :]
    next_step = re.search(r"(?m)^      - (?:name:|uses:|run:)", remainder)
    end = start + len(marker) + (next_step.start() if next_step else len(remainder))
    return job[start:end]


def _embedded_python(workflow_block: str, marker: str) -> str:
    match = re.search(
        rf"(?ms)^[ \t]*# {re.escape(marker)}\n(?P<body>.*?)(?=^[ \t]*PY[ \t]*$)",
        workflow_block,
    )
    assert match is not None
    return textwrap.dedent(match.group("body"))


def _run_python(
    script: str,
    *,
    env: dict[str, str],
    cwd: pathlib.Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        cwd=cwd,
        env={**os.environ, **env},
        text=True,
    )


def _contract_blocked_fixture(
    lane_id: str,
    season_start: int,
    season_end: int,
) -> tuple[FullExtractionLane, dict[str, object], dict[str, object]]:
    lane = FullExtractionLane(
        lane_id=lane_id,
        lane_index=0,
        lane_name=lane_id,
        lane_kind="historical",
        season_start=season_start,
        season_end=season_end,
        patterns=("player_team_season",),
        season_types=(),
        endpoints=("video_details",),
        timeout_seconds=1,
    )
    coverage_hash = _coverage_hash_for_lane(lane)
    row = _canonical_contract_blocked_audit_row(
        lane_id,
        {
            "lane_kind": lane.lane_kind,
            "endpoints": list(lane.endpoints),
            "patterns": list(lane.patterns),
            "season_start": season_start,
            "season_end": season_end,
            "season_types": [],
            "context_measures": [],
            "coverage_units_hash": coverage_hash,
        },
    )
    manifest_lane = {
        "lane_id": lane_id,
        "lane_kind": lane.lane_kind,
        "endpoints": list(lane.endpoints),
        "patterns": list(lane.patterns),
        "season_start": season_start,
        "season_end": season_end,
        "season_types": [],
        "context_measures": [],
        "coverage_units_hash": coverage_hash,
    }
    return lane, row, manifest_lane


def _metadata_commit_script() -> str:
    action = _REFRESH_METADATA_ACTION_PATH.read_text(encoding="utf-8")
    return textwrap.dedent(
        action.split("    - name: Commit refreshed metadata\n", 1)[1].split("      run: |\n", 1)[1]
    )


def _step_run_script(job: str, step_name: str) -> str:
    step = _step_block(job, step_name)
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def _load_discovery_seed_module() -> types.ModuleType:
    module = types.ModuleType("full_extraction_chain_discovery_seed")
    module.__file__ = str(_DISCOVERY_SEED_PATH)
    code = compile(
        _DISCOVERY_SEED_PATH.read_text(encoding="utf-8"),
        str(_DISCOVERY_SEED_PATH),
        "exec",
    )
    exec(code, module.__dict__)
    return module


def test_workflow_definition_guards_use_the_pinned_source_checkout() -> None:
    workflow = _workflow_text()
    guard = _job_block(workflow, "workflow_guard")
    plan = _job_block(workflow, "plan")
    dispatch = _job_block(workflow, "dispatch_next")

    assert (
        "run-name: Full Extraction chain=${{ inputs.chain_id || github.run_id }} "
        "iteration=${{ inputs.iteration }}"
    ) in workflow
    assert "needs: workflow_guard" in plan
    assert "WORKFLOW_DEFINITION_SHA: ${{ github.workflow_sha }}" in guard
    assert 'source_blob="$(git rev-parse "${source_commit}:${WORKFLOW_PATH}")"' in guard
    assert '-f "ref=${WORKFLOW_DEFINITION_SHA}"' in guard
    assert "does not match workflow_source_sha" in guard

    checkout_blocks = re.findall(
        r"(?m)^      - uses: actions/checkout@[^\n]+\n"
        r"        with:\n(?P<inputs>(?:          [^\n]+\n)+)",
        workflow,
    )
    assert len(checkout_blocks) == workflow.count("- uses: actions/checkout@")
    assert checkout_blocks
    assert all("ref: ${{ env.WORKFLOW_SOURCE_SHA }}" in block for block in checkout_blocks)
    assert "Verify redispatch workflow definition" in dispatch
    assert '-f "ref=${WORKFLOW_REF}"' in dispatch
    assert "does not match workflow_source_sha" in dispatch
    assert dispatch.index("Verify redispatch workflow definition") < dispatch.index(
        "gh workflow run full-extraction.yml"
    )


def test_required_extraction_runtime_scripts_exist_and_are_not_ignored() -> None:
    for path in _REQUIRED_EXTRACTION_SCRIPTS:
        assert path.is_file(), f"missing required workflow script: {path}"
        result = subprocess.run(
            ["git", "check-ignore", str(path.relative_to(_REPO_ROOT))],
            cwd=_REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1, result.stdout or result.stderr
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path.relative_to(_REPO_ROOT))],
            cwd=_REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert tracked.returncode == 0, tracked.stdout or tracked.stderr


def test_user_supplied_source_sha_must_descend_from_trusted_branches() -> None:
    workflow = _workflow_text()
    guard = _job_block(workflow, "workflow_guard")
    dispatch = _job_block(workflow, "dispatch_next")

    assert "WORKFLOW_SOURCE_SHA" in guard
    assert "^[0-9a-fA-F]{40}$" in guard
    assert 'git check-ref-format --branch "$WORKFLOW_SOURCE_REF"' in guard
    assert "+refs/heads/${WORKFLOW_SOURCE_REF}:${trusted_branch_ref}" in guard
    assert 'git merge-base --is-ancestor "$source_commit" "$trusted_branch_commit"' in guard
    assert "+refs/heads/${DEFAULT_BRANCH}:${default_branch_ref}" in guard
    assert 'if [ "$PUBLISH" = "true" ]; then' in guard
    assert 'git merge-base --is-ancestor "$source_commit" "$default_branch_commit"' in guard
    assert guard.index("git merge-base --is-ancestor") < guard.index('source_blob="$(git rev-parse')

    assert "^[0-9a-fA-F]{40}$" in dispatch
    assert 'git check-ref-format --branch "$WORKFLOW_REF"' in dispatch
    assert "+refs/heads/${WORKFLOW_REF}:${trusted_branch_ref}" in dispatch
    assert 'git merge-base --is-ancestor "$source_commit" "$trusted_branch_commit"' in dispatch
    assert "+refs/heads/${DEFAULT_BRANCH}:${default_branch_ref}" in dispatch
    assert 'git merge-base --is-ancestor "$source_commit" "$default_branch_commit"' in dispatch
    assert dispatch.index("git merge-base --is-ancestor") < dispatch.index(
        "gh workflow run full-extraction.yml"
    )
    assert '-f workflow_ref="$WORKFLOW_REF"' in dispatch
    assert '-f workflow_sha="$WORKFLOW_SHA"' in dispatch


def test_checkpoint_remaining_count_disagreement_fails_before_outputs() -> None:
    workflow = _workflow_text()
    checkpoint = _job_block(workflow, "checkpoint")
    dispatch = _job_block(workflow, "dispatch_next")
    canonical_upload = _step_block(checkpoint, "Upload checkpoint artifact")
    diagnostic_upload = _step_block(checkpoint, "Upload checkpoint failure diagnostics")

    assert "needs: [plan, preflight, discovery_seed, extract, lane_control]" in checkpoint
    assert "Download checkpoint lane inputs" in checkpoint
    assert 'discovery_name = f"full-extraction-discovery-artifacts-{chain_id}"' in checkpoint
    assert 'requires_workload_contract="$(CHECKPOINT_MANIFEST=' in checkpoint
    assert 'if [ "$requires_workload_contract" = "true" ]; then' in checkpoint
    assert '"player_team_season" in lane.get("patterns", [])' in checkpoint
    assert '--workload-duckdb-path "$(dirname "$workload_manifest")/nba.duckdb"' in checkpoint
    assert (
        "LANE_CONTROL_ACTIVE_LANE_COUNT: ${{ needs.lane_control.outputs.active-lane-count }}"
    ) in checkpoint
    disagreement_guard = "if checkpoint_active_lane_count != lane_control_active_lane_count:"
    assert disagreement_guard in checkpoint
    assert "Lane-control/checkpoint remaining-count disagreement" in checkpoint
    assert "if lane_control_active_lane_count == 0 and not terminal_ready:" in checkpoint
    assert "if lane_control_active_lane_count > 0 and terminal_ready:" in checkpoint
    assert "Checkpoint report includes completed lanes but its database is missing" in checkpoint
    assert "Lane-control/checkpoint generation disagreement" in checkpoint
    assert "Checkpoint artifact suffix/generation disagreement" in checkpoint
    assert '--source-sha "$WORKFLOW_SOURCE_SHA"' in checkpoint
    assert checkpoint.index(disagreement_guard) < checkpoint.index(
        'with Path(os.environ["GITHUB_OUTPUT"]).open'
    )
    assert "steps.checkpoint.outcome == 'success'" in canonical_upload
    assert "if-no-files-found: error" in canonical_upload
    assert "steps.checkpoint.outcome != 'success'" in diagnostic_upload
    assert "steps.canonical_checkpoint.outcome != 'success'" in diagnostic_upload
    assert (
        "full-extraction-checkpoint-diagnostics-${{ env.ACTIVE_CHAIN_ID }}-"
        "${{ github.run_id }}-${{ github.run_attempt }}" in diagnostic_upload
    )
    assert "needs.lane_control.outputs.checkpoint-artifact-name" not in diagnostic_upload

    assert "needs.checkpoint.result == 'success'" in dispatch
    assert (
        "needs.checkpoint.outputs.active-lane-count == needs.lane_control.outputs.active-lane-count"
    ) in dispatch
    assert "needs.checkpoint.outputs.terminal-ready == 'false'" in dispatch


def test_previous_checkpoint_is_verified_before_lane_inventory_selection() -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    verify = _step_block(checkpoint, "Verify previous checkpoint before inventory use")
    inventory = _step_block(checkpoint, "Download checkpoint lane inputs")

    assert checkpoint.index("Verify previous checkpoint before inventory use") < checkpoint.index(
        "Download checkpoint lane inputs"
    )
    assert "full_extraction_control verify-checkpoint" in verify
    assert "--pointer-prefix latest" in verify
    assert "verified-previous-checkpoint.json" in verify
    assert "VERIFIED_PREVIOUS_CHECKPOINT_PATH" in inventory
    assert "PREVIOUS_REPORT_PATH" not in inventory


def test_checkpoint_build_step_avoids_github_expressions_in_oversized_script() -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    build = _step_block(checkpoint, "Build checkpoint database")

    assert len(build) > 21_000
    run_script = build.split("        run: |\n", 1)[1]
    assert "${{" not in run_script
    assert '--run-id "$CURRENT_RUN_ID"' in run_script
    assert (
        'LANE_CONTROL_CONTRACT_BLOCKED_LANE_COUNT="$LANE_CONTROL_CONTRACT_BLOCKED_LANE_COUNT"'
        in run_script
    )


def test_lane_control_requires_a_successful_seed_and_non_skipped_extract() -> None:
    workflow = _workflow_text()
    plan = _job_block(workflow, "plan")
    extract = _job_block(workflow, "extract")
    lane_control = _job_block(workflow, "lane_control")
    checkpoint = _job_block(workflow, "checkpoint")
    dispatch = _job_block(workflow, "dispatch_next")
    lane_control_header = lane_control.split("    steps:\n", 1)[0]

    assert "needs.discovery_seed.result == 'success'" in extract
    assert "needs: [plan, preflight, discovery_seed, extract, terminal_replay]" in (
        lane_control_header
    )
    assert "needs.discovery_seed.result == 'success'" in lane_control_header
    assert "needs.extract.result != 'skipped'" in lane_control_header
    assert "needs.extract.result == 'success'" not in lane_control_header
    assert "--allow-missing-attempted-metadata" in lane_control
    assert "metadata-artifacts.txt" in plan
    assert "gh api" in plan
    assert "matching-metadata-artifacts.txt" in plan
    assert '--name "$metadata_name"' in plan
    assert "has no lane metadata artifacts" in plan

    # Matrix failures still produce metadata/checkpoints and may dispatch a child.
    assert "needs.lane_control.result == 'success'" in checkpoint
    assert "needs.lane_control.result == 'success'" in dispatch
    assert "needs.checkpoint.result == 'success'" in dispatch


def test_resume_source_downloads_each_lane_metadata_artifact_to_a_unique_directory() -> None:
    plan = _job_block(_workflow_text(), "plan")

    assert 'metadata_dir="$RUNNER_TEMP/resume-source/metadata/$metadata_name"' in plan
    assert 'mkdir -p "$metadata_dir"' in plan
    assert '--dir "$metadata_dir"' in plan
    assert '--dir "$RUNNER_TEMP/resume-source/metadata"' not in plan


def test_successful_nonpublishing_preflight_reaches_discovery_seed() -> None:
    discovery = _job_block(_workflow_text(), "discovery_seed")
    discovery_header = discovery.split("    steps:\n", 1)[0]

    assert "needs: [plan, preflight]" in discovery_header
    assert (
        "if: ${{ always() && needs.plan.outputs.matrix-lane-count != '0' && "
        "needs.preflight.result == 'success' }}" in discovery_header
    )


def test_extract_runner_uses_planner_isolated_matrix_endpoints() -> None:
    extract = _job_block(_workflow_text(), "extract")
    run_extraction = _step_block(extract, "Run extraction")

    assert "BACKFILL_ENDPOINTS: ${{ matrix.endpoints }}" in run_extraction
    assert "inputs.backfill_endpoints" not in run_extraction


def test_discovery_artifact_upload_is_success_only_and_fail_closed() -> None:
    plan = _job_block(_workflow_text(), "plan")
    seed = _job_block(_workflow_text(), "discovery_seed")
    manifest_upload = _step_block(plan, "Upload lane manifest")
    verify = _step_block(seed, "Verify complete discovery bundle")
    upload = _step_block(seed, "Upload discovery artifacts")
    recovery_upload = _step_block(seed, "Upload incomplete discovery recovery artifact")

    assert "if: ${{ success() }}" in upload
    assert "if: always()" not in upload
    assert "if-no-files-found: error" in upload
    assert "retention-days: 30" in upload
    assert "retention-days: 30" in manifest_upload
    assert "if-no-files-found: ignore" not in upload
    assert "if: ${{ always() && !success() }}" in recovery_upload
    assert (
        "full-extraction-discovery-recovery-${{ env.ACTIVE_CHAIN_ID }}-"
        "run-${{ github.run_id }}-attempt-${{ github.run_attempt }}" in recovery_upload
    )
    assert "if-no-files-found: warn" in recovery_upload
    assert "retention-days: 30" in recovery_upload
    assert "full-extraction-discovery-artifacts-${{ env.ACTIVE_CHAIN_ID }}" not in recovery_upload
    assert ".github/scripts/verify_discovery_bundle.py" in verify
    assert "--summary-path artifacts/discovery/discovery-seed-summary.json" in verify
    assert "--manifest-path artifacts/discovery/discovery-manifest.json" in verify
    assert "--duckdb-path data/nbadb/nba.duckdb" in verify
    assert "artifacts/discovery/discovery-manifest.json" in upload
    assert "artifacts/discovery/discovery-manifest.json" in recovery_upload
    assert seed.index("- name: Seed discovery artifacts") < seed.index(
        "- name: Verify complete discovery bundle"
    )
    assert seed.index("- name: Verify complete discovery bundle") < seed.index(
        "- name: Upload discovery artifacts"
    )
    assert seed.index("- name: Upload discovery artifacts") < seed.index(
        "- name: Upload incomplete discovery recovery artifact"
    )


def test_incomplete_lane_state_is_recovery_only_and_run_attempt_scoped() -> None:
    workflow = _workflow_text()
    extract = _job_block(workflow, "extract")
    metadata_step = _step_block(extract, "Write lane metadata")
    complete_upload = _step_block(extract, "Upload complete lane artifact")
    recovery_upload = _step_block(extract, "Upload incomplete lane state artifact")
    finalize_receipt = _step_block(extract, "Finalize durable lane artifact receipt")
    metadata_upload = _step_block(extract, "Upload lane metadata")
    metadata_retry = _step_block(extract, "Retry lane metadata upload")
    diagnostic_upload = _step_block(extract, "Upload diagnostics-only lane snapshot")
    checkpoint_download = _step_block(
        _job_block(workflow, "checkpoint"),
        "Download checkpoint lane inputs",
    )
    complete_name = "extraction-lane-${{ env.ACTIVE_CHAIN_ID }}-${{ matrix.lane_id }}"
    recovery_name = (
        "extraction-lane-recovery-${{ env.ACTIVE_CHAIN_ID }}-${{ matrix.lane_id }}-"
        "run-${{ github.run_id }}-attempt-${{ github.run_attempt }}"
    )

    assert complete_name in complete_upload
    assert recovery_name in metadata_step
    assert 'workload_duckdb_path="$(dirname "$workload_manifest")/nba.duckdb"' in metadata_step
    assert 'export WORKLOAD_DUCKDB_PATH="$workload_duckdb_path"' in metadata_step
    assert recovery_name in recovery_upload
    assert complete_name not in recovery_upload
    assert "steps.lane_metadata.outcome == 'success'" in complete_upload
    assert "steps.lane_metadata.outputs.snapshot-attested == 'true'" in complete_upload
    assert "if-no-files-found: error" in complete_upload
    assert "steps.lane_metadata.outcome == 'success'" in recovery_upload
    assert "steps.lane_metadata.outputs.snapshot-attested == 'true'" in recovery_upload
    assert "steps.lane_metadata.outputs.final-outcome != 'complete'" in recovery_upload
    assert "if-no-files-found: error" in recovery_upload
    assert "steps.lane_metadata.outcome == 'success'" in metadata_upload
    assert "steps.finalize_lane_metadata.outcome == 'success'" in metadata_upload
    assert "continue-on-error: true" in metadata_upload
    assert "steps.lane_metadata.outputs.snapshot-attested" not in metadata_upload
    assert "steps.lane_metadata_artifact.outcome == 'failure'" in metadata_retry
    assert "continue-on-error" not in metadata_retry
    metadata_name = "extraction-lane-metadata-${{ env.ACTIVE_CHAIN_ID }}-${{ matrix.lane_id }}"
    assert metadata_name in metadata_upload
    assert metadata_name in metadata_retry
    assert "overwrite: true" in metadata_upload
    assert "overwrite: true" in metadata_retry
    assert "steps.lane_metadata.outcome != 'success'" in diagnostic_upload
    assert "steps.finalize_lane_metadata.outputs.artifact-durable != 'true'" in diagnostic_upload
    assert "steps.lane_metadata_artifact.outcome == 'failure'" in diagnostic_upload
    assert "steps.lane_metadata_artifact_retry.outcome != 'success'" in diagnostic_upload
    assert "extraction-lane-diagnostics-only-" in diagnostic_upload
    assert "data/nbadb/nba.duckdb" in diagnostic_upload
    assert "data/nbadb/nba.duckdb.wal" in diagnostic_upload
    assert "lane-state-attestation.json" in complete_upload
    assert "lane-state-attestation.json" in recovery_upload
    assert "artifacts/extraction/lane-metadata.json" in metadata_upload
    assert "lane-state-attestation.json" not in metadata_upload
    assert "lane-state-attestation.json" in diagnostic_upload
    assert "lane-state-untrusted" in diagnostic_upload
    assert complete_name not in diagnostic_upload
    assert recovery_name not in diagnostic_upload
    assert 'expected_names[f"extraction-lane-{chain_id}-{lane_id}"]' in checkpoint_download
    assert 'gh run download "$run_id"' in checkpoint_download
    assert '--name "$artifact_name"' in checkpoint_download
    assert "extraction-lane-recovery-" not in checkpoint_download
    assert extract.index("- name: Upload complete lane artifact") < extract.index(
        "- name: Finalize durable lane artifact receipt"
    )
    assert extract.index("- name: Upload incomplete lane state artifact") < extract.index(
        "- name: Finalize durable lane artifact receipt"
    )
    assert extract.index("- name: Finalize durable lane artifact receipt") < extract.index(
        "- name: Upload lane metadata"
    )
    assert extract.index("- name: Upload lane metadata") < extract.index(
        "- name: Retry lane metadata upload"
    )
    assert extract.index("- name: Retry lane metadata upload") < extract.index(
        "- name: Upload diagnostics-only lane snapshot"
    )
    assert "FINALIZE_LANE_ARTIFACT_RECEIPT" in finalize_receipt


def test_durable_lane_artifact_receipt_is_bound_or_downgraded(
    tmp_path: pathlib.Path,
) -> None:
    extract = _job_block(_workflow_text(), "extract")
    finalizer = _embedded_python(
        _step_block(extract, "Finalize durable lane artifact receipt"),
        "FINALIZE_LANE_ARTIFACT_RECEIPT",
    )
    metadata_path = tmp_path / "artifacts" / "extraction" / "lane-metadata.json"
    metadata_path.parent.mkdir(parents=True)
    original = {
        "status": "complete",
        "raw_status": "complete",
        "state_artifact": {
            "artifact_name": "extraction-lane-chain-1-lane-1",
            "attested": True,
        },
    }
    metadata_path.write_text(json.dumps(original), encoding="utf-8")
    success_env = {
        "COMPLETE_ARTIFACT_DIGEST": "a" * 64,
        "COMPLETE_ARTIFACT_ID": "12345",
        "COMPLETE_ARTIFACT_OUTCOME": "success",
        "FINAL_OUTCOME": "complete",
        "RECOVERY_ARTIFACT_DIGEST": "",
        "RECOVERY_ARTIFACT_ID": "",
        "RECOVERY_ARTIFACT_OUTCOME": "skipped",
        "SNAPSHOT_ATTESTED": "true",
        "GITHUB_OUTPUT": str(tmp_path / "github-output.txt"),
    }

    accepted = _run_python(finalizer, env=success_env, cwd=tmp_path)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["raw_status"] == "complete"
    assert payload["state_artifact"] == {
        "artifact_name": "extraction-lane-chain-1-lane-1",
        "artifact_id": "12345",
        "artifact_digest": f"sha256:{'a' * 64}",
        "attested": True,
        "uploaded": True,
    }
    assert (tmp_path / "github-output.txt").read_text(encoding="utf-8").splitlines() == [
        "artifact-durable=true",
        "final-outcome=complete",
    ]

    metadata_path.write_text(json.dumps(original), encoding="utf-8")
    (tmp_path / "github-output.txt").unlink()
    rejected = _run_python(
        finalizer,
        env=success_env | {"COMPLETE_ARTIFACT_OUTCOME": "failure"},
        cwd=tmp_path,
    )
    assert rejected.returncode == 0, rejected.stderr or rejected.stdout
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pipeline_failure"
    assert payload["raw_status"] == "state-artifact-upload-failed"
    assert payload["failure_class"] == "runner_infrastructure"
    assert payload["root_error_type"] == "StateArtifactUploadFailure"
    assert payload["failure_class_counts"] == {"runner_infrastructure": 1}
    assert payload["root_error_type_counts"] == {"StateArtifactUploadFailure": 1}
    assert payload["state_artifact"] == {
        "artifact_name": "extraction-lane-chain-1-lane-1",
        "attested": False,
        "uploaded": False,
    }
    assert (tmp_path / "github-output.txt").read_text(encoding="utf-8").splitlines() == [
        "artifact-durable=false",
        "final-outcome=pipeline_failure",
    ]


def test_redispatch_preserves_auto_and_enforces_numeric_iteration_cap() -> None:
    dispatch = _job_block(_workflow_text(), "dispatch_next")

    assert 'max_input="$MAX_ITERATIONS"' in dispatch
    assert 'if [ "$max_input" = "auto" ]; then' in dispatch
    assert 'effective_max="$ITERATION_BUDGET"' in dispatch
    assert 'effective_max="$max_input"' in dispatch
    assert 'if [ "$next" -gt "$effective_max" ]; then' in dispatch
    assert '-f max_iterations="$MAX_ITERATIONS"' in dispatch
    assert '-f max_iterations="$effective_max"' not in dispatch


def test_redispatch_rejects_active_or_successful_chain_iteration_before_enqueue() -> None:
    dispatch = _job_block(_workflow_text(), "dispatch_next")

    assert (
        "group: full-extraction-dispatch-${{ inputs.chain_id || github.run_id }}-"
        "iteration-${{ inputs.iteration }}"
    ) in dispatch
    assert 'next_run_name="Full Extraction chain=${CHAIN_ID} iteration=${next}"' in dispatch
    assert "gh api \\" in dispatch
    assert "--paginate" in dispatch
    assert "--slurp" in dispatch
    assert "/actions/workflows/full-extraction.yml/runs" in dispatch
    assert '-f "event=workflow_dispatch"' in dispatch
    assert 'str(run.get("display_title") or "") == expected_run_name' in dispatch
    assert 'str(run.get("status") or "") != "completed"' in dispatch
    assert 'str(run.get("conclusion") or "") == "success"' in dispatch
    assert "Refusing duplicate redispatch for chain $CHAIN_ID iteration $next" in dispatch

    duplicate_lookup = dispatch.index("/actions/workflows/full-extraction.yml/runs")
    duplicate_rejection = dispatch.index("Refusing duplicate redispatch")
    enqueue = dispatch.index("gh workflow run full-extraction.yml")
    assert duplicate_lookup < duplicate_rejection < enqueue


def test_redispatch_allows_failed_history_and_acknowledges_only_the_new_child(
    tmp_path: pathlib.Path,
) -> None:
    dispatch = _job_block(_workflow_text(), "dispatch_next")
    precheck = _embedded_python(dispatch, "CHILD_RUN_PRECHECK")
    matcher = _embedded_python(dispatch, "CHILD_RUN_MATCHER")
    run_name = "Full Extraction chain=123 iteration=2"
    runs_path = tmp_path / "runs.json"
    existing_ids_path = tmp_path / "existing.json"
    child_path = tmp_path / "child.json"
    failed_run = {
        "id": 100,
        "display_title": run_name,
        "status": "completed",
        "conclusion": "failure",
        "html_url": "https://example.test/runs/100",
    }
    cancelled_run = {
        "id": 101,
        "display_title": run_name,
        "status": "completed",
        "conclusion": "cancelled",
        "html_url": "https://example.test/runs/101",
    }
    runs_path.write_text(
        json.dumps([{"workflow_runs": [failed_run, cancelled_run]}]),
        encoding="utf-8",
    )
    env = {
        "RUNS_PATH": str(runs_path),
        "EXISTING_CHILD_RUN_IDS_PATH": str(existing_ids_path),
        "EXPECTED_RUN_NAME": run_name,
    }

    precheck_result = _run_python(precheck, env=env)

    assert precheck_result.returncode == 0
    assert precheck_result.stdout.strip() == ""
    assert json.loads(existing_ids_path.read_text(encoding="utf-8")) == ["100", "101"]

    new_run = {
        "id": 102,
        "display_title": run_name,
        "status": "queued",
        "conclusion": None,
        "html_url": "https://example.test/runs/102",
    }
    runs_path.write_text(
        json.dumps([{"workflow_runs": [failed_run, cancelled_run, new_run]}]),
        encoding="utf-8",
    )
    match_result = _run_python(
        matcher,
        env={**env, "CHILD_RUN_PATH": str(child_path)},
    )

    assert match_result.returncode == 0, match_result.stderr or match_result.stdout
    assert json.loads(child_path.read_text(encoding="utf-8")) == {
        "display_title": run_name,
        "id": "102",
        "url": "https://example.test/runs/102",
    }


def test_redispatch_precheck_blocks_active_and_successful_runs(tmp_path: pathlib.Path) -> None:
    precheck = _embedded_python(
        _job_block(_workflow_text(), "dispatch_next"),
        "CHILD_RUN_PRECHECK",
    )
    run_name = "Full Extraction chain=123 iteration=2"
    runs_path = tmp_path / "runs.json"
    existing_ids_path = tmp_path / "existing.json"
    runs_path.write_text(
        json.dumps(
            [
                {
                    "workflow_runs": [
                        {
                            "id": 200,
                            "display_title": run_name,
                            "status": "in_progress",
                            "conclusion": None,
                            "html_url": "https://example.test/runs/200",
                        },
                        {
                            "id": 201,
                            "display_title": run_name,
                            "status": "completed",
                            "conclusion": "success",
                            "html_url": "https://example.test/runs/201",
                        },
                    ]
                }
            ]
        ),
        encoding="utf-8",
    )

    result = _run_python(
        precheck,
        env={
            "RUNS_PATH": str(runs_path),
            "EXISTING_CHILD_RUN_IDS_PATH": str(existing_ids_path),
            "EXPECTED_RUN_NAME": run_name,
        },
    )

    assert result.returncode == 0
    assert "200:in_progress:None" in result.stdout
    assert "201:completed:success" in result.stdout


def test_workflow_concurrency_serializes_vpn_chains_but_not_direct_chains() -> None:
    workflow = _workflow_text()
    workflow_concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]

    assert "inputs.network_mode == 'direct'" in workflow_concurrency
    assert "full-extraction-direct-{0}-{1}" in workflow_concurrency
    assert "inputs.chain_id || github.run_id" in workflow_concurrency
    assert "'nbadb-vpn-full-extraction'" in workflow_concurrency
    assert "github.ref" not in workflow_concurrency
    assert "queue: max" in workflow_concurrency
    assert "cancel-in-progress: false" in workflow_concurrency


def test_redispatch_preserves_requested_auto_network_mode() -> None:
    dispatch = _job_block(_workflow_text(), "dispatch_next")

    assert "NETWORK_MODE: ${{ inputs.network_mode }}" in dispatch
    assert "NETWORK_MODE: ${{ needs.preflight.outputs.effective-network-mode" not in dispatch
    assert '-f network_mode="$NETWORK_MODE"' in dispatch


def test_manual_artifact_handoff_requires_and_verifies_original_chain_id(
    tmp_path: pathlib.Path,
) -> None:
    plan = _job_block(_workflow_text(), "plan")
    missing_chain_error = (
        "lane_manifest_run_id requires chain_id so workflow concurrency and discovery artifacts "
        "retain the original chain identity"
    )
    assert missing_chain_error in plan
    assert plan.index(missing_chain_error) < plan.index('gh run download "$LANE_MANIFEST_RUN_ID"')

    verifier = _embedded_python(plan, "MANUAL_HANDOFF_CHAIN_VERIFIER")
    manifest_path = tmp_path / "manifest.json"
    source_sha = "a" * 40
    manifest_path.write_text(
        json.dumps({"chain_id": "12345", "workflow_source_sha": source_sha}) + "\n",
        encoding="utf-8",
    )
    base_env = {
        "MANIFEST_PATH": str(manifest_path),
        "REQUESTED_CHAIN_ID": "12345",
        "WORKFLOW_SOURCE_SHA": source_sha,
    }

    matching = _run_python(
        verifier,
        env={
            **base_env,
            "ARTIFACT_NAME": "full-extraction-next-manifest-12345-iter-2",
        },
    )
    assert matching.returncode == 0, matching.stderr or matching.stdout
    assert "Verified manual manifest handoff for chain 12345" in matching.stdout

    wrong_standard_name = _run_python(
        verifier,
        env={**base_env, "ARTIFACT_NAME": "full-extraction-manifest-99999"},
    )
    assert wrong_standard_name.returncode == 1
    assert "artifact name does not match requested chain_id" in wrong_standard_name.stdout

    manifest_path.write_text(
        json.dumps({"workflow_source_sha": source_sha}) + "\n",
        encoding="utf-8",
    )
    unprovable_custom_name = _run_python(
        verifier,
        env={**base_env, "ARTIFACT_NAME": "manual-manifest"},
    )
    assert unprovable_custom_name.returncode == 1
    assert "Unable to verify original chain identity" in unprovable_custom_name.stdout

    manifest_path.write_text(
        json.dumps({"chain_id": "99999", "workflow_source_sha": source_sha}) + "\n",
        encoding="utf-8",
    )
    mismatched_manifest = _run_python(
        verifier,
        env={**base_env, "ARTIFACT_NAME": "manual-manifest"},
    )
    assert mismatched_manifest.returncode == 1
    assert "Manifest chain identity does not match" in mismatched_manifest.stdout

    manifest_path.write_text(
        json.dumps({"chain_id": "12345", "workflow_source_sha": "b" * 40}) + "\n",
        encoding="utf-8",
    )
    mismatched_source = _run_python(
        verifier,
        env={**base_env, "ARTIFACT_NAME": "manual-manifest"},
    )
    assert mismatched_source.returncode == 1
    assert "Manifest source SHA does not match" in mismatched_source.stdout

    assert 'manifest["workflow_source_sha"] = os.environ["WORKFLOW_SOURCE_SHA"].lower()' in plan
    lane_control = _job_block(_workflow_text(), "lane_control")
    assert 'payload["workflow_source_sha"] = os.environ["WORKFLOW_SOURCE_SHA"].lower()' in (
        lane_control
    )


def test_resume_source_manifest_requires_matching_chain_and_source_sha(
    tmp_path: pathlib.Path,
) -> None:
    plan = _job_block(_workflow_text(), "plan")
    verifier = _embedded_python(plan, "RESUME_SOURCE_MANIFEST_VERIFIER")
    manifest_path = tmp_path / "manifest.json"
    source_sha = "a" * 40
    base_env = {
        "MANIFEST_PATH": str(manifest_path),
        "REQUESTED_CHAIN_ID": "12345",
        "WORKFLOW_SOURCE_SHA": source_sha,
    }

    manifest_path.write_text(
        json.dumps({"chain_id": "12345", "workflow_source_sha": source_sha}) + "\n",
        encoding="utf-8",
    )
    matching = _run_python(verifier, env=base_env)
    assert matching.returncode == 0, matching.stderr or matching.stdout
    assert "Verified resume source manifest for chain 12345" in matching.stdout

    manifest_path.write_text(
        json.dumps({"chain_id": "99999", "workflow_source_sha": source_sha}) + "\n",
        encoding="utf-8",
    )
    wrong_chain = _run_python(verifier, env=base_env)
    assert wrong_chain.returncode == 1
    assert "chain identity does not match" in wrong_chain.stdout

    manifest_path.write_text(
        json.dumps({"chain_id": "12345", "workflow_source_sha": "b" * 40}) + "\n",
        encoding="utf-8",
    )
    wrong_source = _run_python(verifier, env=base_env)
    assert wrong_source.returncode == 1
    assert "manifest SHA does not match" in wrong_source.stdout

    manifest_path.write_text("{}\n", encoding="utf-8")
    missing_provenance = _run_python(verifier, env=base_env)
    assert missing_provenance.returncode == 1
    assert "'<missing>'" in missing_provenance.stdout


def test_checkpoint_generation_derives_from_trusted_manifest_pointer(
    tmp_path: pathlib.Path,
) -> None:
    build_step = _step_block(_job_block(_workflow_text(), "lane_control"), "Build next manifest")
    resolver = _embedded_python(build_step, "CHECKPOINT_GENERATION_RESOLVER")
    manifest_path = tmp_path / "manifest.json"
    chain_id = "fixture-chain"
    source_sha = "a" * 40
    base_manifest = {
        "chain_id": chain_id,
        "chain_state": {},
        "workflow_source_sha": source_sha,
    }
    env = {
        "CHAIN_ID": chain_id,
        "CURRENT_MANIFEST": str(manifest_path),
        "WORKFLOW_SOURCE_SHA": source_sha,
    }

    manifest_path.write_text(json.dumps(base_manifest), encoding="utf-8")
    fresh = _run_python(resolver, env=env)
    assert fresh.returncode == 0, fresh.stderr or fresh.stdout
    assert fresh.stdout.strip() == "1"

    base_manifest["chain_state"] = {
        "latest_checkpoint_run_id": "123456",
        "latest_checkpoint_artifact_name": (f"full-extraction-checkpoint-{chain_id}-iter-7"),
        "latest_checkpoint_coverage_hash": "c" * 64,
        "latest_checkpoint_generation": 7,
    }
    manifest_path.write_text(json.dumps(base_manifest), encoding="utf-8")
    resumed = _run_python(resolver, env=env)
    assert resumed.returncode == 0, resumed.stderr or resumed.stdout
    assert resumed.stdout.strip() == "8"

    base_manifest["chain_state"]["latest_checkpoint_artifact_name"] = (
        f"full-extraction-checkpoint-{chain_id}-iter-6"
    )
    manifest_path.write_text(json.dumps(base_manifest), encoding="utf-8")
    wrong_suffix = _run_python(resolver, env=env)
    assert wrong_suffix.returncode == 1
    assert "artifact suffix does not match its generation" in wrong_suffix.stderr

    base_manifest["chain_state"] = {
        "latest_checkpoint_generation": 7,
        "latest_checkpoint_artifact_name": (f"full-extraction-checkpoint-{chain_id}-iter-7"),
        "latest_checkpoint_coverage_hash": "c" * 64,
    }
    manifest_path.write_text(json.dumps(base_manifest), encoding="utf-8")
    missing_run = _run_python(resolver, env=env)
    assert missing_run.returncode == 1
    assert "requires a valid source run ID" in missing_run.stderr

    base_manifest["chain_state"] = {
        "latest_checkpoint_artifact_name": (f"full-extraction-checkpoint-{chain_id}-iter-7"),
        "latest_checkpoint_generation": 7,
        "latest_checkpoint_run_id": "123456",
    }
    manifest_path.write_text(json.dumps(base_manifest), encoding="utf-8")
    missing_coverage = _run_python(resolver, env=env)
    assert missing_coverage.returncode == 1
    assert "requires a coverage SHA-256" in missing_coverage.stderr

    base_manifest["chain_state"] = {"latest_checkpoint_generation": True}
    manifest_path.write_text(json.dumps(base_manifest), encoding="utf-8")
    boolean_generation = _run_python(resolver, env=env)
    assert boolean_generation.returncode == 1
    assert "must be a non-negative integer" in boolean_generation.stderr

    base_manifest["chain_state"] = {}
    base_manifest["workflow_source_sha"] = "b" * 40
    manifest_path.write_text(json.dumps(base_manifest), encoding="utf-8")
    wrong_source = _run_python(resolver, env=env)
    assert wrong_source.returncode == 1
    assert "manifest source SHA does not match" in wrong_source.stderr

    coverage_resolver = _embedded_python(build_step, "CHECKPOINT_COVERAGE_RESOLVER")
    completed_lane = FullExtractionLane(
        lane_id="completed",
        lane_index=0,
        lane_name="Completed",
        lane_kind="static",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("static_players",),
        resume_only=True,
    )
    active_lane = FullExtractionLane(
        lane_id="active",
        lane_index=1,
        lane_name="Active",
        lane_kind="static",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("static_teams",),
    )
    provisional_path = tmp_path / "provisional-manifest.json"
    provisional_path.write_text(
        json.dumps(manifest_payload([completed_lane, active_lane])),
        encoding="utf-8",
    )
    resolved_coverage = _run_python(
        coverage_resolver,
        env={"PROVISIONAL_MANIFEST": str(provisional_path)},
    )
    assert resolved_coverage.returncode == 0, resolved_coverage.stderr or resolved_coverage.stdout
    assert (
        resolved_coverage.stdout.strip()
        == manifest_payload([completed_lane])["coverage_fingerprint"]
    )

    assert '--latest-checkpoint-generation "$CHECKPOINT_GENERATION"' in build_step
    assert '--latest-checkpoint-coverage-hash "$CHECKPOINT_COVERAGE_HASH"' in build_step
    assert "CHECKPOINT_COVERAGE_RESOLVER" in build_step
    assert "iter-${CHECKPOINT_GENERATION}" in build_step
    assert '--latest-checkpoint-generation "$ITERATION"' not in build_step


def test_checkpoint_result_validator_rejects_generation_and_suffix_drift(
    tmp_path: pathlib.Path,
) -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    validator = _embedded_python(checkpoint, "CHECKPOINT_RESULT_VALIDATOR")
    report_path = tmp_path / "checkpoint-report.json"
    manifest_path = tmp_path / "checkpoint-manifest.json"
    database_path = tmp_path / "nba.duckdb"
    output_path = tmp_path / "github-output.txt"
    database_path.write_bytes(b"checkpoint")
    chain_id = "fixture-chain"
    run_id = "222"
    source_sha = "a" * 40
    expected_generation = 8
    coverage_hash = "c" * 64
    artifact_name = f"full-extraction-checkpoint-{chain_id}-iter-{expected_generation}"
    contract_blocked_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [],
    }
    report = {
        "active_lane_count": 0,
        "chain_id": chain_id,
        "checkpoint_generation": expected_generation,
        "complete_lane_count": 1,
        "coverage_fingerprint": coverage_hash,
        "output_path": str(database_path),
        "previous_checkpoint_generation": expected_generation - 1,
        "run_id": run_id,
        "artifact_name": artifact_name,
        "source_sha": source_sha,
        "terminal_ready": True,
        "contract_blocked_lane_count": 0,
        "contract_blocked_evidence": contract_blocked_evidence,
        "contract_blocked_evidence_sha256": hashlib.sha256(
            json.dumps(
                contract_blocked_evidence,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }
    manifest = {
        "chain_id": chain_id,
        "chain_state": {
            "latest_checkpoint_artifact_name": artifact_name,
            "latest_checkpoint_coverage_hash": coverage_hash,
            "latest_checkpoint_generation": expected_generation,
            "latest_checkpoint_run_id": run_id,
        },
        "workflow_source_sha": source_sha,
    }
    env = {
        "CHAIN_ID": chain_id,
        "CHECKPOINT_ARTIFACT_NAME": artifact_name,
        "CHECKPOINT_MANIFEST_PATH": str(manifest_path),
        "CHECKPOINT_REPORT_PATH": str(report_path),
        "CURRENT_RUN_ID": run_id,
        "EXPECTED_CHECKPOINT_GENERATION": str(expected_generation),
        "GITHUB_OUTPUT": str(output_path),
        "LANE_CONTROL_ACTIVE_LANE_COUNT": "0",
        "WORKFLOW_SOURCE_SHA": source_sha,
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    accepted = _run_python(validator, env=env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        f"artifact_name={artifact_name}",
        f"checkpoint_generation={expected_generation}",
        f"coverage_fingerprint={coverage_hash}",
        "terminal_ready=true",
        "active_lane_count=0",
    ]

    output_path.unlink()
    report["checkpoint_generation"] = expected_generation - 1
    report_path.write_text(json.dumps(report), encoding="utf-8")
    stale_report = _run_python(validator, env=env)
    assert stale_report.returncode == 1
    assert "Lane-control/checkpoint generation disagreement" in stale_report.stdout
    assert not output_path.exists()

    report["checkpoint_generation"] = expected_generation
    report_path.write_text(json.dumps(report), encoding="utf-8")
    wrong_suffix = _run_python(
        validator,
        env={
            **env,
            "CHECKPOINT_ARTIFACT_NAME": (
                f"full-extraction-checkpoint-{chain_id}-iter-{expected_generation - 1}"
            ),
        },
    )
    assert wrong_suffix.returncode == 1
    assert "Checkpoint artifact suffix/generation disagreement" in wrong_suffix.stdout
    assert not output_path.exists()

    report["coverage_fingerprint"] = "d" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")
    wrong_coverage = _run_python(validator, env=env)
    assert wrong_coverage.returncode == 1
    assert "manifest/report coverage fingerprint disagreement" in wrong_coverage.stdout
    assert not output_path.exists()
    report["coverage_fingerprint"] = coverage_hash
    report_path.write_text(json.dumps(report), encoding="utf-8")

    manifest["chain_state"]["latest_checkpoint_generation"] = expected_generation - 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    stale_manifest = _run_python(validator, env=env)
    assert stale_manifest.returncode == 1
    assert "Checkpoint manifest/report generation disagreement" in stale_manifest.stdout
    assert not output_path.exists()


def test_resume_source_creates_validated_pending_contract_blocked_commitment(
    tmp_path: pathlib.Path,
) -> None:
    plan = _job_block(_workflow_text(), "plan")
    builder = _embedded_python(
        plan,
        "RESUME_SOURCE_PENDING_CONTRACT_BLOCKED_EVIDENCE",
    )
    lane, expected_row, manifest_lane = _contract_blocked_fixture(
        "blocked-pending",
        1946,
        1947,
    )
    _, existing_pending_row, _ = _contract_blocked_fixture(
        "blocked-existing-pending",
        1948,
        1949,
    )
    source_path = tmp_path / "source-manifest.json"
    resume_path = tmp_path / "resume-manifest.json"
    audit_path = tmp_path / "resume-audit.json"
    final_path = tmp_path / "final-manifest.json"
    source_path.write_text(
        json.dumps({"lanes": [manifest_lane]}),
        encoding="utf-8",
    )
    resume_path.write_text(
        json.dumps({"resume_summary": {"contract_blocked_lane_count": 1}}),
        encoding="utf-8",
    )
    audit_path.write_text(
        json.dumps({"contract_blocked_lanes": []}),
        encoding="utf-8",
    )
    final_manifest = manifest_payload([], max_matrix_lanes=1)
    final_manifest["chain_state"]["pending_contract_blocked_evidence"] = [existing_pending_row]
    existing_pending_bundle = {
        "schema_version": 1,
        "contract_blocked_lanes": [existing_pending_row],
    }
    final_manifest["chain_state"]["pending_contract_blocked_evidence_sha256"] = hashlib.sha256(
        json.dumps(
            existing_pending_bundle,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    final_path.write_text(json.dumps(final_manifest), encoding="utf-8")
    env = {
        "SOURCE_MANIFEST_PATH": str(source_path),
        "RESUME_MANIFEST_PATH": str(resume_path),
        "RESUME_AUDIT_PATH": str(audit_path),
        "FINAL_MANIFEST_PATH": str(final_path),
    }

    accepted = _run_python(builder, env=env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    state = json.loads(final_path.read_text(encoding="utf-8"))["chain_state"]
    expected_pending_rows = sorted(
        [expected_row, existing_pending_row],
        key=lambda row: str(row["lane_id"]),
    )
    assert state["pending_contract_blocked_evidence"] == expected_pending_rows
    pending_bundle = {
        "schema_version": 1,
        "contract_blocked_lanes": expected_pending_rows,
    }
    assert (
        state["pending_contract_blocked_evidence_sha256"]
        == hashlib.sha256(
            json.dumps(pending_bundle, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert lane.lane_id not in {
        str(item.get("lane_id") or "")
        for item in json.loads(final_path.read_text(encoding="utf-8")).get("lanes", [])
    }

    source_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    resume_path.write_text(
        json.dumps({"resume_summary": {"contract_blocked_lane_count": 0}}),
        encoding="utf-8",
    )
    final_path.write_text(
        json.dumps(manifest_payload([], max_matrix_lanes=1)),
        encoding="utf-8",
    )
    zero_pending = _run_python(builder, env=env)
    assert zero_pending.returncode == 0, zero_pending.stderr or zero_pending.stdout
    zero_state = json.loads(final_path.read_text(encoding="utf-8"))["chain_state"]
    assert zero_state["pending_contract_blocked_evidence"] == []
    assert zero_state["pending_contract_blocked_evidence_sha256"] == ""

    source_path.write_text(
        json.dumps({"lanes": [manifest_lane]}),
        encoding="utf-8",
    )
    resume_path.write_text(
        json.dumps({"resume_summary": {"contract_blocked_lane_count": 0}}),
        encoding="utf-8",
    )
    rejected = _run_python(builder, env=env)
    assert rejected.returncode == 1
    assert "count does not match validated evidence" in rejected.stderr


def test_lane_control_merges_and_clears_pending_contract_blocked_commitment(
    tmp_path: pathlib.Path,
) -> None:
    lane_control = _job_block(_workflow_text(), "lane_control")
    postprocessor = _embedded_python(
        lane_control,
        "LANE_CONTROL_CONTRACT_BLOCKED_POSTPROCESSOR",
    )
    _, previous_row, _ = _contract_blocked_fixture("blocked-previous", 1946, 1947)
    _, pending_row, _ = _contract_blocked_fixture("blocked-pending", 1948, 1949)
    _, current_row, _ = _contract_blocked_fixture("blocked-current", 1950, 1951)

    def evidence_digest(rows: list[dict[str, object]]) -> str:
        return hashlib.sha256(
            json.dumps(
                {"schema_version": 1, "contract_blocked_lanes": rows},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    artifacts = tmp_path / "artifacts" / "full-extraction"
    artifacts.mkdir(parents=True)
    current_manifest_path = artifacts / "current-manifest.json"
    next_manifest_path = artifacts / "next-manifest.json"
    audit_path = artifacts / "extraction-audit.json"
    previous_rows = [previous_row]
    pending_rows = [pending_row]
    current_manifest = {
        "chain_state": {
            "artifact_run_ids": [],
            "contract_blocked_evidence": previous_rows,
            "contract_blocked_evidence_sha256": evidence_digest(previous_rows),
            "pending_contract_blocked_evidence": pending_rows,
            "pending_contract_blocked_evidence_sha256": evidence_digest(pending_rows),
        }
    }
    empty_manifest = manifest_payload([], max_matrix_lanes=1)
    empty_manifest["resume_summary"] = {
        "active_lane_count": 0,
        "resume_only_lane_count": 0,
        "contract_blocked_lane_count": 1,
    }
    current_manifest_path.write_text(json.dumps(current_manifest), encoding="utf-8")
    next_manifest_path.write_text(json.dumps(empty_manifest), encoding="utf-8")
    audit_path.write_text(
        json.dumps({"contract_blocked_lanes": [current_row]}),
        encoding="utf-8",
    )
    env = {
        "CHAIN_ID": "fixture-chain",
        "WORKFLOW_SOURCE_SHA": "a" * 40,
        "CHECKPOINT_ARTIFACT_NAME": "full-extraction-checkpoint-fixture-chain-iter-1",
        "CHECKPOINT_GENERATION": "1",
        "CHECKPOINT_COVERAGE_HASH": "b" * 64,
        "ITERATION": "1",
        "GITHUB_OUTPUT": str(tmp_path / "github-output.txt"),
    }

    accepted = _run_python(postprocessor, env=env, cwd=tmp_path)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    next_state = json.loads(next_manifest_path.read_text(encoding="utf-8"))["chain_state"]
    merged_rows = sorted(
        [previous_row, pending_row, current_row],
        key=lambda row: str(row["lane_id"]),
    )
    assert next_state["previous_contract_blocked_evidence"] == previous_rows
    assert next_state["contract_blocked_evidence"] == merged_rows
    assert next_state["contract_blocked_evidence_sha256"] == evidence_digest(merged_rows)
    assert next_state["pending_contract_blocked_evidence"] == []
    assert next_state["pending_contract_blocked_evidence_sha256"] == ""

    current_manifest["chain_state"]["pending_contract_blocked_evidence_sha256"] = "0" * 64
    current_manifest_path.write_text(json.dumps(current_manifest), encoding="utf-8")
    next_manifest_path.write_text(json.dumps(empty_manifest), encoding="utf-8")
    rejected = _run_python(postprocessor, env=env, cwd=tmp_path)
    assert rejected.returncode == 1
    assert "pending blocked evidence digest does not match" in rejected.stderr

    current_manifest["chain_state"]["pending_contract_blocked_evidence"] = []
    current_manifest["chain_state"]["pending_contract_blocked_evidence_sha256"] = ""
    current_manifest_path.write_text(json.dumps(current_manifest), encoding="utf-8")
    next_manifest_path.write_text(json.dumps(empty_manifest), encoding="utf-8")
    zero_pending = _run_python(postprocessor, env=env, cwd=tmp_path)
    assert zero_pending.returncode == 0, zero_pending.stderr or zero_pending.stdout
    zero_pending_state = json.loads(next_manifest_path.read_text(encoding="utf-8"))["chain_state"]
    assert zero_pending_state["pending_contract_blocked_evidence"] == []
    assert zero_pending_state["pending_contract_blocked_evidence_sha256"] == ""


def test_contract_blocked_evidence_is_cumulative_and_digest_bound(
    tmp_path: pathlib.Path,
) -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    binder = _embedded_python(checkpoint, "CHECKPOINT_CONTRACT_BLOCKED_EVIDENCE_BINDER")
    assert (
        'current_manifest="$(find lane-control-artifact -name current-manifest.json' in checkpoint
    )
    assert 'CURRENT_MANIFEST_PATH="$current_manifest"' in checkpoint
    audit_path = tmp_path / "audit.json"
    previous_path = tmp_path / "previous-report.json"
    report_path = tmp_path / "checkpoint-report.json"

    def blocked_row(
        lane_id: str, season_start: int, season_end: int
    ) -> tuple[dict[str, object], dict[str, object]]:
        lane = FullExtractionLane(
            lane_id=lane_id,
            lane_index=0,
            lane_name=lane_id,
            lane_kind="historical",
            season_start=season_start,
            season_end=season_end,
            patterns=("player_team_season",),
            season_types=(),
            endpoints=("video_details",),
            timeout_seconds=1,
        )
        coverage_hash = _coverage_hash_for_lane(lane)
        row = _canonical_contract_blocked_audit_row(
            lane_id,
            {
                "lane_kind": lane.lane_kind,
                "endpoints": list(lane.endpoints),
                "patterns": list(lane.patterns),
                "season_start": season_start,
                "season_end": season_end,
                "season_types": [],
                "context_measures": [],
                "coverage_units_hash": coverage_hash,
            },
        )
        manifest_lane = {
            "lane_id": lane_id,
            "lane_kind": lane.lane_kind,
            "endpoints": list(lane.endpoints),
            "patterns": list(lane.patterns),
            "season_start": season_start,
            "season_end": season_end,
            "season_types": [],
            "context_measures": [],
            "coverage_units_hash": coverage_hash,
        }
        return row, manifest_lane

    previous_row, _previous_manifest_lane = blocked_row("blocked-old", 1946, 1947)
    pending_row, _pending_manifest_lane = blocked_row("blocked-pending", 1948, 1949)
    current_row, current_manifest_lane = blocked_row("blocked-new", 1950, 1951)
    previous_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [previous_row],
    }
    previous_report = {
        "contract_blocked_lane_count": 1,
        "contract_blocked_evidence": previous_evidence,
        "contract_blocked_evidence_sha256": hashlib.sha256(
            json.dumps(previous_evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    previous_digest = previous_report["contract_blocked_evidence_sha256"]
    pending_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [pending_row],
    }
    pending_digest = hashlib.sha256(
        json.dumps(pending_evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    merged_rows = sorted(
        [previous_row, pending_row, current_row],
        key=lambda row: str(row["lane_id"]),
    )
    merged_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": merged_rows,
    }
    merged_digest = hashlib.sha256(
        json.dumps(merged_evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    audit_path.write_text(json.dumps({"contract_blocked_lanes": [current_row]}), encoding="utf-8")
    previous_path.write_text(json.dumps(previous_report), encoding="utf-8")
    report_path.write_text("{}\n", encoding="utf-8")
    current_manifest_path = tmp_path / "current-manifest.json"
    current_manifest_path.write_text(
        json.dumps(
            {
                "lanes": [current_manifest_lane],
                "chain_state": {
                    "contract_blocked_evidence": [previous_row],
                    "contract_blocked_evidence_sha256": previous_digest,
                    "pending_contract_blocked_evidence": [pending_row],
                    "pending_contract_blocked_evidence_sha256": pending_digest,
                },
            }
        ),
        encoding="utf-8",
    )
    next_manifest_path = tmp_path / "next-manifest.json"
    next_manifest_path.write_text(
        json.dumps(
            {
                "chain_state": {
                    "contract_blocked_evidence": merged_rows,
                    "contract_blocked_evidence_sha256": merged_digest,
                    "pending_contract_blocked_evidence": [],
                    "pending_contract_blocked_evidence_sha256": "",
                }
            }
        ),
        encoding="utf-8",
    )
    verified_previous_path = tmp_path / "verified-previous.json"
    verified_previous_path.write_text(
        json.dumps(
            {
                "contract_blocked_evidence_sha256": previous_report[
                    "contract_blocked_evidence_sha256"
                ]
            }
        ),
        encoding="utf-8",
    )
    env = {
        "CHECKPOINT_REPORT_PATH": str(report_path),
        "CURRENT_MANIFEST_PATH": str(current_manifest_path),
        "NEXT_MANIFEST_PATH": str(next_manifest_path),
        "EXTRACTION_AUDIT_PATH": str(audit_path),
        "LANE_CONTROL_CONTRACT_BLOCKED_LANE_COUNT": "1",
        "PREVIOUS_CHECKPOINT_REPORT_PATH": str(previous_path),
        "VERIFIED_PREVIOUS_CHECKPOINT_PATH": str(verified_previous_path),
    }

    accepted = _run_python(binder, env=env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    bound_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert bound_report["contract_blocked_lane_count"] == 3
    assert [
        row["lane_id"]
        for row in bound_report["contract_blocked_evidence"]["contract_blocked_lanes"]
    ] == ["blocked-new", "blocked-old", "blocked-pending"]
    assert bound_report["contract_blocked_evidence_sha256"] == merged_digest

    current_payload = json.loads(current_manifest_path.read_text(encoding="utf-8"))
    current_payload["chain_state"]["pending_contract_blocked_evidence_sha256"] = "0" * 64
    current_manifest_path.write_text(json.dumps(current_payload), encoding="utf-8")
    pending_mismatch = _run_python(binder, env=env)
    assert pending_mismatch.returncode == 1
    assert "pending contract-blocked evidence digest does not match" in (pending_mismatch.stderr)
    current_payload["chain_state"]["pending_contract_blocked_evidence_sha256"] = pending_digest
    current_manifest_path.write_text(json.dumps(current_payload), encoding="utf-8")

    next_payload = json.loads(next_manifest_path.read_text(encoding="utf-8"))
    next_payload["chain_state"]["pending_contract_blocked_evidence"] = [pending_row]
    next_payload["chain_state"]["pending_contract_blocked_evidence_sha256"] = pending_digest
    next_manifest_path.write_text(json.dumps(next_payload), encoding="utf-8")
    uncleared_pending = _run_python(binder, env=env)
    assert uncleared_pending.returncode == 1
    assert "did not clear pending blocked evidence" in uncleared_pending.stderr
    next_payload["chain_state"]["pending_contract_blocked_evidence"] = []
    next_payload["chain_state"]["pending_contract_blocked_evidence_sha256"] = ""
    next_manifest_path.write_text(json.dumps(next_payload), encoding="utf-8")

    zero_pending_current = json.loads(json.dumps(current_payload))
    zero_pending_current["chain_state"]["pending_contract_blocked_evidence"] = []
    zero_pending_current["chain_state"]["pending_contract_blocked_evidence_sha256"] = ""
    zero_pending_rows = sorted(
        [previous_row, current_row],
        key=lambda row: str(row["lane_id"]),
    )
    zero_pending_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": zero_pending_rows,
    }
    zero_pending_next = {
        "chain_state": {
            "contract_blocked_evidence": zero_pending_rows,
            "contract_blocked_evidence_sha256": hashlib.sha256(
                json.dumps(
                    zero_pending_evidence,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "pending_contract_blocked_evidence": [],
            "pending_contract_blocked_evidence_sha256": "",
        }
    }
    current_manifest_path.write_text(json.dumps(zero_pending_current), encoding="utf-8")
    next_manifest_path.write_text(json.dumps(zero_pending_next), encoding="utf-8")
    report_path.write_text("{}\n", encoding="utf-8")
    zero_pending = _run_python(binder, env=env)
    assert zero_pending.returncode == 0, zero_pending.stderr or zero_pending.stdout

    current_manifest_path.write_text(json.dumps(current_payload), encoding="utf-8")
    next_manifest_path.write_text(json.dumps(next_payload), encoding="utf-8")
    report_path.write_text("{}\n", encoding="utf-8")

    previous_report["contract_blocked_evidence_sha256"] = "0" * 64
    previous_path.write_text(json.dumps(previous_report), encoding="utf-8")
    rejected = _run_python(binder, env=env)
    assert rejected.returncode == 1
    assert "evidence digest does not match" in rejected.stderr

    previous_path.write_text(
        json.dumps(
            previous_report
            | {
                "contract_blocked_evidence_sha256": hashlib.sha256(
                    json.dumps(previous_evidence, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    current_manifest_path.write_text(
        json.dumps(
            {
                "lanes": [current_manifest_lane],
                "chain_state": {
                    "contract_blocked_evidence": [previous_row],
                    "contract_blocked_evidence_sha256": "f" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    ancestry_mismatch = _run_python(binder, env=env)
    assert ancestry_mismatch.returncode == 1
    assert "chain-state contract-blocked evidence digest does not match" in (
        ancestry_mismatch.stderr
    )

    current_manifest_path.write_text(
        json.dumps(
            {
                "lanes": [],
                "chain_state": {
                    "contract_blocked_evidence": [previous_row],
                    "contract_blocked_evidence_sha256": previous_digest,
                },
            }
        ),
        encoding="utf-8",
    )
    outside_manifest = _run_python(binder, env=env)
    assert outside_manifest.returncode == 1
    assert "outside the current manifest" in outside_manifest.stderr

    current_manifest_path.write_text(
        json.dumps(
            {
                "lanes": [current_manifest_lane],
                "chain_state": {
                    "contract_blocked_evidence": [previous_row],
                    "contract_blocked_evidence_sha256": previous_digest,
                },
            }
        ),
        encoding="utf-8",
    )
    next_manifest_path.write_text(
        json.dumps(
            {
                "chain_state": {
                    "contract_blocked_evidence": [previous_row],
                    "contract_blocked_evidence_sha256": previous_digest,
                }
            }
        ),
        encoding="utf-8",
    )
    next_commitment_mismatch = _run_python(binder, env=env)
    assert next_commitment_mismatch.returncode == 1
    assert "blocked evidence does not match next-manifest commitment" in (
        next_commitment_mismatch.stderr
    )


def test_terminal_identity_uses_verified_checkpoint_coverage_and_bound_evidence(
    tmp_path: pathlib.Path,
) -> None:
    workflow = _workflow_text()
    merge = _job_block(workflow, "merge")
    publish = _job_block(workflow, "publish")
    identity_step = _step_block(merge, "Validate terminal checkpoint identity")
    binder = _embedded_python(identity_step, "TERMINAL_CHECKPOINT_IDENTITY_BINDER")
    verified_path = tmp_path / "verified.json"
    report_path = tmp_path / "checkpoint-report.json"
    identity_path = tmp_path / "terminal-assurance-report.json"
    output_path = tmp_path / "github-output.txt"
    coverage = "c" * 64
    evidence = {"schema_version": 1, "contract_blocked_lanes": []}
    evidence_digest = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    verified_path.write_text(
        json.dumps(
            {
                "artifact_name": "checkpoint",
                "checkpoint_generation": 3,
                "coverage_fingerprint": coverage,
                "database_sha256": "d" * 64,
            }
        ),
        encoding="utf-8",
    )
    report = {
        "active_lane_count": 0,
        "contract_blocked_evidence": evidence,
        "contract_blocked_evidence_sha256": evidence_digest,
        "contract_blocked_lane_count": 0,
        "coverage_fingerprint": coverage,
        "terminal_ready": True,
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    env = {
        "CHAIN_ID": "fixture-chain",
        "CHECKPOINT_REPORT_PATH": str(report_path),
        "GITHUB_OUTPUT": str(output_path),
        "TERMINAL_IDENTITY_PATH": str(identity_path),
        "VERIFIED_CHECKPOINT_PATH": str(verified_path),
        "WORKFLOW_SOURCE_SHA": "a" * 40,
    }

    accepted = _run_python(binder, env=env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    assert identity["coverage_fingerprint"] == coverage
    assert identity["contract_blocked_evidence_sha256"] == evidence_digest

    report["coverage_fingerprint"] = "e" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")
    rejected = _run_python(binder, env=env)
    assert rejected.returncode == 1
    assert "coverage fingerprint is unbound" in rejected.stdout

    manifest_step = _step_block(merge, "Build assured data manifest")
    publisher_identity = _step_block(publish, "Validate assured data artifact identity")
    upload = _step_block(publish, "Upload to Kaggle")
    assert "steps.terminal_identity.outputs.coverage_fingerprint" in manifest_step
    assert "needs.merge.outputs.coverage-fingerprint" in publisher_identity
    assert "needs.plan.outputs.coverage-fingerprint" not in publisher_identity
    assert "needs.merge.outputs.coverage-fingerprint" in upload
    assert "terminal-assurance-report.json" in manifest_step


def test_checkpoint_download_plan_combines_source_and_current_complete_lanes(
    tmp_path: pathlib.Path,
) -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    source_resolver = _embedded_python(checkpoint, "CHECKPOINT_SOURCE_RUN_RESOLVER")
    input_resolver = _embedded_python(checkpoint, "CHECKPOINT_LANE_INPUT_RESOLVER")
    manifest_path = tmp_path / "current-manifest.json"
    run_ids_path = tmp_path / "run-ids.txt"
    inventories_dir = tmp_path / "inventories"
    inventories_dir.mkdir()
    download_plan_path = tmp_path / "downloads.tsv"
    source_sha = "a" * 40
    chain_id = "fixture-chain"
    source_run_id = "111"
    current_run_id = "222"
    source_lane_id = "source-complete"
    resumed_lane_id = "resumed-complete"
    diagnostics_only_lane_id = "diagnostics-only"
    manifest = {
        "chain_id": chain_id,
        "workflow_source_sha": source_sha,
        "lanes": [
            {"lane_id": source_lane_id, "patterns": ["static"], "resume_only": True},
            {"lane_id": resumed_lane_id, "patterns": ["static"], "resume_only": False},
            {
                "lane_id": diagnostics_only_lane_id,
                "patterns": ["static"],
                "resume_only": False,
            },
        ],
        "chain_state": {"artifact_run_ids": [source_run_id]},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    resolver_env = {
        "ACTIVE_CHAIN_ID": chain_id,
        "CURRENT_MANIFEST": str(manifest_path),
        "CURRENT_RUN_ID": current_run_id,
        "RUN_IDS_PATH": str(run_ids_path),
        "WORKFLOW_SOURCE_SHA": source_sha,
    }

    resolved = _run_python(source_resolver, env=resolver_env)
    assert resolved.returncode == 0, resolved.stderr or resolved.stdout
    assert run_ids_path.read_text(encoding="utf-8").splitlines() == [
        source_run_id,
        current_run_id,
    ]

    source_metadata = f"extraction-lane-metadata-{chain_id}-{source_lane_id}"
    source_artifact = f"extraction-lane-{chain_id}-{source_lane_id}"
    stale_resumed_metadata = f"extraction-lane-metadata-{chain_id}-{resumed_lane_id}"
    current_metadata = stale_resumed_metadata
    current_artifact = f"extraction-lane-{chain_id}-{resumed_lane_id}"
    diagnostics_only_metadata = f"extraction-lane-metadata-{chain_id}-{diagnostics_only_lane_id}"
    (inventories_dir / f"run-{source_run_id}.json").write_text(
        json.dumps(
            [
                {
                    "artifacts": [
                        {"name": source_metadata, "expired": False},
                        {"name": source_artifact, "expired": False},
                        {"name": stale_resumed_metadata, "expired": False},
                        {"name": diagnostics_only_metadata, "expired": False},
                        {
                            "name": f"extraction-lane-recovery-{chain_id}-{resumed_lane_id}",
                            "expired": False,
                        },
                        {
                            "name": (
                                "extraction-lane-diagnostics-only-"
                                f"{chain_id}-{diagnostics_only_lane_id}-run-111-attempt-1"
                            ),
                            "expired": False,
                        },
                    ]
                }
            ]
        ),
        encoding="utf-8",
    )
    (inventories_dir / f"run-{current_run_id}.json").write_text(
        json.dumps(
            [
                {
                    "artifacts": [
                        {"name": current_metadata, "expired": False},
                        {"name": current_artifact, "expired": False},
                    ]
                }
            ]
        ),
        encoding="utf-8",
    )
    input_env = {
        "ACTIVE_CHAIN_ID": chain_id,
        "CURRENT_MANIFEST": str(manifest_path),
        "DOWNLOAD_PLAN_PATH": str(download_plan_path),
        "INVENTORIES_DIR": str(inventories_dir),
        "VERIFIED_PREVIOUS_CHECKPOINT_PATH": "",
        "RUN_IDS_PATH": str(run_ids_path),
    }

    planned = _run_python(input_resolver, env=input_env)
    assert planned.returncode == 0, planned.stderr or planned.stdout
    assert set(download_plan_path.read_text(encoding="utf-8").splitlines()) == {
        f"{source_run_id}\tmetadata\t{source_metadata}",
        f"{source_run_id}\tlane\t{source_artifact}",
        f"{current_run_id}\tmetadata\t{current_metadata}",
        f"{current_run_id}\tlane\t{current_artifact}",
    }
    assert "recovery" not in download_plan_path.read_text(encoding="utf-8")
    assert diagnostics_only_lane_id not in download_plan_path.read_text(encoding="utf-8")

    source_inventory_path = inventories_dir / f"run-{source_run_id}.json"
    original_source_inventory = source_inventory_path.read_text(encoding="utf-8")
    source_inventory = json.loads(original_source_inventory)
    source_inventory[0]["artifacts"] = [
        artifact
        for artifact in source_inventory[0]["artifacts"]
        if artifact["name"] != stale_resumed_metadata
    ]
    source_inventory[0]["artifacts"].append({"name": current_artifact, "expired": False})
    source_inventory_path.write_text(json.dumps(source_inventory), encoding="utf-8")
    unpaired_lane_ignored = _run_python(input_resolver, env=input_env)
    assert unpaired_lane_ignored.returncode == 0, (
        unpaired_lane_ignored.stderr or unpaired_lane_ignored.stdout
    )
    assert set(download_plan_path.read_text(encoding="utf-8").splitlines()) == {
        f"{source_run_id}\tmetadata\t{source_metadata}",
        f"{source_run_id}\tlane\t{source_artifact}",
        f"{current_run_id}\tmetadata\t{current_metadata}",
        f"{current_run_id}\tlane\t{current_artifact}",
    }
    source_inventory_path.write_text(original_source_inventory, encoding="utf-8")

    current_inventory_path = inventories_dir / f"run-{current_run_id}.json"
    original_current_inventory = current_inventory_path.read_text(encoding="utf-8")
    current_inventory = json.loads(original_current_inventory)
    current_inventory[0]["artifacts"].extend(
        [
            {"name": source_metadata, "expired": False},
            {"name": source_artifact, "expired": False},
        ]
    )
    current_inventory_path.write_text(json.dumps(current_inventory), encoding="utf-8")
    ambiguous = _run_python(input_resolver, env=input_env)
    assert ambiguous.returncode == 1
    assert "requires exactly one same-run lane/metadata pair" in ambiguous.stderr
    assert f"for {source_lane_id}; found 2" in ambiguous.stderr
    current_inventory_path.write_text(original_current_inventory, encoding="utf-8")

    source_inventory = json.loads(original_source_inventory)
    source_inventory[0]["artifacts"] = [
        artifact
        for artifact in source_inventory[0]["artifacts"]
        if artifact["name"] != source_metadata
    ]
    source_inventory_path.write_text(json.dumps(source_inventory), encoding="utf-8")
    unpaired = _run_python(input_resolver, env=input_env)
    assert unpaired.returncode == 1
    assert "requires exactly one same-run lane/metadata pair" in unpaired.stderr
    assert f"for {source_lane_id}; found 0" in unpaired.stderr
    source_inventory_path.write_text(original_source_inventory, encoding="utf-8")

    verified_previous_checkpoint_path = tmp_path / "verified-previous-checkpoint.json"
    verified_previous_checkpoint_path.write_text(
        json.dumps({"included_lane_ids": [source_lane_id]}),
        encoding="utf-8",
    )
    planned_after_checkpoint = _run_python(
        input_resolver,
        env={
            **input_env,
            "VERIFIED_PREVIOUS_CHECKPOINT_PATH": str(verified_previous_checkpoint_path),
        },
    )
    assert planned_after_checkpoint.returncode == 0, (
        planned_after_checkpoint.stderr or planned_after_checkpoint.stdout
    )
    assert download_plan_path.read_text(encoding="utf-8").splitlines() == [
        f"{current_run_id}\tlane\t{current_artifact}",
        f"{current_run_id}\tmetadata\t{current_metadata}",
    ]

    manifest["chain_state"]["artifact_run_ids"] = ["not-a-run-id"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    rejected = _run_python(source_resolver, env=resolver_env)
    assert rejected.returncode == 1
    assert "checkpoint artifact run ID is invalid" in rejected.stderr


def test_checkpoint_download_plan_recovers_zero_active_cancelled_source(
    tmp_path: pathlib.Path,
) -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    source_resolver = _embedded_python(checkpoint, "CHECKPOINT_SOURCE_RUN_RESOLVER")
    input_resolver = _embedded_python(checkpoint, "CHECKPOINT_LANE_INPUT_RESOLVER")
    manifest_path = tmp_path / "current-manifest.json"
    run_ids_path = tmp_path / "run-ids.txt"
    inventories_dir = tmp_path / "inventories"
    inventories_dir.mkdir()
    download_plan_path = tmp_path / "downloads.tsv"
    source_sha = "a" * 40
    chain_id = "cancelled-chain"
    source_run_id = "333"
    current_run_id = "444"
    lane_id = "already-complete"
    manifest_path.write_text(
        json.dumps(
            {
                "active_lane_count": 0,
                "chain_id": chain_id,
                "chain_state": {"artifact_run_ids": [source_run_id]},
                "lanes": [{"lane_id": lane_id, "patterns": ["static"], "resume_only": True}],
                "matrix_lane_count": 0,
                "workflow_source_sha": source_sha,
            }
        ),
        encoding="utf-8",
    )
    source_env = {
        "ACTIVE_CHAIN_ID": chain_id,
        "CURRENT_MANIFEST": str(manifest_path),
        "CURRENT_RUN_ID": current_run_id,
        "RUN_IDS_PATH": str(run_ids_path),
        "WORKFLOW_SOURCE_SHA": source_sha,
    }
    resolved = _run_python(source_resolver, env=source_env)
    assert resolved.returncode == 0, resolved.stderr or resolved.stdout

    metadata_name = f"extraction-lane-metadata-{chain_id}-{lane_id}"
    artifact_name = f"extraction-lane-{chain_id}-{lane_id}"
    (inventories_dir / f"run-{source_run_id}.json").write_text(
        json.dumps(
            [
                {
                    "artifacts": [
                        {"name": metadata_name, "expired": False},
                        {"name": artifact_name, "expired": False},
                    ]
                }
            ]
        ),
        encoding="utf-8",
    )
    (inventories_dir / f"run-{current_run_id}.json").write_text(
        '[{"artifacts": []}]\n',
        encoding="utf-8",
    )
    planned = _run_python(
        input_resolver,
        env={
            "ACTIVE_CHAIN_ID": chain_id,
            "CURRENT_MANIFEST": str(manifest_path),
            "DOWNLOAD_PLAN_PATH": str(download_plan_path),
            "INVENTORIES_DIR": str(inventories_dir),
            "VERIFIED_PREVIOUS_CHECKPOINT_PATH": "",
            "RUN_IDS_PATH": str(run_ids_path),
        },
    )
    assert planned.returncode == 0, planned.stderr or planned.stdout
    assert set(download_plan_path.read_text(encoding="utf-8").splitlines()) == {
        f"{source_run_id}\tmetadata\t{metadata_name}",
        f"{source_run_id}\tlane\t{artifact_name}",
    }


def test_only_redispatch_job_has_actions_write_permission() -> None:
    workflow = _workflow_text()

    for job_name in (
        "extract",
        "terminal_replay",
        "merge",
        "publish",
        "lane_control",
        "checkpoint",
    ):
        job = _job_block(workflow, job_name)
        assert "permissions:\n      actions: read" in job
        assert "actions: write" not in job

    publication_preflight = _job_block(workflow, "publication_preflight")
    assert "permissions:\n      contents: read" in publication_preflight
    assert "contents: write" not in publication_preflight
    assert "actions: write" not in publication_preflight

    dispatch = _job_block(workflow, "dispatch_next")
    assert "permissions:\n      actions: write" in dispatch
    assert workflow.count("actions: write") == 1


def test_publish_false_keeps_terminal_assurance_and_blocks_publication() -> None:
    workflow = _workflow_text()
    merge = _job_block(workflow, "merge")
    publish = _job_block(workflow, "publish")
    publish_input = workflow.split("      publish:\n", 1)[1].split("      chain_id:\n", 1)[0]

    assert "type: boolean" in publish_input
    assert "default: true" in publish_input
    for assurance_step in (
        "Merge lane databases",
        "Transform and load",
        "Append live snapshot",
        "Scan data quality",
        "Export all formats",
    ):
        step = _step_block(merge, assurance_step)
        assert "inputs.publish" not in step

    canary_summary = _step_block(merge, "Record non-publishing canary outcome")
    assert "if: ${{ inputs.publish == false }}" in canary_summary
    assert "Metadata commit/push: skipped." in canary_summary
    assert "Kaggle upload: skipped." in canary_summary
    assert "contents: read" in merge
    assert "contents: write" not in merge
    assert "secrets.KAGGLE_USERNAME" not in merge
    assert "secrets.KAGGLE_KEY" not in merge
    assert "kaggle-publication-state" not in merge
    assert "refresh-metadata" not in merge

    assert "needs: [plan, publication_preflight, merge]" in publish
    assert "needs.publication_preflight.result == 'success'" in publish
    assert "needs.merge.result == 'success'" in publish
    assert "contents: write" in publish
    assert "Refresh checked-in metadata" in publish
    assert "Upload to Kaggle" in publish
    assert '-f publish="$PUBLISH"' in _job_block(workflow, "dispatch_next")


def test_terminal_hard_scan_runs_after_export_and_before_assured_manifest() -> None:
    merge = _job_block(_workflow_text(), "merge")

    export_index = merge.index("- name: Export all formats")
    scan_index = merge.index("- name: Scan data quality")
    manifest_index = merge.index("- name: Build assured data manifest")
    upload_index = merge.index("- name: Upload assured final data artifact")

    assert export_index < scan_index < manifest_index < upload_index


def test_targeted_smoke_is_one_shot_checkpoint_assurance_without_merge() -> None:
    workflow = _workflow_text()
    guard = _job_block(workflow, "workflow_guard")
    plan = _job_block(workflow, "plan")
    plan_gate = _step_block(plan, "Validate targeted smoke plan")
    smoke = _job_block(workflow, "targeted_smoke_assurance")
    merge = _job_block(workflow, "merge")
    dispatch = _job_block(workflow, "dispatch_next")
    smoke_input = workflow.split("      targeted_smoke:\n", 1)[1].split("      chain_id:\n", 1)[0]

    assert "type: boolean" in smoke_input
    assert "default: false" in smoke_input
    assert "targeted_smoke=true requires publish=false" in guard
    assert "targeted_smoke=true requires network_mode=vpn" in guard
    assert "targeted_smoke=true requires max_iterations=1" in guard
    assert "targeted_smoke=true requires retry_pipeline_failures=false" in guard
    assert "requires an inline or artifact-backed manual lane manifest" in guard

    assert "if: ${{ inputs.targeted_smoke }}" in plan_gate
    assert 'if [ "$LANE_COUNT" != "1" ]' in plan_gate
    assert '[ "$ACTIVE_LANE_COUNT" != "1" ]' in plan_gate
    assert '[ "$MATRIX_LANE_COUNT" != "1" ]' in plan_gate
    assert '[ "$DEFERRED_LANE_COUNT" != "0" ]' in plan_gate
    assert plan.index("Validate targeted smoke plan") < plan.index("Upload lane manifest")

    assert "if: ${{ always() && inputs.targeted_smoke }}" in smoke
    assert "needs: [plan, preflight, discovery_seed, extract, lane_control, checkpoint]" in smoke
    assert 'if [ "$LANE_COUNT" != "1" ] || [ "$MATRIX_LANE_COUNT" != "1" ]; then' in smoke
    assert 'if [ "$ACTIVE_LANE_COUNT" != "0" ]' in smoke
    assert 'if [ "$RESUME_ONLY_LANE_COUNT" != "1" ]' in smoke
    assert 'if [ "$CHECKPOINT_TERMINAL_READY" != "true" ]; then' in smoke
    assert "!inputs.targeted_smoke" in merge.split("    runs-on:", 1)[0]
    assert "!inputs.targeted_smoke" in dispatch.split("    runs-on:", 1)[0]


def test_lane_metadata_receives_manifest_coverage_identity() -> None:
    extract = _job_block(_workflow_text(), "extract")
    lane_metadata = _step_block(extract, "Write lane metadata")

    assert "COVERAGE_UNITS_HASH: ${{ matrix.coverage_units_hash }}" in lane_metadata


def test_terminal_publish_state_survives_ephemeral_runner_retries() -> None:
    publish = _job_block(_workflow_text(), "publish")
    restore = _step_block(publish, "Restore Kaggle publication reconciliation state")
    detect = _step_block(publish, "Detect Kaggle publication reconciliation state")
    persist = _step_block(publish, "Persist Kaggle publication reconciliation state")
    receipt = _step_block(publish, "Upload Kaggle publication receipt")
    final_artifact = _step_block(publish, "Upload final database")
    metadata = _step_block(publish, "Refresh checked-in metadata")

    state_path = "logs/kaggle/kaggle-publication-state.json"
    key_prefix = "nbadb-kaggle-publication-state-"
    assert "actions/cache/restore@27d5ce7f107fe9357f9df03efb73ab90386fccae" in restore
    assert state_path in restore
    assert key_prefix in restore
    assert "${{ env.ACTIVE_CHAIN_ID }}" not in restore
    assert "${{ github.run_id }}-${{ github.run_attempt }}" in restore
    assert "restore-keys:" in restore

    assert "if: always()" in detect
    assert f"if [ -f {state_path} ]; then" in detect
    assert 'echo "exists=true"' in detect
    assert "Kaggle publication state was not created" in detect

    assert (
        "if: ${{ always() && steps.kaggle_publication_state.outputs.exists == 'true' }}"
    ) in persist
    assert "actions/cache/save@27d5ce7f107fe9357f9df03efb73ab90386fccae" in persist
    assert state_path in persist
    assert key_prefix in persist
    assert "${{ env.ACTIVE_CHAIN_ID }}" not in persist
    assert "${{ github.run_id }}-${{ github.run_attempt }}" in persist
    assert "if: always()" in receipt
    assert state_path in receipt
    assert "if: always()" in final_artifact
    assert state_path in final_artifact

    upload_position = publish.index("- name: Upload to Kaggle")
    detect_position = publish.index("- name: Detect Kaggle publication reconciliation state")
    persist_position = publish.index("- name: Persist Kaggle publication reconciliation state")
    receipt_position = publish.index("- name: Upload Kaggle publication receipt")
    artifact_position = publish.index("- name: Upload final database")
    metadata_position = publish.index("- name: Refresh checked-in metadata")
    assert (
        upload_position
        < detect_position
        < persist_position
        < receipt_position
        < artifact_position
        < metadata_position
    )
    assert "if: always()" not in metadata


def test_all_publish_workflows_share_durable_kaggle_reconciliation_state() -> None:
    workflow_jobs = (
        (_job_block(_workflow_text(), "publish"), "Upload Kaggle publication receipt"),
        (
            _job_block(_DAILY_PATH.read_text(encoding="utf-8"), "daily"),
            "Upload Kaggle publication receipt",
        ),
        (
            _job_block(_MONTHLY_PATH.read_text(encoding="utf-8"), "monthly"),
            "Upload Kaggle publication receipt",
        ),
    )
    state_path = "logs/kaggle/kaggle-publication-state.json"
    cache_key = "nbadb-kaggle-publication-state-${{ github.run_id }}-${{ github.run_attempt }}"

    for job, receipt_name in workflow_jobs:
        restore = _step_block(job, "Restore Kaggle publication reconciliation state")
        detect = _step_block(job, "Detect Kaggle publication reconciliation state")
        persist = _step_block(job, "Persist Kaggle publication reconciliation state")
        receipt = _step_block(job, receipt_name)

        assert "nbadb-kaggle-publish" in job
        assert state_path in restore
        assert cache_key in restore
        assert "restore-keys: |\n            nbadb-kaggle-publication-state-" in restore
        assert state_path in detect
        assert state_path in persist
        assert cache_key in persist
        assert state_path in receipt
        assert job.index("Restore Kaggle publication reconciliation state") < job.index(
            "Upload to Kaggle"
        )
        assert job.index("Upload to Kaggle") < job.index(
            "Persist Kaggle publication reconciliation state"
        )


def test_publish_workflows_require_default_branch_and_complete_export_metadata() -> None:
    full_preflight = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Validate Kaggle publication readiness",
    )
    assert "EVENT_REF_NAME: ${{ github.ref_name }}" in full_preflight
    assert "WORKFLOW_SOURCE_REF: ${{ env.WORKFLOW_SOURCE_REF }}" in full_preflight
    assert "publish=true requires the default branch" in full_preflight

    for path, job_name, extraction_id in (
        (_DAILY_PATH, "daily", "daily"),
        (_MONTHLY_PATH, "monthly", "monthly"),
    ):
        job = _job_block(path.read_text(encoding="utf-8"), job_name)
        branch_guard = _step_block(job, "Require default branch for Kaggle publication")
        upload = _step_block(job, "Upload to Kaggle")
        metadata_commit = _step_block(job, "Refresh checked-in metadata")
        receipt = _step_block(job, "Upload Kaggle publication receipt")
        assertion = _step_block(job, "Assert extraction and scan passed")

        assert "Kaggle publication requires the default branch" in branch_guard
        for prerequisite in (
            f"steps.{extraction_id}.outcome == 'success'",
            "steps.scan.outcome == 'success'",
            "steps.export.outcome == 'success'",
            "steps.metadata.outcome == 'success'",
        ):
            assert prerequisite in upload
            assert prerequisite in receipt
        assert "id: upload" in upload
        assert "timeout-minutes: 75" in upload
        assert "--data-dir data/nbadb" in upload
        assert "--remote-timeout 3600" in upload
        assert "steps.upload.outcome == 'success'" in metadata_commit
        assert "data-dir: data/nbadb" in metadata_commit
        assert job.index("Upload to Kaggle") < job.index("Refresh checked-in metadata")
        assert "steps.upload.outcome != 'skipped'" in receipt
        assert "EXPORT_OUTCOME: ${{ steps.export.outcome }}" in assertion
        assert "METADATA_OUTCOME: ${{ steps.metadata.outcome }}" in assertion
        assert "UPLOAD_OUTCOME: ${{ steps.upload.outcome }}" in assertion
        assert "METADATA_COMMIT_OUTCOME: ${{ steps.metadata_commit.outcome }}" in assertion


def test_kaggle_publication_preflight_fails_before_lane_fanout_and_rechecks_at_publish() -> None:
    preflight = _job_block(_workflow_text(), "preflight")
    publication_preflight = _job_block(_workflow_text(), "publication_preflight")
    publish = _job_block(_workflow_text(), "publish")
    early_kaggle = _step_block(publication_preflight, "Fail fast on Kaggle publication readiness")
    kaggle = _step_block(publish, "Validate Kaggle publication readiness")

    assert "KAGGLE_USERNAME" not in preflight
    assert "KAGGLE_KEY" not in preflight
    assert "needs: [plan, publication_preflight]" in preflight
    assert "needs.publication_preflight.result == 'success'" in preflight
    assert "if: ${{ inputs.publish }}" in publication_preflight
    assert "contents: write" not in publication_preflight
    assert "KAGGLE_USERNAME: ${{ secrets.KAGGLE_USERNAME }}" in early_kaggle
    assert "KAGGLE_KEY: ${{ secrets.KAGGLE_KEY }}" in early_kaggle
    assert "result = KaggleClient().publication_preflight()" in early_kaggle
    assert "Kaggle publication preflight failed" in early_kaggle
    assert "type(exc).__name__" in early_kaggle
    assert "raise SystemExit(1) from None" in early_kaggle
    assert "dataset_upload" not in early_kaggle
    assert "nbadb upload" not in early_kaggle
    assert "KAGGLE_USERNAME: ${{ secrets.KAGGLE_USERNAME }}" in kaggle
    assert "KAGGLE_KEY: ${{ secrets.KAGGLE_KEY }}" in kaggle
    assert publish.count("secrets.KAGGLE_USERNAME") == 2
    assert publish.count("secrets.KAGGLE_KEY") == 2
    assert 'if [ -z "${KAGGLE_USERNAME:-}" ] || [ -z "${KAGGLE_KEY:-}" ]; then' in kaggle
    assert "KAGGLE_USERNAME and KAGGLE_KEY are required when publish=true" in kaggle
    assert "client = KaggleClient()" in kaggle
    assert "result = client.publication_preflight()" in kaggle
    assert "if acceptable is not True:" in kaggle
    assert "if isinstance(version, bool) or not isinstance(version, int) or version <= 0:" in kaggle
    assert 're.fullmatch(r"[a-z][a-z0-9_]{0,63}", state)' in kaggle
    assert "## Kaggle Publication Preflight" in kaggle
    assert "**Acceptable:** `true`" in kaggle
    assert "**State:** `{state}`" in kaggle
    assert "**Exact remote version:** `{version}`" in kaggle
    assert "publish_key" not in kaggle
    assert "bundle_fingerprint" not in kaggle
    assert 'result.get("dataset")' not in kaggle
    assert "dataset_upload" not in kaggle
    assert "nbadb upload" not in kaggle


def test_shared_publish_concurrency_queues_all_pending_runs() -> None:
    publish_jobs = (
        _job_block(_workflow_text(), "publish"),
        _job_block(_DAILY_PATH.read_text(encoding="utf-8"), "daily"),
        _job_block(_MONTHLY_PATH.read_text(encoding="utf-8"), "monthly"),
    )

    for job in publish_jobs:
        assert (
            "concurrency:\n"
            "      group: nbadb-kaggle-publish\n"
            "      queue: max\n"
            "      cancel-in-progress: false"
        ) in job
        assert "queue: max\n      cancel-in-progress: true" not in job


def test_refresh_metadata_uses_validated_explicit_fast_forward_refspec() -> None:
    action = _REFRESH_METADATA_ACTION_PATH.read_text(encoding="utf-8")
    commit_step = action.split("    - name: Commit refreshed metadata\n", 1)[1]

    assert "  push-ref:\n" in action
    assert "PUSH_REF_INPUT: ${{ inputs.push-ref }}" in commit_step
    assert 'git check-ref-format --branch "$push_ref"' in commit_step
    assert 'remote_ref="refs/heads/${push_ref}"' in commit_step
    assert 'git fetch "${fetch_args[@]}" origin "+${remote_ref}:${tracking_ref}"' in commit_step
    assert 'git diff --quiet "$tracking_ref" -- dataset-metadata.json' in commit_step
    assert 'git merge-base --is-ancestor "$target_commit" "$source_commit"' in commit_step
    assert "Metadata push would not be a fast-forward" in commit_step
    assert 'git push origin "HEAD:${remote_ref}"' in commit_step
    assert "\n        git push\n" not in action
    assert commit_step.index('git diff --quiet "$tracking_ref"') < commit_step.index(
        "git merge-base --is-ancestor"
    )
    assert commit_step.index("git merge-base --is-ancestor") < commit_step.index(
        "git diff --quiet --"
    )
    assert commit_step.index("git push origin") < len(commit_step)

    refresh_steps = (
        _step_block(_job_block(_workflow_text(), "publish"), "Refresh checked-in metadata"),
        _step_block(
            _job_block(_DAILY_PATH.read_text(encoding="utf-8"), "daily"),
            "Refresh checked-in metadata",
        ),
        _step_block(
            _job_block(_MONTHLY_PATH.read_text(encoding="utf-8"), "monthly"),
            "Refresh checked-in metadata",
        ),
    )
    for step in refresh_steps:
        assert "push-ref: ${{ github.event.repository.default_branch }}" in step


def test_refresh_metadata_pushes_detached_head_and_rejects_non_fast_forward(
    tmp_path: pathlib.Path,
) -> None:
    def run(
        command: list[str],
        *,
        cwd: pathlib.Path,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            cwd=cwd,
            env={**os.environ, **(env or {})},
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        return result

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    publisher = tmp_path / "publisher"
    run(["git", "init", "--bare", "--initial-branch=main", str(remote)], cwd=tmp_path)
    run(["git", "clone", str(remote), str(seed)], cwd=tmp_path)
    run(["git", "config", "user.name", "Fixture"], cwd=seed)
    run(["git", "config", "user.email", "fixture@example.test"], cwd=seed)
    (seed / "dataset-metadata.json").write_text('{"version": 1}\n', encoding="utf-8")
    run(["git", "add", "dataset-metadata.json"], cwd=seed)
    run(["git", "commit", "-m", "seed"], cwd=seed)
    run(["git", "push", "-u", "origin", "main"], cwd=seed)

    run(
        ["git", "clone", "--depth=1", remote.resolve().as_uri(), str(publisher)],
        cwd=tmp_path,
    )
    run(["git", "checkout", "--detach", "HEAD"], cwd=publisher)
    source_commit = run(["git", "rev-parse", "HEAD"], cwd=publisher).stdout.strip()
    (publisher / "dataset-metadata.json").write_text('{"version": 2}\n', encoding="utf-8")
    action_env = {
        "COMMIT_MESSAGE": "chore: refresh fixture metadata",
        "DEFAULT_BRANCH": "main",
        "PUSH_REF_INPUT": "main",
    }
    pushed = subprocess.run(
        ["bash", "-c", _metadata_commit_script()],
        cwd=publisher,
        env={**os.environ, **action_env},
        check=False,
        capture_output=True,
        text=True,
    )
    assert pushed.returncode == 0, pushed.stderr or pushed.stdout
    pushed_commit = run(
        ["git", f"--git-dir={remote}", "rev-parse", "main"], cwd=tmp_path
    ).stdout.strip()
    assert pushed_commit != source_commit
    assert (
        run(
            ["git", f"--git-dir={remote}", "show", "main:dataset-metadata.json"],
            cwd=tmp_path,
        ).stdout
        == '{"version": 2}\n'
    )

    stale = tmp_path / "stale"
    updater = tmp_path / "updater"
    run(
        ["git", "clone", "--depth=1", remote.resolve().as_uri(), str(stale)],
        cwd=tmp_path,
    )
    run(["git", "checkout", "--detach", "HEAD"], cwd=stale)
    stale_commit = run(["git", "rev-parse", "HEAD"], cwd=stale).stdout.strip()
    run(["git", "clone", str(remote), str(updater)], cwd=tmp_path)
    run(["git", "config", "user.name", "Fixture"], cwd=updater)
    run(["git", "config", "user.email", "fixture@example.test"], cwd=updater)
    (updater / "concurrent.txt").write_text("branch moved\n", encoding="utf-8")
    run(["git", "add", "concurrent.txt"], cwd=updater)
    run(["git", "commit", "-m", "concurrent update"], cwd=updater)
    run(["git", "push", "origin", "main"], cwd=updater)
    advanced_commit = run(
        ["git", f"--git-dir={remote}", "rev-parse", "main"], cwd=tmp_path
    ).stdout.strip()

    (stale / "dataset-metadata.json").write_text('{"version": 3}\n', encoding="utf-8")
    rejected = subprocess.run(
        ["bash", "-c", _metadata_commit_script()],
        cwd=stale,
        env={**os.environ, **action_env},
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1
    assert "Metadata push would not be a fast-forward" in rejected.stdout
    assert run(["git", "rev-parse", "HEAD"], cwd=stale).stdout.strip() == stale_commit
    assert (
        run(["git", f"--git-dir={remote}", "rev-parse", "main"], cwd=tmp_path).stdout.strip()
        == advanced_commit
    )


def test_publish_depends_on_exact_immutable_assurance_artifact() -> None:
    merge = _job_block(_workflow_text(), "merge")
    publish = _job_block(_workflow_text(), "publish")
    manifest = _step_block(merge, "Build assured data manifest")
    scan = _step_block(merge, "Scan data quality")
    assured_upload = _step_block(merge, "Upload assured final data artifact")
    exact_download = _step_block(publish, "Download exact assured data artifact")
    identity = _step_block(publish, "Validate assured data artifact identity")
    frozen_source = _step_block(publish, "Revalidate frozen publication source")
    metadata = _step_block(publish, "Refresh checked-in metadata")
    upload = _step_block(publish, "Upload to Kaggle")
    receipt = _step_block(publish, "Upload Kaggle publication receipt")
    final_artifact = _step_block(publish, "Upload final database")

    unique_name = (
        "nbadb-full-extraction-assured-${{ env.ACTIVE_CHAIN_ID }}-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert '--chain-id "$ACTIVE_CHAIN_ID"' in manifest
    assert 'source_sha="${WORKFLOW_SOURCE_SHA,,}"' in manifest
    assert '--source-sha "$source_sha"' in manifest
    assert '--coverage-fingerprint "$COVERAGE_FINGERPRINT"' in manifest
    assert "data/nbadb/assured-artifact-manifest.json" in assured_upload
    assert "full-publication: true" in scan
    assert "checkpoint-report: checkpoint-artifact/checkpoint-report.json" in scan
    assert "checkpoint-manifest: artifacts/full-extraction/merge-manifest.json" in scan
    assert "checkpoint-dir: checkpoint-artifact" in scan
    assert "checkpoint-chain-id: ${{ env.ACTIVE_CHAIN_ID }}" in scan
    assert "checkpoint-source-sha: ${{ env.WORKFLOW_SOURCE_SHA }}" in scan
    assert "checkpoint_reports" in merge
    assert "checkpoint_databases" in merge
    assert "must contain exactly one report and database" in merge
    assert 'cp "$checkpoint_report" checkpoint-artifact/checkpoint-report.json' in merge
    assert 'cp "$checkpoint_database" checkpoint-artifact/nba.duckdb' in merge
    assert unique_name in assured_upload
    assert "if-no-files-found: error" in assured_upload
    assert "ARTIFACT_ID: ${{ needs.merge.outputs.final-data-artifact-id }}" in exact_download
    assert (
        "ARTIFACT_DIGEST: ${{ needs.merge.outputs.final-data-artifact-digest }}" in exact_download
    )
    assert "ARTIFACT_NAME: ${{ needs.merge.outputs.final-data-artifact-name }}" in exact_download
    assert "/actions/artifacts/${ARTIFACT_ID}/zip" in exact_download
    assert "actions/download-artifact" not in exact_download
    assert "ASSURED_ARTIFACT_ARCHIVE_VERIFIER" in exact_download
    assert "artifact archive SHA-256 does not match upload digest" in exact_download
    assert "archive_path.read_bytes()" not in exact_download
    assert 'unzip -q "$archive_path" -d data/nbadb' in exact_download
    assert (
        "EXPECTED_ARTIFACT_PREFIX: nbadb-full-extraction-assured-"
        "${{ env.ACTIVE_CHAIN_ID }}-${{ github.run_id }}-" in identity
    )
    assert "github.run_attempt" not in identity
    assert 'artifact_attempt="${ARTIFACT_NAME#"$EXPECTED_ARTIFACT_PREFIX"}"' in identity
    assert '[[ "$artifact_attempt" =~ ^[0-9]+$ ]]' in identity
    assert "data/nbadb/assured-artifact-manifest.json" in identity
    assert "nbadb.core.artifact_identity verify" in identity
    assert '--chain-id "$ACTIVE_CHAIN_ID"' in identity
    assert 'source_sha="${WORKFLOW_SOURCE_SHA,,}"' in identity
    assert '--source-sha "$source_sha"' in identity
    assert '--coverage-fingerprint "$COVERAGE_FINGERPRINT"' in identity
    assert "needs: [plan, publication_preflight, merge]" in publish
    assert "needs.publication_preflight.result == 'success'" in publish
    assert "needs.merge.result == 'success'" in publish
    assert "continue-on-error" not in metadata
    assert "continue-on-error" not in upload
    assert "--full-publication" in upload
    assert "--verify-remote" in upload
    assert 'source_commit="$(git rev-parse "${WORKFLOW_SOURCE_SHA}^{commit}")"' in frozen_source
    assert '"+refs/heads/${DEFAULT_BRANCH}:${target_ref}"' in frozen_source
    assert 'if [ "$target_commit" != "$source_commit" ]; then' in frozen_source
    assert '[ "$parent" != "$source_commit" ]' in frozen_source
    assert '[ "$changed_paths" != "dataset-metadata.json" ]' in frozen_source
    assert '[ "$commit_subject" != "chore: regenerate dataset-metadata.json" ]' in frozen_source
    assert 'cmp --silent "$expected_metadata" "$observed_metadata"' in frozen_source
    assert "exact metadata-only publication child" in frozen_source
    assert "if: always()" in receipt
    assert "if: always()" in final_artifact
    assert "name: nbadb-full-extraction-${{ env.ACTIVE_CHAIN_ID }}" in final_artifact
    assert "data/nbadb/assured-artifact-manifest.json" in final_artifact
    assert publish.index("Revalidate frozen publication source") < publish.index("Upload to Kaggle")
    assert publish.index("Upload final database") < publish.index("Refresh checked-in metadata")


def test_assured_artifact_archive_verifier_rejects_digest_and_identity_mismatch(
    tmp_path: pathlib.Path,
) -> None:
    download = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Download exact assured data artifact",
    )
    verifier = _embedded_python(download, "ASSURED_ARTIFACT_ARCHIVE_VERIFIER")
    archive_path = tmp_path / "assured.zip"
    metadata_path = tmp_path / "artifact.json"
    artifact_id = "123"
    artifact_name = "nbadb-full-extraction-assured-fixture-456-1"
    source_run_id = "456"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nba.duckdb", b"fixture")
    digest = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
    metadata = {
        "expired": False,
        "id": int(artifact_id),
        "name": artifact_name,
        "workflow_run": {"id": int(source_run_id)},
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    env = {
        "ARTIFACT_ARCHIVE_PATH": str(archive_path),
        "ARTIFACT_DIGEST": digest,
        "ARTIFACT_ID": artifact_id,
        "ARTIFACT_METADATA_PATH": str(metadata_path),
        "ARTIFACT_NAME": artifact_name,
        "SOURCE_RUN_ID": source_run_id,
    }

    accepted = _run_python(verifier, env=env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout

    wrong_digest = _run_python(
        verifier,
        env={**env, "ARTIFACT_DIGEST": "sha256:" + "0" * 64},
    )
    assert wrong_digest.returncode == 1
    assert "artifact archive SHA-256 does not match upload digest" in wrong_digest.stdout

    metadata["id"] = 999
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    wrong_id = _run_python(verifier, env=env)
    assert wrong_id.returncode == 1
    assert "artifact metadata ID does not match" in wrong_id.stdout


@pytest.mark.parametrize(
    ("metadata_patch", "expected_error"),
    [
        ({"name": "wrong-name"}, "artifact metadata name does not match"),
        ({"workflow_run": {"id": 999}}, "artifact workflow run identity does not match"),
        ({"expired": True}, "artifact is expired"),
    ],
)
def test_assured_artifact_archive_verifier_rejects_metadata_provenance_tampering(
    tmp_path: pathlib.Path,
    metadata_patch: dict[str, object],
    expected_error: str,
) -> None:
    download = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Download exact assured data artifact",
    )
    verifier = _embedded_python(download, "ASSURED_ARTIFACT_ARCHIVE_VERIFIER")
    archive_path = tmp_path / "assured.zip"
    metadata_path = tmp_path / "artifact.json"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nba.duckdb", b"fixture")
    artifact_id = "123"
    artifact_name = "nbadb-full-extraction-assured-fixture-456-1"
    source_run_id = "456"
    metadata = {
        "expired": False,
        "id": int(artifact_id),
        "name": artifact_name,
        "workflow_run": {"id": int(source_run_id)},
        **metadata_patch,
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    result = _run_python(
        verifier,
        env={
            "ARTIFACT_ARCHIVE_PATH": str(archive_path),
            "ARTIFACT_DIGEST": "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "ARTIFACT_ID": artifact_id,
            "ARTIFACT_METADATA_PATH": str(metadata_path),
            "ARTIFACT_NAME": artifact_name,
            "SOURCE_RUN_ID": source_run_id,
        },
    )

    assert result.returncode == 1
    assert expected_error in result.stdout


@pytest.mark.parametrize("unsafe_member", ["../escape", "/absolute/path"])
def test_assured_artifact_archive_verifier_rejects_unsafe_members(
    tmp_path: pathlib.Path,
    unsafe_member: str,
) -> None:
    download = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Download exact assured data artifact",
    )
    verifier = _embedded_python(download, "ASSURED_ARTIFACT_ARCHIVE_VERIFIER")
    archive_path = tmp_path / "assured.zip"
    metadata_path = tmp_path / "artifact.json"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(unsafe_member, b"fixture")
    metadata_path.write_text(
        json.dumps(
            {
                "expired": False,
                "id": 123,
                "name": "assured-name",
                "workflow_run": {"id": 456},
            }
        ),
        encoding="utf-8",
    )
    result = _run_python(
        verifier,
        env={
            "ARTIFACT_ARCHIVE_PATH": str(archive_path),
            "ARTIFACT_DIGEST": "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "ARTIFACT_ID": "123",
            "ARTIFACT_METADATA_PATH": str(metadata_path),
            "ARTIFACT_NAME": "assured-name",
            "SOURCE_RUN_ID": "456",
        },
    )

    assert result.returncode == 1
    assert "artifact archive contains unsafe paths" in result.stdout


def test_assured_artifact_archive_verifier_rejects_malformed_zip(
    tmp_path: pathlib.Path,
) -> None:
    download = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Download exact assured data artifact",
    )
    verifier = _embedded_python(download, "ASSURED_ARTIFACT_ARCHIVE_VERIFIER")
    archive_path = tmp_path / "assured.zip"
    archive_path.write_bytes(b"not-a-zip")
    metadata_path = tmp_path / "artifact.json"
    metadata_path.write_text(
        json.dumps(
            {
                "expired": False,
                "id": 123,
                "name": "assured-name",
                "workflow_run": {"id": 456},
            }
        ),
        encoding="utf-8",
    )
    result = _run_python(
        verifier,
        env={
            "ARTIFACT_ARCHIVE_PATH": str(archive_path),
            "ARTIFACT_DIGEST": "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            "ARTIFACT_ID": "123",
            "ARTIFACT_METADATA_PATH": str(metadata_path),
            "ARTIFACT_NAME": "assured-name",
            "SOURCE_RUN_ID": "456",
        },
    )

    assert result.returncode == 1
    assert "artifact archive is not a valid ZIP file" in result.stdout


def test_frozen_source_revalidation_accepts_only_exact_metadata_rerun_child(
    tmp_path: pathlib.Path,
) -> None:
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    publisher = tmp_path / "publisher"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "clone", str(remote), str(seed)],
        check=True,
        capture_output=True,
        text=True,
    )
    for key, value in (("user.name", "Fixture"), ("user.email", "fixture@example.test")):
        subprocess.run(["git", "config", key, value], cwd=seed, check=True)
    (seed / "dataset-metadata.json").write_text('{"version": 1}\n', encoding="utf-8")
    subprocess.run(["git", "add", "dataset-metadata.json"], cwd=seed, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=seed, check=True, capture_output=True)
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=seed,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=seed, check=True)

    (seed / "dataset-metadata.json").write_text('{"version": 2}\n', encoding="utf-8")
    subprocess.run(["git", "add", "dataset-metadata.json"], cwd=seed, check=True)
    subprocess.run(
        ["git", "commit", "-m", "chore: regenerate dataset-metadata.json"],
        cwd=seed,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=seed, check=True)
    subprocess.run(
        ["git", "clone", str(remote), str(publisher)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "checkout", "--detach", source_commit], cwd=publisher, check=True)
    (publisher / "data" / "nbadb").mkdir(parents=True)

    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
output=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--output" ]; then
    output="$2"
    break
  fi
  shift
done
test -n "$output"
printf '{"version": 2}\\n' > "$output"
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "DEFAULT_BRANCH": "main",
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "WORKFLOW_SOURCE_SHA": source_commit,
    }
    script = _step_run_script(
        _job_block(_workflow_text(), "publish"), "Revalidate frozen publication source"
    )
    accepted = subprocess.run(
        ["bash", "-c", script],
        cwd=publisher,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    assert "Accepting exact metadata-only publication child" in accepted.stdout

    (publisher / "dataset-metadata.json").write_text('{"version": 2}\n', encoding="utf-8")
    refresh_env = {
        **env,
        "COMMIT_MESSAGE": "chore: regenerate dataset-metadata.json",
        "DEFAULT_BRANCH": "main",
        "PUSH_REF_INPUT": "main",
    }
    refreshed = subprocess.run(
        ["bash", "-c", _metadata_commit_script()],
        cwd=publisher,
        env=refresh_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert refreshed.returncode == 0, refreshed.stderr or refreshed.stdout
    assert "Remote metadata already matches" in refreshed.stdout

    (seed / "unrelated.txt").write_text("moved\n", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=seed, check=True)
    subprocess.run(["git", "commit", "-m", "unrelated"], cwd=seed, check=True, capture_output=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=seed, check=True)
    rejected = subprocess.run(
        ["bash", "-c", script],
        cwd=publisher,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1
    assert "Default branch moved during extraction" in rejected.stdout


def test_zero_active_resume_replays_checkpoint_or_rebuilds_cancelled_source() -> None:
    workflow = _workflow_text()
    preflight = _job_block(workflow, "preflight")
    discovery = _job_block(workflow, "discovery_seed")
    replay = _job_block(workflow, "terminal_replay")
    merge = _job_block(workflow, "merge")
    lane_control = _job_block(workflow, "lane_control")
    checkpoint = _job_block(workflow, "checkpoint")
    completed_manifest_download = _step_block(
        merge, "Download terminal manifest from completed lanes"
    )
    completed_checkpoint_download = _step_block(
        merge, "Download terminal checkpoint from completed lanes"
    )
    replay_download = _step_block(merge, "Download replayed terminal checkpoint")
    prepare_merge = _step_block(merge, "Prepare checkpoint-first merge")
    replay_header = replay.split("    steps:\n", 1)[0]
    lane_control_header = lane_control.split("    steps:\n", 1)[0]

    assert "needs.plan.outputs.matrix-lane-count != '0'" in preflight
    assert "needs.plan.outputs.matrix-lane-count != '0'" in discovery
    assert "needs: [plan, publication_preflight]" in replay_header
    replay_needs = re.search(r"(?m)^    needs: (?P<needs>.+)$", replay_header)
    assert replay_needs is not None
    assert replay_needs.group("needs") == "[plan, publication_preflight]"
    for predicate in (
        "inputs.resume_source_run_id != ''",
        "needs.plan.outputs.lane-count != '0'",
        "needs.plan.outputs.active-lane-count == '0'",
        "needs.plan.outputs.matrix-lane-count == '0'",
    ):
        assert predicate in replay_header
    assert "Terminal replay requires at most one unexpired source" in replay
    assert "checkpoint artifact; found" in replay
    assert "No source checkpoint exists; rebuilding from attested" in replay
    assert 'gh run download "$SOURCE_RUN_ID"' in replay
    assert "steps.source_checkpoint.outputs.artifact_name != ''" in replay
    assert "source checkpoint lane coverage hashes do not match" in replay
    assert "source checkpoint database SHA-256 does not match" in replay
    assert "source checkpoint artifact identity does not match" in replay
    assert "source checkpoint source SHA does not match" in replay
    assert "checkpoint-manifest.json" in replay
    assert 'cp "$checkpoint_manifest" terminal-replay-inputs/terminal-manifest.json' in replay
    assert 'cp "$plan_manifest_path" terminal-replay-inputs/terminal-manifest.json' not in replay
    assert "needs.terminal_replay.outputs.artifact-name == ''" in completed_manifest_download
    assert "needs.terminal_replay.outputs.artifact-name == ''" in completed_checkpoint_download
    assert "needs.terminal_replay.outputs.artifact-name != ''" in replay_download
    assert (
        "TERMINAL_REPLAYED: ${{ needs.terminal_replay.outputs.artifact-name != '' }}"
        in prepare_merge
    )
    for replay_branch in (
        completed_manifest_download,
        completed_checkpoint_download,
        replay_download,
        prepare_merge,
    ):
        assert "needs.terminal_replay.result == 'success'" not in replay_branch
        assert "needs.terminal_replay.result != 'success'" not in replay_branch
    assert "terminal_replay" in lane_control_header
    for predicate in (
        "inputs.resume_source_run_id != ''",
        "needs.plan.outputs.active-lane-count == '0'",
        "needs.plan.outputs.matrix-lane-count == '0'",
        "needs.terminal_replay.result == 'success'",
        "needs.terminal_replay.outputs.artifact-name == ''",
    ):
        assert predicate in lane_control_header
    metadata_download = _step_block(lane_control, "Download lane metadata")
    assert "if: ${{ needs.plan.outputs.active-lane-count != '0' }}" in metadata_download
    assert "needs.lane_control.result == 'success'" in checkpoint
    checkpoint_inputs = _step_block(checkpoint, "Download checkpoint lane inputs")
    assert 'chain_state.get("artifact_run_ids", [])' in checkpoint_inputs
    assert 'os.environ["CURRENT_RUN_ID"]' in checkpoint_inputs
    assert "previous_lane_ids" in checkpoint_inputs
    assert "full-extraction-discovery-artifacts-{chain_id}" in checkpoint_inputs
    assert "needs.terminal_replay.outputs.artifact-name == ''" in merge


def test_terminal_replay_rejects_ambiguous_or_tampered_checkpoint(
    tmp_path: pathlib.Path,
) -> None:
    replay = _job_block(_workflow_text(), "terminal_replay")
    resolver = _embedded_python(replay, "TERMINAL_REPLAY_ARTIFACT_RESOLVER")
    attestation = _embedded_python(replay, "TERMINAL_REPLAY_ATTESTATION")
    artifacts_path = tmp_path / "artifacts.json"
    output_path = tmp_path / "github-output.txt"
    checkpoint_name = "full-extraction-checkpoint-fixture-chain-iter-3"
    artifacts_path.write_text(
        json.dumps(
            [
                {
                    "artifacts": [
                        {"name": checkpoint_name, "expired": False},
                        {
                            "name": "full-extraction-checkpoint-fixture-chain-iter-2",
                            "expired": True,
                        },
                        {"name": "unrelated", "expired": False},
                    ]
                }
            ]
        ),
        encoding="utf-8",
    )
    resolver_env = {
        "ARTIFACTS_PATH": str(artifacts_path),
        "CHAIN_ID": "fixture-chain",
        "GITHUB_OUTPUT": str(output_path),
    }
    resolved = _run_python(resolver, env=resolver_env)
    assert resolved.returncode == 0, resolved.stderr or resolved.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        f"artifact_name={checkpoint_name}",
        "checkpoint_generation=3",
    ]

    output_path.unlink()
    artifacts_path.write_text('[{"artifacts": []}]\n', encoding="utf-8")
    missing = _run_python(resolver, env=resolver_env)
    assert missing.returncode == 0, missing.stderr or missing.stdout
    assert "No source checkpoint exists" in missing.stdout
    assert not output_path.exists()

    artifacts_path.write_text(
        json.dumps(
            [
                {
                    "artifacts": [
                        {"name": checkpoint_name, "expired": False},
                        {
                            "name": "full-extraction-checkpoint-fixture-chain-iter-4",
                            "expired": False,
                        },
                    ]
                }
            ]
        ),
        encoding="utf-8",
    )
    ambiguous = _run_python(resolver, env=resolver_env)
    assert ambiguous.returncode == 1
    assert "requires at most one unexpired source checkpoint" in ambiguous.stdout

    database_path = tmp_path / "nba.duckdb"
    database_path.write_bytes(b"attested-checkpoint")
    plan_manifest_path = tmp_path / "manifest.json"
    plan_manifest_path.write_text(
        json.dumps(
            {
                "lane_count": 1,
                "active_lane_count": 0,
                "matrix_lane_count": 0,
                "coverage_fingerprint": "fixture-coverage",
                "chain_state": {
                    "latest_checkpoint_run_id": "stale-run",
                    "latest_checkpoint_artifact_name": "stale-artifact",
                    "latest_checkpoint_generation": 2,
                    "latest_checkpoint_coverage_hash": "stale-coverage",
                },
            }
        ),
        encoding="utf-8",
    )
    checkpoint_manifest_path = tmp_path / "checkpoint-manifest.json"
    checkpoint_manifest = {
        "chain_id": "fixture-chain",
        "workflow_source_sha": "a" * 40,
        "lane_count": 1,
        "coverage_fingerprint": "fixture-coverage",
        "chain_state": {
            "latest_checkpoint_run_id": "987654",
            "latest_checkpoint_artifact_name": checkpoint_name,
            "latest_checkpoint_generation": 3,
            "latest_checkpoint_coverage_hash": "fixture-coverage",
        },
        "lanes": [
            {
                "lane_id": "fixture-lane",
                "coverage_units_hash": "fixture-lane-coverage",
            }
        ],
    }
    checkpoint_manifest_path.write_text(json.dumps(checkpoint_manifest), encoding="utf-8")
    report_path = tmp_path / "checkpoint-report.json"
    report = {
        "active_lane_count": 0,
        "chain_id": "fixture-chain",
        "checkpoint_generation": 3,
        "complete_lane_count": 1,
        "coverage_fingerprint": "fixture-coverage",
        "included_lane_coverage_hashes": {"fixture-lane": "fixture-lane-coverage"},
        "database_sha256": hashlib.sha256(database_path.read_bytes()).hexdigest(),
        "run_id": "987654",
        "artifact_name": checkpoint_name,
        "source_sha": "a" * 40,
        "terminal_ready": True,
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    attestation_env = {
        "CHAIN_ID": "fixture-chain",
        "CHECKPOINT_DATABASE_PATH": str(database_path),
        "CHECKPOINT_REPORT_PATH": str(report_path),
        "EXPECTED_CHECKPOINT_GENERATION": "3",
        "PLAN_MANIFEST_PATH": str(plan_manifest_path),
        "CHECKPOINT_MANIFEST_PATH": str(checkpoint_manifest_path),
        "SOURCE_CHECKPOINT_ARTIFACT": checkpoint_name,
        "SOURCE_RUN_ID": "987654",
        "WORKFLOW_SOURCE_SHA": "a" * 40,
    }
    accepted = _run_python(attestation, env=attestation_env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout

    checkpoint_manifest["chain_state"]["latest_checkpoint_generation"] = 2
    checkpoint_manifest_path.write_text(json.dumps(checkpoint_manifest), encoding="utf-8")
    stale_checkpoint_pointer = _run_python(attestation, env=attestation_env)
    assert stale_checkpoint_pointer.returncode == 1
    assert "source checkpoint manifest latest generation does not match" in (
        stale_checkpoint_pointer.stdout
    )
    checkpoint_manifest["chain_state"]["latest_checkpoint_generation"] = 3
    checkpoint_manifest_path.write_text(json.dumps(checkpoint_manifest), encoding="utf-8")

    report["included_lane_coverage_hashes"]["fixture-lane"] = "tampered"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    wrong_lane_contract = _run_python(attestation, env=attestation_env)
    assert wrong_lane_contract.returncode == 1
    assert "source checkpoint lane coverage hashes do not match" in wrong_lane_contract.stdout

    report["included_lane_coverage_hashes"]["fixture-lane"] = "fixture-lane-coverage"
    report["database_sha256"] = "0" * 64
    report_path.write_text(json.dumps(report), encoding="utf-8")
    tampered = _run_python(attestation, env=attestation_env)
    assert tampered.returncode == 1
    assert "source checkpoint database SHA-256 does not match" in tampered.stdout


def test_post_dispatch_poll_requires_one_exact_title_child_and_records_it(
    tmp_path: pathlib.Path,
) -> None:
    dispatch = _job_block(_workflow_text(), "dispatch_next")
    matcher = _embedded_python(dispatch, "CHILD_RUN_MATCHER")
    expected_title = "Full Extraction chain=12345 iteration=2"
    runs_path = tmp_path / "runs.json"
    child_path = tmp_path / "child.json"
    existing_ids_path = tmp_path / "existing.json"
    existing_ids_path.write_text("[]\n", encoding="utf-8")
    base_env = {
        "RUNS_PATH": str(runs_path),
        "CHILD_RUN_PATH": str(child_path),
        "EXISTING_CHILD_RUN_IDS_PATH": str(existing_ids_path),
        "EXPECTED_RUN_NAME": expected_title,
    }

    runs_path.write_text('[{"workflow_runs": []}]\n', encoding="utf-8")
    absent = _run_python(matcher, env=base_env)
    assert absent.returncode == 1
    assert not child_path.exists()

    runs_path.write_text(
        json.dumps(
            [
                {
                    "workflow_runs": [
                        {
                            "id": 10,
                            "display_title": "Full Extraction chain=other iteration=2",
                            "html_url": "https://github.example/runs/10",
                        }
                    ]
                },
                {
                    "workflow_runs": [
                        {
                            "id": 42,
                            "display_title": expected_title,
                            "status": "queued",
                            "html_url": "https://github.example/runs/42",
                        }
                    ]
                },
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    single = _run_python(matcher, env=base_env)
    assert single.returncode == 0, single.stderr or single.stdout
    assert json.loads(child_path.read_text(encoding="utf-8")) == {
        "display_title": expected_title,
        "id": "42",
        "url": "https://github.example/runs/42",
    }

    changed_child = _run_python(
        matcher,
        env={**base_env, "EXPECTED_CHILD_RUN_ID": "41"},
    )
    assert changed_child.returncode == 4
    assert "changed during stabilization" in changed_child.stdout

    runs_path.write_text(
        json.dumps(
            [
                {
                    "workflow_runs": [
                        {
                            "id": run_id,
                            "display_title": expected_title,
                            "status": "queued",
                            "html_url": f"https://github.example/runs/{run_id}",
                        }
                    ]
                }
                for run_id in (42, 43)
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    duplicate = _run_python(matcher, env=base_env)
    assert duplicate.returncode == 2
    assert "created 2 exact-title child runs" in duplicate.stdout

    runs_path.write_text(
        json.dumps(
            [
                {
                    "workflow_runs": [
                        {
                            "id": "invalid",
                            "display_title": expected_title,
                            "html_url": "",
                        }
                    ]
                }
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    malformed = _run_python(matcher, env=base_env)
    assert malformed.returncode == 3
    assert "missing a valid id or URL" in malformed.stdout

    enqueue = dispatch.index("gh workflow run full-extraction.yml")
    poll = dispatch.index('child_run_path="$RUNNER_TEMP/full-extraction-child-run.json"')
    assert enqueue < poll
    assert 'CHILD_POLL_ATTEMPTS: "12"' in dispatch
    assert 'CHILD_POLL_INTERVAL_SECONDS: "5"' in dispatch
    assert "--paginate" in dispatch[poll:]
    assert "--slurp" in dispatch[poll:]
    assert dispatch.count("# CHILD_RUN_MATCHER") == 2
    assert 'EXPECTED_CHILD_RUN_ID="$acknowledged_child_run_id"' in dispatch
    assert "exact-title child inventory did not stabilize" in dispatch
    assert "Self-dispatch child run was not visible" in dispatch
    assert 'echo "child_run_id=$child_run_id"' in dispatch
    assert 'echo "child_run_url=$child_run_url"' in dispatch


def test_ci_runs_checksum_pinned_actionlint_on_all_workflows() -> None:
    workflow = _CI_PATH.read_text(encoding="utf-8")
    actionlint = _job_block(workflow, "workflow-lint")

    assert 'ACTIONLINT_VERSION: "1.7.12"' in actionlint
    assert (
        'ACTIONLINT_SHA256: "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8"'
        in actionlint
    )
    assert "releases/download/v${ACTIONLINT_VERSION}/${archive}" in actionlint
    assert "sha256sum --check --strict" in actionlint
    assert "- name: Run actionlint on all workflows\n        run: actionlint" in actionlint
    actionlint_config = (_REPO_ROOT / ".github" / "actionlint.yaml").read_text(encoding="utf-8")
    assert actionlint_config.count('unexpected key "queue" for "concurrency" section') == 3
    assert "daily-update.yml" in actionlint_config
    assert "full-extraction.yml" in actionlint_config
    assert "monthly-update.yml" in actionlint_config
    assert "/latest" not in actionlint.lower()
    assert "@latest" not in actionlint.lower()
    assert "needs: [workflow-lint, lint, metadata, typecheck]" in workflow


def test_full_extraction_artifacts_are_safe_to_replace_on_job_reruns() -> None:
    workflow = _workflow_text()
    upload_steps = re.findall(
        r"(?ms)^      - (?:name: [^\n]+\n(?:        [^\n]*\n)*)?"
        r"        uses: actions/upload-artifact@[^\n]+\n"
        r"        with:\n(?P<inputs>(?:          [^\n]+\n)+)",
        workflow,
    )

    assert len(upload_steps) == workflow.count("uses: actions/upload-artifact@")
    assert upload_steps
    assert all("overwrite: true" in inputs for inputs in upload_steps)


def test_planner_output_drives_exact_discovery_scope_cardinality(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lanes = [
        {
            "lane_id": "historical-game-2022-2023",
            "lane_kind": "historical",
            "season_start": 2022,
            "season_end": 2023,
            "patterns": ["game"],
            "season_types": ["Regular Season", "Playoffs"],
            "endpoints": ["box_score_summary"],
            "timeout_seconds": 5400,
        },
        {
            "lane_id": "historical-date-2023",
            "lane_kind": "historical",
            "season_start": 2023,
            "season_end": 2023,
            "patterns": ["date"],
            "season_types": ["Regular Season"],
            "endpoints": ["scoreboard_v3"],
            "timeout_seconds": 5400,
        },
        {
            "lane_id": "cross-product-2021-2022",
            "lane_kind": "cross_product",
            "season_start": 2021,
            "season_end": 2022,
            "patterns": ["player_team_season"],
            "season_types": ["Regular Season"],
            "endpoints": ["video_details"],
            "timeout_seconds": 6300,
        },
        {
            "lane_id": "historical-player-season-2020-2021",
            "lane_kind": "historical",
            "season_start": 2020,
            "season_end": 2021,
            "patterns": ["player_season"],
            "endpoints": ["player_game_logs_v2"],
            "timeout_seconds": 4800,
        },
    ]
    output_path = tmp_path / "manifest.json"

    assert (
        full_extraction_main(
            [
                "plan",
                "--lane-manifest-json",
                json.dumps({"lanes": lanes}),
                "--max-matrix-lanes",
                "4",
                "--output-path",
                str(output_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    planned_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    discovery = _load_discovery_seed_module()

    assert planned_manifest["matrix_lane_count"] == 4
    assert set(discovery.game_discovery_pairs(planned_manifest)) == {
        ("2022-23", "Regular Season"),
        ("2022-23", "Playoffs"),
        ("2023-24", "Regular Season"),
        ("2023-24", "Playoffs"),
    }
    assert set(discovery.player_team_season_pairs(planned_manifest)) == {
        ("2021-22", "Regular Season"),
        ("2022-23", "Regular Season"),
    }
    assert [scope.seasons for scope in discovery.player_discovery_scopes(planned_manifest)] == [
        ("2020-21",),
        ("2021-22",),
        ("2020-21", "2021-22"),
    ]


def test_seeded_discovery_artifacts_are_installed_after_state_restore() -> None:
    workflow = _workflow_text()
    seed = _job_block(workflow, "discovery_seed")
    extract = _job_block(workflow, "extract")
    ordered_steps = [
        "- name: Download discovery artifacts",
        "- name: Restore durable lane state artifact",
        "- name: Assess restored state",
        "- name: Install discovery artifacts after state restore",
        "- name: Verify installed discovery bundle",
        "- name: Run extraction",
    ]

    assert extract.count("- name: Install discovery artifacts") == 1
    positions = [extract.index(step) for step in ordered_steps]
    assert positions == sorted(positions)
    assert "rm -rf data/nbadb/nba.discovery-artifacts" in extract
    assert 'cp -R "$artifact_dir" data/nbadb/nba.discovery-artifacts' in extract
    assert "data/nbadb/nba.player-team-season-workload.*.parquet" in seed
    workload_manifest = (
        "data/nbadb/nba.player-team-season-workload.player-team-season-workload.json"
    )
    assert workload_manifest in seed
    assert workload_manifest in extract
    assert "-name 'nba.player-team-season-workload.*.parquet'" in extract
    assert "Seeded player/team workload artifact is incomplete" in extract
    assert "-name 'nba.player-team-season-workload*.parquet'" in extract
    assert extract.index("-name 'nba.player-team-season-workload*.parquet'") < extract.index(
        "mapfile -t workload_parquets"
    )
    installed_verify = _step_block(extract, "Verify installed discovery bundle")
    assert "Downloaded discovery bundle is missing discovery-seed-summary.json" in installed_verify
    assert "Downloaded discovery bundle is missing discovery-manifest.json" in installed_verify
    assert ".github/scripts/verify_discovery_bundle.py" in installed_verify
    assert '--manifest-path "$manifest_path"' in installed_verify
    assert "--duckdb-path data/nbadb/nba.duckdb" in installed_verify
    assert extract.index("mapfile -t workload_parquets") > extract.index(
        "- name: Restore durable lane state artifact"
    )


def test_durable_lane_restore_requires_exact_attested_database() -> None:
    workflow = _workflow_text()
    extract = _job_block(workflow, "extract")
    restore = _step_block(extract, "Restore durable lane state artifact")
    assess = _step_block(extract, "Assess restored state")

    assert 'if [ -z "$STATE_ARTIFACT_RUN_ID" ] ||' in restore
    assert "Run ID, name, and digest are all required" in restore
    assert restore.count(".github/scripts/validate_lane_state.py") == 1
    assert restore.count('--expected-sha256 "$STATE_ARTIFACT_DIGEST"') == 1
    assert restore.count("--require-journal") == 1
    assert "--attestation-path" in restore
    assert "--expected-source-sha" in restore
    assert "--expected-chain-id" in restore
    assert "--expected-lane-id" in restore
    assert "--expected-coverage-units-hash" in restore
    assert '--expected-run-id "$STATE_ARTIFACT_RUN_ID"' in restore
    assert '--expected-artifact-name "$STATE_ARTIFACT_NAME"' in restore
    assert "--workload-duckdb-path" in restore
    assert "--workload-season-start" in restore
    assert "--workload-season-end" in restore
    assert "--workload-season-types" in restore
    assert "Workload-bound lane state requires the active discovery workload manifest" in restore
    assert "--allow-attested-empty" in restore
    assert "Required state artifact $STATE_ARTIFACT_NAME is unavailable" in restore
    assert "must contain exactly one nba.duckdb" in restore
    assert "python -c" not in restore
    assert "STATE_ARTIFACT_REQUIRED:" in assess
    assert ".github/scripts/validate_lane_state.py" in assess
    assert '--expected-run-id "$STATE_ARTIFACT_RUN_ID"' in assess
    assert '--expected-artifact-name "$STATE_ARTIFACT_NAME"' in assess
    assert "Required durable lane state was not restored" in assess
    assert "Fresh lane contains unexpected unattested DuckDB state" in assess
    assert "artifacts/extraction/lane-state-untrusted" in assess
    assert "durable lane state failed exact validation" in assess
    assert "python -c" not in assess
    assert "Restore exact completed lane state" not in extract
    assert "Save exact completed lane state" not in extract
    assert "actions/cache/restore@" not in extract
    assert "actions/cache/save@" not in extract
    assert "matrix.parent_lane_id" not in restore
    assert "Restore extraction state" not in extract
    assert "Save extraction state" not in extract
    assert "CACHE_KEY: full-extraction-state" not in workflow
    assert "LANE_STATE_CACHE_KEY" not in workflow


def test_discovery_seed_vpn_lifecycle_is_mode_gated_and_always_cleaned_up() -> None:
    seed = _job_block(_workflow_text(), "discovery_seed")
    vpn_step = _step_block(seed, "Connect NordVPN tunnel for discovery seeding")

    assert seed.count("- name: Connect NordVPN tunnel for discovery seeding") == 1
    assert "RUN_ATTEMPT: ${{ github.run_attempt }}" in vpn_step
    assert "export LANE_INDEX=$((RUN_ATTEMPT - 1))" in vpn_step
    assert "if: ${{ needs.preflight.outputs.effective-network-mode == 'vpn' }}" in seed
    assert "- name: Upload discovery seed VPN diagnostics" in seed
    assert "name: discovery-seed-vpn-diagnostics-${{ env.ACTIVE_CHAIN_ID }}" in seed
    assert "- name: Disconnect discovery seed VPN" in seed
    assert (
        seed.count("if: ${{ always() && needs.preflight.outputs.effective-network-mode == 'vpn' }}")
        == 2
    )
    assert seed.index("- name: Connect NordVPN tunnel for discovery seeding") < seed.index(
        "- name: Seed discovery artifacts"
    )
    assert seed.index("- name: Seed discovery artifacts") < seed.index(
        "- name: Upload discovery seed VPN diagnostics"
    )
    assert seed.index("- name: Upload discovery seed VPN diagnostics") < seed.index(
        "- name: Disconnect discovery seed VPN"
    )


def test_preflight_vpn_failures_are_carried_into_every_lane_quarantine(
    tmp_path: pathlib.Path,
) -> None:
    workflow = _workflow_text()
    preflight = _job_block(workflow, "preflight")
    seed = _job_block(workflow, "discovery_seed")
    extract = _job_block(workflow, "extract")
    vpn_step = _step_block(preflight, "Preflight VPN validation")
    quarantine_step = _step_block(
        preflight,
        "Carry preflight VPN failures into the chain quarantine",
    )

    assert "timeout-minutes: 7" in vpn_step
    assert 'SERVER_LIMIT: "4"' in vpn_step
    assert "RUN_ATTEMPT: ${{ github.run_attempt }}" in vpn_step
    assert "export LANE_INDEX=$((RUN_ATTEMPT - 1))" in vpn_step
    assert 'SERVER_POOL_SIZE: "96"' in vpn_step
    assert 'CONNECT_TIMEOUT_SECONDS: "60"' in vpn_step
    assert 'OVERALL_TIMEOUT_SECONDS: "300"' in vpn_step
    assert (
        "vpn-quarantined-servers-json: "
        "${{ steps.vpn_quarantine.outputs.vpn-quarantined-servers-json }}"
    ) in preflight
    downstream_quarantine = (
        "QUARANTINED_SERVERS_JSON: ${{ needs.preflight.outputs.vpn-quarantined-servers-json }}"
    )
    assert downstream_quarantine in seed
    assert downstream_quarantine in extract
    assert 'CONNECT_TIMEOUT_SECONDS: "60"' in seed
    assert 'CONNECT_TIMEOUT_SECONDS: "60"' in extract
    assert 'SERVER_POOL_SIZE: "96"' in seed
    assert 'SERVER_POOL_SIZE: "96"' in extract
    for job in (preflight, seed, extract):
        assert "timeout-minutes: 7" in job
        assert "350 \\" in job
        assert "10 \\" in job

    output_path = tmp_path / "github-output.txt"
    result = _run_python(
        _embedded_python(quarantine_step, "PREFLIGHT_VPN_QUARANTINE"),
        env={
            "CHAIN_QUARANTINE_JSON": '["us1.nordvpn.com","us2.nordvpn.com"]',
            "PREFLIGHT_FAILED_JSON": '["us2.nordvpn.com","us3.nordvpn.com"]',
            "GITHUB_OUTPUT": str(output_path),
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.read_text(encoding="utf-8") == (
        'vpn-quarantined-servers-json=["us1.nordvpn.com","us2.nordvpn.com","us3.nordvpn.com"]\n'
    )


def test_preflight_auth_attestation_controls_downstream_vpn_recovery() -> None:
    workflow = _workflow_text()
    preflight = _job_block(workflow, "preflight")
    seed = _job_block(workflow, "discovery_seed")
    extract = _job_block(workflow, "extract")

    assert "vpn-auth-source: ${{ steps.vpn.outputs.auth-source }}" in preflight
    assert "**Validated VPN credential source:** ${VPN_AUTH_SOURCE:-unknown}" in preflight
    assert "VPN connected without a valid credential-source attestation" in preflight

    require_token = (
        "REQUIRE_TOKEN_AUTH: ${{ needs.preflight.outputs.vpn-auth-source == 'token' "
        "&& 'true' || 'false' }}"
    )
    configured_prevalidated = (
        "CONFIGURED_AUTH_PREVALIDATED: ${{ needs.preflight.outputs.vpn-auth-source "
        "== 'configured' && 'true' || 'false' }}"
    )
    for job in (seed, extract):
        assert require_token in job
        assert configured_prevalidated in job

    assert "needs.preflight.outputs.vpn-auth-source == 'token' && '1'" in extract


def test_verified_vpn_servers_are_assigned_to_distinct_extract_slots() -> None:
    workflow = _workflow_text()
    preflight = _job_block(workflow, "preflight")
    seed = _job_block(workflow, "discovery_seed")
    extract = _job_block(workflow, "extract")
    seed_vpn_step = _step_block(seed, "Connect NordVPN tunnel for discovery seeding")
    vpn_step = _step_block(extract, "Connect NordVPN tunnel")

    assert "vpn-server: ${{ steps.vpn.outputs.server }}" in preflight
    assert "vpn-server: ${{ steps.vpn.outputs.server }}" in seed
    assert (
        "PREFERRED_SERVERS_JSON: ${{ format('[\"{0}\"]', needs.preflight.outputs.vpn-server) }}"
    ) in seed_vpn_step
    assert 'PREFERRED_SERVER_SLOT_COUNT: "1"' in seed_vpn_step
    assert (
        'PREFERRED_SERVERS_JSON: ${{ format(\'["{0}","{1}"]\', '
        "needs.discovery_seed.outputs.vpn-server, needs.preflight.outputs.vpn-server) }}"
    ) in vpn_step
    assert (
        "PREFERRED_SERVER_SLOT_COUNT: ${{ needs.preflight.outputs.vpn-auth-source == "
        "'token' && '1' || inputs.vpn_parallelism }}"
    ) in vpn_step


def test_network_mode_resolution_rejects_unattested_connected_tunnels(
    tmp_path: pathlib.Path,
) -> None:
    preflight = _job_block(_workflow_text(), "preflight")
    step = _step_block(preflight, "Resolve effective network mode")
    assert "VPN_AUTH_SOURCE: ${{ steps.vpn.outputs.auth-source }}" in step
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    cases = (
        ("vpn", "connected", "configured", 0, "effective-network-mode=vpn\n"),
        ("vpn", "connected", "token", 0, "effective-network-mode=vpn\n"),
        ("vpn", "connected", "", 1, ""),
        ("vpn", "connected", "unknown", 1, ""),
        ("auto", "vpn_auth_failure", "", 0, "effective-network-mode=direct\n"),
        ("direct", "unknown", "", 0, "effective-network-mode=direct\n"),
    )

    for index, (requested, status, auth_source, expected_rc, expected_output) in enumerate(cases):
        output_path = tmp_path / f"network-mode-{index}.txt"
        output_path.touch()
        result = subprocess.run(
            ["bash", "-c", "set -euo pipefail\n" + script],
            check=False,
            capture_output=True,
            env={
                **os.environ,
                "REQUESTED_NETWORK_MODE": requested,
                "VPN_STATUS": status,
                "VPN_AUTH_SOURCE": auth_source,
                "VPN_SERVER": "us1001.nordvpn.com",
                "VPN_EXIT_IP": "192.0.2.1",
                "GITHUB_OUTPUT": str(output_path),
            },
            text=True,
        )

        assert result.returncode == expected_rc, result.stderr or result.stdout
        assert output_path.read_text(encoding="utf-8") == expected_output


def test_effective_preflight_quarantine_is_persisted_into_the_next_manifest(
    tmp_path: pathlib.Path,
) -> None:
    lane_control = _job_block(_workflow_text(), "lane_control")
    build_step = _step_block(lane_control, "Build next manifest")
    assert (
        "PREFLIGHT_QUARANTINE_JSON: "
        "${{ needs.preflight.outputs.vpn-quarantined-servers-json }}" in build_step
    )
    script = _embedded_python(build_step, "PREFLIGHT_QUARANTINE_PERSISTENCE")
    manifest_path = tmp_path / "artifacts" / "full-extraction" / "current-manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "chain_state": {
                    "vpn_quarantined_servers": [
                        "us1.nordvpn.com",
                        "us2.nordvpn.com",
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = _run_python(
        script,
        cwd=tmp_path,
        env={"PREFLIGHT_QUARANTINE_JSON": ('["us2.nordvpn.com","us3.nordvpn.com"]')},
    )

    assert result.returncode == 0, result.stderr or result.stdout
    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted["chain_state"]["vpn_quarantined_servers"] == [
        "us1.nordvpn.com",
        "us2.nordvpn.com",
        "us3.nordvpn.com",
    ]


def test_discovery_seed_has_a_process_deadline_inside_the_job_timeout() -> None:
    seed = _job_block(_workflow_text(), "discovery_seed")
    seed_step = _step_block(seed, "Seed discovery artifacts")

    assert 'NBADB_DISCOVERY_SEED_DEADLINE_SECONDS: "5400"' in seed_step
    assert "bash .github/scripts/run_with_deadline.sh" in seed_step
    assert "5700 \\" in seed_step
    assert "15 \\" in seed_step


def test_discovery_seed_concurrency_tracks_network_mode_and_request_profile() -> None:
    seed = _job_block(_workflow_text(), "discovery_seed")
    configure = seed.split("      - name: Configure discovery seed concurrency\n", 1)[1].split(
        "      - name: Connect NordVPN tunnel for discovery seeding\n",
        1,
    )[0]

    assert (
        "EFFECTIVE_NETWORK_MODE: ${{ needs.preflight.outputs.effective-network-mode }}" in configure
    )
    assert "SEED_REQUEST_PROFILE: ${{ inputs.concurrency }}" in configure
    assert 'if [ "$EFFECTIVE_NETWORK_MODE" = "direct" ]; then' in configure
    assert "seed_concurrency=2" in configure
    assert "seed_rate_limit=2" in configure
    assert "conservative)" in configure
    assert "seed_concurrency=2" in configure
    assert "moderate)" in configure
    assert "seed_concurrency=3" in configure
    assert "seed_rate_limit=2" in configure
    assert "aggressive)" in configure
    assert "seed_concurrency=4" in configure
    assert "seed_rate_limit=3" in configure
    assert 'echo "NBADB_RATE_LIMIT=$seed_rate_limit"' in configure
    assert 'echo "NBADB_DISCOVERY_CONCURRENCY=$seed_concurrency"' in configure
    assert 'echo "NBADB_DISCOVERY_SEED_CONCURRENCY=$seed_concurrency"' in configure


@pytest.mark.parametrize(
    ("network_mode", "profile", "expected_env"),
    [
        (
            "direct",
            "aggressive",
            "NBADB_RATE_LIMIT=2\nNBADB_DISCOVERY_CONCURRENCY=2\n"
            "NBADB_DISCOVERY_SEED_CONCURRENCY=2\n",
        ),
        (
            "vpn",
            "conservative",
            "NBADB_RATE_LIMIT=1\nNBADB_DISCOVERY_CONCURRENCY=2\n"
            "NBADB_DISCOVERY_SEED_CONCURRENCY=2\n",
        ),
        (
            "vpn",
            "moderate",
            "NBADB_RATE_LIMIT=2\nNBADB_DISCOVERY_CONCURRENCY=3\n"
            "NBADB_DISCOVERY_SEED_CONCURRENCY=3\n",
        ),
        (
            "vpn",
            "aggressive",
            "NBADB_RATE_LIMIT=3\nNBADB_DISCOVERY_CONCURRENCY=4\n"
            "NBADB_DISCOVERY_SEED_CONCURRENCY=4\n",
        ),
    ],
)
def test_discovery_seed_profiles_emit_executable_rate_and_concurrency_contract(
    tmp_path: pathlib.Path,
    network_mode: str,
    profile: str,
    expected_env: str,
) -> None:
    seed = _job_block(_workflow_text(), "discovery_seed")
    configure = seed.split("      - name: Configure discovery seed concurrency\n", 1)[1].split(
        "      - name: Connect NordVPN tunnel for discovery seeding\n",
        1,
    )[0]
    script = textwrap.dedent(configure.split("        run: |\n", 1)[1])
    github_env = tmp_path / f"github-env-{network_mode}-{profile}"

    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + script],
        check=False,
        capture_output=True,
        env={
            **os.environ,
            "EFFECTIVE_NETWORK_MODE": network_mode,
            "SEED_REQUEST_PROFILE": profile,
            "GITHUB_ENV": str(github_env),
        },
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert github_env.read_text(encoding="utf-8") == expected_env


def test_chained_discovery_seed_restores_exact_prior_run_artifact() -> None:
    seed = _job_block(_workflow_text(), "discovery_seed")

    assert "actions: read" in seed
    assert "- name: Restore prior discovery artifacts" in seed
    assert (
        "if: ${{ inputs.lane_manifest_run_id != '' || inputs.resume_source_run_id != '' || "
        "github.run_attempt > 1 }}"
    ) in seed
    assert "CURRENT_RUN_ID: ${{ github.run_id }}" in seed
    assert "RUN_ATTEMPT: ${{ github.run_attempt }}" in seed
    assert (
        "MANIFEST_SOURCE_RUN_ID: ${{ inputs.lane_manifest_run_id || inputs.resume_source_run_id }}"
    ) in seed
    assert (
        "DISCOVERY_ARTIFACT_NAME: full-extraction-discovery-artifacts-${{ env.ACTIVE_CHAIN_ID }}"
    ) in seed
    assert (
        "DISCOVERY_RECOVERY_PREFIX: full-extraction-discovery-recovery-${{ env.ACTIVE_CHAIN_ID }}"
    ) in seed
    assert 'restore_discovery_from_run "$CURRENT_RUN_ID" "current-run"' in seed
    assert 'restore_discovery_from_run "$MANIFEST_SOURCE_RUN_ID" "manifest-source"' in seed
    assert seed.index('restore_discovery_from_run "$CURRENT_RUN_ID" "current-run"') < seed.index(
        'restore_discovery_from_run "$MANIFEST_SOURCE_RUN_ID" "manifest-source"'
    )
    assert 'gh run download "$source_run_id"' in seed
    assert '--name "$DISCOVERY_ARTIFACT_NAME"' in seed
    assert '--pattern "$recovery_pattern"' in seed
    assert "sort -V" in seed
    assert "Restored latest incomplete discovery recovery bundle" in seed
    assert "seeding this wave from scratch" in seed
    assert seed.index("- name: Restore prior discovery artifacts") < seed.index(
        "- name: Seed discovery artifacts"
    )
    assert "Prior player/team workload artifact is incomplete; ignoring it" in seed
    assert "Canonical discovery workload bundle is incomplete" in seed
    assert "Canonical discovery workload bundle is missing" in seed
    assert "restored workload pointer or generation failed integrity validation" in seed
    assert "Canonical discovery workload failed integrity validation" in seed
    assert "Discarding invalid recovery workload state before reseeding" in seed


def _restore_discovery_script() -> str:
    seed = _job_block(_workflow_text(), "discovery_seed")
    restore = _step_block(seed, "Restore prior discovery artifacts")
    return textwrap.dedent(restore.split("        run: |\n", 1)[1]).replace(
        "${{ github.repository }}",
        "owner/repo",
    )


def _install_restore_test_commands(tmp_path: pathlib.Path) -> pathlib.Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    gh = fake_bin / "gh"
    gh.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            printf '%s\\n' "$*" >> "$GH_LOG"
            run_id="$3"
            shift 3
            destination=""
            request_kind=""
            request_value=""
            while [ "$#" -gt 0 ]; do
              case "$1" in
                --dir)
                  destination="$2"
                  shift 2
                  ;;
                --name)
                  request_kind="canonical"
                  request_value="$2"
                  shift 2
                  ;;
                --pattern)
                  request_kind="recovery"
                  request_value="$2"
                  shift 2
                  ;;
                *)
                  shift
                  ;;
              esac
            done

            marker=""
            complete="true"
            if [ "$GH_SCENARIO:$run_id:$request_kind" = "multi-recovery:101:recovery" ]; then
              recovery_prefix="${request_value%\\*}"
              for attempt in 1 2; do
                target="$destination/${recovery_prefix}${attempt}"
                mkdir -p "$target"
                if [ "$attempt" = "1" ]; then
                  marker="old-recovery"
                else
                  marker="latest-recovery"
                fi
                printf '{"marker":"%s"}\\n' "$marker" \
                  > "$target/nba.player-team-season-workload.player-team-season-workload.json"
                printf 'test parquet for %s\\n' "$marker" \
                  > "$target/nba.player-team-season-workload.generation.parquet"
              done
              exit 0
            fi
            case "$GH_SCENARIO:$run_id:$request_kind" in
              current-canonical:101:canonical)
                marker="current"
                ;;
              source-fallback:202:canonical)
                marker="source"
                ;;
              single-recovery:101:recovery)
                marker="single-recovery"
                ;;
              canonical-partial:101:canonical)
                marker="partial"
                complete="false"
                ;;
              *)
                exit 1
                ;;
            esac

            mkdir -p "$destination"
            printf '{"marker":"%s"}\\n' "$marker" \
              > "$destination/nba.player-team-season-workload.player-team-season-workload.json"
            if [ "$complete" = "true" ]; then
              printf 'test parquet for %s\\n' "$marker" \
                > "$destination/nba.player-team-season-workload.generation.parquet"
            fi
            """
        ),
        encoding="utf-8",
    )
    gh.chmod(0o755)
    uv = fake_bin / "uv"
    uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    return fake_bin


@pytest.mark.parametrize(
    ("scenario", "expected_marker", "source_run_expected"),
    [
        ("current-canonical", "current", False),
        ("single-recovery", "single-recovery", False),
        ("multi-recovery", "latest-recovery", False),
        ("source-fallback", "source", True),
    ],
)
def test_discovery_restore_executes_precedence_fallback_and_recovery_layouts(
    tmp_path: pathlib.Path,
    scenario: str,
    expected_marker: str,
    source_run_expected: bool,
) -> None:
    fake_bin = _install_restore_test_commands(tmp_path)
    gh_log = tmp_path / "gh.log"
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _restore_discovery_script()],
        check=False,
        capture_output=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GH_LOG": str(gh_log),
            "GH_SCENARIO": scenario,
            "CURRENT_RUN_ID": "101",
            "RUN_ATTEMPT": "2",
            "MANIFEST_SOURCE_RUN_ID": "202",
            "DISCOVERY_ARTIFACT_NAME": "canonical-artifact",
            "DISCOVERY_RECOVERY_PREFIX": "recovery-artifact",
        },
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    restored_pointer = (
        tmp_path / "data/nbadb/nba.player-team-season-workload.player-team-season-workload.json"
    )
    assert json.loads(restored_pointer.read_text(encoding="utf-8"))["marker"] == expected_marker
    calls = gh_log.read_text(encoding="utf-8")
    assert ("run download 202" in calls) is source_run_expected


def test_discovery_restore_rejects_truncated_canonical_bundle(
    tmp_path: pathlib.Path,
) -> None:
    fake_bin = _install_restore_test_commands(tmp_path)
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _restore_discovery_script()],
        check=False,
        capture_output=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GH_LOG": str(tmp_path / "gh.log"),
            "GH_SCENARIO": "canonical-partial",
            "CURRENT_RUN_ID": "101",
            "RUN_ATTEMPT": "2",
            "MANIFEST_SOURCE_RUN_ID": "",
            "DISCOVERY_ARTIFACT_NAME": "canonical-artifact",
            "DISCOVERY_RECOVERY_PREFIX": "recovery-artifact",
        },
        text=True,
    )

    assert result.returncode == 1
    assert "Canonical discovery workload bundle is incomplete" in result.stdout
