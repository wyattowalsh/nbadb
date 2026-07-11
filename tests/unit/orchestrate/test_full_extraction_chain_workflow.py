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
from typing import TYPE_CHECKING

from nbadb.orchestrate.full_extraction_control import main as full_extraction_main

if TYPE_CHECKING:
    import pytest

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


def _metadata_commit_script() -> str:
    action = _REFRESH_METADATA_ACTION_PATH.read_text(encoding="utf-8")
    return textwrap.dedent(
        action.split("    - name: Commit refreshed metadata\n", 1)[1].split("      run: |\n", 1)[1]
    )


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

    assert (
        "LANE_CONTROL_ACTIVE_LANE_COUNT: ${{ needs.lane_control.outputs.active-lane-count }}"
    ) in checkpoint
    disagreement_guard = "if checkpoint_active_lane_count != lane_control_active_lane_count:"
    assert disagreement_guard in checkpoint
    assert "Lane-control/checkpoint remaining-count disagreement" in checkpoint
    assert "if lane_control_active_lane_count == 0 and not terminal_ready:" in checkpoint
    assert "if lane_control_active_lane_count > 0 and terminal_ready:" in checkpoint
    assert "Checkpoint report includes completed lanes but its database is missing" in checkpoint
    assert checkpoint.index(disagreement_guard) < checkpoint.index(
        'with Path(os.environ["GITHUB_OUTPUT"]).open'
    )

    assert "needs.checkpoint.result == 'success'" in dispatch
    assert (
        "needs.checkpoint.outputs.active-lane-count == needs.lane_control.outputs.active-lane-count"
    ) in dispatch
    assert "needs.checkpoint.outputs.terminal-ready == 'false'" in dispatch


def test_lane_control_requires_a_successful_seed_and_non_skipped_extract() -> None:
    workflow = _workflow_text()
    extract = _job_block(workflow, "extract")
    lane_control = _job_block(workflow, "lane_control")
    checkpoint = _job_block(workflow, "checkpoint")
    dispatch = _job_block(workflow, "dispatch_next")
    lane_control_header = lane_control.split("    steps:\n", 1)[0]

    assert "needs.discovery_seed.result == 'success'" in extract
    assert "needs: [plan, preflight, discovery_seed, extract]" in lane_control_header
    assert "needs.discovery_seed.result == 'success'" in lane_control_header
    assert "needs.extract.result != 'skipped'" in lane_control_header
    assert "needs.extract.result == 'success'" not in lane_control_header
    assert "--allow-missing-attempted-metadata" in lane_control

    # Matrix failures still produce metadata/checkpoints and may dispatch a child.
    assert "needs.lane_control.result == 'success'" in checkpoint
    assert "needs.lane_control.result == 'success'" in dispatch
    assert "needs.checkpoint.result == 'success'" in dispatch


def test_discovery_artifact_upload_is_success_only_and_fail_closed() -> None:
    seed = _job_block(_workflow_text(), "discovery_seed")
    verify = _step_block(seed, "Verify complete discovery bundle")
    upload = _step_block(seed, "Upload discovery artifacts")
    recovery_upload = _step_block(seed, "Upload incomplete discovery recovery artifact")

    assert "if: ${{ success() }}" in upload
    assert "if: always()" not in upload
    assert "if-no-files-found: error" in upload
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


def test_incomplete_lane_state_is_recovery_only_and_run_attempt_scoped(
    tmp_path: pathlib.Path,
) -> None:
    workflow = _workflow_text()
    extract = _job_block(workflow, "extract")
    metadata_step = _step_block(extract, "Write lane metadata")
    complete_upload = _step_block(extract, "Upload complete lane artifact")
    recovery_upload = _step_block(extract, "Upload incomplete lane state artifact")
    checkpoint_download = _step_block(
        _job_block(workflow, "checkpoint"),
        "Download current lane artifacts",
    )
    complete_name = "extraction-lane-${{ env.ACTIVE_CHAIN_ID }}-${{ matrix.lane_id }}"
    recovery_name = (
        "extraction-lane-recovery-${{ env.ACTIVE_CHAIN_ID }}-${{ matrix.lane_id }}-"
        "run-${{ github.run_id }}-attempt-${{ github.run_attempt }}"
    )

    assert complete_name in complete_upload
    assert recovery_name in metadata_step
    assert recovery_name in recovery_upload
    assert complete_name not in recovery_upload
    assert "steps.lane_metadata.outputs.final-outcome != 'complete'" in recovery_upload
    assert '--pattern "extraction-lane-${ACTIVE_CHAIN_ID}-*"' in checkpoint_download
    assert "extraction-lane-recovery-" not in checkpoint_download

    rewrite = _embedded_python(metadata_step, "RECOVERY_ARTIFACT_METADATA_REWRITE")
    metadata_path = tmp_path / "artifacts" / "extraction" / "lane-metadata.json"
    metadata_path.parent.mkdir(parents=True)
    runtime_recovery_name = "extraction-lane-recovery-chain-lane-run-123-attempt-2"
    for status, expected_name in (
        ("needs_resume", runtime_recovery_name),
        ("cancelled", runtime_recovery_name),
        ("complete", "extraction-lane-chain-lane"),
    ):
        metadata_path.write_text(
            json.dumps(
                {
                    "status": status,
                    "state_artifact": {"name": "extraction-lane-chain-lane"},
                }
            ),
            encoding="utf-8",
        )
        result = _run_python(
            rewrite,
            cwd=tmp_path,
            env={"RECOVERY_ARTIFACT_NAME": runtime_recovery_name},
        )
        assert result.returncode == 0, result.stderr or result.stdout
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert metadata["state_artifact"]["name"] == expected_name


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


def test_workflow_concurrency_is_chain_iteration_scoped() -> None:
    workflow = _workflow_text()
    workflow_concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]

    assert (
        "group: full-extraction-chain-${{ inputs.chain_id || github.run_id }}-"
        "iteration-${{ inputs.iteration }}"
    ) in workflow_concurrency
    assert "github.ref" not in workflow_concurrency
    assert "cancel-in-progress: false" in workflow_concurrency


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
    manifest_path.write_text("{}\n", encoding="utf-8")
    base_env = {
        "MANIFEST_PATH": str(manifest_path),
        "REQUESTED_CHAIN_ID": "12345",
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

    unprovable_custom_name = _run_python(
        verifier,
        env={**base_env, "ARTIFACT_NAME": "manual-manifest"},
    )
    assert unprovable_custom_name.returncode == 1
    assert "Unable to verify original chain identity" in unprovable_custom_name.stdout

    manifest_path.write_text('{"chain_id": "99999"}\n', encoding="utf-8")
    mismatched_manifest = _run_python(
        verifier,
        env={**base_env, "ARTIFACT_NAME": "manual-manifest"},
    )
    assert mismatched_manifest.returncode == 1
    assert "Manifest chain identity does not match" in mismatched_manifest.stdout


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
    assert (
        upload_position < detect_position < persist_position < receipt_position < artifact_position
    )


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
        assert "EXPORT_OUTCOME: ${{ steps.export.outcome }}" in assertion
        assert "METADATA_OUTCOME: ${{ steps.metadata.outcome }}" in assertion


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
    assert 'git merge-base --is-ancestor "$target_commit" "$source_commit"' in commit_step
    assert "Metadata push would not be a fast-forward" in commit_step
    assert 'git push origin "HEAD:${remote_ref}"' in commit_step
    assert "\n        git push\n" not in action
    assert commit_step.index("git merge-base --is-ancestor") < commit_step.index("git diff --quiet")
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
    assured_upload = _step_block(merge, "Upload assured final data artifact")
    exact_download = _step_block(publish, "Download exact assured data artifact")
    identity = _step_block(publish, "Validate assured data artifact identity")
    metadata = _step_block(publish, "Refresh checked-in metadata")
    upload = _step_block(publish, "Upload to Kaggle")
    receipt = _step_block(publish, "Upload Kaggle publication receipt")
    final_artifact = _step_block(publish, "Upload final database")

    unique_name = (
        "nbadb-full-extraction-assured-${{ env.ACTIVE_CHAIN_ID }}-"
        "${{ github.run_id }}-${{ github.run_attempt }}"
    )
    assert unique_name in assured_upload
    assert "if-no-files-found: error" in assured_upload
    assert "name: ${{ needs.merge.outputs.final-data-artifact-name }}" in exact_download
    assert "pattern:" not in exact_download
    assert "ARTIFACT_ID: ${{ needs.merge.outputs.final-data-artifact-id }}" in identity
    assert "ARTIFACT_DIGEST: ${{ needs.merge.outputs.final-data-artifact-digest }}" in identity
    assert "needs: [plan, publication_preflight, merge]" in publish
    assert "needs.publication_preflight.result == 'success'" in publish
    assert "needs.merge.result == 'success'" in publish
    assert "continue-on-error" not in metadata
    assert "continue-on-error" not in upload
    assert "if: always()" in receipt
    assert "if: always()" in final_artifact
    assert "name: nbadb-full-extraction-${{ env.ACTIVE_CHAIN_ID }}" in final_artifact
    assert publish.index("Refresh checked-in metadata") < publish.index("Upload to Kaggle")


def test_zero_active_resume_replays_terminal_checkpoint_without_lane_jobs() -> None:
    workflow = _workflow_text()
    preflight = _job_block(workflow, "preflight")
    discovery = _job_block(workflow, "discovery_seed")
    replay = _job_block(workflow, "terminal_replay")
    merge = _job_block(workflow, "merge")
    lane_control = _job_block(workflow, "lane_control")
    checkpoint = _job_block(workflow, "checkpoint")
    replay_header = replay.split("    steps:\n", 1)[0]

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
    assert "Terminal replay requires exactly one unexpired source" in replay
    assert "checkpoint artifact; found" in replay
    assert 'gh run download "$SOURCE_RUN_ID"' in replay
    assert "source checkpoint lane coverage hashes do not match" in replay
    assert "source checkpoint database SHA-256 does not match" in replay
    assert "needs.terminal_replay.result == 'success'" in merge
    assert "Download replayed terminal checkpoint" in merge
    assert "needs.plan.outputs.active-lane-count != '0'" in lane_control
    assert "needs.lane_control.result == 'success'" in checkpoint


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
    assert "requires exactly one unexpired source checkpoint" in ambiguous.stdout

    database_path = tmp_path / "nba.duckdb"
    database_path.write_bytes(b"attested-checkpoint")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_count": 1,
                "active_lane_count": 0,
                "matrix_lane_count": 0,
                "coverage_fingerprint": "fixture-coverage",
                "lanes": [
                    {
                        "lane_id": "fixture-lane",
                        "coverage_units_hash": "fixture-lane-coverage",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
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
        "terminal_ready": True,
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    attestation_env = {
        "CHAIN_ID": "fixture-chain",
        "CHECKPOINT_DATABASE_PATH": str(database_path),
        "CHECKPOINT_REPORT_PATH": str(report_path),
        "EXPECTED_CHECKPOINT_GENERATION": "3",
        "MANIFEST_PATH": str(manifest_path),
        "SOURCE_RUN_ID": "987654",
    }
    accepted = _run_python(attestation, env=attestation_env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout

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
            "endpoints": ["player_dashboard_by_year_over_year"],
            "timeout_seconds": 6300,
        },
        {
            "lane_id": "historical-player-season-2020-2021",
            "lane_kind": "historical",
            "season_start": 2020,
            "season_end": 2021,
            "patterns": ["player_season"],
            "endpoints": ["player_career_stats"],
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
        "- name: Restore extraction state",
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
        "- name: Restore extraction state"
    )


def test_discovery_seed_vpn_lifecycle_is_mode_gated_and_always_cleaned_up() -> None:
    seed = _job_block(_workflow_text(), "discovery_seed")

    assert seed.count("- name: Connect NordVPN tunnel for discovery seeding") == 1
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
    assert "conservative) seed_concurrency=4 ;;" in configure
    assert "moderate) seed_concurrency=6 ;;" in configure
    assert "aggressive) seed_concurrency=8 ;;" in configure
    assert 'echo "NBADB_DISCOVERY_CONCURRENCY=$seed_concurrency"' in configure
    assert 'echo "NBADB_DISCOVERY_SEED_CONCURRENCY=$seed_concurrency"' in configure


def test_chained_discovery_seed_restores_exact_prior_run_artifact() -> None:
    seed = _job_block(_workflow_text(), "discovery_seed")

    assert "actions: read" in seed
    assert "- name: Restore prior discovery artifacts" in seed
    assert "if: ${{ inputs.lane_manifest_run_id != '' }}" in seed
    assert "PRIOR_RUN_ID: ${{ inputs.lane_manifest_run_id }}" in seed
    assert (
        "DISCOVERY_ARTIFACT_NAME: full-extraction-discovery-artifacts-${{ env.ACTIVE_CHAIN_ID }}"
    ) in seed
    assert (
        "DISCOVERY_RECOVERY_PATTERN: full-extraction-discovery-recovery-"
        "${{ env.ACTIVE_CHAIN_ID }}-run-${{ inputs.lane_manifest_run_id }}-attempt-*"
    ) in seed
    assert 'gh run download "$PRIOR_RUN_ID"' in seed
    assert '--name "$DISCOVERY_ARTIFACT_NAME"' in seed
    assert '--pattern "$DISCOVERY_RECOVERY_PATTERN"' in seed
    assert "sort -V" in seed
    assert "Restored latest incomplete discovery recovery bundle" in seed
    assert "seeding this wave from scratch" in seed
    assert seed.index("- name: Restore prior discovery artifacts") < seed.index(
        "- name: Seed discovery artifacts"
    )
    assert "Prior player/team workload artifact is incomplete; ignoring it" in seed
