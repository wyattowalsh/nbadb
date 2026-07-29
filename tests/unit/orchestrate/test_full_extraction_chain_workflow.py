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

from nbadb.orchestrate.checkpoint_contract import (
    CheckpointArtifactReceipt,
    CheckpointTransaction,
)
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


def _embedded_python_after(workflow_block: str, anchor: str) -> str:
    remainder = workflow_block[workflow_block.index(anchor) + len(anchor) :]
    match = re.search(
        r"(?ms)python - <<'PY'\n(?P<body>.*?)(?=^[ \t]*PY[ \t]*$)",
        remainder,
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


def _gh_fixture_env(
    tmp_path: pathlib.Path,
    responses: list[object],
) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    responses_path = tmp_path / "gh-responses.json"
    counter_path = tmp_path / "gh-counter.txt"
    responses_path.write_text(json.dumps(responses), encoding="utf-8")
    gh_path = bin_dir / "gh"
    gh_path.write_text(
        f"""#!{sys.executable}
import json
import os
from pathlib import Path

responses = json.loads(Path(os.environ["GH_FIXTURE_RESPONSES"]).read_text())
counter_path = Path(os.environ["GH_FIXTURE_COUNTER"])
counter = int(counter_path.read_text()) if counter_path.exists() else 0
counter_path.write_text(str(counter + 1))
print(json.dumps(responses[min(counter, len(responses) - 1)]))
""",
        encoding="utf-8",
    )
    gh_path.chmod(0o755)
    return {
        "GH_FIXTURE_RESPONSES": str(responses_path),
        "GH_FIXTURE_COUNTER": str(counter_path),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }


def _committed_checkpoint_transaction(
    *,
    chain_id: str,
    source_sha: str,
    generation: int,
    artifact_id: int,
    artifact_run_id: int,
    artifact_digest: str,
    artifact_size_bytes: int,
    database_sha256: str,
    report_sha256: str,
    coverage_fingerprint: str,
    lane_id: str,
    lane_coverage_hash: str,
) -> CheckpointTransaction:
    built = CheckpointTransaction.candidate(
        chain_id=chain_id,
        source_sha=source_sha,
        generation=generation,
        artifact_name=(f"full-extraction-checkpoint-{chain_id}-iter-{generation}"),
        lane_contracts=[
            {
                "lane_id": lane_id,
                "coverage_units_hash": lane_coverage_hash,
            }
        ],
        coverage_fingerprint=coverage_fingerprint,
    ).mark_built(
        database_sha256=database_sha256,
        report_sha256=report_sha256,
    )
    assert built.build is not None
    receipt = CheckpointArtifactReceipt(
        artifact_id=artifact_id,
        artifact_run_id=artifact_run_id,
        artifact_name=built.artifact_name,
        artifact_digest=artifact_digest,
        artifact_size_bytes=artifact_size_bytes,
        database_sha256=database_sha256,
        report_sha256=report_sha256,
        chain_id=chain_id,
        source_sha=source_sha,
        generation=generation,
        coverage_fingerprint=coverage_fingerprint,
        lane_inventory_sha256=built.identity.coverage.lane_inventory_sha256,
    )
    return built.mark_uploaded_verified(receipt).commit()


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


def _workflow_run_blocks(workflow: str) -> list[tuple[int, str]]:
    lines = workflow.splitlines()
    blocks: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if line.strip() != "run: |":
            continue
        indent = len(line) - len(line.lstrip())
        body: list[str] = []
        for candidate in lines[index + 1 :]:
            candidate_indent = len(candidate) - len(candidate.lstrip())
            if candidate.strip() and candidate_indent <= indent:
                break
            body.append(candidate[indent + 2 :] if candidate.strip() else "")
        blocks.append((index + 1, "\n".join(body) + "\n"))
    return blocks


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
        "/actions/workflows/full-extraction.yml/dispatches"
    )


def test_workflow_run_blocks_fit_github_expression_limit() -> None:
    blocks = _workflow_run_blocks(_workflow_text())
    assert blocks
    oversized = [(line, len(body)) for line, body in blocks if len(body) > 20_000]
    assert oversized == []


def test_next_manifest_steps_persist_uncommitted_checkpoint_candidate_identity() -> None:
    lane_control = _job_block(_workflow_text(), "lane_control")
    prepare = _step_block(lane_control, "Prepare next manifest")
    build = _step_block(lane_control, "Build next manifest")
    candidate_upload = _step_block(lane_control, "Upload checkpoint candidate manifest")

    assert 'echo "CHECKPOINT_ARTIFACT_NAME=$CHECKPOINT_ARTIFACT_NAME"' in prepare
    assert 'echo "CHECKPOINT_GENERATION=$CHECKPOINT_GENERATION"' in prepare
    assert "CHECKPOINT_COVERAGE_HASH" not in prepare
    assert '} >> "$GITHUB_ENV"' in prepare
    assert "CHECKPOINT_ARTIFACT_NAME" in build
    assert "CHECKPOINT_GENERATION" in build
    assert "CHECKPOINT_COVERAGE_HASH" not in build
    assert "candidate_artifact_name" in build
    assert "GITHUB_RUN_ID" in build
    assert "GITHUB_RUN_ATTEMPT" in build
    assert "latest_checkpoint_coverage_hash" not in build
    assert "overwrite: false" in candidate_upload
    assert "current-manifest.json" in candidate_upload
    assert "next-manifest.json" in candidate_upload


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
        "/actions/workflows/full-extraction.yml/dispatches"
    )
    assert '"workflow_ref": os.environ["WORKFLOW_REF"]' in dispatch
    assert '"workflow_sha": os.environ["WORKFLOW_SHA"]' in dispatch


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
    assert "steps.canonical_checkpoint.outcome != 'success'" not in diagnostic_upload
    assert "steps.checkpoint_receipt.outcome != 'success'" in diagnostic_upload
    assert "steps.commit_manifest.outcome != 'success'" in diagnostic_upload
    assert "steps.committed_manifest.outcome != 'success'" in diagnostic_upload
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
    resolve = _step_block(checkpoint, "Resolve previous checkpoint receipt")
    download = _step_block(checkpoint, "Download previous checkpoint by immutable ID")
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
    assert (
        "f\"/repos/{os.environ['GITHUB_REPOSITORY']}/actions/artifacts/{artifact_id}\"" in resolve
    )
    assert "isinstance(rest_artifact_id, bool)" in resolve
    assert "not isinstance(rest_artifact_id, int)" in resolve
    assert "rest_artifact_id != artifact_id" in resolve
    assert 'artifact.get("name") != artifact_name' in resolve
    assert 'artifact.get("digest") != expected_digest' in resolve
    assert "isinstance(rest_artifact_size, bool)" in resolve
    assert "not isinstance(rest_artifact_size, int)" in resolve
    assert "rest_artifact_size != expected_size" in resolve
    assert 'artifact.get("expired") is not False' in resolve
    assert 'str(workflow_run.get("id") or "") != run_id' in resolve
    assert 'workflow_run.get("head_sha")' in resolve
    assert "artifact-ids: ${{ steps.previous_checkpoint.outputs.artifact_id }}" in download
    assert "digest-mismatch: error" in download


def test_previous_checkpoint_resolver_allows_legacy_only_when_transaction_key_is_absent(
    tmp_path: pathlib.Path,
) -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    resolve = _step_block(checkpoint, "Resolve previous checkpoint receipt")
    resolver = _embedded_python_after(resolve, "run: |")
    manifest_path = tmp_path / "current-manifest.json"
    output_path = tmp_path / "github-output.txt"
    run_id = "12345"
    artifact_name = "full-extraction-checkpoint-fixture-chain-iter-2"
    env = {
        "CURRENT_MANIFEST": str(manifest_path),
        "GITHUB_OUTPUT": str(output_path),
        "GITHUB_REPOSITORY": "fixture/nbadb",
    }

    for label, malformed_transaction in (
        ("null", None),
        ("empty-string", ""),
        ("empty-list", []),
        ("empty-object", {}),
    ):
        output_path.unlink(missing_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "chain_state": {
                        "latest_checkpoint_run_id": run_id,
                        "latest_checkpoint_artifact_name": artifact_name,
                        "latest_checkpoint_transaction": malformed_transaction,
                    }
                }
            ),
            encoding="utf-8",
        )
        malformed = _run_python(resolver, env=env)
        assert malformed.returncode == 1, label
        assert "previous checkpoint transaction must be committed" in malformed.stderr
        assert not output_path.exists()

    manifest_path.write_text(
        json.dumps(
            {
                "chain_state": {
                    "latest_checkpoint_run_id": run_id,
                    "latest_checkpoint_artifact_name": artifact_name,
                }
            }
        ),
        encoding="utf-8",
    )
    legacy = _run_python(resolver, env=env)
    assert legacy.returncode == 0, legacy.stderr or legacy.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        f"run_id={run_id}",
        f"artifact_name={artifact_name}",
        "artifact_id=",
    ]

    output_path.unlink()
    manifest_path.write_text(
        json.dumps({"chain_state": {}}),
        encoding="utf-8",
    )
    fresh = _run_python(resolver, env=env)
    assert fresh.returncode == 0, fresh.stderr or fresh.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "run_id=",
        "artifact_name=",
        "artifact_id=",
    ]


def test_checkpoint_phases_keep_validation_outputs_on_the_final_step() -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    build = _step_block(checkpoint, "Build checkpoint database")
    bind = _step_block(checkpoint, "Bind checkpoint blocked evidence")
    validate = _step_block(checkpoint, "Validate checkpoint database")
    transaction = _step_block(checkpoint, "Build checkpoint transaction")
    upload = _step_block(checkpoint, "Upload checkpoint artifact")
    collision = _step_block(checkpoint, "Resolve colliding checkpoint sibling")
    sibling_download = _step_block(checkpoint, "Download colliding checkpoint sibling")
    sibling_validate = _step_block(checkpoint, "Validate colliding checkpoint sibling")
    retry = _step_block(checkpoint, "Retry checkpoint artifact upload after stable absence")
    receipt = _step_block(checkpoint, "Verify immutable checkpoint receipt")
    commit = _step_block(checkpoint, "Commit checkpoint manifest")
    committed_upload = _step_block(checkpoint, "Upload committed next manifest")

    assert "id: checkpoint" not in build
    assert "id: checkpoint" not in bind
    assert "id: checkpoint" in validate
    assert '--run-id "$CURRENT_RUN_ID"' in build
    assert checkpoint.index("Build checkpoint database") < checkpoint.index(
        "Bind checkpoint blocked evidence"
    )
    assert checkpoint.index("Bind checkpoint blocked evidence") < checkpoint.index(
        "Validate checkpoint database"
    )
    assert checkpoint.index("Validate checkpoint database") < checkpoint.index(
        "Build checkpoint transaction"
    )
    assert checkpoint.index("Build checkpoint transaction") < checkpoint.index(
        "Upload checkpoint artifact"
    )
    assert checkpoint.index("Upload checkpoint artifact") < checkpoint.index(
        "Resolve colliding checkpoint sibling"
    )
    assert checkpoint.index("Resolve colliding checkpoint sibling") < checkpoint.index(
        "Download colliding checkpoint sibling"
    )
    assert checkpoint.index("Download colliding checkpoint sibling") < checkpoint.index(
        "Validate colliding checkpoint sibling"
    )
    assert checkpoint.index("Validate colliding checkpoint sibling") < checkpoint.index(
        "Retry checkpoint artifact upload after stable absence"
    )
    assert checkpoint.index(
        "Retry checkpoint artifact upload after stable absence"
    ) < checkpoint.index("Verify immutable checkpoint receipt")
    assert checkpoint.index("Verify immutable checkpoint receipt") < checkpoint.index(
        "Commit checkpoint manifest"
    )
    assert checkpoint.index("Commit checkpoint manifest") < checkpoint.index(
        "Upload committed next manifest"
    )
    assert "checkpoint-transaction.json" in transaction
    assert "continue-on-error: true" in upload
    assert "overwrite: false" in upload
    assert "overwrite: true" not in upload
    assert "steps.canonical_checkpoint.outcome == 'failure'" in collision
    assert "steps.checkpoint_collision.outputs.resolution == 'reuse'" in sibling_download
    assert "digest-mismatch: error" in sibling_download
    assert "steps.checkpoint_collision.outputs.resolution == 'reuse'" in sibling_validate
    assert "steps.checkpoint_collision.outputs.resolution == 'absent_timeout'" in retry
    assert "overwrite: false" in retry
    assert "overwrite: true" not in retry
    assert "steps.canonical_checkpoint.outputs.artifact-id" in receipt
    assert "steps.canonical_checkpoint.outputs.artifact-digest" in receipt
    assert "steps.checkpoint_sibling.outputs.artifact_id" in receipt
    assert "steps.checkpoint_sibling.outputs.artifact_digest" in receipt
    assert "steps.canonical_checkpoint_retry.outputs.artifact-id" in receipt
    assert "steps.canonical_checkpoint_retry.outputs.artifact-digest" in receipt
    assert "isinstance(rest_artifact_id, bool)" in receipt
    assert "not isinstance(rest_artifact_id, int)" in receipt
    assert "rest_artifact_id != int(artifact_id)" in receipt
    assert 'artifact.get("name") != os.environ["CHECKPOINT_ARTIFACT_NAME"]' in receipt
    assert 'artifact.get("digest") != expected_digest' in receipt
    assert 'artifact.get("size_in_bytes")' in receipt
    assert 'str(workflow_run.get("id") or "") != os.environ["CURRENT_RUN_ID"]' in receipt
    assert 'workflow_run.get("head_sha")' in receipt
    assert "artifact_size_bytes" in receipt
    assert "receipt_source" in receipt
    assert "artifact-receipt-source: ${{ steps.checkpoint_receipt.outputs.receipt_source }}" in (
        checkpoint
    )
    assert "steps.checkpoint_receipt.outputs.artifact_id" in commit
    assert "steps.checkpoint_receipt.outputs.artifact_digest" in commit
    assert "steps.checkpoint_receipt.outputs.artifact_size_bytes" in commit
    assert "overwrite: false" in committed_upload
    assert "overwrite: true" not in committed_upload
    assert (
        'LANE_CONTROL_CONTRACT_BLOCKED_LANE_COUNT="$LANE_CONTROL_CONTRACT_BLOCKED_LANE_COUNT"'
        in bind
    )
    assert 'with Path(os.environ["GITHUB_OUTPUT"]).open' in validate


def test_checkpoint_collision_inventory_resolution_is_fail_closed(
    tmp_path: pathlib.Path,
) -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    resolver = _embedded_python_after(
        _step_block(checkpoint, "Resolve colliding checkpoint sibling"),
        "run: |",
    ).replace("time.sleep(3)", "time.sleep(0)")
    artifact_name = "full-extraction-checkpoint-fixture-chain-iter-3"
    source_sha = "a" * 40
    owner_head_sha = "b" * 40
    run_id = "12345"
    owner_run = {
        "id": int(run_id),
        "head_sha": owner_head_sha,
    }

    def artifact(
        artifact_id: int,
        *,
        expired: bool = False,
    ) -> dict[str, object]:
        return {
            "id": artifact_id,
            "name": artifact_name,
            "digest": f"sha256:{artifact_id:064x}",
            "size_in_bytes": 4096,
            "expired": expired,
            "workflow_run": {
                "id": int(run_id),
                "head_sha": owner_head_sha,
            },
        }

    def snapshot(*artifacts: dict[str, object]) -> list[dict[str, object]]:
        return [
            {
                "total_count": len(artifacts),
                "artifacts": list(artifacts),
            }
        ]

    def run_case(
        name: str,
        responses: list[object],
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path]:
        case_dir = tmp_path / name
        fixture_env = _gh_fixture_env(case_dir, responses)
        output_path = case_dir / "github-output.txt"
        result = _run_python(
            resolver,
            env={
                **fixture_env,
                "CHECKPOINT_ARTIFACT_NAME": artifact_name,
                "CURRENT_RUN_ID": run_id,
                "GITHUB_OUTPUT": str(output_path),
                "GITHUB_REPOSITORY": "acme/nbadb",
                "WORKFLOW_SOURCE_SHA": source_sha,
            },
            cwd=case_dir,
        )
        return result, output_path

    stable_artifact = artifact(701)
    stable, stable_output = run_case(
        "stable",
        [owner_run, *([snapshot(stable_artifact)] * 4)],
    )
    assert stable.returncode == 0, stable.stderr or stable.stdout
    assert stable_output.read_text(encoding="utf-8").splitlines() == [
        "resolution=reuse",
        "artifact_id=701",
        f"artifact_digest={stable_artifact['digest']}",
        "artifact_size_bytes=4096",
    ]

    absent, absent_output = run_case("absent", [owner_run, *([snapshot()] * 4)])
    assert absent.returncode == 0, absent.stderr or absent.stdout
    assert absent_output.read_text(encoding="utf-8").splitlines() == ["resolution=absent_timeout"]

    ambiguous, ambiguous_output = run_case(
        "ambiguous",
        [owner_run, snapshot(artifact(701), artifact(702))],
    )
    assert ambiguous.returncode == 1
    assert "checkpoint sibling inventory is ambiguous" in ambiguous.stderr
    assert not ambiguous_output.exists()

    expired, expired_output = run_case(
        "expired",
        [owner_run, snapshot(artifact(701, expired=True))],
    )
    assert expired.returncode == 1
    assert "checkpoint sibling inventory contains invalid provenance" in expired.stderr
    assert not expired_output.exists()

    unstable, unstable_output = run_case(
        "unstable",
        [
            owner_run,
            snapshot(),
            snapshot(artifact(701)),
            snapshot(),
            snapshot(artifact(701)),
        ],
    )
    assert unstable.returncode == 1
    assert "checkpoint sibling inventory did not stabilize" in unstable.stderr
    assert not unstable_output.exists()

    malformed, malformed_output = run_case(
        "malformed",
        [owner_run, [{"total_count": 1, "artifacts": "not-a-list"}]],
    )
    assert malformed.returncode == 1
    assert "checkpoint sibling inventory page is malformed" in malformed.stderr
    assert not malformed_output.exists()


def test_checkpoint_collision_sibling_requires_identical_transaction_and_content(
    tmp_path: pathlib.Path,
) -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    validator = _embedded_python_after(
        _step_block(checkpoint, "Validate colliding checkpoint sibling"),
        "run: |",
    )
    artifact_name = "full-extraction-checkpoint-fixture-chain-iter-3"
    source_sha = "a" * 40
    database_bytes = b"checkpoint-database"
    report_bytes = b'{"checkpoint":"report"}\n'
    database_hash = hashlib.sha256(database_bytes).hexdigest()
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    transaction = CheckpointTransaction.candidate(
        chain_id="fixture-chain",
        source_sha=source_sha,
        generation=3,
        artifact_name=artifact_name,
        lane_contracts=[],
        coverage_fingerprint="b" * 64,
    ).mark_built(
        database_sha256=database_hash,
        report_sha256=report_hash,
    )
    relative_paths = {
        "database": pathlib.Path("data/nbadb-checkpoint/nba.duckdb"),
        "report": pathlib.Path("artifacts/full-extraction/checkpoint-report.json"),
        "transaction": pathlib.Path("artifacts/full-extraction/checkpoint-transaction.json"),
    }

    def write_file(root: pathlib.Path, relative_path: pathlib.Path, content: bytes) -> None:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    transaction_bytes = json.dumps(transaction.to_dict(), sort_keys=True).encode("utf-8") + b"\n"
    for root in (tmp_path, tmp_path / "checkpoint-sibling"):
        write_file(root, relative_paths["database"], database_bytes)
        write_file(root, relative_paths["report"], report_bytes)
        write_file(root, relative_paths["transaction"], transaction_bytes)

    output_path = tmp_path / "github-output.txt"
    env = {
        "ARTIFACT_ID": "701",
        "ARTIFACT_DIGEST": "sha256:" + "c" * 64,
        "ARTIFACT_SIZE_BYTES": "4096",
        "CHAIN_ID": "fixture-chain",
        "CHECKPOINT_ARTIFACT_NAME": artifact_name,
        "CHECKPOINT_GENERATION": "3",
        "CURRENT_RUN_ID": "12345",
        "GITHUB_OUTPUT": str(output_path),
        "WORKFLOW_SOURCE_SHA": source_sha,
    }
    accepted = _run_python(validator, env=env, cwd=tmp_path)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "artifact_id=701",
        f"artifact_digest={env['ARTIFACT_DIGEST']}",
        "artifact_size_bytes=4096",
    ]

    mismatched_transaction = CheckpointTransaction.candidate(
        chain_id="fixture-chain",
        source_sha=source_sha,
        generation=3,
        artifact_name=artifact_name,
        lane_contracts=[],
        coverage_fingerprint="d" * 64,
    ).mark_built(
        database_sha256=database_hash,
        report_sha256=report_hash,
    )
    write_file(
        tmp_path / "checkpoint-sibling",
        relative_paths["transaction"],
        json.dumps(mismatched_transaction.to_dict(), sort_keys=True).encode("utf-8"),
    )
    output_path.unlink()
    wrong_transaction = _run_python(validator, env=env, cwd=tmp_path)
    assert wrong_transaction.returncode == 1
    assert "transaction does not match the current build" in wrong_transaction.stderr
    assert not output_path.exists()

    write_file(
        tmp_path / "checkpoint-sibling",
        relative_paths["transaction"],
        transaction_bytes,
    )
    for label, tampered_content in (
        ("database", b"tampered-database"),
        ("report", b'{"tampered":true}\n'),
    ):
        original = database_bytes if label == "database" else report_bytes
        write_file(
            tmp_path / "checkpoint-sibling",
            relative_paths[label],
            tampered_content,
        )
        rejected = _run_python(validator, env=env, cwd=tmp_path)
        assert rejected.returncode == 1
        assert f"checkpoint sibling {label} hash does not match the build" in rejected.stderr
        assert not output_path.exists()
        write_file(
            tmp_path / "checkpoint-sibling",
            relative_paths[label],
            original,
        )


def test_checkpoint_receipt_records_exact_verified_source(
    tmp_path: pathlib.Path,
) -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    receipt_validator = _embedded_python_after(
        _step_block(checkpoint, "Verify immutable checkpoint receipt"),
        "run: |",
    )
    artifact_name = "full-extraction-checkpoint-fixture-chain-iter-3"
    source_sha = "a" * 40
    owner_head_sha = "b" * 40
    run_id = "12345"
    digest = "sha256:" + "c" * 64

    for case_name, outcomes, artifact_id, expected_source in (
        (
            "initial",
            ("success", "skipped", "skipped"),
            "701",
            "newly_uploaded",
        ),
        (
            "sibling",
            ("failure", "success", "skipped"),
            "702",
            "validated_existing",
        ),
        (
            "retry",
            ("failure", "skipped", "success"),
            "703",
            "newly_uploaded_retry",
        ),
    ):
        case_dir = tmp_path / case_name
        artifact = {
            "id": int(artifact_id),
            "name": artifact_name,
            "digest": digest,
            "size_in_bytes": 4096,
            "expired": False,
            "workflow_run": {
                "id": int(run_id),
                "head_sha": owner_head_sha,
            },
        }
        fixture_env = _gh_fixture_env(
            case_dir,
            [
                {
                    "id": int(run_id),
                    "head_sha": owner_head_sha,
                },
                artifact,
            ],
        )
        output_path = case_dir / "github-output.txt"
        initial_outcome, sibling_outcome, retry_outcome = outcomes
        env = {
            **fixture_env,
            "CHECKPOINT_ARTIFACT_NAME": artifact_name,
            "CURRENT_RUN_ID": run_id,
            "GITHUB_OUTPUT": str(output_path),
            "GITHUB_REPOSITORY": "acme/nbadb",
            "INITIAL_UPLOAD_OUTCOME": initial_outcome,
            "INITIAL_ARTIFACT_ID": "701",
            "INITIAL_ARTIFACT_DIGEST": digest,
            "SIBLING_VALIDATION_OUTCOME": sibling_outcome,
            "SIBLING_ARTIFACT_ID": "702",
            "SIBLING_ARTIFACT_DIGEST": digest,
            "RETRY_UPLOAD_OUTCOME": retry_outcome,
            "RETRY_ARTIFACT_ID": "703",
            "RETRY_ARTIFACT_DIGEST": digest,
            "WORKFLOW_SOURCE_SHA": source_sha,
        }
        accepted = _run_python(receipt_validator, env=env, cwd=case_dir)
        assert accepted.returncode == 0, accepted.stderr or accepted.stdout
        assert output_path.read_text(encoding="utf-8").splitlines() == [
            f"artifact_id={artifact_id}",
            f"artifact_digest={digest}",
            "artifact_size_bytes=4096",
            f"receipt_source={expected_source}",
        ]

    no_source_dir = tmp_path / "no-source"
    no_source_dir.mkdir()
    no_source = _run_python(
        receipt_validator,
        env={
            "CHECKPOINT_ARTIFACT_NAME": artifact_name,
            "CURRENT_RUN_ID": run_id,
            "GITHUB_OUTPUT": str(no_source_dir / "github-output.txt"),
            "GITHUB_REPOSITORY": "acme/nbadb",
            "INITIAL_UPLOAD_OUTCOME": "failure",
            "INITIAL_ARTIFACT_ID": "",
            "INITIAL_ARTIFACT_DIGEST": "",
            "SIBLING_VALIDATION_OUTCOME": "failure",
            "SIBLING_ARTIFACT_ID": "",
            "SIBLING_ARTIFACT_DIGEST": "",
            "RETRY_UPLOAD_OUTCOME": "failure",
            "RETRY_ARTIFACT_ID": "",
            "RETRY_ARTIFACT_DIGEST": "",
            "WORKFLOW_SOURCE_SHA": source_sha,
        },
        cwd=no_source_dir,
    )
    assert no_source.returncode == 1
    assert "checkpoint artifact receipt has no verified source" in no_source.stderr


def test_inline_project_imports_run_in_uv_environment() -> None:
    workflow_lines = _workflow_text().splitlines()
    project_import_blocks: list[tuple[int, str]] = []

    for index, invocation in enumerate(workflow_lines):
        if re.search(r"\bpython3?\s+-\s+<<'PY'", invocation) is None:
            continue
        end = next(
            (
                candidate
                for candidate in range(index + 1, len(workflow_lines))
                if workflow_lines[candidate].strip() == "PY"
            ),
            None,
        )
        assert end is not None, f"unterminated Python heredoc at line {index + 1}"
        body = "\n".join(workflow_lines[index + 1 : end])
        if re.search(r"(?m)^\s*(?:from|import)\s+nbadb(?:\.|\s|$)", body):
            project_import_blocks.append((index + 1, invocation.strip()))

    assert project_import_blocks
    violations = [
        (line_number, invocation)
        for line_number, invocation in project_import_blocks
        if re.search(r"\buv run python3?\s+-\s+<<'PY'", invocation) is None
    ]
    assert not violations, violations


def test_lane_control_requires_a_successful_seed_and_non_skipped_extract() -> None:
    workflow = _workflow_text()
    plan = _job_block(workflow, "plan")
    extract = _job_block(workflow, "extract")
    lane_control = _job_block(workflow, "lane_control")
    checkpoint = _job_block(workflow, "checkpoint")
    dispatch = _job_block(workflow, "dispatch_next")
    lane_control_header = lane_control.split("    steps:\n", 1)[0]

    assert "needs.discovery_seed.result == 'success'" in extract
    assert (
        "needs: [plan, preflight, discovery_seed, vpn_quarantine, extract, terminal_replay]"
        in lane_control_header
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

    resolver = _step_block(plan, "Resolve resume source committed manifest")
    download = _step_block(plan, "Download resume source committed manifest")
    prepare = _step_block(plan, "Prepare resume source manifest")
    assert "RESUME_SOURCE_COMMITTED_MANIFEST_RESOLVER" in resolver
    assert "canonical_fallback" in resolver
    assert "ambiguous immutable committed next-manifest" in resolver
    assert "artifacts for attempt" in resolver
    assert "artifact-ids: ${{ steps.resume_source_manifest.outputs.artifact_id }}" in (download)
    assert "digest-mismatch: error" in download
    assert prepare.index('if [ "$RESUME_SOURCE_MANIFEST_RESOLUTION" = "committed" ]') < (
        prepare.index('gh run download "$RESUME_SOURCE_RUN_ID"')
    )
    assert 'find "$RUNNER_TEMP/resume-source/manifest-committed"' in prepare
    assert 'metadata_dir="$RUNNER_TEMP/resume-source/metadata/$metadata_name"' in plan
    assert 'mkdir -p "$metadata_dir"' in plan
    assert '--dir "$metadata_dir"' in plan
    assert '--dir "$RUNNER_TEMP/resume-source/metadata"' not in plan


def test_successful_nonpublishing_preflight_reaches_discovery_seed() -> None:
    discovery = _job_block(_workflow_text(), "discovery_seed")
    discovery_header = discovery.split("    steps:\n", 1)[0]

    assert "needs: [plan, preflight]" in discovery_header
    assert (
        "if: ${{ always() && !cancelled() && needs.plan.outputs.matrix-lane-count != '0' && "
        "needs.preflight.result == 'success' }}" in discovery_header
    )


def test_cancellation_cannot_admit_new_network_or_extraction_jobs() -> None:
    workflow = _workflow_text()
    for job_name in (
        "preflight",
        "discovery_seed",
        "vpn_capacity",
        "vpn_quarantine",
        "extract",
        "terminal_replay",
        "targeted_smoke_assurance",
    ):
        header = _job_block(workflow, job_name).split("    steps:\n", 1)[0]
        assert "if: ${{ always() && !cancelled() && " in header, job_name


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
    artifact_retry_wait = _step_block(extract, "Wait before retrying lane artifact upload")
    complete_upload_retry = _step_block(extract, "Retry complete lane artifact upload")
    recovery_upload_retry = _step_block(
        extract,
        "Retry incomplete lane state artifact upload",
    )
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
    assert "continue-on-error: true" in complete_upload
    assert "if-no-files-found: error" in complete_upload
    assert "steps.lane_metadata.outcome == 'success'" in recovery_upload
    assert "steps.lane_metadata.outputs.snapshot-attested == 'true'" in recovery_upload
    assert "steps.lane_metadata.outputs.final-outcome != 'complete'" in recovery_upload
    assert "continue-on-error: true" in recovery_upload
    assert "if-no-files-found: error" in recovery_upload
    assert "steps.complete_lane_artifact.outcome == 'failure'" in artifact_retry_wait
    assert "steps.recovery_lane_artifact.outcome == 'failure'" in artifact_retry_wait
    assert "sleep 15" in artifact_retry_wait
    assert "steps.complete_lane_artifact.outcome == 'failure'" in complete_upload_retry
    assert "steps.recovery_lane_artifact.outcome == 'failure'" in recovery_upload_retry
    assert "continue-on-error" not in complete_upload_retry
    assert "continue-on-error" not in recovery_upload_retry
    assert complete_name in complete_upload_retry
    assert recovery_name in recovery_upload_retry
    assert "overwrite: true" in complete_upload_retry
    assert "overwrite: true" in recovery_upload_retry
    assert "lane-state-attestation.json" in complete_upload_retry
    assert "lane-state-attestation.json" in recovery_upload_retry
    assert "steps.complete_lane_artifact_retry.outputs.artifact-id" in finalize_receipt
    assert "steps.complete_lane_artifact_retry.outputs.artifact-digest" in finalize_receipt
    assert "steps.recovery_lane_artifact_retry.outputs.artifact-id" in finalize_receipt
    assert "steps.recovery_lane_artifact_retry.outputs.artifact-digest" in finalize_receipt
    assert "steps.complete_lane_artifact_retry.outcome" in finalize_receipt
    assert "steps.recovery_lane_artifact_retry.outcome" in finalize_receipt
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
        "- name: Wait before retrying lane artifact upload"
    )
    assert extract.index("- name: Wait before retrying lane artifact upload") < extract.index(
        "- name: Retry complete lane artifact upload"
    )
    assert extract.index("- name: Retry complete lane artifact upload") < extract.index(
        "- name: Retry incomplete lane state artifact upload"
    )
    assert extract.index("- name: Retry incomplete lane state artifact upload") < extract.index(
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


def test_vpn_control_artifacts_retry_without_consuming_lane_retries() -> None:
    workflow = _workflow_text()
    capacity = _job_block(workflow, "vpn_capacity")
    extract = _job_block(workflow, "extract")

    capacity_upload = _step_block(capacity, "Publish connected VPN capacity marker")
    capacity_retry = _step_block(capacity, "Retry connected VPN capacity marker")
    capacity_barrier = _step_block(capacity, "Wait for simultaneous VPN capacity")
    capacity_enforcement = _step_block(capacity, "Enforce concurrent VPN capacity")
    auth_upload = _step_block(extract, "Publish VPN auth circuit marker")
    auth_lookup = _step_block(extract, "Check for a sibling VPN auth circuit marker")
    auth_retry = _step_block(extract, "Retry VPN auth circuit marker publication")
    auth_verify = _step_block(extract, "Verify VPN auth circuit marker")
    auth_final = _step_block(extract, "Recheck VPN auth circuit before connector")
    vpn_connect = _step_block(extract, "Connect NordVPN tunnel")
    deferred_upload = _step_block(extract, "Upload circuit-deferred lane metadata")
    deferred_retry = _step_block(extract, "Retry circuit-deferred lane metadata upload")
    diagnostic_upload = _step_block(extract, "Upload diagnostics-only lane snapshot")

    assert "continue-on-error: true" in capacity_upload
    assert "steps.capacity_marker.outcome == 'failure'" in capacity_retry
    assert "overwrite: true" in capacity_retry
    assert "steps.capacity_marker_retry.outcome == 'success'" in capacity_barrier
    assert "steps.capacity_marker_retry.outcome" in capacity_enforcement

    assert "continue-on-error: true" in auth_upload
    assert "steps.vpn_auth_circuit_marker.outcome == 'failure'" in auth_lookup
    assert "--timeout-seconds 30" in auth_lookup
    assert "continue-on-error: true" in auth_lookup
    assert "steps.vpn_auth_circuit_lookup.outputs.status == 'absent_timeout'" in auth_retry
    assert "continue-on-error: true" in auth_retry
    assert "overwrite: false" in auth_retry
    assert "--timeout-seconds 120" in auth_verify
    assert "steps.vpn_auth_circuit.outputs.status == 'closed'" in auth_final
    assert "steps.vpn_auth_circuit_final.outputs.status == 'closed'" in vpn_connect
    assert extract.index("Recheck VPN auth circuit before connector") < extract.index(
        "Connect NordVPN tunnel"
    )
    assert (
        "steps.vpn_auth_circuit_final.outputs.status || steps.vpn_auth_circuit.outputs.status"
    ) in extract

    assert "continue-on-error: true" in deferred_upload
    assert "steps.circuit_lane_metadata_artifact.outcome == 'failure'" in deferred_retry
    assert "overwrite: true" in deferred_retry
    assert "steps.circuit_lane_metadata_artifact_retry.outcome != 'success'" in diagnostic_upload
    assert extract.index("Retry circuit-deferred lane metadata upload") < extract.index(
        "Upload diagnostics-only lane snapshot"
    )


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
        "artifact_id": "",
        "artifact_digest": "",
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
    assert '"max_iterations": os.environ["MAX_ITERATIONS"]' in dispatch
    assert '"max_iterations": os.environ["ITERATION_BUDGET"]' not in dispatch


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
    enqueue = dispatch.index("/actions/workflows/full-extraction.yml/dispatches")
    assert duplicate_lookup < duplicate_rejection < enqueue


def test_redispatch_cancels_an_unacknowledged_child_when_parent_stops() -> None:
    dispatch = _job_block(_workflow_text(), "dispatch_next")

    assert "cancel_dispatched_child()" in dispatch
    assert "on_dispatch_signal()" in dispatch
    assert "on_dispatch_exit()" in dispatch
    assert "trap on_dispatch_exit EXIT" in dispatch
    assert "trap on_dispatch_signal INT TERM" in dispatch
    assert "child_dispatch_may_exist=true" in dispatch
    assert '"return_run_details": True' in dispatch
    assert 'child_run_id = str(response.get("workflow_run_id") or "").strip()' in dispatch
    assert "child_acknowledged=true" in dispatch
    assert "/actions/runs/${candidate_id}/cancel" in dispatch
    assert "unacknowledged child run" in dispatch

    dispatch_start = dispatch.index("child_dispatch_may_exist=true")
    enqueue = dispatch.index("/actions/workflows/full-extraction.yml/dispatches")
    identity = dispatch.index('response.get("workflow_run_id")', enqueue)
    acknowledgement = dispatch.index("child_acknowledged=true")
    trap_disarm = dispatch.index("trap - EXIT INT TERM", acknowledgement)
    assert dispatch_start < enqueue < identity < acknowledgement < trap_disarm


def test_redispatch_allows_failed_history_and_acknowledges_only_the_new_child(
    tmp_path: pathlib.Path,
) -> None:
    dispatch = _job_block(_workflow_text(), "dispatch_next")
    precheck = _embedded_python(dispatch, "CHILD_RUN_PRECHECK")
    response_parser = _embedded_python_after(
        dispatch,
        'DISPATCH_RESPONSE_PATH="$dispatch_response_path"',
    )
    run_name = "Full Extraction chain=123 iteration=2"
    runs_path = tmp_path / "runs.json"
    existing_ids_path = tmp_path / "existing.json"
    response_path = tmp_path / "dispatch-response.json"
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

    response_path.write_text(
        json.dumps(
            {
                "workflow_run_id": 102,
                "run_url": "https://api.github.test/repos/acme/nbadb/actions/runs/102",
                "html_url": "https://github.test/acme/nbadb/actions/runs/102",
            }
        ),
        encoding="utf-8",
    )
    response_result = _run_python(
        response_parser,
        env={
            "DISPATCH_RESPONSE_PATH": str(response_path),
            "CHILD_RUN_PATH": str(child_path),
            "EXPECTED_RUN_NAME": run_name,
            "GITHUB_API_URL": "https://api.github.test",
            "GITHUB_REPOSITORY": "acme/nbadb",
            "GITHUB_SERVER_URL": "https://github.test",
        },
    )

    assert response_result.returncode == 0, response_result.stderr or response_result.stdout
    assert json.loads(child_path.read_text(encoding="utf-8")) == {
        "display_title": run_name,
        "id": "102",
        "url": "https://github.test/acme/nbadb/actions/runs/102",
        "api_url": "https://api.github.test/repos/acme/nbadb/actions/runs/102",
    }

    response_path.write_text(
        json.dumps(
            {
                "workflow_run_id": "invalid",
                "run_url": "https://api.github.test/actions/runs/102",
                "html_url": "https://github.test/actions/runs/102",
            }
        ),
        encoding="utf-8",
    )
    malformed = _run_python(
        response_parser,
        env={
            "DISPATCH_RESPONSE_PATH": str(response_path),
            "CHILD_RUN_PATH": str(child_path),
            "EXPECTED_RUN_NAME": run_name,
            "GITHUB_API_URL": "https://api.github.test",
            "GITHUB_REPOSITORY": "acme/nbadb",
            "GITHUB_SERVER_URL": "https://github.test",
        },
    )
    assert malformed.returncode == 1
    assert "did not return an exact child identity" in malformed.stderr


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
    assert '"network_mode": os.environ["NETWORK_MODE"]' in dispatch


def test_manifest_handoff_uses_an_exact_immutable_receipt() -> None:
    workflow = _workflow_text()
    dispatch_inputs = workflow.split("    inputs:\n", 1)[1].split("\nenv:\n", 1)[0]
    input_names = re.findall(r"(?m)^      ([a-z][a-z0-9_]*):$", dispatch_inputs)
    assert len(input_names) == 25
    assert "lane_manifest_artifact_id" in input_names
    assert "lane_manifest_artifact_digest" in input_names

    guard = _step_block(
        _job_block(workflow, "workflow_guard"),
        "Verify immutable workflow definition",
    )
    assert (
        "lane_manifest_artifact_id and lane_manifest_artifact_digest must be provided together"
        in guard
    )
    assert (
        'if [ "$has_manifest_receipt" = "true" ] && { '
        '[ -z "$LANE_MANIFEST_RUN_ID" ] || [ -z "$LANE_MANIFEST_ARTIFACT_NAME" ]; };'
    ) in guard
    assert "receipt-aware manifest handoff requires run ID, artifact name, ID, and digest" in guard
    assert "receipt-aware manifest handoff cannot be combined with lane_manifest_json" in guard

    plan = _job_block(workflow, "plan")
    verify = _step_block(plan, "Verify exact input manifest receipt")
    download = _step_block(plan, "Download exact input manifest")
    build = _step_block(plan, "Build lane manifest")
    assert plan.index("Verify exact input manifest receipt") < plan.index(
        "Download exact input manifest"
    )
    assert plan.index("Download exact input manifest") < plan.index("Build lane manifest")
    assert "if: ${{ inputs.lane_manifest_artifact_id != '' }}" in verify
    assert "isinstance(rest_artifact_id, bool)" in verify
    assert "not isinstance(rest_artifact_id, int)" in verify
    assert "rest_artifact_id != int(artifact_id)" in verify
    assert 'artifact.get("name") != os.environ["LANE_MANIFEST_ARTIFACT_NAME"]' in verify
    assert 'artifact.get("digest") != digest' in verify
    assert 'artifact.get("size_in_bytes")' in verify
    assert 'str(workflow_run.get("id") or "") != run_id' in verify
    assert 'workflow_run.get("head_sha")' in verify
    assert "artifact-ids: ${{ inputs.lane_manifest_artifact_id }}" in download
    assert "run-id: ${{ inputs.lane_manifest_run_id }}" in download
    assert "digest-mismatch: error" in download
    legacy_gate = (
        'if [ -z "$LANE_MANIFEST_ARTIFACT_ID" ] && [ -z "$LANE_MANIFEST_ARTIFACT_DIGEST" ]; then'
    )
    assert legacy_gate in build
    assert build.index(legacy_gate) < build.index('gh run download "$LANE_MANIFEST_RUN_ID"')
    assert (
        'elif [ -z "$LANE_MANIFEST_ARTIFACT_ID" ] || [ -z "$LANE_MANIFEST_ARTIFACT_DIGEST" ]; then'
    ) in build

    lane_control = _job_block(workflow, "lane_control")
    next_manifest = _step_block(lane_control, "Build next manifest")
    assert (
        "f\"{int(os.environ['ITERATION']) + 1}-run-{os.environ['GITHUB_RUN_ID']}-\""
        in next_manifest
    )
    assert "f\"attempt-{os.environ['GITHUB_RUN_ATTEMPT']}\"" in next_manifest
    committed_upload = _step_block(
        _job_block(workflow, "checkpoint"),
        "Upload committed next manifest",
    )
    assert "overwrite: false" in committed_upload

    dispatch = _job_block(workflow, "dispatch_next")
    manifest_receipt = _step_block(dispatch, "Verify committed manifest dispatch receipt")
    dispatch_step = _step_block(dispatch, "Dispatch next iteration")
    assert "ARTIFACT_ID: ${{ needs.checkpoint.outputs.manifest-artifact-id }}" in (manifest_receipt)
    assert (
        "ARTIFACT_DIGEST: ${{ needs.checkpoint.outputs.manifest-artifact-digest }}"
        in manifest_receipt
    )
    assert "ARTIFACT_ID: ${{ steps.manifest_receipt.outputs.artifact_id }}" in (dispatch_step)
    assert "ARTIFACT_DIGEST: ${{ steps.manifest_receipt.outputs.artifact_digest }}" in dispatch_step
    assert '"lane_manifest_artifact_id": os.environ["ARTIFACT_ID"]' in dispatch
    assert '"lane_manifest_artifact_digest": os.environ["ARTIFACT_DIGEST"]' in dispatch


def test_redispatch_manifest_receipt_is_exact_and_fail_closed(
    tmp_path: pathlib.Path,
) -> None:
    dispatch = _job_block(_workflow_text(), "dispatch_next")
    verifier_step = _step_block(dispatch, "Verify committed manifest dispatch receipt")
    verifier = _embedded_python(verifier_step, "REDISPATCH_MANIFEST_RECEIPT_VERIFIER")
    assert dispatch.index("Verify committed manifest dispatch receipt") < dispatch.index(
        "/actions/workflows/full-extraction.yml/dispatches"
    )

    chain_id = "fixture-chain"
    current_run_id = "12345"
    current_run_attempt = "2"
    iteration = "3"
    artifact_id = "701"
    owner_head_sha = "b" * 40
    artifact_name = "full-extraction-next-manifest-fixture-chain-iter-4-run-12345-attempt-2"
    artifact_digest = "sha256:" + "c" * 64
    owner_run = {
        "id": int(current_run_id),
        "head_sha": owner_head_sha,
        "run_attempt": int(current_run_attempt),
    }
    artifact = {
        "id": int(artifact_id),
        "name": artifact_name,
        "digest": artifact_digest,
        "size_in_bytes": 4096,
        "expired": False,
        "workflow_run": {
            "id": int(current_run_id),
            "head_sha": owner_head_sha,
        },
    }
    base_env = {
        "ARTIFACT_DIGEST": artifact_digest.removeprefix("sha256:"),
        "ARTIFACT_ID": artifact_id,
        "ARTIFACT_NAME": artifact_name,
        "CHAIN_ID": chain_id,
        "CURRENT_RUN_ATTEMPT": current_run_attempt,
        "CURRENT_RUN_ID": current_run_id,
        "GITHUB_REPOSITORY": "acme/nbadb",
        "ITERATION": iteration,
    }

    accepted_dir = tmp_path / "accepted"
    accepted_fixture = _gh_fixture_env(accepted_dir, [owner_run, artifact])
    output_path = accepted_dir / "github-output.txt"
    accepted = _run_python(
        verifier,
        env={
            **accepted_fixture,
            **base_env,
            "GITHUB_OUTPUT": str(output_path),
        },
        cwd=accepted_dir,
    )
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        f"artifact_name={artifact_name}",
        f"artifact_id={artifact_id}",
        f"artifact_digest={artifact_digest}",
    ]

    for label, overrides, error in (
        (
            "missing-id",
            {"ARTIFACT_ID": ""},
            "artifact ID must be positive",
        ),
        (
            "legacy-name",
            {"ARTIFACT_NAME": f"full-extraction-manifest-{chain_id}"},
            "exact immutable committed next-manifest artifact",
        ),
        (
            "bad-digest",
            {"ARTIFACT_DIGEST": "not-a-digest"},
            "artifact digest must be SHA-256",
        ),
    ):
        rejected_dir = tmp_path / label
        rejected_fixture = _gh_fixture_env(rejected_dir, [owner_run, artifact])
        counter_path = pathlib.Path(rejected_fixture["GH_FIXTURE_COUNTER"])
        rejected = _run_python(
            verifier,
            env={
                **rejected_fixture,
                **base_env,
                **overrides,
                "GITHUB_OUTPUT": str(rejected_dir / "github-output.txt"),
            },
            cwd=rejected_dir,
        )
        assert rejected.returncode == 1
        assert error in rejected.stderr
        assert not counter_path.exists()

    mismatch_dir = tmp_path / "rest-mismatch"
    mismatch_fixture = _gh_fixture_env(
        mismatch_dir,
        [owner_run, {**artifact, "digest": "sha256:" + "d" * 64}],
    )
    rest_mismatch = _run_python(
        verifier,
        env={
            **mismatch_fixture,
            **base_env,
            "GITHUB_OUTPUT": str(mismatch_dir / "github-output.txt"),
        },
        cwd=mismatch_dir,
    )
    assert rest_mismatch.returncode == 1
    assert "REST identity does not match the immutable upload receipt" in (rest_mismatch.stderr)

    bool_attempt_name = "full-extraction-next-manifest-fixture-chain-iter-4-run-12345-attempt-1"
    bool_attempt_dir = tmp_path / "bool-attempt"
    bool_attempt_fixture = _gh_fixture_env(
        bool_attempt_dir,
        [
            {**owner_run, "run_attempt": True},
            {**artifact, "name": bool_attempt_name},
        ],
    )
    bool_attempt = _run_python(
        verifier,
        env={
            **bool_attempt_fixture,
            **base_env,
            "ARTIFACT_NAME": bool_attempt_name,
            "CURRENT_RUN_ATTEMPT": "1",
            "GITHUB_OUTPUT": str(bool_attempt_dir / "github-output.txt"),
        },
        cwd=bool_attempt_dir,
    )
    assert bool_attempt.returncode == 1
    assert "owner run identity is invalid" in bool_attempt.stderr

    bool_artifact_id_dir = tmp_path / "bool-artifact-id"
    bool_artifact_id_fixture = _gh_fixture_env(
        bool_artifact_id_dir,
        [owner_run, {**artifact, "id": True}],
    )
    bool_artifact_id = _run_python(
        verifier,
        env={
            **bool_artifact_id_fixture,
            **base_env,
            "ARTIFACT_ID": "1",
            "GITHUB_OUTPUT": str(bool_artifact_id_dir / "github-output.txt"),
        },
        cwd=bool_artifact_id_dir,
    )
    assert bool_artifact_id.returncode == 1
    assert "REST identity does not match the immutable upload receipt" in (bool_artifact_id.stderr)


def test_input_manifest_receipt_rejects_any_rest_identity_mismatch(
    tmp_path: pathlib.Path,
) -> None:
    verifier = _embedded_python_after(
        _step_block(
            _job_block(_workflow_text(), "plan"),
            "Verify exact input manifest receipt",
        ),
        "run: |",
    )
    artifact_id = "701"
    run_id = "12345"
    source_sha = "a" * 40
    owner_head_sha = "b" * 40
    artifact_name = "full-extraction-next-manifest-fixture-chain-iter-3-run-12345-attempt-1"
    digest = "sha256:" + "c" * 64
    valid_artifact = {
        "id": int(artifact_id),
        "name": artifact_name,
        "digest": digest,
        "size_in_bytes": 4096,
        "expired": False,
        "workflow_run": {
            "id": int(run_id),
            "head_sha": owner_head_sha,
        },
    }
    owner_run = {
        "id": int(run_id),
        "head_sha": owner_head_sha,
    }
    base_env = {
        "GITHUB_REPOSITORY": "acme/nbadb",
        "LANE_MANIFEST_ARTIFACT_DIGEST": digest,
        "LANE_MANIFEST_ARTIFACT_ID": artifact_id,
        "LANE_MANIFEST_ARTIFACT_NAME": artifact_name,
        "LANE_MANIFEST_RUN_ID": run_id,
        "WORKFLOW_SOURCE_SHA": source_sha,
    }

    def run_case(
        name: str,
        artifact: dict[str, object],
    ) -> subprocess.CompletedProcess[str]:
        case_dir = tmp_path / name
        fixture_env = _gh_fixture_env(case_dir, [owner_run, artifact])
        return _run_python(
            verifier,
            env={**fixture_env, **base_env},
            cwd=case_dir,
        )

    accepted = run_case("accepted", valid_artifact)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout

    mismatches = {
        "id": {**valid_artifact, "id": 702},
        "name": {**valid_artifact, "name": "wrong-manifest"},
        "digest": {**valid_artifact, "digest": "sha256:" + "d" * 64},
        "size": {**valid_artifact, "size_in_bytes": 0},
        "expired": {**valid_artifact, "expired": True},
        "run": {
            **valid_artifact,
            "workflow_run": {"id": 12346, "head_sha": owner_head_sha},
        },
        "source": {
            **valid_artifact,
            "workflow_run": {"id": int(run_id), "head_sha": "c" * 40},
        },
    }
    for label, mismatched_artifact in mismatches.items():
        rejected = run_case(label, mismatched_artifact)
        assert rejected.returncode == 1
        assert "lane-manifest REST identity does not match its committed receipt" in (
            rejected.stderr
        )


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

    matching_receipt_name = _run_python(
        verifier,
        env={
            **base_env,
            "ARTIFACT_NAME": ("full-extraction-next-manifest-12345-iter-2-run-98765-attempt-1"),
        },
    )
    assert matching_receipt_name.returncode == 0, (
        matching_receipt_name.stderr or matching_receipt_name.stdout
    )

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


def test_resume_source_prefers_exact_committed_manifest_and_falls_back_only_when_absent(
    tmp_path: pathlib.Path,
) -> None:
    plan = _job_block(_workflow_text(), "plan")
    resolver = _embedded_python(plan, "RESUME_SOURCE_COMMITTED_MANIFEST_RESOLVER")
    chain_id = "12345"
    source_run_id = "987654"
    owner_head_sha = "b" * 40
    exact_name = "full-extraction-next-manifest-12345-iter-3-run-987654-attempt-2"
    owner_run = {
        "id": int(source_run_id),
        "head_sha": owner_head_sha,
        "run_attempt": 2,
    }
    exact_artifact = {
        "id": 701,
        "name": exact_name,
        "digest": "sha256:" + "c" * 64,
        "size_in_bytes": 4096,
        "expired": False,
        "workflow_run": {
            "id": int(source_run_id),
            "head_sha": owner_head_sha,
        },
    }
    canonical_artifact = {
        **exact_artifact,
        "id": 600,
        "name": f"full-extraction-manifest-{chain_id}",
    }

    def run_case(
        name: str,
        artifacts: list[dict[str, object]],
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path]:
        case_dir = tmp_path / name
        fixture_env = _gh_fixture_env(
            case_dir,
            [
                owner_run,
                [
                    {
                        "total_count": len(artifacts),
                        "artifacts": artifacts,
                    }
                ],
            ],
        )
        output_path = case_dir / "github-output.txt"
        result = _run_python(
            resolver,
            env={
                **fixture_env,
                "CHAIN_ID": chain_id,
                "GITHUB_OUTPUT": str(output_path),
                "GITHUB_REPOSITORY": "acme/nbadb",
                "RESUME_SOURCE_RUN_ID": source_run_id,
            },
            cwd=case_dir,
        )
        return result, output_path

    committed, committed_output = run_case(
        "committed",
        [
            canonical_artifact,
            {
                **exact_artifact,
                "id": 700,
                "name": ("full-extraction-next-manifest-12345-iter-3-run-987654-attempt-1"),
            },
            exact_artifact,
        ],
    )
    assert committed.returncode == 0, committed.stderr or committed.stdout
    assert committed_output.read_text(encoding="utf-8").splitlines() == [
        "resolution=committed",
        f"artifact_name={exact_name}",
        "artifact_id=701",
        f"artifact_digest={exact_artifact['digest']}",
        f"source_run_id={source_run_id}",
        "source_run_attempt=2",
    ]

    prior_artifact = {
        **exact_artifact,
        "id": 700,
        "name": ("full-extraction-next-manifest-12345-iter-3-run-987654-attempt-1"),
    }
    prior_attempt, prior_output = run_case(
        "prior-attempt",
        [canonical_artifact, prior_artifact],
    )
    assert prior_attempt.returncode == 0, prior_attempt.stderr or prior_attempt.stdout
    assert prior_output.read_text(encoding="utf-8").splitlines()[-2:] == [
        f"source_run_id={source_run_id}",
        "source_run_attempt=1",
    ]

    fallback, fallback_output = run_case("fallback", [canonical_artifact])
    assert fallback.returncode == 0, fallback.stderr or fallback.stdout
    assert "No immutable committed next-manifest exists" in fallback.stdout
    assert fallback_output.read_text(encoding="utf-8").splitlines() == [
        "resolution=canonical_fallback"
    ]

    ambiguous, ambiguous_output = run_case(
        "ambiguous",
        [exact_artifact, {**exact_artifact, "id": 702}],
    )
    assert ambiguous.returncode == 1
    assert "ambiguous immutable committed next-manifest" in ambiguous.stderr
    assert not ambiguous_output.exists()

    wrong_provenance, wrong_output = run_case(
        "wrong-provenance",
        [
            {
                **exact_artifact,
                "workflow_run": {
                    "id": int(source_run_id),
                    "head_sha": "0" * 40,
                },
            }
        ],
    )
    assert wrong_provenance.returncode == 1
    assert "committed-manifest artifact provenance is invalid" in (wrong_provenance.stderr)
    assert not wrong_output.exists()


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
        "RESUME_SOURCE_MANIFEST_RESOLUTION": "canonical_fallback",
        "SOURCE_ARTIFACT_NAME": "full-extraction-manifest-12345",
        "SOURCE_RUN_ID": "987654",
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

    transaction = _committed_checkpoint_transaction(
        chain_id="12345",
        source_sha=source_sha,
        generation=2,
        artifact_id=701,
        artifact_run_id=987654,
        artifact_digest="sha256:" + "c" * 64,
        artifact_size_bytes=4096,
        database_sha256="d" * 64,
        report_sha256="e" * 64,
        coverage_fingerprint="f" * 64,
        lane_id="fixture-lane",
        lane_coverage_hash="0" * 64,
    )
    manifest_path.write_text(
        json.dumps(
            {
                "chain_id": "12345",
                "workflow_source_sha": source_sha,
                "chain_state": {
                    "latest_checkpoint_transaction": transaction.to_dict(),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    committed_env = {
        **base_env,
        "RESUME_SOURCE_MANIFEST_RESOLUTION": "committed",
        "SOURCE_ARTIFACT_NAME": ("full-extraction-next-manifest-12345-iter-3-run-987654-attempt-2"),
    }
    committed = _run_python(verifier, env=committed_env)
    assert committed.returncode == 0, committed.stderr or committed.stdout

    uncommitted_payload = transaction.to_dict()
    uncommitted_payload["state"] = "built"
    manifest_path.write_text(
        json.dumps(
            {
                "chain_id": "12345",
                "workflow_source_sha": source_sha,
                "chain_state": {
                    "latest_checkpoint_transaction": uncommitted_payload,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    uncommitted = _run_python(verifier, env=committed_env)
    assert uncommitted.returncode == 1
    assert "matching committed checkpoint transaction" in uncommitted.stdout


def test_checkpoint_generation_derives_from_trusted_manifest_pointer(
    tmp_path: pathlib.Path,
) -> None:
    build_step = _step_block(_job_block(_workflow_text(), "lane_control"), "Prepare next manifest")
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

    assert "CHECKPOINT_COVERAGE_RESOLVER" not in build_step
    assert "--latest-checkpoint-generation" not in build_step
    assert "--latest-checkpoint-coverage-hash" not in build_step
    assert "--latest-checkpoint-run-id" not in build_step
    assert "--latest-checkpoint-artifact-name" not in build_step
    assert (
        'CHECKPOINT_ARTIFACT_NAME="full-extraction-checkpoint-'
        '${CHAIN_ID}-iter-${CHECKPOINT_GENERATION}"'
    ) in build_step
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
            "latest_checkpoint_artifact_name": (
                f"full-extraction-checkpoint-{chain_id}-iter-{expected_generation - 1}"
            ),
            "latest_checkpoint_coverage_hash": "b" * 64,
            "latest_checkpoint_generation": expected_generation - 1,
            "latest_checkpoint_run_id": "111",
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

    report["coverage_fingerprint"] = "not-a-sha"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    wrong_coverage = _run_python(validator, env=env)
    assert wrong_coverage.returncode == 1
    assert "Checkpoint report coverage hash must be a SHA-256" in wrong_coverage.stdout
    assert not output_path.exists()
    report["coverage_fingerprint"] = coverage_hash
    report_path.write_text(json.dumps(report), encoding="utf-8")

    manifest["chain_state"]["latest_checkpoint_generation"] = expected_generation
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    stale_manifest = _run_python(validator, env=env)
    assert stale_manifest.returncode == 1
    assert "Checkpoint candidate precommitted or skipped a generation" in stale_manifest.stdout
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
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "1",
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
                        {"name": source_metadata},
                        {"name": source_artifact, "expired": None},
                        {
                            "name": f"full-extraction-discovery-artifacts-{chain_id}",
                        },
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
    assert '"publish": os.environ["PUBLISH"]' in _job_block(workflow, "dispatch_next")


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

    assert "if: ${{ always() && !cancelled() && inputs.targeted_smoke }}" in smoke
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
        ({"expired": None}, "artifact is expired"),
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
    source_manifest_resolver = _step_block(replay, "Resolve immutable source committed manifest")
    source_manifest_download = _step_block(replay, "Download immutable source committed manifest")
    source_resolver = _step_block(replay, "Resolve exact source checkpoint receipt")
    source_download = _step_block(replay, "Download exact source checkpoint")
    replay_attestation = _step_block(replay, "Attest terminal replay inputs")
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
    assert "TERMINAL_REPLAY_MANIFEST_RESOLVER" in source_manifest_resolver
    assert "full-extraction-next-manifest-" in source_manifest_resolver
    assert "source workflow run identity is invalid" in source_manifest_resolver
    assert "source committed-manifest artifact provenance is invalid" in (source_manifest_resolver)
    assert "artifact-ids: ${{ steps.source_manifest.outputs.artifact_id }}" in (
        source_manifest_download
    )
    assert "run-id: ${{ steps.source_manifest.outputs.source_run_id }}" in (
        source_manifest_download
    )
    assert "digest-mismatch: error" in source_manifest_download
    assert "latest_checkpoint_transaction" in source_resolver
    assert "zero-active replay requires a committed checkpoint transaction" in source_resolver
    assert "source checkpoint REST identity does not match its committed receipt" in (
        source_resolver
    )
    assert "rebuilding from attested complete-lane artifacts" in source_resolver
    assert 'gh run download "$SOURCE_RUN_ID"' not in replay
    assert "artifact-ids: ${{ steps.source_checkpoint.outputs.artifact_id }}" in (source_download)
    assert "run-id: ${{ steps.source_checkpoint.outputs.source_run_id }}" in source_download
    assert "digest-mismatch: error" in source_download
    assert "steps.source_checkpoint.outputs.artifact_id != ''" in replay
    assert "CHECKPOINT_TRANSACTION_PATH" in replay_attestation
    assert "TRUST_MANIFEST_PATH" in replay_attestation
    assert "zero-active replay trust manifest identity does not match" in (replay_attestation)
    assert "source checkpoint built transaction does not match the committed trust root" in (
        replay_attestation
    )
    assert "latest_checkpoint_run_id" not in replay_attestation
    assert "latest_checkpoint_artifact_name" not in replay_attestation
    assert "latest_checkpoint_generation" not in replay_attestation
    assert "latest_checkpoint_coverage_hash" not in replay_attestation
    assert "source checkpoint lane coverage hashes do not match" in replay
    assert "source checkpoint database SHA-256 does not match" in replay
    assert "source checkpoint report SHA-256 does not match" in replay
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


def test_terminal_replay_resolves_source_runs_immutable_committed_manifest(
    tmp_path: pathlib.Path,
) -> None:
    replay = _job_block(_workflow_text(), "terminal_replay")
    resolver = _embedded_python(replay, "TERMINAL_REPLAY_MANIFEST_RESOLVER")
    chain_id = "fixture-chain"
    source_run_id = "987654"
    source_run_attempt = 2
    owner_head_sha = "e" * 40
    artifact_name = "full-extraction-next-manifest-fixture-chain-iter-4-run-987654-attempt-2"
    artifact_digest = "sha256:" + "f" * 64
    owner_run = {
        "id": int(source_run_id),
        "head_sha": owner_head_sha,
        "run_attempt": source_run_attempt,
    }
    exact_artifact = {
        "id": 801,
        "name": artifact_name,
        "digest": artifact_digest,
        "size_in_bytes": 2048,
        "expired": False,
        "workflow_run": {
            "id": int(source_run_id),
            "head_sha": owner_head_sha,
        },
    }
    stale_canonical = {
        **exact_artifact,
        "id": 700,
        "name": f"full-extraction-manifest-{chain_id}",
    }

    def run_case(
        name: str,
        inventory_artifacts: list[dict[str, object]],
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path]:
        case_dir = tmp_path / name
        fixture_env = _gh_fixture_env(
            case_dir,
            [
                owner_run,
                [
                    {
                        "total_count": len(inventory_artifacts),
                        "artifacts": inventory_artifacts,
                    }
                ],
            ],
        )
        output_path = case_dir / "github-output.txt"
        result = _run_python(
            resolver,
            env={
                **fixture_env,
                "CHAIN_ID": chain_id,
                "GITHUB_OUTPUT": str(output_path),
                "GITHUB_REPOSITORY": "acme/nbadb",
                "SOURCE_RUN_ID": source_run_id,
            },
            cwd=case_dir,
        )
        return result, output_path

    resolved, output_path = run_case(
        "resolved",
        [
            stale_canonical,
            {
                **exact_artifact,
                "id": 800,
                "name": ("full-extraction-next-manifest-fixture-chain-iter-4-run-987654-attempt-1"),
            },
            exact_artifact,
        ],
    )
    assert resolved.returncode == 0, resolved.stderr or resolved.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        f"artifact_name={artifact_name}",
        "artifact_id=801",
        f"artifact_digest={artifact_digest}",
        "artifact_size_bytes=2048",
        f"source_run_id={source_run_id}",
        f"source_run_head_sha={owner_head_sha}",
        f"source_run_attempt={source_run_attempt}",
    ]

    prior_artifact = {
        **exact_artifact,
        "id": 800,
        "name": ("full-extraction-next-manifest-fixture-chain-iter-4-run-987654-attempt-1"),
    }
    prior_attempt, prior_output = run_case(
        "prior-attempt",
        [stale_canonical, prior_artifact],
    )
    assert prior_attempt.returncode == 0, prior_attempt.stderr or prior_attempt.stdout
    assert prior_output.read_text(encoding="utf-8").splitlines()[-1] == ("source_run_attempt=1")

    missing, missing_output = run_case("missing", [stale_canonical])
    assert missing.returncode == 0, missing.stderr or missing.stdout
    assert "No immutable committed next-manifest exists" in missing.stdout
    assert not missing_output.exists()

    ambiguous, ambiguous_output = run_case(
        "ambiguous",
        [exact_artifact, {**exact_artifact, "id": 802}],
    )
    assert ambiguous.returncode == 1
    assert "ambiguous immutable committed next-manifest" in ambiguous.stderr
    assert not ambiguous_output.exists()

    wrong_head, wrong_head_output = run_case(
        "wrong-head",
        [
            {
                **exact_artifact,
                "workflow_run": {
                    "id": int(source_run_id),
                    "head_sha": "0" * 40,
                },
            }
        ],
    )
    assert wrong_head.returncode == 1
    assert "committed-manifest artifact provenance is invalid" in wrong_head.stderr
    assert not wrong_head_output.exists()


def test_terminal_replay_uses_committed_transaction_and_rejects_tampering(
    tmp_path: pathlib.Path,
) -> None:
    replay = _job_block(_workflow_text(), "terminal_replay")
    resolver = _embedded_python(replay, "TERMINAL_REPLAY_ARTIFACT_RESOLVER")
    attestation = _embedded_python(replay, "TERMINAL_REPLAY_ATTESTATION")
    chain_id = "fixture-chain"
    source_sha = "a" * 40
    coverage_fingerprint = "b" * 64
    lane_coverage_hash = "c" * 64
    artifact_digest = "sha256:" + "d" * 64
    source_run_id = "987654"
    owner_head_sha = "e" * 40
    artifact_id = 701
    checkpoint_name = f"full-extraction-checkpoint-{chain_id}-iter-3"
    database_path = tmp_path / "nba.duckdb"
    database_path.write_bytes(b"attested-checkpoint")
    database_sha256 = hashlib.sha256(database_path.read_bytes()).hexdigest()
    report_path = tmp_path / "checkpoint-report.json"
    report = {
        "active_lane_count": 0,
        "chain_id": chain_id,
        "checkpoint_generation": 3,
        "complete_lane_count": 1,
        "coverage_fingerprint": coverage_fingerprint,
        "included_lane_coverage_hashes": {
            "fixture-lane": lane_coverage_hash,
        },
        "database_sha256": database_sha256,
        "run_id": source_run_id,
        "artifact_name": checkpoint_name,
        "source_sha": source_sha,
        "terminal_ready": True,
    }
    report_bytes = json.dumps(report, sort_keys=True).encode("utf-8")
    report_path.write_bytes(report_bytes)
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    transaction = _committed_checkpoint_transaction(
        chain_id=chain_id,
        source_sha=source_sha,
        generation=3,
        artifact_id=artifact_id,
        artifact_run_id=int(source_run_id),
        artifact_digest=artifact_digest,
        artifact_size_bytes=4096,
        database_sha256=database_sha256,
        report_sha256=report_sha256,
        coverage_fingerprint=coverage_fingerprint,
        lane_id="fixture-lane",
        lane_coverage_hash=lane_coverage_hash,
    )
    transaction_payload = transaction.to_dict()
    plan_manifest_path = tmp_path / "manifest.json"
    plan_manifest = {
        "lane_count": 1,
        "active_lane_count": 0,
        "matrix_lane_count": 0,
        "coverage_fingerprint": coverage_fingerprint,
        "chain_state": {
            "latest_checkpoint_run_id": "stale-flat-run",
            "latest_checkpoint_artifact_name": "stale-flat-artifact",
            "latest_checkpoint_generation": 2,
            "latest_checkpoint_coverage_hash": "stale-flat-coverage",
        },
    }
    plan_manifest_path.write_text(json.dumps(plan_manifest), encoding="utf-8")
    trust_manifest_path = tmp_path / "next-manifest.json"
    trust_manifest = {
        "chain_id": chain_id,
        "workflow_source_sha": source_sha,
        "chain_state": {
            "latest_checkpoint_transaction": transaction_payload,
        },
    }
    trust_manifest_path.write_text(json.dumps(trust_manifest), encoding="utf-8")
    owner_run = {
        "id": int(source_run_id),
        "head_sha": owner_head_sha,
    }
    artifact = {
        "id": artifact_id,
        "name": checkpoint_name,
        "digest": artifact_digest,
        "size_in_bytes": 4096,
        "expired": False,
        "workflow_run": {
            "id": int(source_run_id),
            "head_sha": owner_head_sha,
        },
    }
    resolver_dir = tmp_path / "resolver"
    fixture_env = _gh_fixture_env(resolver_dir, [owner_run, artifact])
    output_path = tmp_path / "github-output.txt"
    resolver_env = {
        **fixture_env,
        "CHAIN_ID": chain_id,
        "GITHUB_OUTPUT": str(output_path),
        "GITHUB_REPOSITORY": "acme/nbadb",
        "PLAN_MANIFEST_PATH": str(trust_manifest_path),
        "SOURCE_RUN_ID": source_run_id,
        "WORKFLOW_SOURCE_SHA": source_sha,
    }
    resolved = _run_python(resolver, env=resolver_env)
    assert resolved.returncode == 0, resolved.stderr or resolved.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        f"artifact_name={checkpoint_name}",
        f"artifact_id={artifact_id}",
        f"artifact_digest={artifact_digest}",
        "artifact_size_bytes=4096",
        f"source_run_id={source_run_id}",
        "checkpoint_generation=3",
        f"coverage_fingerprint={coverage_fingerprint}",
        f"database_sha256={database_sha256}",
        f"report_sha256={report_sha256}",
    ]

    output_path.unlink()
    trust_manifest["chain_state"] = {}
    trust_manifest_path.write_text(json.dumps(trust_manifest), encoding="utf-8")
    missing = _run_python(resolver, env=resolver_env)
    assert missing.returncode == 0, missing.stderr or missing.stdout
    assert "No committed source checkpoint transaction exists" in missing.stdout
    assert not output_path.exists()

    for label, malformed_transaction in (
        ("null", None),
        ("empty-string", ""),
        ("empty-list", []),
        ("empty-object", {}),
    ):
        trust_manifest["chain_state"] = {
            "latest_checkpoint_transaction": malformed_transaction,
        }
        trust_manifest_path.write_text(json.dumps(trust_manifest), encoding="utf-8")
        malformed = _run_python(resolver, env=resolver_env)
        assert malformed.returncode == 1, label
        assert "zero-active replay requires a committed checkpoint transaction" in malformed.stderr
        assert not output_path.exists()

    trust_manifest["chain_state"] = {
        "latest_checkpoint_transaction": transaction_payload,
    }
    trust_manifest_path.write_text(json.dumps(trust_manifest), encoding="utf-8")
    invalid_transaction = json.loads(json.dumps(transaction_payload))
    invalid_transaction["receipt"]["database_sha256"] = "0" * 64
    trust_manifest["chain_state"]["latest_checkpoint_transaction"] = invalid_transaction
    trust_manifest_path.write_text(json.dumps(trust_manifest), encoding="utf-8")
    invalid_receipt = _run_python(resolver, env=resolver_env)
    assert invalid_receipt.returncode == 1
    assert "committed checkpoint artifact receipt is invalid" in invalid_receipt.stderr
    assert not output_path.exists()

    trust_manifest["chain_state"]["latest_checkpoint_transaction"] = transaction_payload
    trust_manifest_path.write_text(json.dumps(trust_manifest), encoding="utf-8")
    mismatch_dir = tmp_path / "resolver-rest-mismatch"
    mismatch_env = _gh_fixture_env(
        mismatch_dir,
        [owner_run, {**artifact, "size_in_bytes": 8192}],
    )
    rest_mismatch = _run_python(
        resolver,
        env={**resolver_env, **mismatch_env},
    )
    assert rest_mismatch.returncode == 1
    assert "REST identity does not match its committed receipt" in rest_mismatch.stderr
    assert not output_path.exists()

    checkpoint_manifest_path = tmp_path / "checkpoint-manifest.json"
    checkpoint_manifest = {
        "chain_id": chain_id,
        "workflow_source_sha": source_sha,
        "lane_count": 1,
        "coverage_fingerprint": coverage_fingerprint,
        "chain_state": {
            "latest_checkpoint_run_id": "stale-candidate-run",
            "latest_checkpoint_artifact_name": "stale-candidate-artifact",
            "latest_checkpoint_generation": 2,
            "latest_checkpoint_coverage_hash": "stale-candidate-coverage",
        },
        "lanes": [
            {
                "lane_id": "fixture-lane",
                "coverage_units_hash": lane_coverage_hash,
            }
        ],
    }
    checkpoint_manifest_path.write_text(json.dumps(checkpoint_manifest), encoding="utf-8")
    candidate_transaction_path = tmp_path / "checkpoint-transaction.json"
    candidate_transaction = json.loads(json.dumps(transaction_payload))
    candidate_transaction["state"] = "built"
    candidate_transaction["receipt"] = None
    candidate_transaction_path.write_text(
        json.dumps(candidate_transaction),
        encoding="utf-8",
    )
    attestation_env = {
        "CHAIN_ID": chain_id,
        "CHECKPOINT_DATABASE_PATH": str(database_path),
        "CHECKPOINT_TRANSACTION_PATH": str(candidate_transaction_path),
        "CHECKPOINT_REPORT_PATH": str(report_path),
        "EXPECTED_CHECKPOINT_GENERATION": "3",
        "EXPECTED_COVERAGE_FINGERPRINT": coverage_fingerprint,
        "EXPECTED_DATABASE_SHA256": database_sha256,
        "EXPECTED_REPORT_SHA256": report_sha256,
        "PLAN_MANIFEST_PATH": str(plan_manifest_path),
        "TRUST_MANIFEST_PATH": str(trust_manifest_path),
        "CHECKPOINT_MANIFEST_PATH": str(checkpoint_manifest_path),
        "SOURCE_CHECKPOINT_ARTIFACT": checkpoint_name,
        "SOURCE_RUN_ID": source_run_id,
        "WORKFLOW_SOURCE_SHA": source_sha,
    }
    accepted = _run_python(attestation, env=attestation_env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout

    mismatched_candidate = json.loads(json.dumps(candidate_transaction))
    mismatched_candidate["build"]["database_sha256"] = "0" * 64
    candidate_transaction_path.write_text(
        json.dumps(mismatched_candidate),
        encoding="utf-8",
    )
    wrong_candidate = _run_python(attestation, env=attestation_env)
    assert wrong_candidate.returncode == 1
    assert "built transaction does not match the committed trust root" in (wrong_candidate.stdout)
    candidate_transaction_path.write_text(
        json.dumps(candidate_transaction),
        encoding="utf-8",
    )

    tampered_report = {**report}
    tampered_report["included_lane_coverage_hashes"] = {
        "fixture-lane": "0" * 64,
    }
    report_path.write_text(json.dumps(tampered_report, sort_keys=True), encoding="utf-8")
    wrong_lane_contract = _run_python(attestation, env=attestation_env)
    assert wrong_lane_contract.returncode == 1
    assert "source checkpoint lane coverage hashes do not match" in wrong_lane_contract.stdout
    report_path.write_bytes(report_bytes)

    database_path.write_bytes(b"tampered")
    tampered_database = _run_python(attestation, env=attestation_env)
    assert tampered_database.returncode == 1
    assert "source checkpoint database SHA-256 does not match" in (tampered_database.stdout)
    database_path.write_bytes(b"attested-checkpoint")

    report_path.write_bytes(report_bytes + b"\n")
    tampered_report_file = _run_python(attestation, env=attestation_env)
    assert tampered_report_file.returncode == 1
    assert "source checkpoint report SHA-256 does not match" in (tampered_report_file.stdout)


def test_dispatch_rest_response_and_child_provenance_are_exact(
    tmp_path: pathlib.Path,
) -> None:
    dispatch = _job_block(_workflow_text(), "dispatch_next")
    redispatch_guard = _step_block(dispatch, "Verify redispatch workflow definition")
    response_parser = _embedded_python_after(
        dispatch,
        'DISPATCH_RESPONSE_PATH="$dispatch_response_path"',
    )
    provenance_validator = _embedded_python_after(
        dispatch,
        'CHILD_DETAILS_PATH="$child_details_path"',
    )
    expected_title = "Full Extraction chain=12345 iteration=2"
    pinned_source_sha = "a" * 40
    trusted_branch_tip_sha = "b" * 40
    response_path = tmp_path / "dispatch-response.json"
    child_path = tmp_path / "child.json"
    details_path = tmp_path / "child-details.json"
    expected_html_url = "https://github.example/acme/nbadb/actions/runs/42"
    expected_api_url = "https://api.github.example/repos/acme/nbadb/actions/runs/42"
    response_path.write_text(
        json.dumps(
            {
                "workflow_run_id": 42,
                "html_url": expected_html_url,
                "run_url": expected_api_url,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    response_env = {
        "DISPATCH_RESPONSE_PATH": str(response_path),
        "CHILD_RUN_PATH": str(child_path),
        "EXPECTED_RUN_NAME": expected_title,
        "GITHUB_API_URL": "https://api.github.example",
        "GITHUB_REPOSITORY": "acme/nbadb",
        "GITHUB_SERVER_URL": "https://github.example",
    }

    parsed = _run_python(response_parser, env=response_env)
    assert parsed.returncode == 0, parsed.stderr or parsed.stdout
    assert json.loads(child_path.read_text(encoding="utf-8")) == {
        "api_url": expected_api_url,
        "display_title": expected_title,
        "id": "42",
        "url": expected_html_url,
    }

    details = {
        "id": 42,
        "display_title": expected_title,
        "html_url": expected_html_url,
        "event": "workflow_dispatch",
        "head_sha": trusted_branch_tip_sha,
    }
    details_path.write_text(json.dumps(details) + "\n", encoding="utf-8")
    provenance_env = {
        "CHILD_DETAILS_PATH": str(details_path),
        "EXPECTED_CHILD_RUN_ID": "42",
        "EXPECTED_RUN_NAME": expected_title,
        "EXPECTED_CHILD_URL": expected_html_url,
        "TRUSTED_BRANCH_TIP_SHA": trusted_branch_tip_sha,
        "WORKFLOW_SHA": pinned_source_sha,
    }
    accepted = _run_python(provenance_validator, env=provenance_env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout

    for key, invalid_value in (
        ("id", 43),
        ("display_title", "Full Extraction chain=other iteration=2"),
        ("html_url", "https://github.example/acme/nbadb/actions/runs/43"),
        ("event", "schedule"),
        ("head_sha", "c" * 40),
    ):
        invalid_details = {**details, key: invalid_value}
        details_path.write_text(
            json.dumps(invalid_details) + "\n",
            encoding="utf-8",
        )
        rejected = _run_python(provenance_validator, env=provenance_env)
        assert rejected.returncode == 1
        assert "self-dispatched child provenance does not match" in rejected.stderr

    response_path.write_text(
        json.dumps(
            {
                "workflow_run_id": 42,
                "html_url": "https://github.example/acme/nbadb/actions/runs/41",
                "run_url": expected_api_url,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    mismatched_response = _run_python(response_parser, env=response_env)
    assert mismatched_response.returncode == 1
    assert "did not return an exact child identity" in mismatched_response.stderr

    response_path.write_text(
        json.dumps(
            {
                "workflow_run_id": 42,
                "html_url": f"https://attacker.example{expected_html_url}",
                "run_url": f"https://attacker.example{expected_api_url}",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    suffix_spoof = _run_python(response_parser, env=response_env)
    assert suffix_spoof.returncode == 1
    assert "did not return an exact child identity" in suffix_spoof.stderr

    payload = dispatch.index('"return_run_details": True')
    enqueue = dispatch.index("/actions/workflows/full-extraction.yml/dispatches")
    response = dispatch.index('response.get("workflow_run_id")', enqueue)
    exact_get = dispatch.index('"$child_run_api_url" > "$child_details_path"', response)
    provenance = dispatch.index("self-dispatched child provenance does not match", exact_get)
    acknowledgement = dispatch.index("child_acknowledged=true", provenance)
    assert payload < enqueue < response < exact_get < provenance < acknowledgement
    assert "gh workflow run full-extraction.yml" not in dispatch
    assert "# CHILD_RUN_MATCHER" not in dispatch
    assert '-H "X-GitHub-Api-Version: 2022-11-28"' in dispatch
    assert '"return_run_details": True' in dispatch
    assert "GITHUB_SERVER_URL" in dispatch
    assert "GITHUB_API_URL" in dispatch
    assert "gh api \\\n              --method GET" in dispatch
    assert "id: redispatch_guard" in redispatch_guard
    assert 'echo "trusted_branch_tip_sha=$trusted_branch_commit"' in redispatch_guard
    assert (
        "TRUSTED_BRANCH_TIP_SHA: "
        "${{ steps.redispatch_guard.outputs.trusted_branch_tip_sha }}" in dispatch
    )
    assert '"workflow_sha": os.environ["WORKFLOW_SHA"]' in dispatch
    assert 'os.environ["TRUSTED_BRANCH_TIP_SHA"].lower()' in provenance_validator
    assert 'os.environ["WORKFLOW_SHA"].lower()' not in provenance_validator
    assert 'CHILD_POLL_INTERVAL_SECONDS: "5"' in dispatch
    assert "for _attempt in 1 2 3; do" in dispatch
    assert 'EXPECTED_CHILD_RUN_ID="$child_run_id"' in dispatch
    assert "Exact self-dispatched child run $child_run_id was not readable" in dispatch
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
    assert workflow.count(".github/scripts/run_extract_lane.py") == 3
    assert workflow.count(".github/scripts/vpn_control_plane.py") == 3


def test_full_extraction_artifact_overwrite_semantics_are_explicit() -> None:
    workflow = _workflow_text()
    upload_steps = re.findall(
        r"(?ms)^      - (?:name: [^\n]+\n(?:        [^\n]*\n)*)?"
        r"        uses: actions/upload-artifact@[^\n]+\n"
        r"        with:\n(?P<inputs>(?:          [^\n]+\n)+)",
        workflow,
    )

    assert len(upload_steps) == workflow.count("uses: actions/upload-artifact@")
    assert upload_steps
    assert all(
        "overwrite: true" in inputs or "overwrite: false" in inputs for inputs in upload_steps
    )
    assert workflow.count("overwrite: false") == 7
    assert "vpn-capacity-connected-run-${{ github.run_id }}-attempt-" in workflow
    assert "full-extraction-vpn-auth-circuit-run-${{ github.run_id }}-attempt-" in workflow

    capacity = _job_block(workflow, "vpn_capacity")
    extract = _job_block(workflow, "extract")
    lane_control = _job_block(workflow, "lane_control")
    checkpoint = _job_block(workflow, "checkpoint")
    for block, step_name in (
        (capacity, "Publish connected VPN capacity marker"),
        (extract, "Publish VPN auth circuit marker"),
        (extract, "Retry VPN auth circuit marker publication"),
        (lane_control, "Upload checkpoint candidate manifest"),
        (checkpoint, "Upload checkpoint artifact"),
        (checkpoint, "Retry checkpoint artifact upload after stable absence"),
        (checkpoint, "Upload committed next manifest"),
    ):
        step = _step_block(block, step_name)
        assert "overwrite: false" in step
        assert "overwrite: true" not in step


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
    final_quarantine = _job_block(workflow, "vpn_quarantine")
    extract = _job_block(workflow, "extract")
    vpn_step = _step_block(preflight, "Preflight VPN validation")
    quarantine_step = _step_block(
        preflight,
        "Carry preflight VPN failures into the chain quarantine",
    )

    assert "timeout-minutes: 8" in vpn_step
    assert "continue-on-error: true" in vpn_step
    assert 'SERVER_LIMIT: "4"' in vpn_step
    assert "RUN_ATTEMPT: ${{ github.run_attempt }}" in vpn_step
    assert "export LANE_INDEX=$((RUN_ATTEMPT - 1))" in vpn_step
    assert 'SERVER_POOL_SIZE: "96"' in vpn_step
    assert 'PRESERVE_RECOMMENDATION_RANK: "true"' in vpn_step
    assert 'CONNECT_TIMEOUT_SECONDS: "60"' in vpn_step
    assert 'OVERALL_TIMEOUT_SECONDS: "300"' in vpn_step
    diagnostics = _step_block(preflight, "Build redacted preflight VPN diagnostics")
    upload = _step_block(preflight, "Upload redacted preflight VPN diagnostics")
    assert "if: ${{ always() && inputs.network_mode != 'direct' }}" in diagnostics
    assert '"attempted_servers": server_list("ATTEMPTED_SERVERS_JSON")' in diagnostics
    assert '"failed_servers": server_list("FAILED_SERVERS_JSON")' in diagnostics
    assert "OPENVPN_USER" not in diagnostics
    assert "OPENVPN_PASSWORD" not in diagnostics
    assert "NORDVPN_TOKEN" not in diagnostics
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in upload
    assert "full-extraction-preflight-vpn-diagnostics-${{ env.ACTIVE_CHAIN_ID }}" in upload
    assert "continue-on-error: true" in upload

    diagnostics_dir = tmp_path / "artifacts" / "full-extraction" / "preflight-vpn-diagnostics"
    diagnostics_dir.mkdir(parents=True)
    diagnostics_result = _run_python(
        _embedded_python(diagnostics, "PREFLIGHT_VPN_DIAGNOSTICS"),
        cwd=tmp_path,
        env={
            **os.environ,
            "VPN_STATUS": "vpn_network_error",
            "VPN_AUTH_SOURCE": "",
            "VPN_SERVER": "",
            "VPN_EXIT_IP": "",
            "NBA_PROBE_STATUS": "timeout",
            "NBA_PROBE_DIAGNOSTIC": "NBA Stats probe timed out",
            "ATTEMPTED_SERVERS_JSON": '["us1001.nordvpn.com","us1002.nordvpn.com"]',
            "FAILED_SERVERS_JSON": '["us1001.nordvpn.com","us1002.nordvpn.com"]',
        },
    )
    assert diagnostics_result.returncode == 0, diagnostics_result.stderr
    diagnostics_payload = json.loads((diagnostics_dir / "summary.json").read_text(encoding="utf-8"))
    assert diagnostics_payload == {
        "schema_version": 1,
        "status": "vpn_network_error",
        "auth_source": "",
        "server": "",
        "exit_ip": "",
        "nba_probe_status": "timeout",
        "nba_probe_diagnostic": "NBA Stats probe timed out",
        "attempted_servers": ["us1001.nordvpn.com", "us1002.nordvpn.com"],
        "failed_servers": ["us1001.nordvpn.com", "us1002.nordvpn.com"],
    }
    assert (
        "vpn-quarantined-servers-json: "
        "${{ steps.vpn_quarantine.outputs.vpn-quarantined-servers-json }}"
    ) in preflight
    downstream_quarantine = (
        "QUARANTINED_SERVERS_JSON: ${{ needs.preflight.outputs.vpn-quarantined-servers-json }}"
    )
    assert downstream_quarantine in seed
    assert "BASELINE_QUARANTINE_JSON: ${{ needs.preflight.outputs." in final_quarantine
    assert (
        "DISCOVERY_FAILED_SERVERS_JSON: "
        "${{ needs.discovery_seed.outputs.vpn-failed-servers-json || '[]' }}"
    ) in final_quarantine
    assert "aggregate-quarantine" in final_quarantine
    assert (
        "QUARANTINED_SERVERS_JSON: ${{ needs.vpn_quarantine.outputs.vpn-quarantined-servers-json }}"
    ) in extract
    assert 'CONNECT_TIMEOUT_SECONDS: "60"' in seed
    assert 'CONNECT_TIMEOUT_SECONDS: "60"' in extract
    assert 'SERVER_POOL_SIZE: "96"' in seed
    assert 'SERVER_POOL_SIZE: "96"' in extract
    for job in (preflight, seed):
        assert "timeout-minutes: 8" in job
        assert "450 \\" in job
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


def test_configured_auth_capacity_gate_bounds_matrix_admission(
    tmp_path: pathlib.Path,
) -> None:
    workflow = _workflow_text()
    preflight = _job_block(workflow, "preflight")
    capacity = _job_block(workflow, "vpn_capacity")
    quarantine = _job_block(workflow, "vpn_quarantine")
    extract = _job_block(workflow, "extract")
    matrix_step = _step_block(preflight, "Build concurrent VPN capacity gate")
    connect_step = _step_block(capacity, "Prove concurrent VPN capacity")
    quarantine_step = _step_block(capacity, "Merge discovery failures into capacity quarantine")
    barrier_step = _step_block(capacity, "Wait for simultaneous VPN capacity")
    rerun_guard = _step_block(capacity, "Reject partial VPN capacity reruns")
    recheck_step = _step_block(capacity, "Revalidate VPN after capacity barrier")

    assert "vpn-capacity-required: ${{ steps.vpn_capacity.outputs.required }}" in preflight
    assert "vpn-capacity-count: ${{ steps.vpn_capacity.outputs.capacity-count }}" in preflight
    assert "vpn-capacity-matrix: ${{ steps.vpn_capacity.outputs.matrix }}" in preflight
    assert "needs.preflight.outputs.vpn-capacity-required == 'true'" in capacity
    assert "timeout-minutes: 35" in capacity
    assert "fail-fast: false" in capacity
    assert "max-parallel: ${{ fromJSON(inputs.vpn_parallelism) }}" in capacity
    assert "matrix: ${{ fromJSON(needs.preflight.outputs.vpn-capacity-matrix) }}" in capacity
    assert "timeout-minutes: 16" in connect_step
    assert "continue-on-error: true" in connect_step
    assert 'configured-auth-prevalidated: "true"' in connect_step
    assert 'auth-recovery-base-delay-seconds: "300"' in connect_step
    assert 'require-auth-recovery-budget: "true"' in connect_step
    assert "server-limit: ${{ matrix.server_limit }}" in connect_step
    assert "auth-recovery-rounds: ${{ matrix.auth_recovery_rounds }}" in connect_step
    assert "fallback-technology: ${{ matrix.fallback_technology }}" in connect_step
    assert "preferred-only: ${{ matrix.preferred_only }}" in connect_step
    assert (
        "preserve-recommendation-rank: ${{ matrix.preserve_recommendation_rank }}" in connect_step
    )
    assert "preferred-server-slot-count: ${{ matrix.expected_capacity }}" in connect_step
    assert "recommendation-slot-count: ${{ matrix.recommendation_slot_count }}" in connect_step
    assert "recommendation-slot-index: ${{ matrix.recommendation_slot_index }}" in connect_step
    assert (
        "quarantined-servers-json: "
        "${{ steps.capacity_quarantine.outputs.vpn-quarantined-servers-json }}"
    ) in connect_step
    assert "DISCOVERY_FAILED_SERVERS_JSON" in quarantine_step
    assert "PREFLIGHT_QUARANTINE_JSON" in quarantine_step
    assert 'overall-timeout-seconds: "780"' in connect_step
    assert "vpn-capacity-connected-run-${{ github.run_id }}-attempt-" in capacity
    assert "python3 .github/scripts/vpn_control_plane.py capacity-wait" in barrier_step
    assert "github.run_attempt > 1" in rerun_guard
    assert "/attempts/${RUN_ATTEMPT}/jobs?per_page=100" in rerun_guard
    assert 'startswith("vpn_capacity (")' in rerun_guard
    assert "len(cohort) != expected" in rerun_guard
    assert "rerun all jobs" in rerun_guard
    assert "EXPECTED_CAPACITY: ${{ matrix.expected_capacity }}" in barrier_step
    assert 'sudo kill -0 "$VPN_PID"' in recheck_step
    assert "ip route get 1.1.1.1" in recheck_step
    assert "Enforce concurrent VPN capacity" in capacity
    assert (
        "vpn-capacity-diagnostics-${{ env.ACTIVE_CHAIN_ID }}-${{ matrix.lane_index }}"
    ) in capacity
    assert "needs: [plan, preflight, discovery_seed, vpn_capacity]" in quarantine
    assert "needs: [plan, preflight, discovery_seed, vpn_capacity, vpn_quarantine]" in extract
    assert (
        "needs.vpn_capacity.result == 'success' || needs.vpn_capacity.result == 'skipped'"
    ) in extract
    assert "needs.vpn_quarantine.result == 'success'" in extract
    singleton_download = _step_block(quarantine, "Download singleton VPN capacity marker")
    parallel_download = _step_block(quarantine, "Download parallel VPN capacity markers")
    assert "needs.preflight.outputs.vpn-capacity-required == 'true'" in singleton_download
    assert "needs.preflight.outputs.vpn-capacity-count == '1'" in singleton_download
    assert (
        "name: vpn-capacity-connected-run-${{ github.run_id }}-attempt-"
        "${{ github.run_attempt }}-lane-0"
    ) in singleton_download
    assert (
        "path: capacity-markers/vpn-capacity-connected-run-${{ github.run_id }}-attempt-"
        "${{ github.run_attempt }}-lane-0/"
    ) in singleton_download
    assert "needs.preflight.outputs.vpn-capacity-required == 'true'" in parallel_download
    assert "needs.preflight.outputs.vpn-capacity-count != '1'" in parallel_download
    assert (
        "pattern: vpn-capacity-connected-run-${{ github.run_id }}-attempt-"
        "${{ github.run_attempt }}-lane-*"
    ) in parallel_download
    assert "merge-multiple: false" in parallel_download
    assert "EXPECTED_CAPACITY: ${{ needs.preflight.outputs.vpn-capacity-count }}" in quarantine

    artifacts = tmp_path / "artifacts" / "full-extraction"
    artifacts.mkdir(parents=True)
    (artifacts / "preflight-manifest.json").write_text(
        json.dumps(
            {
                "github_matrix": {
                    "include": [
                        {"lane_id": "fresh-1", "resume_only": "false"},
                        {"lane_id": "fresh-2", "resume_only": False},
                        {"lane_id": "resume", "resume_only": "true"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "github-output.txt"
    result = _run_python(
        _embedded_python(matrix_step, "VPN_CAPACITY_MATRIX"),
        cwd=tmp_path,
        env={
            "EFFECTIVE_NETWORK_MODE": "vpn",
            "GITHUB_OUTPUT": str(output_path),
            "ACTIVE_LANE_COUNT": "2",
            "MATRIX_LANE_COUNT": "3",
            "REQUESTED_VPN_PARALLELISM": "6",
            "VPN_AUTH_SOURCE": "configured",
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.read_text(encoding="utf-8") == (
        "required=true\n"
        "capacity-count=2\n"
        'matrix={"include":[{"lane_index":0,"expected_capacity":2,"server_limit":1,'
        '"auth_recovery_rounds":0,"fallback_technology":"",'
        '"preferred_only":true,"preserve_recommendation_rank":false,'
        '"recommendation_slot_count":0,"recommendation_slot_index":0},'
        '{"lane_index":1,"expected_capacity":2,"server_limit":6,'
        '"auth_recovery_rounds":1,"fallback_technology":"openvpn_tcp",'
        '"preferred_only":false,"preserve_recommendation_rank":true,'
        '"recommendation_slot_count":1,"recommendation_slot_index":0}]}\n'
    )


@pytest.mark.parametrize(
    ("requested_parallelism", "resume_only", "expected_capacity"),
    [
        ("1", ["false"], 1),
        ("2", ["false", "false"], 2),
        ("2", ["false"], 1),
        ("3", ["false"] * 3, 3),
        ("4", ["false"] * 4, 4),
        ("5", ["false"] * 5, 5),
        ("6", ["false"] * 6, 6),
    ],
)
def test_configured_auth_capacity_gate_matches_executable_lane_count(
    tmp_path: pathlib.Path,
    requested_parallelism: str,
    resume_only: list[str],
    expected_capacity: int,
) -> None:
    preflight = _job_block(_workflow_text(), "preflight")
    matrix_step = _step_block(preflight, "Build concurrent VPN capacity gate")
    artifacts = tmp_path / "artifacts" / "full-extraction"
    artifacts.mkdir(parents=True)
    lanes = [
        {"lane_id": f"lane-{index}", "resume_only": value}
        for index, value in enumerate(resume_only)
    ]
    (artifacts / "preflight-manifest.json").write_text(
        json.dumps({"github_matrix": {"include": lanes}}),
        encoding="utf-8",
    )
    output_path = tmp_path / "github-output.txt"

    result = _run_python(
        _embedded_python(matrix_step, "VPN_CAPACITY_MATRIX"),
        cwd=tmp_path,
        env={
            "ACTIVE_LANE_COUNT": str(sum(value == "false" for value in resume_only)),
            "EFFECTIVE_NETWORK_MODE": "vpn",
            "GITHUB_OUTPUT": str(output_path),
            "MATRIX_LANE_COUNT": str(len(lanes)),
            "REQUESTED_VPN_PARALLELISM": requested_parallelism,
            "VPN_AUTH_SOURCE": "configured",
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    fresh_slot_count = max(expected_capacity - 1, 0)
    expected_matrix = {
        "include": [
            {
                "lane_index": lane_index,
                "expected_capacity": expected_capacity,
                "server_limit": 1 if lane_index == 0 else 6,
                "auth_recovery_rounds": 0 if lane_index == 0 else 1,
                "fallback_technology": "" if lane_index == 0 else "openvpn_tcp",
                "preferred_only": lane_index == 0,
                "preserve_recommendation_rank": (lane_index > 0 and fresh_slot_count == 1),
                "recommendation_slot_count": 0 if lane_index == 0 else fresh_slot_count,
                "recommendation_slot_index": max(lane_index - 1, 0),
            }
            for lane_index in range(expected_capacity)
        ]
    }
    assert output_path.read_text(encoding="utf-8") == (
        "required=true\n"
        f"capacity-count={expected_capacity}\n"
        f"matrix={json.dumps(expected_matrix, separators=(',', ':'))}\n"
    )


def test_capacity_quarantine_merge_executes_and_fails_closed(
    tmp_path: pathlib.Path,
) -> None:
    capacity = _job_block(_workflow_text(), "vpn_capacity")
    quarantine_step = _step_block(capacity, "Merge discovery failures into capacity quarantine")
    script = _embedded_python(quarantine_step, "CAPACITY_VPN_QUARANTINE")
    output_path = tmp_path / "github-output.txt"

    result = _run_python(
        script,
        env={
            "PREFLIGHT_QUARANTINE_JSON": '["US1.NORDVPN.COM","us2.nordvpn.com"]',
            "DISCOVERY_FAILED_SERVERS_JSON": '["us2.nordvpn.com","US3.NORDVPN.COM"]',
            "GITHUB_OUTPUT": str(output_path),
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.read_text(encoding="utf-8") == (
        'vpn-quarantined-servers-json=["us1.nordvpn.com","us2.nordvpn.com","us3.nordvpn.com"]\n'
    )

    invalid = _run_python(
        script,
        env={
            "PREFLIGHT_QUARANTINE_JSON": "{}",
            "DISCOVERY_FAILED_SERVERS_JSON": "[]",
            "GITHUB_OUTPUT": str(tmp_path / "invalid-output.txt"),
        },
    )
    assert invalid.returncode != 0
    assert "must be a JSON array of server hostnames" in invalid.stderr


def test_auth_rejection_itself_suppresses_small_wave_redispatch() -> None:
    workflow = _workflow_text()
    lane_control = _job_block(workflow, "lane_control")
    dispatch = _job_block(workflow, "dispatch_next")

    assert 'summary.get("vpn_auth_circuit_rejection_lane_count", 0)' in lane_control
    assert 'summary.get("vpn_auth_circuit_check_failed_lane_count", 0)' in lane_control
    assert 'or int(summary.get("vpn_auth_circuit_rejection_lane_count", 0)) > 0' in lane_control
    assert (
        'or int(summary.get("vpn_auth_circuit_check_failed_lane_count", 0)) > 0' not in lane_control
    )
    assert "needs.lane_control.outputs.vpn-auth-circuit-open != 'true'" in dispatch


@pytest.mark.parametrize(
    ("github_matrix", "matrix_lane_count", "active_lane_count", "error"),
    [
        (None, "1", "1", "github_matrix must be an object"),
        ({}, "1", "1", "github_matrix.include must be a list"),
        ({"include": []}, "1", "1", "lane count does not match"),
        (
            {"include": [{"lane_id": "resume", "resume_only": "true"}]},
            "1",
            "1",
            "contains no executable lanes",
        ),
    ],
)
def test_configured_auth_capacity_gate_rejects_inconsistent_manifest(
    tmp_path: pathlib.Path,
    github_matrix: object,
    matrix_lane_count: str,
    active_lane_count: str,
    error: str,
) -> None:
    preflight = _job_block(_workflow_text(), "preflight")
    matrix_step = _step_block(preflight, "Build concurrent VPN capacity gate")
    artifacts = tmp_path / "artifacts" / "full-extraction"
    artifacts.mkdir(parents=True)
    (artifacts / "preflight-manifest.json").write_text(
        json.dumps({"github_matrix": github_matrix}),
        encoding="utf-8",
    )
    output_path = tmp_path / "github-output.txt"

    result = _run_python(
        _embedded_python(matrix_step, "VPN_CAPACITY_MATRIX"),
        cwd=tmp_path,
        env={
            "ACTIVE_LANE_COUNT": active_lane_count,
            "EFFECTIVE_NETWORK_MODE": "vpn",
            "GITHUB_OUTPUT": str(output_path),
            "MATRIX_LANE_COUNT": matrix_lane_count,
            "REQUESTED_VPN_PARALLELISM": "2",
            "VPN_AUTH_SOURCE": "configured",
        },
    )

    assert result.returncode != 0
    assert error in result.stderr


@pytest.mark.parametrize(
    ("effective_mode", "auth_source", "active_lane_count", "resume_only"),
    [
        ("direct", "configured", "1", "false"),
        ("vpn", "token", "1", "false"),
        ("vpn", "configured", "0", "true"),
    ],
)
def test_vpn_capacity_gate_skips_nonconfigured_or_nonexecutable_waves(
    tmp_path: pathlib.Path,
    effective_mode: str,
    auth_source: str,
    active_lane_count: str,
    resume_only: str,
) -> None:
    preflight = _job_block(_workflow_text(), "preflight")
    matrix_step = _step_block(preflight, "Build concurrent VPN capacity gate")
    artifacts = tmp_path / "artifacts" / "full-extraction"
    artifacts.mkdir(parents=True)
    (artifacts / "preflight-manifest.json").write_text(
        json.dumps(
            {"github_matrix": {"include": [{"lane_id": "lane", "resume_only": resume_only}]}}
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "github-output.txt"

    result = _run_python(
        _embedded_python(matrix_step, "VPN_CAPACITY_MATRIX"),
        cwd=tmp_path,
        env={
            "ACTIVE_LANE_COUNT": active_lane_count,
            "EFFECTIVE_NETWORK_MODE": effective_mode,
            "GITHUB_OUTPUT": str(output_path),
            "MATRIX_LANE_COUNT": "1",
            "REQUESTED_VPN_PARALLELISM": "2",
            "VPN_AUTH_SOURCE": auth_source,
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.read_text(encoding="utf-8") == (
        'required=false\ncapacity-count=0\nmatrix={"include":'
        '[{"lane_index":0,"expected_capacity":0,"server_limit":1,'
        '"auth_recovery_rounds":0,"fallback_technology":"",'
        '"preferred_only":true,"preserve_recommendation_rank":false,'
        '"recommendation_slot_count":0,"recommendation_slot_index":0}]}\n'
    )


def test_vpn_matrix_batch_exposure_is_capped_per_parallel_tunnel() -> None:
    workflow = _workflow_text()
    plan = _job_block(workflow, "plan")
    lane_control = _job_block(workflow, "lane_control")
    build_manifest = _step_block(plan, "Build lane manifest")
    next_manifest = _step_block(lane_control, "Prepare next manifest")

    for step in (build_manifest, next_manifest):
        assert "vpn_matrix_cap=$((VPN_PARALLELISM * 32))" in step
        assert '--max-matrix-lanes "$effective_matrix_batch_size"' in step
    assert "NETWORK_MODE: ${{ inputs.network_mode }}" in build_manifest
    assert (
        "EFFECTIVE_NETWORK_MODE: ${{ needs.preflight.outputs.effective-network-mode }}"
    ) in next_manifest


def test_extract_auth_throttle_recovery_holds_the_active_matrix_slot() -> None:
    extract = _job_block(_workflow_text(), "extract")
    vpn_step = _step_block(extract, "Connect NordVPN tunnel")
    budget_step = _step_block(extract, "Initialize lane job budget")

    assert 'JOB_TIMEOUT_SECONDS: "21000"' in budget_step
    assert 'FINALIZATION_RESERVE_SECONDS: "1200"' in budget_step
    assert "NBADB_EXTRACT_JOB_DEADLINE_EPOCH_SECONDS" in budget_step
    assert "NBADB_EXTRACT_FINALIZATION_RESERVE_SECONDS" in budget_step
    assert extract.index("- name: Initialize lane job budget") < extract.index(
        "- uses: actions/checkout@"
    )
    assert "timeout-minutes: 16" in vpn_step
    assert 'AUTH_REJECTION_LIMIT: "1"' in vpn_step
    assert 'AUTH_RECOVERY_REJECTION_LIMIT: "3"' in vpn_step
    assert 'AUTH_RECOVERY_ROUNDS: "1"' in vpn_step
    assert 'AUTH_RECOVERY_BASE_DELAY_SECONDS: "300"' in vpn_step
    assert 'REQUIRE_AUTH_RECOVERY_BUDGET: "true"' in vpn_step
    assert 'OVERALL_TIMEOUT_SECONDS: "780"' in vpn_step
    assert "            930 \\" in vpn_step
    assert "            5 \\" in vpn_step

    step_timeout = re.search(r"timeout-minutes: (?P<value>\d+)", vpn_step)
    overall_timeout = re.search(r'OVERALL_TIMEOUT_SECONDS: "(?P<value>\d+)"', vpn_step)
    wrapper = re.search(
        r"run_with_deadline\.sh \\\n\s+(?P<deadline>\d+) \\\n\s+(?P<grace>\d+) \\",
        vpn_step,
    )
    assert step_timeout is not None
    assert overall_timeout is not None
    assert wrapper is not None

    step_seconds = int(step_timeout.group("value")) * 60
    overall_seconds = int(overall_timeout.group("value"))
    wrapper_seconds = int(wrapper.group("deadline"))
    grace_seconds = int(wrapper.group("grace"))
    assert overall_seconds + 10 < wrapper_seconds
    assert wrapper_seconds + grace_seconds < step_seconds


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
    assert (
        "RECOMMENDATION_SLOT_COUNT: ${{ needs.preflight.outputs.vpn-auth-source == 'token' "
        "&& '0' || needs.plan.outputs.vpn-slot-count }}"
    ) in vpn_step
    assert "RECOMMENDATION_SLOT_INDEX: ${{ matrix.vpn_slot }}" in vpn_step


def test_extract_vpn_slots_use_non_cancelling_serial_queues() -> None:
    workflow = _workflow_text()
    plan = _job_block(workflow, "plan")
    extract = _job_block(workflow, "extract")
    extract_strategy = extract.split("    strategy:\n", 1)[1].split("    concurrency:\n", 1)[0]
    lane_control = _step_block(
        _job_block(workflow, "lane_control"),
        "Prepare next manifest",
    )

    assert "vpn-slot-count: ${{ steps.manifest.outputs.vpn-slot-count }}" in plan
    assert '--vpn-slot-count "$VPN_PARALLELISM"' in plan
    assert "vpn-slot-count={manifest.get('vpn_slot_count', 0)}" in plan
    assert "matrix.vpn_slot" in extract
    assert "format('vpn-slot-{0}', matrix.vpn_slot)" in extract
    assert "format('direct-lane-{0}', matrix.lane_index)" in extract
    assert "queue: max" in extract
    assert "cancel-in-progress: false" in extract
    assert (
        "max-parallel: ${{ fromJSON(needs.preflight.outputs.effective-network-mode == "
        "'direct' && inputs.direct_parallelism || (needs.preflight.outputs.vpn-auth-source "
        "== 'token' && '1' || needs.plan.outputs.matrix-lane-count)) }}"
    ) in extract
    assert "'token' && '1' || inputs.vpn_parallelism" not in extract_strategy
    assert '--vpn-slot-count "$VPN_PARALLELISM"' in lane_control


def test_network_mode_resolution_rejects_unattested_connected_tunnels(
    tmp_path: pathlib.Path,
) -> None:
    preflight = _job_block(_workflow_text(), "preflight")
    step = _step_block(preflight, "Resolve effective network mode")
    assert "VPN_AUTH_SOURCE: ${{ steps.vpn.outputs.auth-source }}" in step
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    cases = (
        (
            "vpn",
            "connected",
            "configured",
            "us1001.nordvpn.com",
            "192.0.2.1",
            0,
            "effective-network-mode=vpn\n",
            "",
        ),
        (
            "vpn",
            "connected",
            "token",
            "us1001.nordvpn.com",
            "192.0.2.1",
            0,
            "effective-network-mode=vpn\n",
            "",
        ),
        (
            "vpn",
            "connected",
            "",
            "us1001.nordvpn.com",
            "192.0.2.1",
            1,
            "",
            "credential-source attestation",
        ),
        (
            "vpn",
            "connected",
            "unknown",
            "us1001.nordvpn.com",
            "192.0.2.1",
            1,
            "",
            "credential-source attestation",
        ),
        (
            "vpn",
            "connected",
            "configured",
            "",
            "192.0.2.1",
            1,
            "",
            "server and exit-IP attestations",
        ),
        (
            "vpn",
            "connected",
            "configured",
            "us1001.nordvpn.com",
            "",
            1,
            "",
            "server and exit-IP attestations",
        ),
        ("vpn", "vpn_network_error", "", "", "", 1, "", "refusing requested VPN extraction"),
        ("vpn", "vpn_auth_failure", "", "", "", 1, "", "refusing requested VPN extraction"),
        ("vpn", "", "", "", "", 1, "", "refusing requested VPN extraction"),
        ("auto", "vpn_auth_failure", "", "", "", 0, "effective-network-mode=direct\n", ""),
        ("direct", "unknown", "", "", "", 0, "effective-network-mode=direct\n", ""),
        ("unsupported", "unknown", "", "", "", 1, "", "Unsupported network_mode"),
    )

    for index, (
        requested,
        status,
        auth_source,
        server,
        exit_ip,
        expected_rc,
        expected_output,
        expected_error,
    ) in enumerate(cases):
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
                "VPN_SERVER": server,
                "VPN_EXIT_IP": exit_ip,
                "GITHUB_OUTPUT": str(output_path),
            },
            text=True,
        )

        assert result.returncode == expected_rc, result.stderr or result.stdout
        assert output_path.read_text(encoding="utf-8") == expected_output
        assert expected_error in result.stdout


def test_effective_attempt_quarantine_is_persisted_into_the_next_manifest(
    tmp_path: pathlib.Path,
) -> None:
    lane_control = _job_block(_workflow_text(), "lane_control")
    build_step = _step_block(lane_control, "Prepare next manifest")
    assert (
        "PREFLIGHT_QUARANTINE_JSON: "
        "${{ needs.vpn_quarantine.outputs.vpn-quarantined-servers-json }}" in build_step
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
