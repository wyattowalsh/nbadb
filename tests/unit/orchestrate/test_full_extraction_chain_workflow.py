from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import textwrap
import types
import zipfile
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

from nbadb.contracts.assurance_admission import AssuranceAdmission
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.orchestrate.checkpoint_contract import (
    CheckpointArtifactReceipt,
    CheckpointTransaction,
    CheckpointW2AuthorityIdentity,
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
from nbadb.orchestrate.operation_authority import (
    NetworkMode,
    OperationAuthorityV1,
    OperationKind,
)
from nbadb.orchestrate.public_value_authority_store import PUBLIC_VALUE_AUTHORITY_TABLES
from nbadb.orchestrate.w2_database_assurance import W2DatabaseAuthorityReceiptV1
from nbadb.orchestrate.w2_operation_store import RAW_NBA_API_W2_OPERATION_TABLE

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "full-extraction.yml"
_CI_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_DAILY_PATH = _REPO_ROOT / ".github" / "workflows" / "daily-update.yml"
_MONTHLY_PATH = _REPO_ROOT / ".github" / "workflows" / "monthly-update.yml"
_REFRESH_METADATA_ACTION_PATH = (
    _REPO_ROOT / ".github" / "actions" / "refresh-metadata" / "action.yml"
)
_DISCOVERY_SEED_PATH = _REPO_ROOT / ".github" / "scripts" / "seed_discovery_artifacts.py"
_FULL_EXTRACTION_ATTEMPT_GATE_PATH = (
    _REPO_ROOT / ".github" / "scripts" / "validate_full_extraction_attempt.py"
)
_FULL_EXTRACTION_HANDOFFS_PATH = _REPO_ROOT / ".github" / "scripts" / "full_extraction_handoffs.py"
_LEGACY_MANIFEST_HANDOFF_PATH = (
    _REPO_ROOT / ".github" / "scripts" / "resolve_legacy_manifest_handoff.py"
)
_REQUIRED_EXTRACTION_SCRIPTS = (
    _REPO_ROOT / ".github" / "scripts" / "attest_free_execution_job.py",
    _FULL_EXTRACTION_HANDOFFS_PATH,
    _REPO_ROOT / ".github" / "scripts" / "probe_discovery_transport.py",
    _LEGACY_MANIFEST_HANDOFF_PATH,
    _REPO_ROOT / ".github" / "scripts" / "verify_discovery_bundle.py",
)


def _checkpoint_w2_authority() -> CheckpointW2AuthorityIdentity:
    relation_counts = tuple(
        sorted(
            (table_name, 0)
            for table_name in (*PUBLIC_VALUE_AUTHORITY_TABLES, RAW_NBA_API_W2_OPERATION_TABLE)
        )
    )
    database_authority = W2DatabaseAuthorityReceiptV1.build(
        w2_required_logical_call_count=0,
        w2_source_call_admission_inventory_sha256="4" * 64,
        raw_authority_v2_bundle_count=0,
        raw_authority_v2_bundle_inventory_sha256="5" * 64,
        raw_authority_v2_persistence_receipt_inventory_sha256="6" * 64,
        w2_publication_receipt_count=0,
        w2_publication_receipt_inventory_sha256="7" * 64,
        w2_exact_six_schema_inventory_sha256="8" * 64,
        w2_relation_row_counts=relation_counts,
        w2_relation_row_count=0,
        w2_relation_inventory_sha256="9" * 64,
    )
    return CheckpointW2AuthorityIdentity(
        database_authority=database_authority,
        database_authority_sha256=database_authority.receipt_sha256,
        expected_call_count=0,
        expected_call_inventory_sha256="0" * 64,
        database_authority_closed=True,
    )


def _assurance_admission(source_sha: str = "a" * 40) -> AssuranceAdmission:
    authority = expected_nba_api_provider_authority()
    return AssuranceAdmission(
        source_sha=source_sha,
        assurance_manifest_sha256="1" * 64,
        generation_semantic_sha256="2" * 64,
        provider_evidence_sha256=str(authority["provider_evidence_sha256"]),
        provider_authority_sha256=str(authority["authority_sha256"]),
        authority_semantic_diff_sha256="3" * 64,
        authority_update_mode="full",
        first_extraction=True,
        model_status="GREEN",
    )


def _workflow_text() -> str:
    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def workflow_input_names(workflow: str) -> list[str]:
    return list(yaml.safe_load(workflow)[True]["workflow_dispatch"]["inputs"])


def _write_planner_operation_authority(
    path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    operation: OperationKind,
    manifest_lane_count: int,
    vpn_parallelism: int = 2,
    direct_parallelism: int = 0,
    chain_id: str = "fixture-chain",
) -> OperationAuthorityV1:
    """Bind one exact operation authority to the checked workflow and this runtime."""

    repository = "fixture/nbadb"
    source_sha = "a" * 40
    authority = OperationAuthorityV1(
        repository=repository,
        workflow_path=".github/workflows/full-extraction.yml",
        workflow_content_sha256=hashlib.sha256(_WORKFLOW_PATH.read_bytes()).hexdigest(),
        workflow_commit_sha=source_sha,
        source_sha=source_sha,
        trusted_ref="refs/heads/main",
        run_id=101,
        run_attempt=1,
        event="workflow_dispatch",
        actor="fixture-actor",
        chain_id=chain_id,
        iteration=1,
        operation=operation,
        requested_network_mode=NetworkMode.VPN,
        requested_vpn_parallelism=vpn_parallelism,
        requested_direct_parallelism=direct_parallelism,
        max_iterations=64,
        retry_pipeline_failures=True,
        allow_re_extraction=False,
        manifest_lane_count=manifest_lane_count,
    )
    path.write_text(json.dumps(authority.to_dict()), encoding="utf-8")
    for name, value in {
        "GITHUB_REPOSITORY": repository,
        "GITHUB_RUN_ID": "101",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "fixture-actor",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": source_sha,
        "WORKFLOW_SOURCE_SHA": source_sha,
    }.items():
        monkeypatch.setenv(name, value)
    return authority


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


def _helper_embedded_python(marker: str) -> str:
    return _embedded_python(
        _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8"),
        marker,
    )


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
import sys
from pathlib import Path

responses = json.loads(Path(os.environ["GH_FIXTURE_RESPONSES"]).read_text())
counter_path = Path(os.environ["GH_FIXTURE_COUNTER"])
counter = int(counter_path.read_text()) if counter_path.exists() else 0
counter_path.write_text(str(counter + 1))
with Path(os.environ["GH_FIXTURE_LOG"]).open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
print(json.dumps(responses[min(counter, len(responses) - 1)]))
""",
        encoding="utf-8",
    )
    gh_path.chmod(0o755)
    return {
        "GH_FIXTURE_RESPONSES": str(responses_path),
        "GH_FIXTURE_COUNTER": str(counter_path),
        "GH_FIXTURE_LOG": str(tmp_path / "gh-calls.jsonl"),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }


def _owner_recheck_snapshot(
    owner_run: Mapping[str, object],
    *,
    source_sha: str,
    repository: str = "acme/nbadb",
) -> dict[str, object]:
    run_id = owner_run["id"]
    owner_head_sha = str(owner_run["head_sha"]).lower()
    workflow_path = ".github/workflows/full-extraction.yml"
    return {
        "repository": repository,
        "run": {
            "attempt": owner_run.get("run_attempt", 1),
            "conclusion": owner_run.get("conclusion"),
            "event": owner_run.get("event", "workflow_dispatch"),
            "head_branch": owner_run.get("head_branch", "main"),
            "head_sha": owner_head_sha,
            "id": run_id,
            "path": owner_run.get("path", workflow_path),
            "status": owner_run.get("status"),
            "url": owner_run.get(
                "url",
                f"https://api.github.test/repos/{repository}/actions/runs/{run_id}",
            ),
            "workflow_id": owner_run.get("workflow_id"),
        },
        "schema_version": 1,
        "semantic_source": {
            "relation": "identical" if owner_head_sha == source_sha else "ancestor",
            "sha": source_sha,
        },
        "workflow": {
            "blob_sha": "b" * 40,
            "path": workflow_path,
            "sha256": "c" * 64,
            "size_in_bytes": 1,
        },
    }


def _committed_checkpoint_transaction(
    *,
    chain_id: str,
    source_sha: str,
    generation: int,
    artifact_id: int,
    artifact_run_id: int,
    run_attempt: int = 1,
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
        w2_authority=_checkpoint_w2_authority(),
    )
    assert built.build is not None
    receipt = CheckpointArtifactReceipt(
        artifact_id=artifact_id,
        artifact_run_id=artifact_run_id,
        artifact_run_attempt=run_attempt,
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
        w2_authority_identity_sha256=built.build.w2_authority.identity_sha256,
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


def test_workflow_file_fits_github_hosted_limit_with_margin() -> None:
    size = _WORKFLOW_PATH.stat().st_size
    assert size <= 495_000
    assert size <= 500_000


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
        relative = str(path.relative_to(_REPO_ROOT))
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=_REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert tracked.returncode == 0, tracked.stdout or tracked.stderr
        assert _CI_PATH.read_text(encoding="utf-8").count(relative) == 3, relative


def test_user_supplied_source_sha_must_descend_from_trusted_branches() -> None:
    workflow = _workflow_text()
    guard = _job_block(workflow, "workflow_guard")
    dispatch = _job_block(workflow, "dispatch_next")

    assert "WORKFLOW_SOURCE_SHA" in guard
    assert "^[0-9a-fA-F]{40}$" in guard
    assert 'git check-ref-format --branch "$WORKFLOW_SOURCE_REF"' in guard
    assert "+refs/heads/${WORKFLOW_SOURCE_REF}:${trusted_branch_ref}" in guard
    assert 'git merge-base --is-ancestor "$source_commit" "$trusted_branch_commit"' in guard
    # Publication is structurally unavailable here: the guard pins PUBLISH false and
    # rejects any publication attempt instead of re-checking default-branch ancestry,
    # because publication moved to the exact handoff publication workflow.
    assert "PUBLISH: ${{ false }}" in guard
    assert 'if [ "$PUBLISH" = "true" ]; then' in guard
    assert (
        "Publication is unavailable in full-extraction.yml; "
        "dispatch the exact handoff publication workflow" in guard
    )
    assert "+refs/heads/${DEFAULT_BRANCH}:${default_branch_ref}" not in guard
    assert 'git merge-base --is-ancestor "$source_commit" "$default_branch_commit"' not in guard
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
    validate = _step_block(checkpoint, "Validate checkpoint database")

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
    assert "lane_control_active_lane_count == 0" in checkpoint
    assert "and not terminal_ready" in checkpoint
    assert "and not dependent_activation_required" in checkpoint
    assert "if lane_control_active_lane_count > 0 and terminal_ready:" in checkpoint
    assert "Checkpoint report includes completed lanes but its database is missing" in checkpoint
    assert "Lane-control/checkpoint generation disagreement" in checkpoint
    assert "Checkpoint artifact suffix/generation disagreement" in checkpoint
    assert '--source-sha "$WORKFLOW_SOURCE_SHA"' in checkpoint
    assert validate.index(disagreement_guard) < validate.index(
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
    source_sha = "a" * 40
    artifact_name = "full-extraction-checkpoint-fixture-chain-iter-2"
    env = {
        "CURRENT_MANIFEST": str(manifest_path),
        "GITHUB_OUTPUT": str(output_path),
        "GITHUB_REPOSITORY": "fixture/nbadb",
        "WORKFLOW_SOURCE_SHA": source_sha,
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
                    "workflow_source_sha": source_sha,
                    "chain_state": {
                        "latest_checkpoint_run_id": run_id,
                        "latest_checkpoint_artifact_name": artifact_name,
                        "latest_checkpoint_transaction": malformed_transaction,
                    },
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
                "workflow_source_sha": source_sha,
                "chain_state": {
                    "latest_checkpoint_run_id": run_id,
                    "latest_checkpoint_artifact_name": artifact_name,
                },
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
        json.dumps({"workflow_source_sha": source_sha, "chain_state": {}}),
        encoding="utf-8",
    )
    fresh = _run_python(resolver, env=env)
    assert fresh.returncode == 0, fresh.stderr or fresh.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "run_id=",
        "artifact_name=",
        "artifact_id=",
    ]


def test_previous_checkpoint_exact_id_rejects_rest_and_same_name_drift(
    tmp_path: pathlib.Path,
) -> None:
    checkpoint = _job_block(_workflow_text(), "checkpoint")
    resolver = _embedded_python_after(
        _step_block(checkpoint, "Resolve previous checkpoint receipt"),
        "run: |",
    )
    chain_id = "fixture-chain"
    source_sha = "a" * 40
    run_id = 12345
    artifact_id = 701
    artifact_name = "full-extraction-checkpoint-fixture-chain-iter-2"
    artifact_digest = "sha256:" + "d" * 64
    transaction = _committed_checkpoint_transaction(
        chain_id=chain_id,
        source_sha=source_sha,
        generation=2,
        artifact_id=artifact_id,
        artifact_run_id=run_id,
        artifact_digest=artifact_digest,
        artifact_size_bytes=4096,
        database_sha256="b" * 64,
        report_sha256="c" * 64,
        coverage_fingerprint="e" * 64,
        lane_id="fixture-lane",
        lane_coverage_hash="f" * 64,
    )
    manifest_path = tmp_path / "current-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "workflow_source_sha": source_sha,
                "chain_state": {
                    "latest_checkpoint_artifact_name": artifact_name,
                    "latest_checkpoint_run_id": str(run_id),
                    "latest_checkpoint_transaction": transaction.to_dict(),
                },
            }
        ),
        encoding="utf-8",
    )
    owner_run = {
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": source_sha,
        "id": run_id,
        "path": ".github/workflows/full-extraction.yml",
        "repository": {"full_name": "acme/nbadb"},
        "run_attempt": 1,
        "status": "completed",
        "url": f"https://api.github.test/repos/acme/nbadb/actions/runs/{run_id}",
        "workflow_id": 99,
    }
    artifact = {
        "archive_download_url": (
            f"https://api.github.test/repos/acme/nbadb/actions/artifacts/{artifact_id}/zip"
        ),
        "digest": artifact_digest,
        "expired": False,
        "id": artifact_id,
        "name": artifact_name,
        "size_in_bytes": 4096,
        "workflow_run": {"head_sha": source_sha, "id": run_id},
    }

    def run_case(
        label: str,
        rest_owner: Mapping[str, object],
        rest_artifact: Mapping[str, object],
        *,
        rechecked_owner: Mapping[str, object] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path]:
        case_dir = tmp_path / label
        recheck_path = case_dir / "owner-recheck.json"
        recheck_path.parent.mkdir(parents=True, exist_ok=True)
        recheck_path.write_text(
            json.dumps(
                _owner_recheck_snapshot(
                    rechecked_owner or rest_owner,
                    source_sha=source_sha,
                )
            ),
            encoding="utf-8",
        )
        fixture = _gh_fixture_env(case_dir, [rest_owner, rest_artifact, rest_owner])
        output_path = case_dir / "github-output.txt"
        result = _run_python(
            resolver,
            env={
                **fixture,
                "CURRENT_MANIFEST": str(manifest_path),
                "GITHUB_API_URL": "https://api.github.test",
                "GITHUB_OUTPUT": str(output_path),
                "GITHUB_REPOSITORY": "acme/nbadb",
                "OWNER_RECHECK_PATH": str(recheck_path),
                "WORKFLOW_SOURCE_SHA": source_sha,
            },
            cwd=case_dir,
        )
        return result, output_path

    accepted, accepted_output = run_case("accepted", owner_run, artifact)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    assert accepted_output.read_text(encoding="utf-8").splitlines() == [
        f"run_id={run_id}",
        f"artifact_name={artifact_name}",
        f"artifact_id={artifact_id}",
    ]

    rerun, rerun_output = run_case(
        "rerun-after-recheck",
        {**owner_run, "run_attempt": 2},
        artifact,
        rechecked_owner=owner_run,
    )
    assert rerun.returncode == 1
    assert "changed after provenance recheck" in rerun.stderr
    assert not rerun_output.exists()
    rerun_calls = [
        json.loads(line)
        for line in (tmp_path / "rerun-after-recheck" / "gh-calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rerun_calls) == 1
    assert rerun_calls[0][-1].endswith(f"/actions/runs/{run_id}")
    assert all("/artifacts" not in argument for call in rerun_calls for argument in call)

    boolean_workflow_id, boolean_workflow_output = run_case(
        "boolean-workflow-id-after-recheck",
        {**owner_run, "workflow_id": True},
        artifact,
        rechecked_owner=owner_run,
    )
    assert boolean_workflow_id.returncode == 1
    assert "changed after provenance recheck" in boolean_workflow_id.stderr
    assert not boolean_workflow_output.exists()
    boolean_calls = [
        json.loads(line)
        for line in (tmp_path / "boolean-workflow-id-after-recheck" / "gh-calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(boolean_calls) == 1
    assert all("/artifacts" not in argument for call in boolean_calls for argument in call)

    rest_faults = (
        ("expired", owner_run, {**artifact, "expired": True}),
        ("digest", owner_run, {**artifact, "digest": "sha256:" + "0" * 64}),
        ("size", owner_run, {**artifact, "size_in_bytes": 8192}),
        (
            "workflow-run",
            owner_run,
            {
                **artifact,
                "workflow_run": {"head_sha": source_sha, "id": run_id + 1},
            },
        ),
        ("source-sha", {**owner_run, "head_sha": "0" * 40}, artifact),
        ("same-name-newer-id", owner_run, {**artifact, "id": artifact_id + 1}),
    )
    for label, rest_owner, rest_artifact in rest_faults:
        rejected, rejected_output = run_case(label, rest_owner, rest_artifact)
        assert rejected.returncode == 1, label
        assert not rejected_output.exists(), label
        assert (
            "previous checkpoint REST identity does not match its committed receipt"
            in rejected.stderr
            or "previous checkpoint owner run changed after provenance recheck" in rejected.stderr
        ), label


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


def test_checkpoint_external_failure_boundaries_gate_committed_state_and_child() -> None:
    workflow = _workflow_text()
    lane_control = _job_block(workflow, "lane_control")
    checkpoint = _job_block(workflow, "checkpoint")
    dispatch = _job_block(workflow, "dispatch_next")
    candidate_upload = _step_block(
        lane_control,
        "Upload checkpoint candidate manifest",
    )
    build_transaction = _step_block(checkpoint, "Build checkpoint transaction")
    checkpoint_upload = _step_block(checkpoint, "Upload checkpoint artifact")
    receipt = _step_block(checkpoint, "Verify immutable checkpoint receipt")
    commit = _step_block(checkpoint, "Commit checkpoint manifest")
    committed_upload = _step_block(checkpoint, "Upload committed next manifest")
    diagnostics = _step_block(checkpoint, "Upload checkpoint failure diagnostics")

    assert "continue-on-error" not in candidate_upload
    assert (
        "needs.lane_control.result == 'success'"
        in checkpoint.split(
            "    steps:\n",
            1,
        )[0]
    )
    assert "if: ${{ steps.checkpoint.outcome == 'success' }}" in build_transaction
    assert "if: ${{ steps.checkpoint.outcome == 'success' }}" in checkpoint_upload
    assert "steps.canonical_checkpoint.outcome == 'success'" in receipt
    assert "steps.checkpoint_sibling.outcome == 'success'" in receipt
    assert "steps.canonical_checkpoint_retry.outcome == 'success'" in receipt
    assert "if: ${{ steps.checkpoint_receipt.outcome == 'success' }}" in commit
    assert "if: ${{ steps.commit_manifest.outcome == 'success' }}" in committed_upload
    assert "continue-on-error" not in committed_upload
    for failed_gate in (
        "steps.checkpoint.outcome != 'success'",
        "steps.checkpoint_receipt.outcome != 'success'",
        "steps.commit_manifest.outcome != 'success'",
        "steps.committed_manifest.outcome != 'success'",
    ):
        assert failed_gate in diagnostics
    dispatch_header = dispatch.split("    steps:\n", 1)[0]
    assert "needs.checkpoint.result == 'success'" in dispatch_header
    assert "needs.checkpoint.outputs.terminal-ready == 'false'" in dispatch_header
    assert checkpoint.index("Upload checkpoint artifact") < checkpoint.index(
        "Verify immutable checkpoint receipt"
    )
    assert checkpoint.index("Verify immutable checkpoint receipt") < checkpoint.index(
        "Commit checkpoint manifest"
    )
    assert checkpoint.index("Commit checkpoint manifest") < checkpoint.index(
        "Upload committed next manifest"
    )


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
                "CURRENT_RUN_HEAD_SHA": owner_head_sha,
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
        w2_authority=_checkpoint_w2_authority(),
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
        w2_authority=_checkpoint_w2_authority(),
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
            "CURRENT_RUN_HEAD_SHA": owner_head_sha,
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
    helper = _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8")
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
    assert "metadata-artifact-receipts.json" in helper
    assert "resolve-artifacts-by-prefix" in helper
    assert "download-artifact-bundle" in helper
    assert '--artifact-name-prefix "extraction-lane-metadata-${CHAIN_ID}-"' in helper
    assert "has no lane metadata artifacts" in helper

    # Matrix failures still produce metadata/checkpoints and may dispatch a child.
    assert "needs.lane_control.result == 'success'" in checkpoint
    assert "needs.lane_control.result == 'success'" in dispatch
    assert "needs.checkpoint.result == 'success'" in dispatch


def test_resume_source_downloads_each_lane_metadata_artifact_to_a_unique_directory() -> None:
    plan = _job_block(_workflow_text(), "plan")
    helper = _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8")

    resolver = _step_block(plan, "Resolve resume source committed manifest")
    download = _step_block(plan, "Download exact resume source manifest")
    prepare = _step_block(plan, "Prepare resume source manifest")
    upload = _step_block(plan, "Upload lane manifest")
    assert (
        "python .github/scripts/full_extraction_handoffs.py "
        "resolve-resume-source-committed-manifest"
    ) in resolver
    assert "OWNER_RECHECK_PATH: ${{ runner.temp }}/workflow-provenance/" in resolver
    assert "artifact-ids: ${{ steps.resume_source_manifest.outputs.artifact_id }}" in (download)
    assert "digest-mismatch: error" in download
    assert 'gh run download "$RESUME_SOURCE_RUN_ID"' not in prepare
    assert 'find "$RUNNER_TEMP/resume-source/manifest-committed"' in prepare
    assert "RESUME_SOURCE_SELECTION_RECEIPT_BUILDER" in prepare
    assert "resume-source-input-manifest.json" in prepare
    assert "resume-source-selection.json" in prepare
    assert "id: plan_manifest_artifact" in upload
    assert "name: ${{ steps.manifest.outputs.plan-artifact-name }}" in upload
    assert "resume-source-input-manifest.json" in upload
    assert "resume-source-selection.json" in upload
    assert "PLAN_MANIFEST_ARTIFACT_RECEIPT_VERIFIER" in plan
    assert (
        "plan-manifest-artifact-id: ${{ steps.plan_manifest_receipt.outputs.artifact_id }}"
    ) in plan
    assert (
        "plan-manifest-artifact-digest: ${{ steps.plan_manifest_receipt.outputs.artifact_digest }}"
    ) in plan
    assert '--output-dir "$RUNNER_TEMP/resume-source/metadata"' in helper
    assert 'metadata_count="$(python -c' in helper
    assert '--receipt-bundle "$metadata_receipts"' in helper
    assert "gh run download" not in prepare


def test_every_plan_generates_and_only_authentically_archives_exact_green_assurance() -> None:
    plan = _job_block(_workflow_text(), "plan")
    helper = _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8")
    fetch = _step_block(plan, "Fetch nba_api upstream docs and tools")
    generate = _step_block(
        plan,
        "Generate deterministic pre-extraction contract assurance",
    )
    build = _step_block(plan, "Build lane manifest")
    finalize = _step_block(plan, "Finalize operation-authority-bound lane manifest")
    upload = _step_block(plan, "Upload lane manifest")

    assert plan.index("Fetch nba_api upstream docs and tools") < plan.index(
        "Generate deterministic pre-extraction contract assurance"
    )
    assert plan.index("Generate deterministic pre-extraction contract assurance") < plan.index(
        "Build lane manifest"
    )
    assert "if:" not in fetch.split("        run:", 1)[0]
    assert "if:" not in generate.split("        env:", 1)[0]
    assert "ENDPOINT_ANALYSIS_DOCS_ROOT: ${{ runner.temp }}/nba_api-upstream" in generate
    assert generate.count("generate_pre_extraction_assurance(") == 2
    assert "expected_semantic_sha256=reference.semantic_sha256" in generate
    assert "validate_assurance_generation(generation.directory)" in generate
    assert "require_production_admissible(generation.admission)" in generate
    assert "admission.source_sha != expected_source_sha" in generate
    assert "generation/assurance-admission.json" in generate
    assert ("python .github/scripts/full_extraction_handoffs.py build-lane-manifest") in build
    assert (
        "ASSURANCE_ADMISSION_PATH: ${{ steps.contract_assurance.outputs.admission-path }}"
    ) in build
    assert (
        "artifacts/contract-assurance/pre-extraction/generation/assurance-admission.json"
        in generate
    )
    assert (
        "ASSURANCE_ADMISSION_PATH: ${{ steps.contract_assurance.outputs.admission-path }}"
    ) in build
    assert '[ ! -f "$ASSURANCE_ADMISSION_PATH" ]' in helper
    assert '[ -L "$ASSURANCE_ADMISSION_PATH" ]' in helper
    assert (
        "CONTRACT_ASSURANCE_ADMISSION_PATH: ${{ steps.contract_assurance.outputs.admission-path }}"
    ) in finalize
    assert "generated_admission != assurance_admission" in finalize
    assert "generated_admission_sha256 != os.environ[" in finalize
    assert '"CONTRACT_ASSURANCE_ADMISSION_SHA256"' in finalize
    assert "artifacts/contract-assurance/pre-extraction/generation/" in upload
    # The authority receipt replaces the retired free-execution admission gate for
    # persistent-storage mutations inside the plan job.
    assert "if: ${{ steps.manifest.outputs.operation-authority-status == 'validated' }}" in upload
    assert "artifacts/full-extraction/operation-authority.json" in upload
    assert "steps.free_execution_collector_state.outputs.status == 'admitted'" not in upload
    assert (
        "assurance-admission-sha256: ${{ steps.manifest.outputs.assurance-admission-sha256 }}"
    ) in plan
    assert "assurance-model-status: ${{ steps.manifest.outputs.assurance-model-status }}" in plan


def test_full_extraction_builds_only_an_exact_capacity_blocked_plan() -> None:
    workflow = _workflow_text()
    guard = _step_block(
        _job_block(workflow, "workflow_guard"),
        "Verify immutable workflow definition",
    )
    plan = _job_block(workflow, "plan")
    helper = _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8")
    collector_state = _step_block(
        plan,
        "Establish fail-closed free-execution collector state",
    )
    collectors = _step_block(
        plan,
        "Record authenticated free-execution collector state",
    )
    operation_authority = _step_block(plan, "Create exact operation authority")
    build = _step_block(plan, "Build lane manifest")
    finalize = _step_block(plan, "Finalize operation-authority-bound lane manifest")
    blocked = _job_block(workflow, "free_execution_blocked")
    workflow_concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]

    # The operation-authority network contract: VPN-only, bounded VPN-to-direct
    # fallback, or free/direct, 0-6 VPN lanes, and 0-6 direct lanes with VPN-only
    # pinned to zero direct capacity and direct-only pinned to zero VPN capacity.
    assert (
        'network_mode:\n        description: "Provider network route: '
        'VPN-only, bounded VPN-to-direct fallback, or free/direct"' in workflow
    )
    assert "default: auto" in workflow
    assert "options:\n          - vpn\n          - auto\n          - direct" in workflow
    assert (
        'direct_parallelism:\n        description: "Bounded direct fallback lanes; '
        'zero for VPN-only operations"' in workflow
    )
    assert 'default: "2"' in workflow
    assert 'options:\n          - "0"' in workflow
    assert '          - "6"' in workflow
    assert "group: nbadb-full-extraction-chain" in workflow_concurrency
    assert "queue:" not in workflow_concurrency
    assert "cancel-in-progress: false" in workflow_concurrency
    assert "operation must be exactly targeted_smoke, extract, or continue" in guard
    assert "VPN/direct parallelism must be within the bounded 0-6/0-6 ranges" in guard
    assert "network_mode=vpn requires direct_parallelism=0" in guard
    assert "network_mode=direct requires vpn_parallelism=0" in guard
    assert "operation=continue requires all five exact resume source inputs" in guard
    assert "resume source inputs require operation=continue" in guard

    assert plan.index("Establish fail-closed free-execution collector state") < plan.index(
        "astral-sh/setup-uv@"
    )
    assert "python3 .github/scripts/attest_free_execution_job.py collect" in collector_state
    assert 'echo "status=capacity_blocked"' not in collector_state
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in collector_state
    assert "enable-cache: false" in plan
    assert "enable-cache: true" not in plan
    assert "prune-cache:" not in plan
    assert "authenticated execution-context" in collectors
    assert "artifacts/full-extraction/operation-authority.json" in operation_authority
    assert "status=validated" in operation_authority
    assert 'handle.write(f"digest={authority.authority_sha256}\\n")' in operation_authority
    assert 'handle.write(f"operation={authority.operation.value}\\n")' in operation_authority
    assert "continuation_source=continuation_source" in operation_authority

    for forbidden in (
        "Legacy free-execution admission experiment",
        "github.event_name != 'workflow_dispatch'",
        "TrustedFreeEligibilityEvidenceV1",
        "FreeExecutionSlotV1",
        "FreeExecutionAdmissionV1.admitted(",
        "authorize_provider_request",
        "plan-free-execution-admission",
        'os.environ["GITHUB_WORKFLOW"]',
        "free-direct-slot-0",
        "github-hosted-standard-direct-slot-0",
        "CommonTeamYearsExtractor",
        "CommonAllPlayersExtractor",
        "LeagueGameLogExtractor",
        "_sync_extract",
    ):
        assert forbidden not in workflow

    # Planning runs only under the exact operation authority; the retired
    # FreeExecution receipt output stays forbidden.
    assert '--operation-authority-path "$OPERATION_AUTHORITY_PATH"' in helper
    assert '--vpn-slot-count "$VPN_PARALLELISM"' in helper
    assert "--free-execution-receipt-output-path" not in helper
    for forbidden_argument in (
        "--free-execution-admission-path",
        "--free-execution-repository",
        "--free-execution-workflow",
        "--free-execution-run-id",
        "--free-execution-job",
    ):
        assert forbidden_argument not in helper
    assert 'effective_matrix_batch_size="$MATRIX_BATCH_SIZE"' in helper
    assert "OPERATION_AUTHORITY_PATH: ${{ steps.operation_authority.outputs.path }}" in build

    upload_conditions = {
        "Upload endpoint coverage diagnostics": (
            "steps.free_execution_collector_state.outputs.status == 'admitted'",
            "steps.free_execution_collector_state.outputs.authenticated == 'true'",
            "inputs.lane_manifest_json == ''",
            "inputs.lane_manifest_run_id == ''",
            "inputs.resume_source_run_id == ''",
        ),
        "Upload dependent workload bundle": (
            "steps.dependent_phase.outputs.compile-required == 'true'",
            "steps.operation_authority.outputs.status == 'validated'",
        ),
        "Upload lane manifest": (
            "steps.manifest.outputs.operation-authority-status == 'validated'",
        ),
        "Verify uploaded lane manifest receipt": (
            "steps.manifest.outputs.operation-authority-status == 'validated'",
        ),
    }
    for step_name, required_conditions in upload_conditions.items():
        mutation_step = _step_block(plan, step_name)
        for condition in required_conditions:
            assert condition in mutation_step, step_name

    upload = _step_block(plan, "Upload lane manifest")
    assert "free-execution-admission.json" not in upload
    assert "manifest operation authority differs from the exact file" in finalize
    assert "manifest operation authority digest differs" in finalize
    assert "authorized manifest must not contain FreeExecution authority" in finalize
    assert "authorized extraction manifest requires a nonempty matrix" in finalize
    assert "operation authority lane count differs from the final matrix" in finalize
    assert "full-extraction plan assurance differs from the current generated admission" in finalize
    assert 'handle.write("operation-authority-status=validated\\n")' in finalize
    assert 'f"operation-authority-sha256={authority.authority_sha256}\\n"' in finalize
    assert "free-execution-admission-status=" not in finalize

    blocked_header = blocked.split("    runs-on:", 1)[0]
    assert "needs.plan.outputs.operation-authority-status != 'validated'" in blocked_header
    assert "free-execution-collector-authenticated != 'true'" in blocked_header
    assert "free-execution-runtime-context-status != 'authenticated'" in blocked_header
    assert "free-execution-mutations-authorized != 'true'" in blocked_header
    assert "operation-authority-status == 'capacity_blocked'" not in blocked_header
    assert "not authentically admitted" in blocked
    assert "exit 1" in blocked


def test_pre_admission_jobs_have_no_unauthorized_external_mutation_surface() -> None:
    workflow_text = _workflow_text()
    workflow = yaml.safe_load(workflow_text)
    workflow_guard_steps = workflow["jobs"]["workflow_guard"]["steps"]
    plan_steps = workflow["jobs"]["plan"]["steps"]

    assert [step.get("uses") for step in workflow_guard_steps if step.get("uses")] == [
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    ]
    assert [step.get("uses") for step in plan_steps if step.get("uses")] == [
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9",
        "actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    ]

    setup_uv = next(
        step for step in plan_steps if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    )
    assert setup_uv["with"]["enable-cache"] is False
    assert "prune-cache" not in setup_uv["with"]

    upload_steps = [
        step
        for step in plan_steps
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert [step["name"] for step in upload_steps] == [
        "Upload endpoint coverage diagnostics",
        "Upload dependent workload bundle",
        "Upload lane manifest",
    ]
    # Each plan-job upload stays fail-closed under the current authority semantics:
    # collector-admitted for the diagnostics bundle, operation-authority-validated for
    # the dependent workload bundle and the final lane manifest.
    upload_conditions = {
        "Upload endpoint coverage diagnostics": (
            "steps.free_execution_collector_state.outputs.status == 'admitted'",
            "steps.free_execution_collector_state.outputs.authenticated == 'true'",
            "inputs.lane_manifest_json == ''",
            "inputs.lane_manifest_run_id == ''",
            "inputs.resume_source_run_id == ''",
        ),
        "Upload dependent workload bundle": (
            "steps.dependent_phase.outputs.compile-required == 'true'",
            "steps.operation_authority.outputs.status == 'validated'",
        ),
        "Upload lane manifest": (
            "steps.manifest.outputs.operation-authority-status == 'validated'",
        ),
    }
    for step in upload_steps:
        condition = str(step.get("if", ""))
        for required in upload_conditions[step["name"]]:
            assert required in condition, step["name"]

    pre_admission_scripts = "\n".join(
        str(step.get("run", "")) for step in workflow_guard_steps + plan_steps
    )
    for forbidden_command in (
        "--method POST",
        "--method PATCH",
        "--method PUT",
        "--method DELETE",
        " -X POST",
        " -X PATCH",
        " -X PUT",
        " -X DELETE",
        "git push",
        "gh workflow run",
        "gh run rerun",
        "gh release",
        "kaggle",
    ):
        assert forbidden_command not in pre_admission_scripts


def test_full_extraction_action_pins_are_full_forty_char_shas() -> None:
    workflow = _workflow_text()
    pins = re.findall(r"(?m)^\s+uses: ([^@\s]+@[0-9a-fA-F]+)", workflow)
    download_artifact = "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
    truncated = [pin for pin in pins if len(pin.rsplit("@", 1)[1]) != 40]
    download_pins = [pin for pin in pins if pin.startswith("actions/download-artifact@")]
    assert pins
    assert truncated == []
    assert download_pins
    assert all(pin == download_artifact for pin in download_pins)


def test_provider_work_and_mutations_are_unreachable_from_blocked_plan() -> None:
    workflow = _workflow_text()
    plan = _job_block(workflow, "plan")
    finalize = _step_block(plan, "Finalize operation-authority-bound lane manifest")
    mutating_jobs = (
        "publication_preflight",
        "preflight",
        "discovery_seed",
        "vpn_capacity",
        "vpn_quarantine",
        "extract",
        "terminal_replay",
        "targeted_smoke_assurance",
        "merge",
        "publish",
        "lane_control",
        "checkpoint",
        "dispatch_next",
    )

    # The validated operation authority replaces the retired free-execution admission
    # status as the gate every provider or mutation job must re-assert.
    assert 'manifest.get("operation_authority") != authority_payload' in finalize
    assert "matrix_rows" in finalize
    assert 'manifest.get("matrix_lane_count") != len(matrix_rows)' in finalize
    for job_name in mutating_jobs:
        header = _job_block(workflow, job_name).split("    runs-on:", 1)[0]
        assert "needs.plan.outputs.operation-authority-status == 'validated'" in header, job_name
        assert "free-execution-collector-status == 'admitted'" in header, job_name
        assert "free-execution-collector-authenticated == 'true'" in header, job_name
        assert "free-execution-runtime-context-status == 'authenticated'" in header, job_name
        assert "free-execution-storage-mutations-allowed == 'true'" in header, job_name
        assert "free-execution-provider-calls-allowed == 'true'" in header, job_name
        assert "free-execution-mutations-authorized == 'true'" in header, job_name

    for job_name, guard_name, provider_step in (
        (
            "discovery_seed",
            "Block discovery provider work until runtime collectors exist",
            "Seed discovery artifacts",
        ),
        (
            "extract",
            "Block extraction provider work until runtime collectors exist",
            "Run extraction",
        ),
        (
            "merge",
            "Block live snapshot provider work until runtime collectors exist",
            "Append live snapshot",
        ),
    ):
        job = _job_block(workflow, job_name)
        guard = _step_block(job, guard_name)
        provider = _step_block(job, provider_step)
        assert job.index(guard_name) < job.index(provider_step)
        assert "attest_free_execution_job.py authorize --output artifacts/" in guard
        assert "attest_free_execution_job.py verify --input artifacts/" in provider
        assert "Authenticated runtime collector integration is not implemented" not in guard
        assert "authorize_provider_request" not in guard
        assert "OPERATION_AUTHORITY_STATUS:" in guard
        assert "needs.plan.outputs.operation-authority-status" in guard
        assert "OPERATION_AUTHORITY_STATUS:" in provider
        assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in guard
        assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in provider


def test_terminal_live_snapshot_cannot_run_from_capacity_blocked_plan() -> None:
    workflow = _workflow_text()
    replay = _job_block(workflow, "terminal_replay")
    merge = _job_block(workflow, "merge")
    live_guard = _step_block(
        merge,
        "Block live snapshot provider work until runtime collectors exist",
    )

    assert (
        "needs.plan.outputs.operation-authority-status == 'validated'"
        in replay.split("    runs-on:", 1)[0]
    )
    assert (
        "needs.plan.outputs.operation-authority-status == 'validated'"
        in merge.split("    runs-on:", 1)[0]
    )
    assert "free-execution-mutations-authorized == 'true'" in replay.split("    runs-on:", 1)[0]
    assert "free-execution-mutations-authorized == 'true'" in merge.split("    runs-on:", 1)[0]
    assert "attest_free_execution_job.py authorize --output artifacts/live-snapshot/" in live_guard
    assert "runtime collector integration is not implemented" not in live_guard.lower()
    assert merge.index("Block live snapshot provider work") < merge.index("Append live snapshot")
    assert 'manifest.get("operation_authority") != authority_payload' in _step_block(
        _job_block(workflow, "plan"),
        "Finalize operation-authority-bound lane manifest",
    )


def test_capacity_blocked_plan_never_reaches_discovery_seed() -> None:
    discovery = _job_block(_workflow_text(), "discovery_seed")
    discovery_header = discovery.split("    steps:\n", 1)[0]

    assert "needs: [plan, preflight]" in discovery_header
    assert "needs.plan.outputs.operation-authority-status == 'validated'" in discovery_header
    assert "needs.plan.outputs.free-execution-mutations-authorized == 'true'" in discovery_header
    assert "needs.plan.outputs.free-execution-provider-calls-allowed == 'true'" in discovery_header
    assert "needs.plan.outputs.matrix-lane-count != '0'" in discovery_header
    assert "needs.preflight.result == 'success'" in discovery_header


def test_successful_plan_missing_or_unknown_admission_status_fails_closeout() -> None:
    workflow = yaml.safe_load(_workflow_text())
    condition = str(workflow["jobs"]["free_execution_blocked"]["if"])

    assert "always()" in condition
    assert "needs.plan.result == 'success'" in condition
    # Any authority or collector state other than the exact validated/admitted set
    # fails closed, including unknown or missing statuses.
    assert "needs.plan.outputs.operation-authority-status != 'validated'" in condition
    assert "operation-authority-status == 'capacity_blocked'" not in condition
    assert "free-execution-collector-status != 'admitted'" in condition
    assert "free-execution-collector-authenticated != 'true'" in condition
    assert "free-execution-runtime-context-status != 'authenticated'" in condition
    assert "free-execution-storage-mutations-allowed != 'true'" in condition
    assert "free-execution-provider-calls-allowed != 'true'" in condition
    assert "free-execution-mutations-authorized != 'true'" in condition


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
    assert "steps.manifest.outputs.operation-authority-status == 'validated'" in manifest_upload
    assert (
        "steps.free_execution_collector_state.outputs.storage-mutations-allowed == 'true'"
        not in manifest_upload
    )
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
    assert "resolve-artifacts-by-prefix" in checkpoint_download
    assert "workflow_source_provenance.py resolve-artifact" in checkpoint_download
    assert "workflow_source_provenance.py download-artifact" in checkpoint_download
    assert "gh run download" not in checkpoint_download
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
    assert '-f "event=workflow_dispatch"' not in dispatch
    assert 'str(run.get("event") or "") == "workflow_dispatch"' in dispatch
    assert dispatch.count('-H "X-GitHub-Api-Version: 2026-03-10"') >= 5
    assert 'str(run.get("display_title") or "") == expected_run_name' in dispatch
    assert 'str(run.get("status") or "") != "completed"' in dispatch
    assert 'not in {"action_required", "cancelled", "failure", "timed_out"}' in dispatch
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
    assert '"return_run_details"' not in dispatch
    assert '"ref": os.environ["WORKFLOW_REF"]' in dispatch
    assert '"inputs": inputs' in dispatch
    assert "set(response) !=" in dispatch
    assert 'raw_child_run_id = response.get("workflow_run_id")' in dispatch
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
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "failure",
        "html_url": "https://example.test/runs/100",
    }
    cancelled_run = {
        "id": 101,
        "display_title": run_name,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "cancelled",
        "html_url": "https://example.test/runs/101",
    }
    non_dispatch_success = {
        "id": 99,
        "display_title": run_name,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://example.test/runs/99",
    }
    runs_path.write_text(
        json.dumps(
            [
                {
                    "total_count": 3,
                    "workflow_runs": [
                        non_dispatch_success,
                        failed_run,
                        cancelled_run,
                    ],
                }
            ]
        ),
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
                    "total_count": 2,
                    "workflow_runs": [
                        {
                            "id": 200,
                            "display_title": run_name,
                            "event": "workflow_dispatch",
                            "status": "in_progress",
                            "conclusion": None,
                            "html_url": "https://example.test/runs/200",
                        },
                        {
                            "id": 201,
                            "display_title": run_name,
                            "event": "workflow_dispatch",
                            "status": "completed",
                            "conclusion": "success",
                            "html_url": "https://example.test/runs/201",
                        },
                    ],
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


@pytest.mark.parametrize(
    ("status", "conclusion", "blocked"),
    [
        ("completed", "action_required", False),
        ("completed", "cancelled", False),
        ("completed", "failure", False),
        ("completed", "timed_out", False),
        ("completed", "success", True),
        ("completed", None, True),
        ("completed", "neutral", True),
        ("completed", "skipped", True),
        ("completed", "stale", True),
        ("completed", "unknown", True),
        ("queued", None, True),
        ("in_progress", None, True),
    ],
)
def test_redispatch_precheck_uses_exact_replaceable_allowlist(
    tmp_path: pathlib.Path,
    status: str,
    conclusion: str | None,
    blocked: bool,
) -> None:
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
                    "total_count": 1,
                    "workflow_runs": [
                        {
                            "id": 200,
                            "display_title": run_name,
                            "event": "workflow_dispatch",
                            "status": status,
                            "conclusion": conclusion,
                            "html_url": "https://example.test/runs/200",
                        }
                    ],
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

    assert result.returncode == 0, result.stderr or result.stdout
    if blocked:
        assert f"200:{status}:{conclusion}" in result.stdout
    else:
        assert result.stdout.strip() == ""


def test_redispatch_precheck_rejects_missing_event(tmp_path: pathlib.Path) -> None:
    precheck = _embedded_python(
        _job_block(_workflow_text(), "dispatch_next"),
        "CHILD_RUN_PRECHECK",
    )
    runs_path = tmp_path / "runs.json"
    existing_ids_path = tmp_path / "existing.json"
    runs_path.write_text(
        json.dumps(
            [
                {
                    "total_count": 1,
                    "workflow_runs": [
                        {
                            "id": 200,
                            "display_title": "Full Extraction chain=123 iteration=2",
                            "status": "completed",
                            "conclusion": "success",
                            "html_url": "https://example.test/runs/200",
                        }
                    ],
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
            "EXPECTED_RUN_NAME": "Full Extraction chain=123 iteration=2",
        },
    )

    assert result.returncode == 1
    assert "inventory entry is malformed" in result.stderr


def test_workflow_concurrency_serializes_the_single_free_direct_slot() -> None:
    workflow = _workflow_text()
    workflow_concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]

    # The whole workflow occupies one explicit non-cancelling chain slot; provider
    # slot serialization moved to the extract job's per-slot concurrency groups.
    assert "group: nbadb-full-extraction-chain" in workflow_concurrency
    assert "inputs.network_mode" not in workflow_concurrency
    assert "inputs.chain_id" not in workflow_concurrency
    assert "github.ref" not in workflow_concurrency
    assert "queue:" not in workflow_concurrency
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
    assert ("python .github/scripts/full_extraction_handoffs.py build-lane-manifest") in build
    assert "LANE_MANIFEST_ARTIFACT_ID: ${{ inputs.lane_manifest_artifact_id }}" in build
    assert "LANE_MANIFEST_ARTIFACT_DIGEST: ${{ inputs.lane_manifest_artifact_digest }}" in build

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


def test_cross_run_boundaries_use_shared_semantic_source_provenance_gate() -> None:
    workflow = _workflow_text()
    handoffs = _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8")
    plan = _job_block(workflow, "plan")
    discovery = _job_block(workflow, "discovery_seed")
    terminal = _job_block(workflow, "terminal_replay")
    checkpoint = _job_block(workflow, "checkpoint")
    helper = "python .github/scripts/workflow_source_provenance.py attest-run"

    exact_handoff = _step_block(plan, "Verify exact input manifest receipt")
    resume_source = _step_block(plan, "Resolve resume source committed manifest")
    dependent_foundation = _step_block(plan, "Attest dependent foundation owner")
    build_manifest = _step_block(plan, "Build lane manifest")
    discovery_source = _step_block(discovery, "Resolve prior discovery artifact receipt")
    terminal_source = _step_block(terminal, "Verify plan-selected resume source receipt")
    previous_source = _step_block(
        checkpoint,
        "Attest previous checkpoint owner provenance",
    )
    for block in (exact_handoff, terminal_source, previous_source):
        assert helper in block
        assert '--source-sha "$WORKFLOW_SOURCE_SHA"' in block
        assert '--trusted-branch "$WORKFLOW_SOURCE_REF"' in block
        assert "--workflow-path .github/workflows/full-extraction.yml" in block

    assert (
        "python .github/scripts/full_extraction_handoffs.py "
        "resolve-resume-source-committed-manifest"
    ) in resume_source
    assert (
        "python .github/scripts/full_extraction_handoffs.py "
        "resolve-prior-discovery-artifact-receipt"
    ) in discovery_source
    assert (
        "python .github/scripts/full_extraction_handoffs.py build-lane-manifest"
    ) in build_manifest
    assert "--required-state active-or-completed" in exact_handoff
    assert "--required-state active-or-completed" in previous_source
    assert "--required-state completed" in dependent_foundation
    assert "--required-state completed" in terminal_source
    assert workflow.count(helper) >= 3
    assert workflow.count("workflow_source_provenance.py recheck-run") >= 3
    for owner_stem in ("lane-manifest", "terminal-source", "previous-checkpoint"):
        assert (
            f'--attestation "$RUNNER_TEMP/workflow-provenance/{owner_stem}-owner.json"' in workflow
        )
        assert (
            f'--output "$RUNNER_TEMP/workflow-provenance/{owner_stem}-owner-recheck.json"'
            in workflow
        )
    for owner_stem in ("resume-source", "discovery-source"):
        assert (
            f'--attestation "$RUNNER_TEMP/workflow-provenance/{owner_stem}-owner.json"' in handoffs
        )
        assert (
            f'--output "$RUNNER_TEMP/workflow-provenance/{owner_stem}-owner-recheck.json"'
            in handoffs
        )

    ci = _CI_PATH.read_text(encoding="utf-8")
    assert ci.count(".github/scripts/workflow_source_provenance.py") == 3
    assert ci.count(".github/scripts/resolve_legacy_manifest_handoff.py") == 3


def test_terminal_manifest_and_replay_use_exact_current_head_receipts() -> None:
    workflow = _workflow_text()
    checkpoint = _job_block(workflow, "checkpoint")
    terminal_replay = _job_block(workflow, "terminal_replay")
    merge = _job_block(workflow, "merge")

    committed_upload = _step_block(checkpoint, "Upload committed next manifest")
    committed_receipt = _step_block(checkpoint, "Verify committed next manifest receipt")
    assert "id: committed_manifest_upload" in committed_upload
    assert checkpoint.index("Upload committed next manifest") < checkpoint.index(
        "Verify committed next manifest receipt"
    )
    assert "workflow_source_provenance.py verify-current-artifact" in committed_receipt
    assert "CURRENT_RUN_HEAD_SHA: ${{ github.sha }}" in committed_receipt
    assert "artifact-size-bytes=" in committed_receipt
    assert "artifact-archive-url=" in committed_receipt
    assert "manifest-artifact-size:" in checkpoint
    assert "manifest-artifact-archive-url:" in checkpoint

    replay_upload = _step_block(terminal_replay, "Upload attested terminal replay inputs")
    replay_receipt = _step_block(terminal_replay, "Verify terminal replay artifact receipt")
    assert "id: replay_upload" in replay_upload
    assert terminal_replay.index("Upload attested terminal replay inputs") < terminal_replay.index(
        "Verify terminal replay artifact receipt"
    )
    assert "workflow_source_provenance.py verify-current-artifact" in replay_receipt
    assert "CURRENT_RUN_HEAD_SHA: ${{ github.sha }}" in replay_receipt
    assert "artifact-id:" in terminal_replay
    assert "artifact-digest:" in terminal_replay
    assert "artifact-size:" in terminal_replay
    assert "artifact-archive-url:" in terminal_replay

    terminal_manifest_verify = _step_block(
        merge,
        "Verify terminal manifest receipt before download",
    )
    terminal_manifest_download = _step_block(
        merge,
        "Download terminal manifest from completed lanes",
    )
    replay_verify = _step_block(merge, "Verify replayed terminal receipt before download")
    replay_download = _step_block(merge, "Download replayed terminal checkpoint")
    assert merge.index("Verify terminal manifest receipt before download") < merge.index(
        "Download terminal manifest from completed lanes"
    )
    assert merge.index("Verify replayed terminal receipt before download") < merge.index(
        "Download replayed terminal checkpoint"
    )
    assert "workflow_source_provenance.py verify-current-artifact" in terminal_manifest_verify
    assert "workflow_source_provenance.py verify-current-artifact" in replay_verify
    assert "artifact-ids: ${{ needs.checkpoint.outputs.manifest-artifact-id }}" in (
        terminal_manifest_download
    )
    assert "artifact-ids: ${{ needs.terminal_replay.outputs.artifact-id }}" in replay_download
    assert "digest-mismatch: error" in terminal_manifest_download
    assert "digest-mismatch: error" in replay_download
    assert "name: ${{ needs.terminal_replay.outputs.artifact-name }}" not in replay_download


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
    workflow_source_sha = "a" * 40
    owner_head_sha = "b" * 40
    artifact_name = "full-extraction-next-manifest-fixture-chain-iter-4-run-12345-attempt-1"
    artifact_digest = "sha256:" + "c" * 64
    owner_run = {
        "conclusion": None,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "id": int(current_run_id),
        "head_sha": owner_head_sha,
        "path": ".github/workflows/full-extraction.yml",
        "repository": {"full_name": "acme/nbadb"},
        "run_attempt": int(current_run_attempt),
        "status": "in_progress",
        "url": (f"https://api.github.test/repos/acme/nbadb/actions/runs/{current_run_id}"),
        "workflow_id": 99,
    }
    artifact = {
        "archive_download_url": (
            f"https://api.github.test/repos/acme/nbadb/actions/artifacts/{artifact_id}/zip"
        ),
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
        "ARTIFACT_ARCHIVE_URL": artifact["archive_download_url"],
        "ARTIFACT_SIZE_BYTES": "4096",
        "CHAIN_ID": chain_id,
        "CURRENT_RUN_ATTEMPT": current_run_attempt,
        "CURRENT_RUN_HEAD_SHA": owner_head_sha,
        "CURRENT_RUN_ID": current_run_id,
        "GITHUB_API_URL": "https://api.github.test",
        "GITHUB_REPOSITORY": "acme/nbadb",
        "ITERATION": iteration,
        "WORKFLOW_SOURCE_SHA": workflow_source_sha,
        "WORKFLOW_SOURCE_REF": "main",
    }

    accepted_dir = tmp_path / "accepted"
    accepted_fixture = _gh_fixture_env(accepted_dir, [owner_run, artifact, owner_run])
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
            "wrong-run",
            {
                "ARTIFACT_NAME": (
                    "full-extraction-next-manifest-fixture-chain-iter-4-run-54321-attempt-1"
                )
            },
            "artifact run does not match",
        ),
        (
            "wrong-iteration",
            {
                "ARTIFACT_NAME": (
                    "full-extraction-next-manifest-fixture-chain-iter-5-run-12345-attempt-1"
                )
            },
            "artifact iteration is not the exact next iteration",
        ),
        (
            "future-attempt",
            {
                "ARTIFACT_NAME": (
                    "full-extraction-next-manifest-fixture-chain-iter-4-run-12345-attempt-3"
                )
            },
            "artifact attempt must be exactly one",
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

    wrong_source_dir = tmp_path / "wrong-source"
    wrong_source_sha = "d" * 40
    wrong_source_fixture = _gh_fixture_env(
        wrong_source_dir,
        [
            {**owner_run, "head_sha": wrong_source_sha},
            {
                **artifact,
                "workflow_run": {
                    "id": int(current_run_id),
                    "head_sha": wrong_source_sha,
                },
            },
        ],
    )
    wrong_source = _run_python(
        verifier,
        env={
            **wrong_source_fixture,
            **base_env,
            "GITHUB_OUTPUT": str(wrong_source_dir / "github-output.txt"),
        },
        cwd=wrong_source_dir,
    )
    assert wrong_source.returncode == 1
    assert "owner run identity is invalid" in wrong_source.stderr

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

    producer_attempt_two_dir = tmp_path / "producer-attempt-two"
    producer_attempt_two_fixture = _gh_fixture_env(
        producer_attempt_two_dir,
        [
            owner_run,
            {
                **artifact,
                "name": ("full-extraction-next-manifest-fixture-chain-iter-4-run-12345-attempt-2"),
            },
        ],
    )
    producer_attempt_two = _run_python(
        verifier,
        env={
            **producer_attempt_two_fixture,
            **base_env,
            "GITHUB_OUTPUT": str(producer_attempt_two_dir / "github-output.txt"),
        },
        cwd=producer_attempt_two_dir,
    )
    assert producer_attempt_two.returncode == 1
    assert "REST identity does not match the immutable upload receipt" in (
        producer_attempt_two.stderr
    )
    assert not (producer_attempt_two_dir / "github-output.txt").exists()

    final_owner_drift_dir = tmp_path / "final-owner-drift"
    final_owner_drift_fixture = _gh_fixture_env(
        final_owner_drift_dir,
        [
            owner_run,
            artifact,
            {**owner_run, "conclusion": "success", "status": "completed"},
        ],
    )
    final_owner_drift = _run_python(
        verifier,
        env={
            **final_owner_drift_fixture,
            **base_env,
            "GITHUB_OUTPUT": str(final_owner_drift_dir / "github-output.txt"),
        },
        cwd=final_owner_drift_dir,
    )
    assert final_owner_drift.returncode == 1
    assert "owner changed after exact artifact selection" in final_owner_drift.stderr
    assert not (final_owner_drift_dir / "github-output.txt").exists()


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
    owner_head_sha = source_sha
    artifact_name = "full-extraction-next-manifest-fixture-chain-iter-3-run-12345-attempt-1"
    digest = "sha256:" + "c" * 64
    valid_artifact = {
        "archive_download_url": (
            f"https://api.github.test/repos/acme/nbadb/actions/artifacts/{artifact_id}/zip"
        ),
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
    owner_run: dict[str, object] = {
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "id": int(run_id),
        "head_sha": owner_head_sha,
        "path": ".github/workflows/full-extraction.yml",
        "repository": {"full_name": "acme/nbadb"},
        "run_attempt": 1,
        "status": "completed",
        "url": f"https://api.github.test/repos/acme/nbadb/actions/runs/{run_id}",
        "workflow_id": 99,
    }
    base_env = {
        "GITHUB_API_URL": "https://api.github.test",
        "GITHUB_REPOSITORY": "acme/nbadb",
        "LANE_MANIFEST_ARTIFACT_DIGEST": digest,
        "LANE_MANIFEST_ARTIFACT_ID": artifact_id,
        "LANE_MANIFEST_ARTIFACT_NAME": artifact_name,
        "LANE_MANIFEST_RUN_ID": run_id,
        "WORKFLOW_SOURCE_SHA": source_sha,
    }

    def run_case(
        name: str,
        artifact: Mapping[str, object],
        *,
        rest_owner: Mapping[str, object] = owner_run,
        rechecked_owner: Mapping[str, object] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        case_dir = tmp_path / name
        case_dir.mkdir(parents=True, exist_ok=True)
        recheck_path = case_dir / "owner-recheck.json"
        recheck_path.write_text(
            json.dumps(
                _owner_recheck_snapshot(
                    rechecked_owner or rest_owner,
                    source_sha=source_sha,
                )
            ),
            encoding="utf-8",
        )
        fixture_env = _gh_fixture_env(case_dir, [rest_owner, artifact, rest_owner])
        return _run_python(
            verifier,
            env={
                **fixture_env,
                **base_env,
                "OWNER_RECHECK_PATH": str(recheck_path),
            },
            cwd=case_dir,
        )

    accepted = run_case("accepted", valid_artifact)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout

    cross_source_dir = tmp_path / "cross-source"
    cross_source_sha = "b" * 40
    cross_source_artifact = {
        **valid_artifact,
        "workflow_run": {
            "id": int(run_id),
            "head_sha": cross_source_sha,
        },
    }
    cross_source_owner = {**owner_run, "head_sha": cross_source_sha}
    cross_source_dir.mkdir(parents=True, exist_ok=True)
    (cross_source_dir / "owner-recheck.json").write_text(
        json.dumps(
            _owner_recheck_snapshot(
                cross_source_owner,
                source_sha=source_sha,
            )
        ),
        encoding="utf-8",
    )
    cross_source_fixture = _gh_fixture_env(
        cross_source_dir,
        [
            cross_source_owner,
            cross_source_artifact,
            cross_source_owner,
        ],
    )
    cross_source = _run_python(
        verifier,
        env={
            **cross_source_fixture,
            **base_env,
            "OWNER_RECHECK_PATH": str(cross_source_dir / "owner-recheck.json"),
        },
        cwd=cross_source_dir,
    )
    assert cross_source.returncode == 0, cross_source.stderr or cross_source.stdout

    rerun = run_case(
        "rerun-after-recheck",
        valid_artifact,
        rest_owner={**owner_run, "run_attempt": 2},
        rechecked_owner=owner_run,
    )
    assert rerun.returncode == 1
    assert "changed after provenance recheck" in rerun.stderr
    rerun_calls = [
        json.loads(line)
        for line in (tmp_path / "rerun-after-recheck" / "gh-calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rerun_calls) == 1
    assert rerun_calls[0][-1].endswith(f"/actions/runs/{run_id}")
    assert all("/artifacts" not in argument for call in rerun_calls for argument in call)

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
    helper = _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8")
    missing_chain_error = (
        "lane_manifest_run_id requires chain_id so workflow concurrency and discovery artifacts "
        "retain the original chain identity"
    )
    assert missing_chain_error in helper
    assert helper.index(missing_chain_error) < helper.index(
        "python .github/scripts/resolve_legacy_manifest_handoff.py resolve"
    )

    verifier = _helper_embedded_python("MANUAL_HANDOFF_CHAIN_VERIFIER")
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

    assert 'manifest["workflow_source_sha"] = os.environ["WORKFLOW_SOURCE_SHA"].lower()' not in (
        helper
    )
    build = _step_block(plan, "Build lane manifest")
    assert ("python .github/scripts/full_extraction_handoffs.py build-lane-manifest") in build
    assert (
        "ASSURANCE_ADMISSION_PATH: ${{ steps.contract_assurance.outputs.admission-path }}"
    ) in build
    lane_control = _job_block(_workflow_text(), "lane_control")
    assert 'payload["workflow_source_sha"] = os.environ["WORKFLOW_SOURCE_SHA"].lower()' not in (
        lane_control
    )
    assert "assurance_admission=manifest.assurance_admission" in lane_control


def test_legacy_manifest_handoff_resolves_exact_owner_bound_artifact(
    tmp_path: pathlib.Path,
) -> None:
    resolver = _LEGACY_MANIFEST_HANDOFF_PATH.read_text(encoding="utf-8")
    source_sha = "a" * 40
    run_id = "12345"
    artifact_name = "full-extraction-manifest-12345"
    artifact = {
        "archive_download_url": (
            "https://api.github.test/repos/acme/nbadb/actions/artifacts/701/zip"
        ),
        "digest": "sha256:" + "c" * 64,
        "expired": False,
        "id": 701,
        "name": artifact_name,
        "size_in_bytes": 4096,
        "workflow_run": {
            "head_sha": source_sha,
            "id": int(run_id),
        },
    }
    owner = {
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": source_sha,
        "id": int(run_id),
        "path": ".github/workflows/full-extraction.yml",
        "repository": {"full_name": "acme/nbadb"},
        "run_attempt": 1,
        "status": "completed",
        "url": f"https://api.github.test/repos/acme/nbadb/actions/runs/{run_id}",
        "workflow_id": 99,
    }

    def run_case(
        name: str,
        responses: list[object],
        *,
        workflow_source_sha: str = source_sha,
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path, pathlib.Path]:
        case_dir = tmp_path / name
        fixture_env = _gh_fixture_env(case_dir, responses)
        receipt_path = case_dir / "receipt.json"
        owner_response = responses[0]
        assert isinstance(owner_response, dict)
        attestation_path = case_dir / "owner-attestation.json"
        attestation_path.write_text(
            json.dumps(
                {
                    "repository": "acme/nbadb",
                    "run": {
                        "attempt": owner_response.get("run_attempt"),
                        "conclusion": owner_response.get("conclusion"),
                        "event": owner_response.get("event"),
                        "head_branch": owner_response.get("head_branch"),
                        "head_sha": owner_response.get("head_sha"),
                        "id": int(run_id),
                        "path": owner_response.get("path"),
                        "status": owner_response.get("status"),
                        "url": owner_response.get("url"),
                        "workflow_id": owner_response.get("workflow_id"),
                    },
                    "schema_version": 1,
                    "semantic_source": {
                        "relation": (
                            "identical"
                            if owner_response.get("head_sha") == workflow_source_sha
                            else "ancestor"
                        ),
                        "sha": workflow_source_sha,
                    },
                    "workflow": {
                        "blob_sha": "c" * 40,
                        "path": ".github/workflows/full-extraction.yml",
                        "sha256": "d" * 64,
                        "size_in_bytes": 10,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = _run_python(
            resolver,
            env={
                **fixture_env,
                "GITHUB_API_URL": "https://api.github.test",
                "GITHUB_REPOSITORY": "acme/nbadb",
                "LANE_MANIFEST_ARTIFACT_NAME": artifact_name,
                "LANE_MANIFEST_RUN_ID": run_id,
                "LEGACY_MANIFEST_HANDOFF_MODE": "resolve",
                "LEGACY_MANIFEST_RECEIPT_POLL_INTERVAL_SECONDS": "0",
                "LEGACY_RECEIPT_PATH": str(receipt_path),
                "OWNER_ATTESTATION_PATH": str(attestation_path),
                "WORKFLOW_SOURCE_SHA": workflow_source_sha,
            },
            cwd=case_dir,
        )
        return result, receipt_path, pathlib.Path(fixture_env["GH_FIXTURE_LOG"])

    snapshot = {"artifacts": [artifact], "total_count": 1}
    accepted, receipt_path, call_log = run_case(
        "accepted",
        [owner, snapshot, snapshot, snapshot, artifact, owner],
    )
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == {
        "archive_download_url": artifact["archive_download_url"],
        "digest": artifact["digest"],
        "expired": False,
        "id": 701,
        "name": artifact_name,
        "size_in_bytes": 4096,
        "workflow_run_id": int(run_id),
        "workflow_run_sha": source_sha,
    }
    calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
    assert len(calls) == 6
    assert all("X-GitHub-Api-Version: 2026-03-10" in call for call in calls)
    assert all("name=full-extraction-manifest-12345" in call[-1] for call in calls[1:4])
    assert calls[-2][-1].endswith("/actions/artifacts/701")
    assert calls[-1][-1].endswith(f"/actions/runs/{run_id}")

    rerun, rerun_receipt, _ = run_case(
        "rerun-attempt-two",
        [{**owner, "run_attempt": 2}],
    )
    assert rerun.returncode == 1
    assert "owner attestation is invalid" in rerun.stderr
    assert not rerun_receipt.exists()

    missing_digest_artifact = {**artifact, "digest": ""}
    missing_digest_snapshot = {
        "artifacts": [missing_digest_artifact],
        "total_count": 1,
    }
    missing_digest, missing_digest_receipt, _ = run_case(
        "missing-digest",
        [owner, missing_digest_snapshot],
    )
    assert missing_digest.returncode == 1
    assert "artifact identity is malformed" in missing_digest.stderr
    assert not missing_digest_receipt.exists()

    cross_source_sha = "b" * 40
    cross_source_artifact = {
        **artifact,
        "workflow_run": {
            "head_sha": cross_source_sha,
            "id": int(run_id),
        },
    }
    cross_source_snapshot = {
        "artifacts": [cross_source_artifact],
        "total_count": 1,
    }
    cross_source, cross_source_receipt, _ = run_case(
        "cross-source",
        [
            {**owner, "head_sha": cross_source_sha},
            cross_source_snapshot,
            cross_source_snapshot,
            cross_source_snapshot,
            cross_source_artifact,
            {**owner, "head_sha": cross_source_sha},
        ],
    )
    assert cross_source.returncode == 0, cross_source.stderr or cross_source.stdout
    assert (
        json.loads(cross_source_receipt.read_text(encoding="utf-8"))["workflow_run_sha"]
        == cross_source_sha
    )

    numeric_expiry_artifact = {**artifact, "expired": 0}
    numeric_expiry_snapshot = {
        "artifacts": [numeric_expiry_artifact],
        "total_count": 1,
    }
    numeric_expiry, numeric_expiry_receipt, _ = run_case(
        "numeric-expiry",
        [owner, numeric_expiry_snapshot],
    )
    assert numeric_expiry.returncode == 1
    assert "artifact identity is malformed" in numeric_expiry.stderr
    assert not numeric_expiry_receipt.exists()

    ambiguous_snapshot = {
        "artifacts": [
            artifact,
            {
                **artifact,
                "archive_download_url": (
                    "https://api.github.test/repos/acme/nbadb/actions/artifacts/702/zip"
                ),
                "digest": "sha256:" + "d" * 64,
                "id": 702,
            },
        ],
        "total_count": 2,
    }
    ambiguous, ambiguous_receipt, _ = run_case(
        "ambiguous",
        [owner, ambiguous_snapshot, ambiguous_snapshot, ambiguous_snapshot],
    )
    assert ambiguous.returncode == 1
    assert "artifact name is absent or ambiguous" in ambiguous.stderr
    assert not ambiguous_receipt.exists()

    direct_drift, direct_drift_receipt, _ = run_case(
        "direct-drift",
        [
            owner,
            snapshot,
            snapshot,
            snapshot,
            {**artifact, "size_in_bytes": 4097},
            owner,
        ],
    )
    assert direct_drift.returncode == 1
    assert "artifact changed before exact-ID download" in direct_drift.stderr
    assert not direct_drift_receipt.exists()

    many_artifacts = [
        {
            **artifact,
            "archive_download_url": (
                f"https://api.github.test/repos/acme/nbadb/actions/artifacts/{artifact_id}/zip"
            ),
            "digest": f"sha256:{artifact_id:064x}",
            "id": artifact_id,
        }
        for artifact_id in range(701, 802)
    ]
    first_page = {"artifacts": many_artifacts[:100], "total_count": 101}
    second_page = {"artifacts": many_artifacts[100:], "total_count": 101}
    paginated, paginated_receipt, paginated_log = run_case(
        "paginated",
        [owner, first_page, second_page, first_page, second_page, first_page, second_page],
    )
    assert paginated.returncode == 1
    assert "artifact name is absent or ambiguous" in paginated.stderr
    assert not paginated_receipt.exists()
    paginated_calls = [
        json.loads(line) for line in paginated_log.read_text(encoding="utf-8").splitlines()
    ]
    assert len(paginated_calls) == 7
    assert sum("page=2" in call[-1] for call in paginated_calls) == 3


def test_legacy_manifest_archive_extraction_is_digest_and_layout_bound(
    tmp_path: pathlib.Path,
) -> None:
    extractor = _LEGACY_MANIFEST_HANDOFF_PATH.read_text(encoding="utf-8")

    def run_case(
        name: str,
        members: dict[str, bytes],
        *,
        digest_override: str | None = None,
        size_override: int | None = None,
        special_name: str | None = None,
        symlink_name: str | None = None,
        artifact_name: str = "full-extraction-manifest-12345",
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path]:
        case_dir = tmp_path / name
        case_dir.mkdir()
        archive_path = case_dir / "manifest.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            for member_name, body in members.items():
                archive.writestr(member_name, body)
            if symlink_name is not None:
                member = zipfile.ZipInfo(symlink_name)
                member.external_attr = 0o120777 << 16
                archive.writestr(member, "manifest.json")
            if special_name is not None:
                member = zipfile.ZipInfo(special_name)
                member.external_attr = (stat.S_IFIFO | 0o644) << 16
                archive.writestr(member, b"")
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        receipt_path = case_dir / "receipt.json"
        receipt_path.write_text(
            json.dumps(
                {
                    "digest": digest_override or f"sha256:{digest}",
                    "name": artifact_name,
                    "size_in_bytes": (
                        archive_path.stat().st_size if size_override is None else size_override
                    ),
                }
            ),
            encoding="utf-8",
        )
        output_dir = case_dir / "output"
        output_dir.mkdir()
        result = _run_python(
            extractor,
            env={
                "LEGACY_ARCHIVE_PATH": str(archive_path),
                "LEGACY_MANIFEST_HANDOFF_MODE": "extract",
                "LEGACY_OUTPUT_DIR": str(output_dir),
                "LEGACY_RECEIPT_PATH": str(receipt_path),
            },
            cwd=case_dir,
        )
        return result, output_dir

    accepted, accepted_output = run_case(
        "accepted",
        {"nested/manifest.json": b'{"chain_id":"12345"}\n'},
    )
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    assert (accepted_output / "manifest.json").read_bytes() == (b'{"chain_id":"12345"}\n')

    ambiguous, ambiguous_output = run_case(
        "ambiguous",
        {
            "manifest.json": b"{}\n",
            "nested/manifest.json": b"{}\n",
        },
    )
    assert ambiguous.returncode == 1
    assert "exactly one manifest" in ambiguous.stderr
    assert not list(ambiguous_output.iterdir())

    unsafe, unsafe_output = run_case(
        "unsafe",
        {"manifest.json": b"{}\n"},
        symlink_name="nested/link",
    )
    assert unsafe.returncode == 1
    assert "unsafe member" in unsafe.stderr
    assert not list(unsafe_output.iterdir())

    traversal, traversal_output = run_case(
        "traversal",
        {
            "../manifest.json": b"{}\n",
        },
    )
    assert traversal.returncode == 1
    assert "unsafe member" in traversal.stderr
    assert not list(traversal_output.iterdir())

    special, special_output = run_case(
        "special",
        {"manifest.json": b"{}\n"},
        special_name="nested/fifo",
    )
    assert special.returncode == 1
    assert "unsafe member" in special.stderr
    assert not list(special_output.iterdir())

    special_directory, special_directory_output = run_case(
        "special-directory",
        {"manifest.json": b"{}\n"},
        special_name="nested/fifo/",
    )
    assert special_directory.returncode == 1
    assert "unsafe member" in special_directory.stderr
    assert not list(special_directory_output.iterdir())

    digest_mismatch, digest_mismatch_output = run_case(
        "digest-mismatch",
        {"manifest.json": b"{}\n"},
        digest_override="sha256:" + "0" * 64,
    )
    assert digest_mismatch.returncode == 1
    assert "archive digest does not match REST identity" in digest_mismatch.stderr
    assert not list(digest_mismatch_output.iterdir())

    size_mismatch, size_mismatch_output = run_case(
        "size-mismatch",
        {"manifest.json": b"{}\n"},
        size_override=1,
    )
    assert size_mismatch.returncode == 1
    assert "archive receipt is invalid" in size_mismatch.stderr
    assert not list(size_mismatch_output.iterdir())

    empty, empty_output = run_case("empty", {})
    assert empty.returncode == 1
    assert "archive is empty" in empty.stderr
    assert not list(empty_output.iterdir())

    backslash, backslash_output = run_case(
        "backslash",
        {"manifest.json": b"{}\n", "nested\\member": b"unsafe"},
    )
    assert backslash.returncode == 1
    assert "unsafe member" in backslash.stderr
    assert not list(backslash_output.iterdir())

    normalized_duplicate, normalized_duplicate_output = run_case(
        "normalized-duplicate",
        {
            "manifest.json": b"{}\n",
            "nested/member": b"first",
            "nested//member": b"second",
        },
    )
    assert normalized_duplicate.returncode == 1
    assert "unsafe member" in normalized_duplicate.stderr
    assert not list(normalized_duplicate_output.iterdir())

    file_parent, file_parent_output = run_case(
        "file-parent",
        {
            "manifest.json": b"{}\n",
            "nested": b"file",
            "nested/member": b"child",
        },
    )
    assert file_parent.returncode == 1
    assert "file-parent collision" in file_parent.stderr
    assert not list(file_parent_output.iterdir())

    wrong_member, wrong_member_output = run_case(
        "wrong-member",
        {"manifest.json": b"{}\n"},
        artifact_name=("full-extraction-next-manifest-12345-iter-2-run-98765-attempt-1"),
    )
    assert wrong_member.returncode == 1
    assert "exactly one manifest" in wrong_member.stderr
    assert not list(wrong_member_output.iterdir())


def test_resume_source_prefers_exact_committed_manifest_and_falls_back_only_when_absent(
    tmp_path: pathlib.Path,
) -> None:
    resolver = _helper_embedded_python("RESUME_SOURCE_COMMITTED_MANIFEST_RESOLVER")
    chain_id = "12345"
    source_run_id = "987654"
    owner_head_sha = "a" * 40
    exact_name = "full-extraction-next-manifest-12345-iter-3-run-987654-attempt-1"
    canonical_name = f"full-extraction-manifest-{chain_id}"
    owner_run: dict[str, object] = {
        "conclusion": "failure",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "id": int(source_run_id),
        "head_sha": owner_head_sha,
        "path": ".github/workflows/full-extraction.yml",
        "repository": {"full_name": "acme/nbadb"},
        "run_attempt": 1,
        "status": "completed",
        "url": (f"https://api.github.test/repos/acme/nbadb/actions/runs/{source_run_id}"),
        "workflow_id": 99,
    }

    def manifest_artifact(
        artifact_id: int,
        name: str,
        *,
        source_sha: str = owner_head_sha,
    ) -> dict[str, object]:
        return {
            "archive_download_url": (
                f"https://api.github.test/repos/acme/nbadb/actions/artifacts/{artifact_id}/zip"
            ),
            "digest": "sha256:" + f"{artifact_id:064x}",
            "expired": False,
            "id": artifact_id,
            "name": name,
            "size_in_bytes": 4096,
            "workflow_run": {
                "id": int(source_run_id),
                "head_sha": source_sha,
            },
        }

    exact_artifact = manifest_artifact(701, exact_name)
    canonical_artifact = manifest_artifact(600, canonical_name)

    def run_case(
        name: str,
        artifacts: list[dict[str, object]],
        *,
        direct_artifact: dict[str, object] | None = None,
        inventory_observations: list[object] | None = None,
        owner: dict[str, object] = owner_run,
        rechecked_owner: dict[str, object] | None = None,
        workflow_source_sha: str = owner_head_sha,
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path]:
        case_dir = tmp_path / name
        case_dir.mkdir(parents=True, exist_ok=True)
        snapshot = [
            {
                "total_count": len(artifacts),
                "artifacts": artifacts,
            }
        ]
        if direct_artifact is None:
            committed_candidates = [
                (int(match.group("attempt")), artifact)
                for artifact in artifacts
                if (
                    match := re.fullmatch(
                        (
                            r"full-extraction-next-manifest-12345-iter-[1-9][0-9]*-"
                            r"run-987654-attempt-(?P<attempt>[1-9][0-9]*)"
                        ),
                        str(artifact.get("name") or ""),
                    )
                )
                is not None
            ]
            direct_artifact = (
                max(committed_candidates, key=lambda candidate: candidate[0])[1]
                if committed_candidates
                else next(
                    (artifact for artifact in artifacts if artifact.get("name") == canonical_name),
                    artifacts[0] if artifacts else {},
                )
            )
        recheck_path = case_dir / "owner-recheck.json"
        recheck_path.write_text(
            json.dumps(
                _owner_recheck_snapshot(
                    rechecked_owner or owner,
                    source_sha=workflow_source_sha,
                )
            ),
            encoding="utf-8",
        )
        fixture_env = _gh_fixture_env(
            case_dir,
            [
                owner,
                *(inventory_observations or [snapshot, snapshot, snapshot]),
                direct_artifact,
                owner,
            ],
        )
        output_path = case_dir / "github-output.txt"
        result = _run_python(
            resolver,
            env={
                **fixture_env,
                "CHAIN_ID": chain_id,
                "GITHUB_API_URL": "https://api.github.test",
                "GITHUB_OUTPUT": str(output_path),
                "GITHUB_REPOSITORY": "acme/nbadb",
                "RESUME_SOURCE_RUN_ID": source_run_id,
                "RESUME_MANIFEST_RECEIPT_POLL_INTERVAL_SECONDS": "0",
                "OWNER_RECHECK_PATH": str(recheck_path),
                "WORKFLOW_SOURCE_SHA": workflow_source_sha,
            },
            cwd=case_dir,
        )
        return result, output_path

    committed, committed_output = run_case(
        "committed",
        [
            canonical_artifact,
            exact_artifact,
        ],
    )
    assert committed.returncode == 0, committed.stderr or committed.stdout
    assert committed_output.read_text(encoding="utf-8").splitlines() == [
        "resolution=committed",
        f"artifact_name={exact_name}",
        "artifact_id=701",
        f"artifact_digest={exact_artifact['digest']}",
        "artifact_size_bytes=4096",
        f"artifact_archive_url={exact_artifact['archive_download_url']}",
        f"source_run_id={source_run_id}",
        f"source_run_head_sha={owner_head_sha}",
        "source_run_attempt=1",
        "source_run_status=completed",
        "source_run_conclusion=failure",
        "source_workflow_id=99",
    ]

    future_artifact = manifest_artifact(
        700,
        "full-extraction-next-manifest-12345-iter-3-run-987654-attempt-2",
    )
    future_attempt, future_output = run_case("future-attempt", [future_artifact])
    assert future_attempt.returncode == 1
    assert "attempt exceeds the owner run attempt" in future_attempt.stderr
    assert not future_output.exists()

    fallback, fallback_output = run_case("fallback", [canonical_artifact])
    assert fallback.returncode == 0, fallback.stderr or fallback.stdout
    assert fallback_output.read_text(encoding="utf-8").splitlines() == [
        "resolution=canonical",
        f"artifact_name={canonical_name}",
        "artifact_id=600",
        f"artifact_digest={canonical_artifact['digest']}",
        "artifact_size_bytes=4096",
        f"artifact_archive_url={canonical_artifact['archive_download_url']}",
        f"source_run_id={source_run_id}",
        f"source_run_head_sha={owner_head_sha}",
        "source_run_attempt=1",
        "source_run_status=completed",
        "source_run_conclusion=failure",
        "source_workflow_id=99",
    ]

    ambiguous, ambiguous_output = run_case(
        "ambiguous",
        [exact_artifact, manifest_artifact(702, exact_name)],
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
    assert "artifact REST identity is malformed" in wrong_provenance.stderr
    assert not wrong_output.exists()

    numeric_expiry, numeric_expiry_output = run_case(
        "numeric-expiry",
        [{**exact_artifact, "expired": 0}],
    )
    assert numeric_expiry.returncode == 1
    assert "artifact REST identity is malformed" in numeric_expiry.stderr
    assert not numeric_expiry_output.exists()

    cross_source_sha = "b" * 40
    cross_source_owner = {**owner_run, "head_sha": cross_source_sha}
    cross_source_artifact = manifest_artifact(
        701,
        exact_name,
        source_sha=cross_source_sha,
    )
    cross_source, cross_source_output = run_case(
        "cross-source",
        [cross_source_artifact],
        owner=cross_source_owner,
        workflow_source_sha=owner_head_sha,
    )
    assert cross_source.returncode == 0, cross_source.stderr or cross_source.stdout
    assert f"source_run_head_sha={cross_source_sha}" in cross_source_output.read_text(
        encoding="utf-8"
    )

    rerun, rerun_output = run_case(
        "rerun-after-recheck",
        [exact_artifact],
        owner={**owner_run, "run_attempt": 2},
        rechecked_owner=owner_run,
    )
    assert rerun.returncode == 1
    assert "changed after provenance recheck" in rerun.stderr
    assert not rerun_output.exists()
    rerun_calls = [
        json.loads(line)
        for line in (tmp_path / "rerun-after-recheck" / "gh-calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rerun_calls) == 1
    assert rerun_calls[0][-1].endswith(f"/actions/runs/{source_run_id}")
    assert all("/artifacts" not in argument for call in rerun_calls for argument in call)

    stable_snapshot = [{"total_count": 1, "artifacts": [exact_artifact]}]
    mutated_snapshot = [{"total_count": 1, "artifacts": [canonical_artifact]}]
    unstable, unstable_output = run_case(
        "unstable",
        [exact_artifact],
        inventory_observations=[
            stable_snapshot,
            stable_snapshot,
            mutated_snapshot,
        ],
    )
    assert unstable.returncode == 1
    assert "did not stabilize" in unstable.stderr
    assert not unstable_output.exists()

    changed_direct = {**exact_artifact, "size_in_bytes": 8192}
    rechecked, rechecked_output = run_case(
        "direct-recheck",
        [exact_artifact],
        direct_artifact=changed_direct,
    )
    assert rechecked.returncode == 1
    assert "changed before exact-ID download" in rechecked.stderr
    assert not rechecked_output.exists()


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
        "RESUME_SOURCE_MANIFEST_RESOLUTION": "canonical",
        "SOURCE_ARTIFACT_NAME": "full-extraction-manifest-12345",
        "SOURCE_RUN_HEAD_SHA": source_sha,
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


def test_resume_source_selection_receipt_binds_exact_member_bytes(
    tmp_path: pathlib.Path,
) -> None:
    plan = _job_block(_workflow_text(), "plan")
    builder = _embedded_python(plan, "RESUME_SOURCE_SELECTION_RECEIPT_BUILDER")
    source_sha = "a" * 40
    source_path = tmp_path / "resume-source-input-manifest.json"
    source_path.write_text(
        json.dumps(
            {
                "chain_id": "12345",
                "workflow_source_sha": source_sha,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "resume-source-selection.json"
    artifact_id = 701
    archive_url = "https://api.github.test/repos/acme/nbadb/actions/artifacts/701/zip"
    result = _run_python(
        builder,
        env={
            "GITHUB_API_URL": "https://api.github.test",
            "GITHUB_REPOSITORY": "acme/nbadb",
            "REQUESTED_CHAIN_ID": "12345",
            "RESUME_SOURCE_ARTIFACT_ARCHIVE_URL": archive_url,
            "RESUME_SOURCE_ARTIFACT_DIGEST": "sha256:" + "b" * 64,
            "RESUME_SOURCE_ARTIFACT_ID": str(artifact_id),
            "RESUME_SOURCE_ARTIFACT_SIZE": "4096",
            "RESUME_SOURCE_MANIFEST_ARTIFACT_NAME": (
                "full-extraction-next-manifest-12345-iter-3-run-987654-attempt-1"
            ),
            "RESUME_SOURCE_MANIFEST_RESOLUTION": "committed",
            "RESUME_SOURCE_RUN_ATTEMPT": "2",
            "RESUME_SOURCE_RUN_CONCLUSION": "failure",
            "RESUME_SOURCE_RUN_HEAD_SHA": source_sha,
            "RESUME_SOURCE_RUN_ID": "987654",
            "RESUME_SOURCE_RUN_STATUS": "completed",
            "RESUME_SOURCE_WORKFLOW_ID": "99",
            "SELECTION_RECEIPT_PATH": str(receipt_path),
            "SOURCE_MANIFEST_PATH": str(source_path),
            "WORKFLOW_SOURCE_SHA": source_sha,
        },
    )
    assert result.returncode == 0, result.stderr or result.stdout
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert set(receipt) == {
        "member",
        "resolution",
        "schema_version",
        "source_artifact",
        "source_run",
    }
    assert receipt["schema_version"] == 1
    assert receipt["resolution"] == "committed"
    assert receipt["source_artifact"]["id"] == artifact_id
    assert receipt["source_artifact"]["archive_download_url"] == archive_url
    assert receipt["member"] == {
        "bundled_name": "resume-source-input-manifest.json",
        "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "size_in_bytes": len(source_path.read_bytes()),
        "source_name": "next-manifest.json",
    }


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
        "dependent_activation_required=false",
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
    builder = _helper_embedded_python("RESUME_SOURCE_PENDING_CONTRACT_BLOCKED_EVIDENCE")
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
    final_manifest = manifest_payload(
        [],
        assurance_admission=_assurance_admission(),
        chain_id="fixture-chain",
        max_matrix_lanes=1,
    )
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
        json.dumps(
            manifest_payload(
                [],
                assurance_admission=_assurance_admission(),
                chain_id="fixture-chain",
                max_matrix_lanes=1,
            )
        ),
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
    empty_manifest = manifest_payload(
        [],
        assurance_admission=_assurance_admission(),
        chain_id="fixture-chain",
        max_matrix_lanes=1,
    )
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
    provider_authority = expected_nba_api_provider_authority()
    verified_path.write_text(
        json.dumps(
            {
                "artifact_name": "checkpoint",
                "checkpoint_generation": 3,
                "coverage_fingerprint": coverage,
                "database_sha256": "d" * 64,
                "provider_authority": provider_authority,
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
        "provider_authority": provider_authority,
        "provider_authority_sha256": provider_authority["authority_sha256"],
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
    assert identity["provider_authority"] == provider_authority
    assert identity["provider_authority_sha256"] == provider_authority["authority_sha256"]

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


def test_only_dispatch_and_metadata_closeout_jobs_have_actions_write_permission() -> None:
    workflow = _workflow_text()

    for job_name in (
        "extract",
        "terminal_replay",
        "merge",
        "lane_control",
        "checkpoint",
    ):
        job = _job_block(workflow, job_name)
        assert "permissions:\n      actions: read" in job
        assert "actions: write" not in job

    publication_preflight = _job_block(workflow, "publication_preflight")
    assert "permissions:\n      actions: read\n      contents: read" in publication_preflight
    assert "contents: write" not in publication_preflight
    assert "actions: write" not in publication_preflight

    publish = _job_block(workflow, "publish")
    assert "permissions:\n      actions: write" in publish
    assert "contents: write" in publish
    assert "deployments: write" in publish

    dispatch = _job_block(workflow, "dispatch_next")
    assert "permissions:\n      actions: write" in dispatch
    assert workflow.count("actions: write") == 2


def test_publish_false_keeps_terminal_assurance_and_blocks_publication() -> None:
    workflow = _workflow_text()
    workflow_yaml = yaml.safe_load(workflow)
    merge = _job_block(workflow, "merge")
    publish = _job_block(workflow, "publish")
    dispatch = _job_block(workflow, "dispatch_next")
    dispatch_inputs = workflow_yaml[True]["workflow_dispatch"]["inputs"]

    # Publication is not an input of this workflow at all: inputs.operation selects
    # targeted_smoke/extract/continue and publication is delegated to the exact
    # handoff publication workflow.
    assert "publish" not in dispatch_inputs
    assert "targeted_smoke" not in dispatch_inputs
    assert [dispatch_inputs["operation"]["options"]] == [["targeted_smoke", "extract", "continue"]]
    assert dispatch_inputs["operation"]["default"] == "extract"
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
    assert "if:" not in canary_summary
    assert "**Publish requested:** false" in canary_summary
    assert "Metadata commit/push: skipped." in canary_summary
    assert "Kaggle upload: skipped." in canary_summary
    assert "contents: read" in merge
    assert "contents: write" not in merge
    assert "secrets.KAGGLE_USERNAME" not in merge
    assert "secrets.KAGGLE_KEY" not in merge
    assert "kaggle-publication-state" not in merge
    assert "refresh-metadata" not in merge

    # The in-workflow publish job stays structurally disabled until the handoff
    # publication workflow owns publication.
    assert "needs: [plan, publication_preflight, merge]" in publish
    assert "if: ${{ false && " in publish
    assert "needs.plan.outputs.operation-authority-status == 'validated'" in publish
    assert "needs.publication_preflight.result == 'success'" in publish
    assert "needs.merge.result == 'success'" in publish
    assert "contents: write" in publish
    assert "Refresh checked-in metadata" in publish
    assert "Upload to Kaggle" in publish
    assert "PUBLISH: ${{ false }}" in dispatch
    assert 'if [ "$PUBLISH" = "true" ]; then' in dispatch
    assert "publish=true requires pinned workflow_sha" in dispatch


def test_terminal_hard_scan_runs_after_export_and_before_assured_manifest() -> None:
    merge = _job_block(_workflow_text(), "merge")

    export_index = merge.index("- name: Export all formats")
    scan_index = merge.index("- name: Scan data quality")
    manifest_index = merge.index("- name: Build assured data manifest")
    upload_index = merge.index("- name: Upload assured final data artifact")

    assert export_index < scan_index < manifest_index < upload_index


def test_targeted_smoke_is_capacity_blocked_before_checkpoint_assurance() -> None:
    workflow = _workflow_text()
    guard = _job_block(workflow, "workflow_guard")
    plan = _job_block(workflow, "plan")
    plan_gate = _step_block(plan, "Validate targeted smoke plan")
    smoke = _job_block(workflow, "targeted_smoke_assurance")
    merge = _job_block(workflow, "merge")
    dispatch = _job_block(workflow, "dispatch_next")

    # targeted_smoke is an exact operation choice, not a boolean input, and stays
    # free/direct with exactly one lane and one iteration.
    assert "targeted_smoke requires free/direct-only 0/1 lane capacity" in guard
    assert "targeted_smoke requires exactly one lane and one iteration" in guard
    assert "targeted_smoke forbids retry_pipeline_failures" in guard
    assert "targeted_smoke requires an inline or artifact-backed manual lane manifest" in guard
    handoffs = _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8")
    assert "INLINE_MANIFEST_ADMISSION_REBIND" in handoffs

    assert "if: ${{ inputs.operation == 'targeted_smoke' }}" in plan_gate
    assert 'if [ "$LANE_COUNT" != "1" ]' in plan_gate
    assert '[ "$ACTIVE_LANE_COUNT" != "1" ]' in plan_gate
    assert '[ "$MATRIX_LANE_COUNT" != "1" ]' in plan_gate
    assert '[ "$DEFERRED_LANE_COUNT" != "0" ]' in plan_gate
    assert '[ "$VPN_SLOT_COUNT" != "0" ]' in plan_gate
    assert '[ "$OPERATION_AUTHORITY_STATUS" != "validated" ]' in plan_gate
    assert "Targeted smoke must execute one exact free/direct lane" in plan_gate
    assert plan.index("Validate targeted smoke plan") < plan.index("Upload lane manifest")

    assert "if: ${{ always() && !cancelled() && inputs.operation == 'targeted_smoke' &&" in smoke
    assert (
        "needs.plan.outputs.operation-authority-status == 'validated'"
        in smoke.split("    runs-on:", 1)[0]
    )
    assert "free-execution-mutations-authorized == 'true'" in smoke.split("    runs-on:", 1)[0]
    assert "needs: [plan, preflight, discovery_seed, extract, lane_control, checkpoint]" in smoke
    assert 'if [ "$LANE_COUNT" != "1" ] || [ "$MATRIX_LANE_COUNT" != "1" ]; then' in smoke
    assert 'if [ "$ACTIVE_LANE_COUNT" != "0" ]' in smoke
    assert 'if [ "$RESUME_ONLY_LANE_COUNT" != "1" ]' in smoke
    assert 'if [ "$CHECKPOINT_TERMINAL_READY" != "true" ]; then' in smoke
    assert "inputs.operation != 'targeted_smoke'" in merge.split("    runs-on:", 1)[0]
    assert "inputs.operation != 'targeted_smoke'" in dispatch.split("    runs-on:", 1)[0]


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
    assert (
        "restore-keys: |\n            nbadb-kaggle-publication-state-${{ github.run_id }}-"
    ) in restore

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


def test_metadata_closeout_dispatches_and_verifies_exact_head_ci() -> None:
    publish = _job_block(_workflow_text(), "publish")
    resolver = _step_block(publish, "Resolve checked-in metadata head")
    dispatch = _step_block(publish, "Dispatch exact metadata-head CI")
    closeout = _step_block(publish, "Verify exact metadata-head CI closeout")
    receipt = _step_block(publish, "Upload metadata closeout receipt")

    assert "actions: write" in publish
    assert "METADATA_HEAD_EVIDENCE_BUILDER" in resolver
    assert "MetadataHeadEvidence" in resolver
    assert "metadata-head-evidence.json" in resolver
    assert "commit_row != [metadata_head_sha, source_sha]" in resolver
    assert 'changed_files != ("dataset-metadata.json",)' in resolver
    assert 'subject != "chore: regenerate dataset-metadata.json"' in resolver
    assert "observed == expected_metadata.read_bytes()" in resolver

    assert "METADATA_CI_DISPATCH_RECEIPT_VERIFIER" in dispatch
    assert 'API_VERSION = "2026-03-10"' in dispatch
    assert 'dispatch_payload = {"ref": os.environ["DEFAULT_BRANCH"], "inputs": {}}' in dispatch
    assert "return_run_details" not in dispatch
    assert 'set(response) != {"workflow_run_id", "run_url", "html_url"}' in dispatch
    assert 'f"/repos/{repository}/actions/runs/{run_id}"' in dispatch
    assert 'run.get("head_sha") != metadata_head_sha' in dispatch
    assert 'run.get("event") != "workflow_dispatch"' in dispatch
    assert 'run.get("run_attempt") != 1' in dispatch
    assert "CIDispatchReceipt" in dispatch

    assert "METADATA_CI_CLOSEOUT_VERIFIER" in closeout
    assert "REQUIRED_METADATA_CI_JOBS" in closeout
    assert "/attempts/1/jobs" in closeout
    assert "?per_page=100&page={page}" in closeout
    assert 'f"/repos/{repository}/actions/jobs/{job_id}"' in closeout
    assert 'direct.get("run_id") != run_id' in closeout
    assert 'direct.get("head_sha") != head.metadata_head_sha' in closeout
    assert 'direct.get("head_branch") != default_branch' in closeout
    assert "run_attempt=1" in closeout
    assert 'direct.get("run_attempt")' not in closeout
    assert 'run.get("status") == "completed" and required_jobs_completed' in closeout
    assert "validate_metadata_head(head, dispatch=dispatch, ci_run=ci_run)" in closeout
    assert 'f"/repos/{repository}/git/ref/heads/{encoded_branch}"' in closeout
    assert "default branch no longer equals the validated metadata head" in closeout
    for name in ("workflow-lint", "lint", "metadata", "typecheck", "docs", "test"):
        assert name in _CI_PATH.read_text(encoding="utf-8")

    assert "if: always()" in receipt
    assert "artifacts/publication/" in receipt
    assert "github.run_id" in receipt
    assert "github.run_attempt" in receipt
    assert publish.index("Refresh checked-in metadata") < publish.index(
        "Resolve checked-in metadata head"
    )
    assert publish.index("Resolve checked-in metadata head") < publish.index(
        "Dispatch exact metadata-head CI"
    )
    assert publish.index("Dispatch exact metadata-head CI") < publish.index(
        "Verify exact metadata-head CI closeout"
    )


def test_metadata_closeout_verifier_accepts_unchanged_source_without_ci(
    tmp_path: pathlib.Path,
) -> None:
    closeout = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Verify exact metadata-head CI closeout",
    )
    verifier = _embedded_python(closeout, "METADATA_CI_CLOSEOUT_VERIFIER")
    source_sha = "a" * 40
    evidence_dir = tmp_path / "artifacts" / "publication"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "metadata-head-evidence.json").write_text(
        json.dumps(
            {
                "repository": "acme/nbadb",
                "source_sha": source_sha,
                "metadata_head_sha": source_sha,
                "parent_shas": [],
                "changed_files": [],
                "byte_reproducible": True,
            }
        ),
        encoding="utf-8",
    )
    api_url = "https://api.github.test"
    fixture_env = _gh_fixture_env(
        tmp_path,
        [
            {
                "ref": "refs/heads/main",
                "url": f"{api_url}/repos/acme/nbadb/git/refs/heads/main",
                "object": {"type": "commit", "sha": source_sha},
            }
        ],
    )

    result = _run_python(
        verifier,
        cwd=tmp_path,
        env={
            **fixture_env,
            "CI_RUN_ID": "",
            "DEFAULT_BRANCH": "main",
            "GITHUB_API_URL": api_url,
            "GITHUB_SERVER_URL": "https://github.test",
            "METADATA_CI_MAX_POLLS": "1",
            "METADATA_CI_POLL_INTERVAL_SECONDS": "0",
            "METADATA_HEAD_SHA": source_sha,
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    closeout_payload = json.loads(
        (evidence_dir / "metadata-closeout.json").read_text(encoding="utf-8")
    )
    assert closeout_payload == {
        "ci_run_id": None,
        "metadata_child_created": False,
        "metadata_head_sha": source_sha,
    }
    calls = pathlib.Path(fixture_env["GH_FIXTURE_LOG"]).read_text(encoding="utf-8")
    assert "/git/ref/heads/main" in calls


def test_metadata_closeout_verifier_requires_six_direct_exact_head_jobs(
    tmp_path: pathlib.Path,
) -> None:
    closeout = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Verify exact metadata-head CI closeout",
    )
    verifier = _embedded_python(closeout, "METADATA_CI_CLOSEOUT_VERIFIER")
    repository = "acme/nbadb"
    source_sha = "a" * 40
    metadata_head_sha = "b" * 40
    workflow_id = 77
    run_id = 88
    api_url = "https://api.github.test"
    server_url = "https://github.test"
    required_names = ["workflow-lint", "lint", "metadata", "typecheck", "docs", "test"]
    evidence_dir = tmp_path / "artifacts" / "publication"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "metadata-head-evidence.json").write_text(
        json.dumps(
            {
                "repository": repository,
                "source_sha": source_sha,
                "metadata_head_sha": metadata_head_sha,
                "parent_shas": [source_sha],
                "changed_files": ["dataset-metadata.json"],
                "byte_reproducible": True,
            }
        ),
        encoding="utf-8",
    )
    (evidence_dir / "metadata-ci-dispatch.json").write_text(
        json.dumps(
            {
                "repository": repository,
                "workflow_id": workflow_id,
                "workflow_path": ".github/workflows/ci.yml",
                "run_id": run_id,
                "head_sha": metadata_head_sha,
                "event": "workflow_dispatch",
                "explicitly_dispatched": True,
            }
        ),
        encoding="utf-8",
    )
    run_receipt = {
        "id": run_id,
        "url": f"{api_url}/repos/{repository}/actions/runs/{run_id}",
        "html_url": f"{server_url}/{repository}/actions/runs/{run_id}",
        "workflow_id": workflow_id,
        "path": ".github/workflows/ci.yml",
        "name": "CI",
        "event": "workflow_dispatch",
        "run_attempt": 1,
        "head_sha": metadata_head_sha,
        "head_branch": "main",
        "repository": {"full_name": repository},
        "head_repository": {"full_name": repository},
        "status": "completed",
        "conclusion": "success",
    }
    listed_jobs = [
        {"id": 100 + index, "name": name, "status": "completed"}
        for index, name in enumerate(required_names)
    ]
    direct_jobs = [
        {
            "id": job["id"],
            "name": job["name"],
            "url": f"{api_url}/repos/{repository}/actions/jobs/{job['id']}",
            "run_url": f"{api_url}/repos/{repository}/actions/runs/{run_id}",
            "html_url": f"{server_url}/{repository}/runs/{run_id}/jobs/{job['id']}",
            "workflow_name": "CI",
            "run_id": run_id,
            "head_sha": metadata_head_sha,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
        }
        for job in listed_jobs
    ]
    ref_receipt = {
        "ref": "refs/heads/main",
        "url": f"{api_url}/repos/{repository}/git/refs/heads/main",
        "object": {"type": "commit", "sha": metadata_head_sha},
    }
    fixture_env = _gh_fixture_env(
        tmp_path,
        [
            run_receipt,
            {"total_count": len(listed_jobs), "jobs": listed_jobs},
            *direct_jobs,
            ref_receipt,
        ],
    )

    result = _run_python(
        verifier,
        cwd=tmp_path,
        env={
            **fixture_env,
            "CI_RUN_ID": str(run_id),
            "DEFAULT_BRANCH": "main",
            "GITHUB_API_URL": api_url,
            "GITHUB_SERVER_URL": server_url,
            "METADATA_CI_MAX_POLLS": "1",
            "METADATA_CI_POLL_INTERVAL_SECONDS": "0",
            "METADATA_HEAD_SHA": metadata_head_sha,
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout
    closeout_payload = json.loads(
        (evidence_dir / "metadata-closeout.json").read_text(encoding="utf-8")
    )
    assert closeout_payload["validation"] == {
        "ci_run_id": run_id,
        "metadata_child_created": True,
        "metadata_head_sha": metadata_head_sha,
    }
    assert {job["name"] for job in closeout_payload["ci_run"]["jobs"]} == set(required_names)
    calls = [
        json.loads(line)
        for line in pathlib.Path(fixture_env["GH_FIXTURE_LOG"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(calls) == 9
    assert any("/attempts/1/jobs?per_page=100&page=1" in " ".join(call) for call in calls)
    assert sum("/actions/jobs/" in " ".join(call) for call in calls) == 6


@pytest.mark.parametrize("lagging_side", ("run", "jobs"))
def test_metadata_closeout_waits_for_run_and_job_receipts_to_converge(
    tmp_path: pathlib.Path,
    lagging_side: str,
) -> None:
    closeout = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Verify exact metadata-head CI closeout",
    )
    verifier = _embedded_python(closeout, "METADATA_CI_CLOSEOUT_VERIFIER")
    repository = "acme/nbadb"
    source_sha = "a" * 40
    metadata_head_sha = "b" * 40
    workflow_id = 77
    run_id = 88
    api_url = "https://api.github.test"
    server_url = "https://github.test"
    required_names = ["workflow-lint", "lint", "metadata", "typecheck", "docs", "test"]
    evidence_dir = tmp_path / "artifacts" / "publication"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "metadata-head-evidence.json").write_text(
        json.dumps(
            {
                "repository": repository,
                "source_sha": source_sha,
                "metadata_head_sha": metadata_head_sha,
                "parent_shas": [source_sha],
                "changed_files": ["dataset-metadata.json"],
                "byte_reproducible": True,
            }
        ),
        encoding="utf-8",
    )
    (evidence_dir / "metadata-ci-dispatch.json").write_text(
        json.dumps(
            {
                "repository": repository,
                "workflow_id": workflow_id,
                "workflow_path": ".github/workflows/ci.yml",
                "run_id": run_id,
                "head_sha": metadata_head_sha,
                "event": "workflow_dispatch",
                "explicitly_dispatched": True,
            }
        ),
        encoding="utf-8",
    )

    def run_receipt(status: str) -> dict[str, object]:
        return {
            "id": run_id,
            "url": f"{api_url}/repos/{repository}/actions/runs/{run_id}",
            "html_url": f"{server_url}/{repository}/actions/runs/{run_id}",
            "workflow_id": workflow_id,
            "path": ".github/workflows/ci.yml",
            "name": "CI",
            "event": "workflow_dispatch",
            "run_attempt": 1,
            "head_sha": metadata_head_sha,
            "head_branch": "main",
            "repository": {"full_name": repository},
            "head_repository": {"full_name": repository},
            "status": status,
            "conclusion": "success" if status == "completed" else None,
        }

    completed_jobs = [
        {"id": 100 + index, "name": name, "status": "completed"}
        for index, name in enumerate(required_names)
    ]
    first_jobs = [dict(job) for job in completed_jobs]
    if lagging_side == "jobs":
        first_jobs[-1]["status"] = "in_progress"
    direct_jobs = [
        {
            "id": job["id"],
            "name": job["name"],
            "url": f"{api_url}/repos/{repository}/actions/jobs/{job['id']}",
            "run_url": f"{api_url}/repos/{repository}/actions/runs/{run_id}",
            "html_url": f"{server_url}/{repository}/runs/{run_id}/jobs/{job['id']}",
            "workflow_name": "CI",
            "run_id": run_id,
            "head_sha": metadata_head_sha,
            "head_branch": "main",
            "status": "completed",
            "conclusion": "success",
        }
        for job in completed_jobs
    ]
    fixture_env = _gh_fixture_env(
        tmp_path,
        [
            run_receipt("in_progress" if lagging_side == "run" else "completed"),
            {"total_count": len(first_jobs), "jobs": first_jobs},
            run_receipt("completed"),
            {"total_count": len(completed_jobs), "jobs": completed_jobs},
            *direct_jobs,
            {
                "ref": "refs/heads/main",
                "url": f"{api_url}/repos/{repository}/git/refs/heads/main",
                "object": {"type": "commit", "sha": metadata_head_sha},
            },
        ],
    )

    result = _run_python(
        verifier,
        cwd=tmp_path,
        env={
            **fixture_env,
            "CI_RUN_ID": str(run_id),
            "DEFAULT_BRANCH": "main",
            "GITHUB_API_URL": api_url,
            "GITHUB_SERVER_URL": server_url,
            "METADATA_CI_MAX_POLLS": "2",
            "METADATA_CI_POLL_INTERVAL_SECONDS": "0",
            "METADATA_HEAD_SHA": metadata_head_sha,
        },
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_all_publish_workflows_preserve_scoped_kaggle_reconciliation_state() -> None:
    # Every publish-family job serializes on the same explicit non-cancelling group.
    # The scheduled daily/monthly publishers additionally queue every pending run
    # (queue: max); the full-extraction publish job keeps the plain serial group
    # while it is disabled behind its legacy false gate.
    plain_serial_group = (
        "concurrency:\n      group: nbadb-kaggle-publish\n      cancel-in-progress: false"
    )
    queueing_serial_group = (
        "concurrency:\n"
        "      group: nbadb-kaggle-publish\n"
        "      queue: max\n"
        "      cancel-in-progress: false"
    )
    workflow_jobs = (
        (
            _job_block(_workflow_text(), "publish"),
            "Upload Kaggle publication receipt",
            "nbadb-kaggle-publication-state-${{ github.run_id }}-",
            plain_serial_group,
        ),
        (
            _job_block(_DAILY_PATH.read_text(encoding="utf-8"), "daily"),
            "Upload Kaggle publication receipt",
            "nbadb-kaggle-publication-state-",
            queueing_serial_group,
        ),
        (
            _job_block(_MONTHLY_PATH.read_text(encoding="utf-8"), "monthly"),
            "Upload Kaggle publication receipt",
            "nbadb-kaggle-publication-state-",
            queueing_serial_group,
        ),
    )
    state_path = "logs/kaggle/kaggle-publication-state.json"
    cache_key = "nbadb-kaggle-publication-state-${{ github.run_id }}-${{ github.run_attempt }}"

    for job, receipt_name, restore_prefix, concurrency_block in workflow_jobs:
        restore = _step_block(job, "Restore Kaggle publication reconciliation state")
        detect = _step_block(job, "Detect Kaggle publication reconciliation state")
        persist = _step_block(job, "Persist Kaggle publication reconciliation state")
        receipt = _step_block(job, receipt_name)

        assert "nbadb-kaggle-publish" in job
        assert concurrency_block in job
        assert state_path in restore
        assert cache_key in restore
        assert f"restore-keys: |\n            {restore_prefix}" in restore
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
        workflow = path.read_text(encoding="utf-8")
        job = _job_block(workflow, job_name)
        branch_guard = _step_block(job, "Require default branch for Kaggle publication")
        upload = _step_block(job, "Upload to Kaggle")
        receipt = _step_block(job, "Upload Kaggle publication receipt")
        assertion = _step_block(job, "Assert extraction and scan passed")

        assert "Kaggle publication requires the default branch" in branch_guard
        scan = _step_block(job, "Scan data quality")
        assert "full-publication: true" not in scan
        assert "data-dir: data/nbadb" in scan
        assert "successor-generation-store" not in scan
        assert "checkpoint-report:" not in scan
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
        assert "--full-publication" not in upload
        assert "--successor-generation-store" not in upload
        assert "--publication-ledger github-deployment" in upload
        assert "--require-durable-intent" in upload
        assert "--remote-timeout 3600" in upload
        assert "DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}" in upload
        assert "GH_TOKEN: ${{ github.token }}" in upload
        assert 'NBADB_KAGGLE_REQUIRE_DEFAULT_HEAD: "true"' in upload
        assert "NBADB_KAGGLE_PUBLICATION_SOURCE_SHA: ${{ github.sha }}" in upload
        assert 'gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/${DEFAULT_BRANCH}"' in upload
        assert (
            'if [ "$current_source_sha" != "$NBADB_KAGGLE_PUBLICATION_SOURCE_SHA" ]; then' in upload
        )
        assert upload.index('current_source_sha="$(gh api') < upload.index("uv run nbadb upload")
        assert ("permissions:\n  actions: read\n  contents: read\n  deployments: write") in workflow
        assert "Refresh checked-in metadata" not in job
        assert "refresh-metadata" not in job
        assert "steps.upload.outcome != 'skipped'" in receipt
        assert "EXPORT_OUTCOME: ${{ steps.export.outcome }}" in assertion
        assert "METADATA_OUTCOME: ${{ steps.metadata.outcome }}" in assertion
        assert "UPLOAD_OUTCOME: ${{ steps.upload.outcome }}" in assertion
        assert "METADATA_COMMIT_OUTCOME" not in assertion


def test_kaggle_publication_preflight_fails_before_lane_fanout_and_rechecks_at_publish() -> None:
    preflight = _job_block(_workflow_text(), "preflight")
    publication_preflight = _job_block(_workflow_text(), "publication_preflight")
    publish = _job_block(_workflow_text(), "publish")
    early_kaggle = _step_block(publication_preflight, "Fail fast on Kaggle publication readiness")
    kaggle = _step_block(publish, "Validate Kaggle publication readiness")

    assert "KAGGLE_USERNAME" not in preflight
    assert "KAGGLE_KEY" not in preflight
    assert "needs: [plan, publication_preflight]" in preflight
    assert "(!false || needs.publication_preflight.result == 'success')" in preflight
    assert "needs: [workflow_guard, plan]" in publication_preflight
    publication_preflight_header = publication_preflight.split("    runs-on:", 1)[0]
    # Publication is disabled in this workflow behind the legacy false gate while the
    # exact handoff publication workflow owns Kaggle publication; the retained
    # authority and collector fragments still define the gate it would run under.
    assert "if: ${{ false && " in publication_preflight_header
    for admission_fragment in (
        "needs.plan.result == 'success'",
        "needs.plan.outputs.operation-authority-status == 'validated'",
        "free-execution-collector-status == 'admitted'",
        "free-execution-collector-authenticated == 'true'",
        "free-execution-runtime-context-status == 'authenticated'",
        "free-execution-storage-mutations-allowed == 'true'",
        "free-execution-provider-calls-allowed == 'true'",
        "free-execution-mutations-authorized == 'true'",
    ):
        assert admission_fragment in publication_preflight_header
    assert "inputs.publish" not in publication_preflight_header
    assert "inputs.publish" not in workflow_input_names(_workflow_text())
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
    # All publish-family jobs serialize on the one shared non-cancelling group. The
    # scheduled publishers queue every pending run; the full-extraction publish job,
    # currently disabled behind its legacy false gate, keeps the plain serial group.
    publish_jobs = (
        (
            _job_block(_workflow_text(), "publish"),
            ("concurrency:\n      group: nbadb-kaggle-publish\n      cancel-in-progress: false"),
        ),
        (
            _job_block(_DAILY_PATH.read_text(encoding="utf-8"), "daily"),
            (
                "concurrency:\n"
                "      group: nbadb-kaggle-publish\n"
                "      queue: max\n"
                "      cancel-in-progress: false"
            ),
        ),
        (
            _job_block(_MONTHLY_PATH.read_text(encoding="utf-8"), "monthly"),
            (
                "concurrency:\n"
                "      group: nbadb-kaggle-publish\n"
                "      queue: max\n"
                "      cancel-in-progress: false"
            ),
        ),
    )

    for job, concurrency_block in publish_jobs:
        assert concurrency_block in job
        assert "cancel-in-progress: true" not in job
    assert "group: nbadb-kaggle-publish" in publish_jobs[0][0]


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
    exact_receipt = _step_block(publish, "Verify exact assured data artifact receipt")
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
    assert publish.index("Verify exact assured data artifact receipt") < publish.index(
        "Download exact assured data artifact"
    )
    assert "workflow_source_provenance.py verify-current-artifact" in exact_receipt
    assert "CURRENT_RUN_HEAD_SHA: ${{ github.sha }}" in exact_receipt
    assert '--head-sha "$CURRENT_RUN_HEAD_SHA"' in exact_receipt
    assert '--run-attempt "$CURRENT_RUN_ATTEMPT"' in exact_receipt
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
    assert 'target.open("xb")' in exact_download
    assert "ARTIFACT_OUTPUT_DIR: data/nbadb" in exact_download
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
    assert "--publication-ledger github-deployment" in upload
    assert "--require-durable-intent" in upload
    assert "GH_TOKEN: ${{ github.token }}" in upload
    assert "NBADB_KAGGLE_PUBLICATION_SOURCE_SHA: ${{ env.WORKFLOW_SOURCE_SHA }}" in upload
    assert 'NBADB_KAGGLE_REQUIRE_DEFAULT_HEAD: "true"' in upload
    assert "deployments: write" in publish
    assert 'source_commit="$(git rev-parse "${WORKFLOW_SOURCE_SHA}^{commit}")"' in frozen_source
    assert '"+refs/heads/${DEFAULT_BRANCH}:${target_ref}"' in frozen_source
    assert 'if [ "$target_commit" != "$source_commit" ]; then' in frozen_source
    assert '[ "$parent" != "$source_commit" ]' in frozen_source
    assert '[ "$changed_paths" != "dataset-metadata.json" ]' in frozen_source
    assert '[ "$commit_subject" != "chore: regenerate dataset-metadata.json" ]' in frozen_source
    assert 'cmp --silent "$expected_metadata" "$observed_metadata"' in frozen_source
    assert "exact metadata-only publication child" in frozen_source
    assert (
        "NBADB_KAGGLE_EXPECTED_DEFAULT_HEAD_SHA=%s" in frozen_source
        and '"$target_commit" >> "$GITHUB_ENV"' in frozen_source
    )
    assert "if: always()" in receipt
    assert "if: always()" in final_artifact
    assert "name: nbadb-full-extraction-${{ env.ACTIVE_CHAIN_ID }}" in final_artifact
    assert "data/nbadb/assured-artifact-manifest.json" in final_artifact
    assert publish.index("Revalidate frozen publication source") < publish.index("Upload to Kaggle")
    assert publish.index("Upload final database") < publish.index("Refresh checked-in metadata")


def test_all_owner_consumers_validate_complete_schema_v1_snapshot() -> None:
    control_plane = _workflow_text() + _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8")

    assert control_plane.count('type(owner_snapshot.get("schema_version")) is not int') == 6
    assert control_plane.count('workflow_claim.get("blob_sha")') == 6
    assert control_plane.count('workflow_claim.get("sha256")') == 6
    assert control_plane.count('type(workflow_claim.get("size_in_bytes")) is not int') == 6
    assert control_plane.count('semantic_source.get("relation")') == 12
    assert control_plane.count('(semantic_source.get("relation") == "identical")') == 6
    assert control_plane.count('== str(owner_claim.get("head_sha") or "").lower()') == 6


def test_assured_artifact_archive_verifier_rejects_digest_and_identity_mismatch(
    tmp_path: pathlib.Path,
) -> None:
    download = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Download exact assured data artifact",
    )
    verifier = _embedded_python(download, "ASSURED_ARTIFACT_ARCHIVE_VERIFIER")
    archive_path = tmp_path / "assured.zip"
    receipt_path = tmp_path / "artifact-receipt.json"
    artifact_id = "123"
    artifact_name = "nbadb-full-extraction-assured-fixture-456-1"
    source_run_id = "456"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nba.duckdb", b"fixture")
    digest = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
    receipt = {
        "digest": digest,
        "id": int(artifact_id),
        "name": artifact_name,
        "producer_run_attempt": 1,
        "reconciliation_role": "publication_reconcile",
        "size_in_bytes": archive_path.stat().st_size,
        "verified_owner_run_attempt": 1,
        "workflow_run_id": int(source_run_id),
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    env = {
        "ARTIFACT_ARCHIVE_PATH": str(archive_path),
        "ARTIFACT_DIGEST": digest,
        "ARTIFACT_ID": artifact_id,
        "ARTIFACT_NAME": artifact_name,
        "ARTIFACT_OUTPUT_DIR": str(tmp_path / "output"),
        "CHAIN_ID": "fixture",
        "CURRENT_RUN_ATTEMPT": "1",
        "PRODUCER_RUN_ATTEMPT": "1",
        "RECEIPT_PATH": str(receipt_path),
        "RECONCILIATION_ROLE": "publication_reconcile",
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

    receipt["id"] = 999
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    wrong_id = _run_python(verifier, env=env)
    assert wrong_id.returncode == 1
    assert "artifact receipt ID does not match" in wrong_id.stdout


@pytest.mark.parametrize(
    ("receipt_patch", "expected_error"),
    [
        ({"name": "wrong-name"}, "artifact receipt name does not match"),
        ({"workflow_run_id": 999}, "artifact receipt workflow run identity does not match"),
        ({"producer_run_attempt": 2}, "artifact receipt producer attempt does not match"),
        ({"verified_owner_run_attempt": 2}, "artifact receipt owner attempt does not match"),
        (
            {"reconciliation_role": "dispatch_reconcile"},
            "artifact receipt reconciliation role does not match",
        ),
        ({"digest": "sha256:" + "0" * 64}, "artifact receipt digest does not match"),
        ({"size_in_bytes": 999}, "artifact archive size does not match its receipt"),
    ],
)
def test_assured_artifact_archive_verifier_rejects_receipt_provenance_tampering(
    tmp_path: pathlib.Path,
    receipt_patch: dict[str, object],
    expected_error: str,
) -> None:
    download = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Download exact assured data artifact",
    )
    verifier = _embedded_python(download, "ASSURED_ARTIFACT_ARCHIVE_VERIFIER")
    archive_path = tmp_path / "assured.zip"
    receipt_path = tmp_path / "artifact-receipt.json"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nba.duckdb", b"fixture")
    artifact_id = "123"
    artifact_name = "nbadb-full-extraction-assured-fixture-456-1"
    source_run_id = "456"
    digest = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
    receipt = {
        "digest": digest,
        "id": int(artifact_id),
        "name": artifact_name,
        "producer_run_attempt": 1,
        "reconciliation_role": "publication_reconcile",
        "size_in_bytes": archive_path.stat().st_size,
        "verified_owner_run_attempt": 1,
        "workflow_run_id": int(source_run_id),
        **receipt_patch,
    }
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    result = _run_python(
        verifier,
        env={
            "ARTIFACT_ARCHIVE_PATH": str(archive_path),
            "ARTIFACT_DIGEST": digest,
            "ARTIFACT_ID": artifact_id,
            "ARTIFACT_NAME": artifact_name,
            "ARTIFACT_OUTPUT_DIR": str(tmp_path / "output"),
            "CHAIN_ID": "fixture",
            "CURRENT_RUN_ATTEMPT": "1",
            "PRODUCER_RUN_ATTEMPT": "1",
            "RECEIPT_PATH": str(receipt_path),
            "RECONCILIATION_ROLE": "publication_reconcile",
            "SOURCE_RUN_ID": source_run_id,
        },
    )

    assert result.returncode == 1
    assert expected_error in result.stdout


@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("traversal", "unsafe member"),
        ("absolute", "unsafe member"),
        ("backslash", "unsafe member"),
        ("normalized-duplicate", "unsafe member"),
        ("symlink", "unsafe member"),
        ("special-file", "unsafe member"),
        ("special-directory", "unsafe member"),
        ("file-parent", "file-parent collision"),
        ("empty", "archive is empty"),
    ],
)
def test_assured_artifact_archive_verifier_rejects_unsafe_members(
    tmp_path: pathlib.Path,
    case: str,
    expected_error: str,
) -> None:
    download = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Download exact assured data artifact",
    )
    verifier = _embedded_python(download, "ASSURED_ARTIFACT_ARCHIVE_VERIFIER")
    archive_path = tmp_path / "assured.zip"
    receipt_path = tmp_path / "artifact-receipt.json"
    with zipfile.ZipFile(archive_path, "w") as archive:
        if case != "empty":
            archive.writestr("safe.json", b"must-not-be-written")
        if case == "traversal":
            archive.writestr("../escape", b"fixture")
        elif case == "absolute":
            archive.writestr("/absolute/path", b"fixture")
        elif case == "backslash":
            archive.writestr("nested\\member", b"fixture")
        elif case == "normalized-duplicate":
            archive.writestr("duplicate/member", b"first")
            archive.writestr("duplicate//member", b"second")
        elif case == "symlink":
            member = zipfile.ZipInfo("nested/link")
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, "target")
        elif case == "special-file":
            member = zipfile.ZipInfo("nested/fifo")
            member.external_attr = (stat.S_IFIFO | 0o644) << 16
            archive.writestr(member, b"")
        elif case == "special-directory":
            member = zipfile.ZipInfo("nested/fifo/")
            member.external_attr = (stat.S_IFIFO | 0o755) << 16
            archive.writestr(member, b"")
        elif case == "file-parent":
            archive.writestr("nested", b"file")
            archive.writestr("nested/member", b"child")
        elif case != "empty":
            raise AssertionError(case)
    digest = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
    receipt_path.write_text(
        json.dumps(
            {
                "digest": digest,
                "id": 123,
                "name": "nbadb-full-extraction-assured-fixture-456-1",
                "producer_run_attempt": 1,
                "reconciliation_role": "publication_reconcile",
                "size_in_bytes": archive_path.stat().st_size,
                "verified_owner_run_attempt": 1,
                "workflow_run_id": 456,
            }
        ),
        encoding="utf-8",
    )
    result = _run_python(
        verifier,
        env={
            "ARTIFACT_ARCHIVE_PATH": str(archive_path),
            "ARTIFACT_DIGEST": digest,
            "ARTIFACT_ID": "123",
            "ARTIFACT_NAME": "nbadb-full-extraction-assured-fixture-456-1",
            "ARTIFACT_OUTPUT_DIR": str(tmp_path / "output"),
            "CHAIN_ID": "fixture",
            "CURRENT_RUN_ATTEMPT": "1",
            "PRODUCER_RUN_ATTEMPT": "1",
            "RECEIPT_PATH": str(receipt_path),
            "RECONCILIATION_ROLE": "publication_reconcile",
            "SOURCE_RUN_ID": "456",
        },
    )

    assert result.returncode == 1
    assert expected_error in result.stdout
    assert not (tmp_path / "output" / "safe.json").exists()


@pytest.mark.parametrize("collision_kind", ["file", "broken-symlink"])
def test_assured_artifact_archive_verifier_preflights_destination_parents(
    tmp_path: pathlib.Path,
    collision_kind: str,
) -> None:
    download = _step_block(
        _job_block(_workflow_text(), "publish"),
        "Download exact assured data artifact",
    )
    verifier = _embedded_python(download, "ASSURED_ARTIFACT_ARCHIVE_VERIFIER")
    archive_path = tmp_path / "assured.zip"
    receipt_path = tmp_path / "artifact-receipt.json"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("safe.json", b"must-not-be-written")
        archive.writestr("nested/data.json", b"blocked")
    digest = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
    artifact_name = "nbadb-full-extraction-assured-fixture-456-1"
    receipt_path.write_text(
        json.dumps(
            {
                "digest": digest,
                "id": 123,
                "name": artifact_name,
                "producer_run_attempt": 1,
                "reconciliation_role": "publication_reconcile",
                "size_in_bytes": archive_path.stat().st_size,
                "verified_owner_run_attempt": 1,
                "workflow_run_id": 456,
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    nested = output_dir / "nested"
    if collision_kind == "file":
        nested.write_text("existing", encoding="utf-8")
    else:
        nested.symlink_to(output_dir / "missing-target", target_is_directory=True)

    result = _run_python(
        verifier,
        env={
            "ARTIFACT_ARCHIVE_PATH": str(archive_path),
            "ARTIFACT_DIGEST": digest,
            "ARTIFACT_ID": "123",
            "ARTIFACT_NAME": artifact_name,
            "ARTIFACT_OUTPUT_DIR": str(output_dir),
            "CHAIN_ID": "fixture",
            "CURRENT_RUN_ATTEMPT": "1",
            "PRODUCER_RUN_ATTEMPT": "1",
            "RECEIPT_PATH": str(receipt_path),
            "RECONCILIATION_ROLE": "publication_reconcile",
            "SOURCE_RUN_ID": "456",
        },
    )

    assert result.returncode == 1
    assert "destination" in result.stdout
    assert not (output_dir / "safe.json").exists()


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
    receipt_path = tmp_path / "artifact-receipt.json"
    digest = "sha256:" + hashlib.sha256(archive_path.read_bytes()).hexdigest()
    receipt_path.write_text(
        json.dumps(
            {
                "digest": digest,
                "id": 123,
                "name": "nbadb-full-extraction-assured-fixture-456-1",
                "producer_run_attempt": 1,
                "reconciliation_role": "publication_reconcile",
                "size_in_bytes": archive_path.stat().st_size,
                "verified_owner_run_attempt": 1,
                "workflow_run_id": 456,
            }
        ),
        encoding="utf-8",
    )
    result = _run_python(
        verifier,
        env={
            "ARTIFACT_ARCHIVE_PATH": str(archive_path),
            "ARTIFACT_DIGEST": digest,
            "ARTIFACT_ID": "123",
            "ARTIFACT_NAME": "nbadb-full-extraction-assured-fixture-456-1",
            "ARTIFACT_OUTPUT_DIR": str(tmp_path / "output"),
            "CHAIN_ID": "fixture",
            "CURRENT_RUN_ATTEMPT": "1",
            "PRODUCER_RUN_ATTEMPT": "1",
            "RECEIPT_PATH": str(receipt_path),
            "RECONCILIATION_ROLE": "publication_reconcile",
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
    metadata_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=seed,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
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
    github_env = tmp_path / "github-env"
    env = {
        **os.environ,
        "DEFAULT_BRANCH": "main",
        "GITHUB_ENV": str(github_env),
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
    assert (
        github_env.read_text(encoding="utf-8")
        == f"NBADB_KAGGLE_EXPECTED_DEFAULT_HEAD_SHA={metadata_commit}\n"
    )

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
    plan_receipt = _step_block(replay, "Verify exact zero-active plan artifact receipt")
    plan_download = _step_block(replay, "Download exact zero-active plan artifact")
    source_selection = _step_block(replay, "Verify plan-selected resume source receipt")
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
    assert "TERMINAL_REPLAY_MANIFEST_RESOLVER" not in replay
    assert "TERMINAL_REPLAY_PLAN_ARTIFACT_VERIFIER" in plan_receipt
    assert "needs.plan.outputs.plan-manifest-artifact-id" in plan_receipt
    assert "needs.plan.outputs.plan-manifest-artifact-digest" in plan_receipt
    assert "artifact-ids: ${{ needs.plan.outputs.plan-manifest-artifact-id }}" in (plan_download)
    assert "run-id: ${{ github.run_id }}" in plan_download
    assert "digest-mismatch: error" in plan_download
    assert "TERMINAL_REPLAY_PLAN_SELECTION_VERIFIER" in source_selection
    assert "resume-source-selection.json" in source_selection
    assert "resume-source-input-manifest.json" in source_selection
    assert "REST identity changed after planning" in source_selection
    assert "source-committed-manifest" not in replay
    assert (
        "python .github/scripts/full_extraction_handoffs.py resolve-exact-source-checkpoint-receipt"
    ) in source_resolver
    assert "steps.source_selection.outputs.artifact_id != ''" in source_resolver
    assert "steps.source_selection.outputs.source_run_id" in source_resolver
    assert 'gh run download "$SOURCE_RUN_ID"' not in replay
    assert "artifact-ids: ${{ steps.source_checkpoint.outputs.artifact_id }}" in (source_download)
    assert "run-id: ${{ steps.source_checkpoint.outputs.source_run_id }}" in source_download
    assert "digest-mismatch: error" in source_download
    assert "steps.source_checkpoint.outputs.artifact_id != ''" in replay
    assert (
        "python .github/scripts/full_extraction_handoffs.py attest-terminal-replay-inputs"
    ) in replay_attestation
    assert "steps.source_checkpoint.outputs.artifact_id != ''" in replay_attestation
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


def test_terminal_replay_binds_plan_and_selected_source_receipts(
    tmp_path: pathlib.Path,
) -> None:
    replay = _job_block(_workflow_text(), "terminal_replay")
    plan_job = _job_block(_workflow_text(), "plan")
    plan_upload_verifier = _embedded_python(
        plan_job,
        "PLAN_MANIFEST_ARTIFACT_RECEIPT_VERIFIER",
    )
    plan_verifier = _embedded_python(
        replay,
        "TERMINAL_REPLAY_PLAN_ARTIFACT_VERIFIER",
    )
    selection_verifier = _embedded_python(
        replay,
        "TERMINAL_REPLAY_PLAN_SELECTION_VERIFIER",
    )
    chain_id = "fixture-chain"
    repository = "acme/nbadb"
    source_sha = "e" * 40
    plan_owner_sha = "d" * 40

    plan_case = tmp_path / "plan-receipt"
    plan_artifact_id = 900
    plan_run_id = 555
    plan_digest = "a" * 64
    plan_name = f"full-extraction-manifest-{chain_id}"
    plan_api_url = (
        f"https://api.github.test/repos/{repository}/actions/artifacts/{plan_artifact_id}"
    )
    plan_owner = {
        "conclusion": None,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": plan_owner_sha,
        "id": plan_run_id,
        "path": ".github/workflows/full-extraction.yml",
        "repository": {"full_name": repository},
        "run_attempt": 1,
        "status": "in_progress",
        "url": (f"https://api.github.test/repos/{repository}/actions/runs/{plan_run_id}"),
        "workflow_id": 77,
    }
    plan_artifact = {
        "archive_download_url": f"{plan_api_url}/zip",
        "digest": f"sha256:{plan_digest}",
        "expired": False,
        "id": plan_artifact_id,
        "name": plan_name,
        "size_in_bytes": 4096,
        "url": plan_api_url,
        "workflow_run": {"head_sha": plan_owner_sha, "id": plan_run_id},
    }
    plan_fixture = _gh_fixture_env(
        plan_case,
        [
            plan_owner,
            plan_artifact,
            plan_owner,
            plan_owner,
            plan_artifact,
            plan_owner,
        ],
    )
    plan_output = plan_case / "github-output.txt"
    plan_env = {
        **plan_fixture,
        "CHAIN_ID": chain_id,
        "CURRENT_RUN_HEAD_SHA": plan_owner_sha,
        "GITHUB_API_URL": "https://api.github.test",
        "GITHUB_OUTPUT": str(plan_output),
        "GITHUB_REPOSITORY": repository,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": str(plan_run_id),
        "PLAN_ARTIFACT_DIGEST": plan_digest,
        "PLAN_ARTIFACT_ID": str(plan_artifact_id),
        "PLAN_ARTIFACT_NAME": plan_name,
        "PLAN_ARTIFACT_ARCHIVE_URL": f"{plan_api_url}/zip",
        "PLAN_ARTIFACT_SIZE": "4096",
        "WORKFLOW_SOURCE_SHA": source_sha,
        "WORKFLOW_SOURCE_REF": "main",
    }
    upload_output = plan_case / "upload-output.txt"
    upload_result = _run_python(
        plan_upload_verifier,
        env={**plan_env, "GITHUB_OUTPUT": str(upload_output)},
        cwd=plan_case,
    )
    assert upload_result.returncode == 0, upload_result.stderr or upload_result.stdout
    assert upload_output.read_text(encoding="utf-8").splitlines() == [
        f"artifact_archive_url={plan_api_url}/zip",
        f"artifact_digest=sha256:{plan_digest}",
        f"artifact_id={plan_artifact_id}",
        f"artifact_name={plan_name}",
        "artifact_size_bytes=4096",
    ]
    plan_result = _run_python(plan_verifier, env=plan_env, cwd=plan_case)
    assert plan_result.returncode == 0, plan_result.stderr or plan_result.stdout
    assert plan_output.read_text(encoding="utf-8").splitlines() == [
        f"artifact_digest=sha256:{plan_digest}",
        f"artifact_id={plan_artifact_id}",
        f"artifact_name={plan_name}",
        "artifact_size_bytes=4096",
    ]

    plan_drift_case = tmp_path / "plan-rest-drift"
    drift_fixture = _gh_fixture_env(
        plan_drift_case,
        [plan_owner, {**plan_artifact, "name": "wrong-plan"}],
    )
    plan_drift = _run_python(
        plan_verifier,
        env={
            **plan_env,
            **drift_fixture,
            "GITHUB_OUTPUT": str(plan_drift_case / "github-output.txt"),
        },
        cwd=plan_drift_case,
    )
    assert plan_drift.returncode == 1
    assert "does not match its exact job receipt" in plan_drift.stderr

    selection_case = tmp_path / "source-selection"
    artifact_dir = selection_case / "plan-artifact"
    artifact_dir.mkdir(parents=True)
    source_run_id = 987654
    source_run_attempt = 1
    source_owner_sha = "c" * 40
    source_artifact_id = 801
    source_artifact_name = "full-extraction-next-manifest-fixture-chain-iter-4-run-987654-attempt-1"
    source_digest = "sha256:" + "f" * 64
    source_artifact_url = (
        f"https://api.github.test/repos/{repository}/actions/artifacts/{source_artifact_id}"
    )
    source_manifest = {
        "chain_id": chain_id,
        "workflow_source_sha": source_sha,
        "chain_state": {},
    }
    source_path = artifact_dir / "resume-source-input-manifest.json"
    source_path.write_text(
        json.dumps(source_manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "manifest.json").write_text(
        json.dumps(
            {
                "active_lane_count": 0,
                "chain_id": chain_id,
                "lane_count": 1,
                "matrix_lane_count": 0,
                "workflow_source_sha": source_sha,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    source_owner = {
        "conclusion": "failure",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": source_owner_sha,
        "id": source_run_id,
        "path": ".github/workflows/full-extraction.yml",
        "repository": {"full_name": repository},
        "run_attempt": source_run_attempt,
        "status": "completed",
        "url": (f"https://api.github.test/repos/{repository}/actions/runs/{source_run_id}"),
        "workflow_id": 88,
    }
    source_artifact = {
        "archive_download_url": f"{source_artifact_url}/zip",
        "digest": source_digest,
        "expired": False,
        "id": source_artifact_id,
        "name": source_artifact_name,
        "size_in_bytes": 2048,
        "url": source_artifact_url,
        "workflow_run": {"head_sha": source_owner_sha, "id": source_run_id},
    }
    receipt = {
        "member": {
            "bundled_name": "resume-source-input-manifest.json",
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "size_in_bytes": len(source_path.read_bytes()),
            "source_name": "next-manifest.json",
        },
        "resolution": "committed",
        "schema_version": 1,
        "source_artifact": {
            "archive_download_url": f"{source_artifact_url}/zip",
            "digest": source_digest,
            "expired": False,
            "id": source_artifact_id,
            "name": source_artifact_name,
            "size_in_bytes": 2048,
        },
        "source_run": {
            "attempt": source_run_attempt,
            "conclusion": "failure",
            "event": "workflow_dispatch",
            "head_sha": source_owner_sha,
            "id": source_run_id,
            "path": ".github/workflows/full-extraction.yml",
            "status": "completed",
            "workflow_id": 88,
        },
    }
    receipt_path = artifact_dir / "resume-source-selection.json"
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    owner_recheck_path = selection_case / "owner-recheck.json"
    owner_recheck_path.write_text(
        json.dumps(
            _owner_recheck_snapshot(
                source_owner,
                source_sha=source_sha,
                repository=repository,
            )
        ),
        encoding="utf-8",
    )
    selection_fixture = _gh_fixture_env(
        selection_case,
        [source_owner, source_artifact, source_owner],
    )
    selection_output = selection_case / "github-output.txt"
    selection_env = {
        **selection_fixture,
        "CHAIN_ID": chain_id,
        "EXPECTED_ARTIFACT_ARCHIVE_URL": f"{source_artifact_url}/zip",
        "EXPECTED_ARTIFACT_DIGEST": source_digest,
        "EXPECTED_ARTIFACT_ID": str(source_artifact_id),
        "EXPECTED_ARTIFACT_NAME": source_artifact_name,
        "EXPECTED_ARTIFACT_SIZE": "2048",
        "EXPECTED_RESOLUTION": "committed",
        "EXPECTED_RUN_ATTEMPT": str(source_run_attempt),
        "EXPECTED_RUN_CONCLUSION": "failure",
        "EXPECTED_RUN_HEAD_SHA": source_owner_sha,
        "EXPECTED_RUN_ID": str(source_run_id),
        "EXPECTED_RUN_STATUS": "completed",
        "EXPECTED_WORKFLOW_ID": "88",
        "GITHUB_API_URL": "https://api.github.test",
        "GITHUB_OUTPUT": str(selection_output),
        "GITHUB_REPOSITORY": repository,
        "OWNER_RECHECK_PATH": str(owner_recheck_path),
        "REQUESTED_SOURCE_RUN_ID": str(source_run_id),
        "WORKFLOW_SOURCE_SHA": source_sha,
    }
    selected = _run_python(
        selection_verifier,
        env=selection_env,
        cwd=selection_case,
    )
    assert selected.returncode == 0, selected.stderr or selected.stdout
    assert selection_output.read_text(encoding="utf-8").splitlines() == [
        f"artifact_id={source_artifact_id}",
        f"artifact_name={source_artifact_name}",
        f"source_run_id={source_run_id}",
        f"source_run_attempt={source_run_attempt}",
    ]

    rerun_case = tmp_path / "source-rest-rerun"
    rerun_fixture = _gh_fixture_env(
        rerun_case,
        [{**source_owner, "run_attempt": 2}, source_artifact],
    )
    rerun = _run_python(
        selection_verifier,
        env={
            **selection_env,
            **rerun_fixture,
            "GITHUB_OUTPUT": str(rerun_case / "github-output.txt"),
        },
        cwd=selection_case,
    )
    assert rerun.returncode == 1
    assert "REST identity changed after planning" in rerun.stderr
    rerun_calls = [
        json.loads(line)
        for line in pathlib.Path(rerun_fixture["GH_FIXTURE_LOG"])
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(rerun_calls) == 1
    assert rerun_calls[0][-1].endswith(f"/actions/runs/{source_run_id}")
    assert all("/actions/artifacts/" not in argument for argument in rerun_calls[0])

    receipt["member"]["sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    member_tamper = _run_python(
        selection_verifier,
        env={
            **selection_env,
            "GITHUB_OUTPUT": str(selection_case / "tampered-output.txt"),
        },
        cwd=selection_case,
    )
    assert member_tamper.returncode == 1
    assert "receipt does not match job outputs" in member_tamper.stderr

    receipt["member"]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    rest_faults = (
        ("expired", source_owner, {**source_artifact, "expired": True}),
        (
            "digest",
            source_owner,
            {**source_artifact, "digest": "sha256:" + "0" * 64},
        ),
        ("size", source_owner, {**source_artifact, "size_in_bytes": 4096}),
        (
            "workflow-run",
            source_owner,
            {
                **source_artifact,
                "workflow_run": {
                    "head_sha": source_owner_sha,
                    "id": source_run_id + 1,
                },
            },
        ),
        (
            "source-sha",
            {**source_owner, "head_sha": "0" * 40},
            source_artifact,
        ),
        (
            "same-name-newer-id",
            source_owner,
            {**source_artifact, "id": source_artifact_id + 1},
        ),
    )
    for label, rest_owner, rest_artifact in rest_faults:
        fault_case = tmp_path / f"source-rest-{label}"
        fault_fixture = _gh_fixture_env(
            fault_case,
            [rest_owner, rest_artifact],
        )
        rest_drift = _run_python(
            selection_verifier,
            env={
                **selection_env,
                **fault_fixture,
                "GITHUB_OUTPUT": str(fault_case / "github-output.txt"),
            },
            cwd=selection_case,
        )
        assert rest_drift.returncode == 1, label
        assert "REST identity changed after planning" in rest_drift.stderr, label


def test_terminal_replay_uses_committed_transaction_and_rejects_tampering(
    tmp_path: pathlib.Path,
) -> None:
    resolver = _helper_embedded_python("TERMINAL_REPLAY_ARTIFACT_RESOLVER")
    attestation = _helper_embedded_python("TERMINAL_REPLAY_ATTESTATION")
    assert 'transaction["schema_version"] != 3' in resolver
    assert "w2_authority_identity_sha256" in resolver
    assert "w2_database_authority_sha256" in resolver
    assert "w2_expected_call_inventory_sha256" in resolver
    assert 'candidate_transaction["schema_version"] != 3' in attestation
    assert "report_w2_authority" in attestation
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
    w2_authority = _checkpoint_w2_authority()
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
        **w2_authority.identity_payload(),
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
        "conclusion": "success",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "id": int(source_run_id),
        "head_sha": owner_head_sha,
        "path": ".github/workflows/full-extraction.yml",
        "repository": {"full_name": "acme/nbadb"},
        "run_attempt": 1,
        "status": "completed",
        "url": (f"https://api.github.test/repos/acme/nbadb/actions/runs/{source_run_id}"),
        "workflow_id": 99,
    }
    artifact = {
        "archive_download_url": (
            f"https://api.github.test/repos/acme/nbadb/actions/artifacts/{artifact_id}/zip"
        ),
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
    fixture_env = _gh_fixture_env(resolver_dir, [owner_run, artifact, owner_run])
    owner_recheck_path = resolver_dir / "owner-recheck.json"
    owner_recheck_path.write_text(
        json.dumps(
            _owner_recheck_snapshot(
                owner_run,
                source_sha=source_sha,
            )
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "github-output.txt"
    resolver_env = {
        **fixture_env,
        "CHAIN_ID": chain_id,
        "GITHUB_API_URL": "https://api.github.test",
        "GITHUB_OUTPUT": str(output_path),
        "GITHUB_REPOSITORY": "acme/nbadb",
        "OWNER_RECHECK_PATH": str(owner_recheck_path),
        "PLAN_MANIFEST_PATH": str(trust_manifest_path),
        "SOURCE_RUN_ID": source_run_id,
        "SOURCE_RUN_ATTEMPT": "1",
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
        f"w2_authority_identity_sha256={w2_authority.identity_sha256}",
        f"w2_database_authority_sha256={w2_authority.database_authority_sha256}",
        f"w2_expected_call_count={w2_authority.expected_call_count}",
        (f"w2_expected_call_inventory_sha256={w2_authority.expected_call_inventory_sha256}"),
        "w2_database_authority_closed=true",
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
        assert "checkpoint transaction" in malformed.stderr
        assert not output_path.exists()

    adversarial_transactions: list[tuple[str, dict[str, object]]] = []
    legacy_transaction = json.loads(json.dumps(transaction_payload))
    legacy_transaction["schema_version"] = 1
    adversarial_transactions.append(("legacy-schema", legacy_transaction))
    missing_w2_transaction = json.loads(json.dumps(transaction_payload))
    del missing_w2_transaction["build"]["w2_authority"]
    adversarial_transactions.append(("missing-w2", missing_w2_transaction))
    partial_w2_transaction = json.loads(json.dumps(transaction_payload))
    del partial_w2_transaction["build"]["w2_authority"]["w2_expected_call_inventory_sha256"]
    adversarial_transactions.append(("partial-w2", partial_w2_transaction))
    foreign_w2_transaction = json.loads(json.dumps(transaction_payload))
    foreign_w2_transaction["build"]["w2_authority"]["w2_database_authority"]["kind"] = (
        "foreign_w2_receipt"
    )
    adversarial_transactions.append(("foreign-w2", foreign_w2_transaction))
    open_w2_transaction = json.loads(json.dumps(transaction_payload))
    open_w2_transaction["build"]["w2_authority"]["w2_database_authority_closed"] = False
    adversarial_transactions.append(("open-w2", open_w2_transaction))
    missing_w2_receipt_binding = json.loads(json.dumps(transaction_payload))
    del missing_w2_receipt_binding["receipt"]["w2_authority_identity_sha256"]
    adversarial_transactions.append(("missing-w2-receipt-binding", missing_w2_receipt_binding))
    for label, adversarial_transaction in adversarial_transactions:
        trust_manifest["chain_state"] = {
            "latest_checkpoint_transaction": adversarial_transaction,
        }
        trust_manifest_path.write_text(json.dumps(trust_manifest), encoding="utf-8")
        rejected = _run_python(resolver, env=resolver_env)
        assert rejected.returncode == 1, label
        assert not output_path.exists(), label

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
    del candidate_transaction["receipt"]
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
        "EXPECTED_W2_AUTHORITY_IDENTITY_SHA256": w2_authority.identity_sha256,
        "EXPECTED_W2_DATABASE_AUTHORITY_SHA256": (w2_authority.database_authority_sha256),
        "EXPECTED_W2_EXPECTED_CALL_COUNT": str(w2_authority.expected_call_count),
        "EXPECTED_W2_EXPECTED_CALL_INVENTORY_SHA256": (w2_authority.expected_call_inventory_sha256),
        "EXPECTED_W2_DATABASE_AUTHORITY_CLOSED": "true",
        "PLAN_MANIFEST_PATH": str(plan_manifest_path),
        "TRUST_MANIFEST_PATH": str(trust_manifest_path),
        "CHECKPOINT_MANIFEST_PATH": str(checkpoint_manifest_path),
        "SOURCE_CHECKPOINT_ARTIFACT": checkpoint_name,
        "SOURCE_RUN_ID": source_run_id,
        "SOURCE_RUN_ATTEMPT": "1",
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

    missing_candidate_w2 = json.loads(json.dumps(candidate_transaction))
    del missing_candidate_w2["build"]["w2_authority"]
    candidate_transaction_path.write_text(
        json.dumps(missing_candidate_w2),
        encoding="utf-8",
    )
    candidate_without_w2 = _run_python(attestation, env=attestation_env)
    assert candidate_without_w2.returncode == 1
    assert "built build has a foreign field shape" in candidate_without_w2.stdout
    candidate_transaction_path.write_text(
        json.dumps(candidate_transaction),
        encoding="utf-8",
    )

    report_without_w2 = dict(report)
    del report_without_w2["w2_database_authority"]
    report_path.write_text(
        json.dumps(report_without_w2, sort_keys=True),
        encoding="utf-8",
    )
    missing_report_w2 = _run_python(attestation, env=attestation_env)
    assert missing_report_w2.returncode == 1
    assert "report W2 authority" in missing_report_w2.stdout
    report_path.write_bytes(report_bytes)

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
    payload_builder = _embedded_python(dispatch, "EXACT_WORKFLOW_DISPATCH_PAYLOAD")
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
    payload_path = tmp_path / "dispatch-payload.json"
    payload_result = _run_python(
        payload_builder,
        env={
            "ARTIFACT_DIGEST": "sha256:" + "d" * 64,
            "ARTIFACT_ID": "701",
            "ARTIFACT_NAME": "full-extraction-next-manifest-12345-iter-2-run-9-attempt-1",
            "BACKFILL_ENDPOINTS": "",
            "BACKFILL_PATTERNS": "",
            "CHAIN_ID": "12345",
            "CHUNK_PROFILE": "standard",
            "CONCURRENCY": "6",
            "DIRECT_PARALLELISM": "2",
            "DIRECT_REQUEST_PROFILE": "conservative",
            "DIRECT_TIMEOUT_CAP_MINUTES": "30",
            "DISPATCH_PAYLOAD_PATH": str(payload_path),
            "MATRIX_BATCH_SIZE": "64",
            "MAX_ITERATIONS": "auto",
            "NETWORK_MODE": "vpn",
            "NEXT_CONCURRENCY": "6",
            "NEXT_ITERATION": "2",
            "PARENT_RUN_ID": "9",
            "PUBLISH": "false",
            "RETRY_PIPELINE_FAILURES": "true",
            "VPN_PARALLELISM": "6",
            "WORKFLOW_REF": "main",
            "WORKFLOW_SHA": pinned_source_sha,
        },
    )
    assert payload_result.returncode == 0, payload_result.stderr or payload_result.stdout
    payload_document = json.loads(payload_path.read_text(encoding="utf-8"))
    assert set(payload_document) == {"inputs", "ref"}
    assert payload_document["ref"] == "main"
    assert "return_run_details" not in payload_document
    assert payload_document["inputs"]["lane_manifest_artifact_id"] == "701"
    assert payload_document["inputs"]["workflow_sha"] == pinned_source_sha
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
        "url": expected_api_url,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": trusted_branch_tip_sha,
        "path": ".github/workflows/full-extraction.yml",
        "run_attempt": 1,
        "workflow_id": 77,
    }
    details_path.write_text(json.dumps(details) + "\n", encoding="utf-8")
    provenance_env = {
        "CHILD_DETAILS_PATH": str(details_path),
        "EXPECTED_CHILD_API_URL": expected_api_url,
        "EXPECTED_CHILD_BRANCH": "main",
        "EXPECTED_CHILD_RUN_ID": "42",
        "EXPECTED_RUN_NAME": expected_title,
        "EXPECTED_CHILD_URL": expected_html_url,
        "EXPECTED_WORKFLOW_ID": "77",
        "EXPECTED_WORKFLOW_PATH": ".github/workflows/full-extraction.yml",
        "TRUSTED_BRANCH_TIP_SHA": trusted_branch_tip_sha,
        "WORKFLOW_SHA": pinned_source_sha,
    }
    accepted = _run_python(provenance_validator, env=provenance_env)
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout

    for key, invalid_value in (
        ("id", 43),
        ("display_title", "Full Extraction chain=other iteration=2"),
        ("html_url", "https://github.example/acme/nbadb/actions/runs/43"),
        ("url", "https://api.github.example/repos/acme/nbadb/actions/runs/43"),
        ("event", "schedule"),
        ("head_branch", "release"),
        ("head_sha", "c" * 40),
        ("path", ".github/workflows/other.yml"),
        ("run_attempt", 2),
        ("workflow_id", 78),
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

    response_path.write_text(
        json.dumps(
            {
                "workflow_run_id": 42,
                "html_url": expected_html_url,
                "run_url": expected_api_url,
                "unexpected": "field",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    extra_response_field = _run_python(response_parser, env=response_env)
    assert extra_response_field.returncode == 1
    assert "did not return an exact child identity" in extra_response_field.stderr

    payload = dispatch.index('payload = {\n              "ref"')
    enqueue = dispatch.index("/actions/workflows/full-extraction.yml/dispatches")
    response = dispatch.index('response.get("workflow_run_id")', enqueue)
    exact_get = dispatch.index('"$child_run_api_url" > "$child_details_path"', response)
    provenance = dispatch.index("self-dispatched child provenance does not match", exact_get)
    acknowledgement = dispatch.index("child_acknowledged=true", provenance)
    assert payload < enqueue < response < exact_get < provenance < acknowledgement
    assert "gh workflow run full-extraction.yml" not in dispatch
    assert "# CHILD_RUN_MATCHER" not in dispatch
    assert '-H "X-GitHub-Api-Version: 2026-03-10"' in dispatch
    assert '"return_run_details"' not in dispatch
    assert "set(response) != {" in dispatch
    assert "GITHUB_SERVER_URL" in dispatch
    assert "GITHUB_API_URL" in dispatch
    assert "gh api \\\n              --method GET" in dispatch
    assert "id: redispatch_guard" in redispatch_guard
    assert 'handle.write(f"workflow_id={workflow_id}\\n")' in redispatch_guard
    assert 'definition.get("path") != os.environ["WORKFLOW_PATH"]' in redispatch_guard
    assert 'definition.get("state") != "active"' in redispatch_guard
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
    assert "vpn-capacity-connected-run-${{ github.run_id }}-attempt-" in workflow
    assert "full-extraction-vpn-auth-circuit-run-${{ github.run_id }}-attempt-" in workflow

    capacity = _job_block(workflow, "vpn_capacity")
    extract = _job_block(workflow, "extract")
    lane_control = _job_block(workflow, "lane_control")
    checkpoint = _job_block(workflow, "checkpoint")
    plan = _job_block(workflow, "plan")
    for block, step_name, artifact_name in (
        (
            capacity,
            "Publish connected VPN capacity marker",
            "vpn-capacity-connected-run-${{ github.run_id }}-attempt-",
        ),
        (
            extract,
            "Publish VPN auth circuit marker",
            "full-extraction-vpn-auth-circuit-run-${{ github.run_id }}-attempt-",
        ),
        (
            extract,
            "Retry VPN auth circuit marker publication",
            "full-extraction-vpn-auth-circuit-run-${{ github.run_id }}-attempt-",
        ),
        (
            lane_control,
            "Upload checkpoint candidate manifest",
            "full-extraction-checkpoint-candidate-{0}-run-{1}-attempt-{2}",
        ),
        (
            checkpoint,
            "Upload checkpoint artifact",
            "needs.lane_control.outputs.checkpoint-artifact-name",
        ),
        (
            checkpoint,
            "Retry checkpoint artifact upload after stable absence",
            "needs.lane_control.outputs.checkpoint-artifact-name",
        ),
        (
            checkpoint,
            "Upload committed next manifest",
            "needs.lane_control.outputs.artifact-name",
        ),
        (
            plan,
            "Upload dependent workload bundle",
            "full-extraction-dependent-workload-${{ env.ACTIVE_CHAIN_ID }}-run-",
        ),
    ):
        step = _step_block(block, step_name)
        assert "overwrite: false" in step
        assert "overwrite: true" not in step
        assert artifact_name in step


def test_planner_output_drives_exact_discovery_scope_cardinality(
    tmp_path: pathlib.Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
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
    operation_authority_path = tmp_path / "operation-authority.json"
    authority = _write_planner_operation_authority(
        operation_authority_path,
        monkeypatch,
        operation=OperationKind.EXTRACT,
        manifest_lane_count=len(lanes),
    )

    assert (
        full_extraction_main(
            [
                "plan",
                "--operation-authority-path",
                str(operation_authority_path),
                "--lane-manifest-json",
                json.dumps(
                    {
                        "manifest_version": 5,
                        "chain_id": "fixture-chain",
                        "workflow_source_sha": "a" * 40,
                        "lanes": lanes,
                        "provider_authority": expected_nba_api_provider_authority(),
                        "assurance_admission": _assurance_admission().to_dict(),
                    }
                ),
                "--max-matrix-lanes",
                "4",
                "--vpn-slot-count",
                "2",
                "--output-path",
                str(output_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    planned_manifest = json.loads(output_path.read_text(encoding="utf-8"))
    discovery = _load_discovery_seed_module()

    # The authorized plan emits one exact authority-bound matrix wave: every lane
    # dispatched, nothing deferred, and no FreeExecution authority of any kind.
    assert planned_manifest["matrix_lane_count"] == len(lanes)
    assert planned_manifest["deferred_lane_count"] == 0
    assert len(planned_manifest["github_matrix"]["include"]) == len(lanes)
    assert len(planned_manifest["lanes"]) == len(lanes)
    assert {row["lane_id"] for row in planned_manifest["lanes"]} == {
        row["lane_id"] for row in lanes
    }
    assert planned_manifest["operation"] == "extract"
    assert planned_manifest["operation_authority"] == authority.to_dict()
    assert planned_manifest["operation_authority_sha256"] == authority.authority_sha256
    assert planned_manifest["vpn_slot_count"] == 2
    assert planned_manifest["direct_slot_count"] == 0
    assert "free_execution_admission" not in planned_manifest
    assert "free_execution_intent_manifest" not in planned_manifest
    # The dispatched matrix wave carries exactly the planned discovery scope.
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
    logical_scope_manifest = dict(planned_manifest)
    logical_scope_manifest.pop("github_matrix")
    assert set(discovery.game_discovery_pairs(logical_scope_manifest)) == {
        ("2022-23", "Regular Season"),
        ("2022-23", "Playoffs"),
        ("2023-24", "Regular Season"),
        ("2023-24", "Playoffs"),
    }
    assert set(discovery.player_team_season_pairs(logical_scope_manifest)) == {
        ("2021-22", "Regular Season"),
        ("2022-23", "Regular Season"),
    }
    assert [
        scope.seasons for scope in discovery.player_discovery_scopes(logical_scope_manifest)
    ] == [("2020-21",), ("2021-22",), ("2020-21", "2021-22")]


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
    assert "Run ID, name, database digest, artifact ID, and archive digest" in restore
    assert "STATE_ARTIFACT_ID: ${{ matrix.state_artifact_id }}" in restore
    assert "STATE_ARTIFACT_ARCHIVE_DIGEST: ${{ matrix.state_artifact_archive_digest }}" in restore
    assert "workflow_source_provenance.py resolve-artifact" in restore
    assert "workflow_source_provenance.py download-artifact" in restore
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
    assert "durable lane state receipt does not match the manifest pointer" in restore
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
                        {"lane_id": "fresh-1", "resume_only": False},
                        {"lane_id": "fresh-2", "resume_only": False},
                        {"lane_id": "resume", "resume_only": True},
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
        ("1", [False], 1),
        ("2", [False, False], 2),
        ("2", [False], 1),
        ("3", [False] * 3, 3),
        ("4", [False] * 4, 4),
        ("5", [False] * 5, 5),
        ("6", [False] * 6, 6),
    ],
)
def test_configured_auth_capacity_gate_matches_executable_lane_count(
    tmp_path: pathlib.Path,
    requested_parallelism: str,
    resume_only: list[bool],
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
            "ACTIVE_LANE_COUNT": str(sum(not value for value in resume_only)),
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
            "resume_only values must be exact booleans",
        ),
        (
            {"include": [{"lane_id": "resume", "resume_only": True}]},
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
        ("direct", "configured", "1", False),
        ("vpn", "token", "1", False),
        ("vpn", "configured", "0", True),
    ],
)
def test_vpn_capacity_gate_skips_nonconfigured_or_nonexecutable_waves(
    tmp_path: pathlib.Path,
    effective_mode: str,
    auth_source: str,
    active_lane_count: str,
    resume_only: bool,
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


def test_capacity_blocked_plan_exposes_no_direct_matrix_lane() -> None:
    workflow = _workflow_text()
    plan = _job_block(workflow, "plan")
    lane_control = _job_block(workflow, "lane_control")
    build_manifest = _step_block(plan, "Build lane manifest")
    helper = _FULL_EXTRACTION_HANDOFFS_PATH.read_text(encoding="utf-8")
    finalize = _step_block(plan, "Finalize operation-authority-bound lane manifest")

    assert 'effective_matrix_batch_size="$MATRIX_BATCH_SIZE"' in helper
    assert '--max-matrix-lanes "$effective_matrix_batch_size"' in helper
    assert '--vpn-slot-count "$VPN_PARALLELISM"' in helper
    assert "vpn_matrix_cap" not in helper
    assert "OPERATION_AUTHORITY_PATH: ${{ steps.operation_authority.outputs.path }}" in (
        build_manifest
    )
    assert 'manifest.get("operation_authority") != authority_payload' in finalize
    assert "matrix_rows" in finalize
    assert "len(matrix_rows) != authority.manifest_lane_count" in finalize
    assert (
        "needs.plan.outputs.operation-authority-status == 'validated'"
        in lane_control.split("    runs-on:", 1)[0]
    )
    assert (
        "free-execution-mutations-authorized == 'true'" in lane_control.split("    runs-on:", 1)[0]
    )


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


def test_extract_free_direct_slot_uses_one_non_cancelling_serial_queue() -> None:
    workflow = _workflow_text()
    plan = _job_block(workflow, "plan")
    extract = _job_block(workflow, "extract")
    extract_strategy = extract.split("    strategy:\n", 1)[1].split("    concurrency:\n", 1)[0]
    lane_control = _step_block(
        _job_block(workflow, "lane_control"),
        "Prepare next manifest",
    )

    assert "vpn-slot-count: ${{ steps.manifest.outputs.vpn-slot-count }}" in plan
    assert "execution-slot-count: ${{ steps.manifest.outputs.execution-slot-count }}" in plan
    assert '--vpn-slot-count "$VPN_PARALLELISM"' in plan
    assert "vpn-slot-count={manifest.get('vpn_slot_count', 0)}" in plan
    assert (
        "execution-slot-count={authority.requested_vpn_parallelism "
        "+ authority.requested_direct_parallelism}"
    ) in plan
    # Each execution slot serializes exactly one lane at a time without cancelling
    # the lane already holding the slot.
    assert "group: nbadb-free-direct-provider-slot-${{ matrix.execution_slot }}" in extract
    assert "cancel-in-progress: false" in extract
    assert "max-parallel: 1" in extract
    assert "'token' && '1' || inputs.vpn_parallelism" not in extract_strategy
    assert "--vpn-slot-count 0" in lane_control


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
    assert "DIRECT_REQUEST_PROFILE: ${{ inputs.direct_request_profile }}" in configure
    assert 'if [ "$EFFECTIVE_NETWORK_MODE" = "direct" ]; then' in configure
    assert "direct|conservative)" in configure
    assert "seed_concurrency=2" in configure
    assert "seed_rate_limit=2" in configure
    assert "moderate)" in configure
    assert "seed_concurrency=4" in configure
    assert "seed_rate_limit=4" in configure
    assert "aggressive)" in configure
    assert "seed_concurrency=6" in configure
    assert "seed_rate_limit=5" in configure
    assert "turbo)" in configure
    assert "seed_concurrency=8" in configure
    assert "seed_rate_limit=6" in configure
    assert "conservative)" in configure
    assert "seed_concurrency=3" in configure
    assert "seed_rate_limit=2" in configure
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
            "NBADB_RATE_LIMIT=5\nNBADB_DISCOVERY_CONCURRENCY=6\n"
            "NBADB_DISCOVERY_SEED_CONCURRENCY=6\n",
        ),
        (
            "direct",
            "turbo",
            "NBADB_RATE_LIMIT=6\nNBADB_DISCOVERY_CONCURRENCY=8\n"
            "NBADB_DISCOVERY_SEED_CONCURRENCY=8\n",
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
            "DIRECT_REQUEST_PROFILE": profile,
            "GITHUB_ENV": str(github_env),
        },
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert github_env.read_text(encoding="utf-8") == expected_env


def test_chained_discovery_seed_restores_exact_prior_run_artifact() -> None:
    workflow = _workflow_text()
    guard = _job_block(workflow, "workflow_guard")
    seed = _job_block(_workflow_text(), "discovery_seed")
    resolver = _step_block(seed, "Resolve prior discovery artifact receipt")
    download = _step_block(seed, "Download exact prior discovery artifact")
    restore = _step_block(seed, "Restore prior discovery artifacts")

    assert "actions: read" in guard
    assert "- name: Validate full extraction attempt" in guard
    assert "FULL_EXTRACTION_ATTEMPT_GATE_ROLE: primary" in guard
    assert "actions: read" in seed
    assert "- name: Resolve prior discovery artifact receipt" in seed
    assert (
        "if: ${{ inputs.lane_manifest_run_id != '' || inputs.resume_source_run_id != '' }}"
    ) in resolver
    assert "github.run_attempt > 1" not in seed
    assert (
        "python .github/scripts/full_extraction_handoffs.py "
        "resolve-prior-discovery-artifact-receipt"
    ) in resolver
    assert "OWNER_RECHECK_PATH: ${{ runner.temp }}/workflow-provenance/" in resolver
    assert "artifact-ids: ${{ steps.prior_discovery.outputs.artifact_id }}" in download
    assert "run-id: ${{ steps.prior_discovery.outputs.source_run_id }}" in download
    assert "digest-mismatch: error" in download
    assert "gh run download" not in seed
    assert "--pattern" not in resolver
    assert "- name: Restore prior discovery artifacts" in seed
    assert "DISCOVERY_SOURCE_KIND" in restore
    assert "source manifest layout is ambiguous" in restore
    assert "requires exactly one active lane manifest" in restore
    assert "restored discovery manifest" in restore
    assert "Discovery restore rejects symbolic links" in restore
    assert "Discovery restore artifact layout is ambiguous" in restore
    assert "Canonical discovery bundle layout is incomplete" in restore
    assert seed.index("- name: Resolve prior discovery artifact receipt") < seed.index(
        "- name: Download exact prior discovery artifact"
    )
    assert seed.index("- name: Download exact prior discovery artifact") < seed.index(
        "- name: Restore prior discovery artifacts"
    )
    assert seed.index("- name: Restore prior discovery artifacts") < seed.index(
        "- name: Seed discovery artifacts"
    )


def _attempt_gate_run(
    *,
    run_id: int,
    title: str,
    status: str,
    conclusion: str | None,
    event: str = "workflow_dispatch",
) -> dict[str, object]:
    return {
        "conclusion": conclusion,
        "display_title": title,
        "event": event,
        "html_url": f"https://github.test/acme/nbadb/actions/runs/{run_id}",
        "id": run_id,
        "status": status,
    }


def _attempt_gate_pages(runs: Sequence[object]) -> list[dict[str, object]]:
    return [{"total_count": len(runs), "workflow_runs": runs}]


def _run_attempt_gate(
    tmp_path: pathlib.Path,
    *,
    overrides: dict[str, str] | None = None,
    role: str = "partial",
    observations: list[object] | None = None,
) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "FULL_EXTRACTION_ATTEMPT_GATE_POLL_INTERVAL_SECONDS": "0",
        "FULL_EXTRACTION_ATTEMPT_GATE_ROLE": role,
        "FULL_EXTRACTION_CHAIN_INPUT": "",
        "FULL_EXTRACTION_EXPECTED_RUN_NAME": ("Full Extraction chain=fixture iteration=1"),
        "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_DIGEST": "",
        "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_ID": "",
        "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "",
        "FULL_EXTRACTION_LANE_MANIFEST_JSON_PRESENT": "false",
        "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "",
        "FULL_EXTRACTION_OPERATION": "extract",
        "FULL_EXTRACTION_RESUME_SOURCE_RUN_ID": "",
        "GITHUB_REPOSITORY": "acme/nbadb",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "101",
    }
    if overrides:
        env.update(overrides)
    if observations is not None:
        env.update(_gh_fixture_env(tmp_path, observations))
    return _run_python(
        _FULL_EXTRACTION_ATTEMPT_GATE_PATH.read_text(encoding="utf-8"),
        env=env,
        cwd=tmp_path,
    )


def test_every_job_runs_shared_attempt_gate_immediately_after_exact_checkout() -> None:
    workflow_text = _workflow_text()
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]

    assert len(jobs) == 16
    assert (
        "FULL_EXTRACTION_LANE_MANIFEST_JSON_PRESENT: ${{ inputs.lane_manifest_json != '' }}"
    ) in workflow_text
    assert "FULL_EXTRACTION_LANE_MANIFEST_JSON:" not in workflow_text
    for job_name, job in jobs.items():
        if job_name == "free_execution_blocked":
            assert job["permissions"] == {}
            assert len(job["steps"]) == 1
            assert job["steps"][0]["name"] == "Stop before provider execution"
            continue
        assert job["permissions"]["actions"] in {"read", "write"}
        steps = job["steps"]
        checkout_index = next(
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("actions/checkout@")
        )
        gate_index = next(
            index
            for index, step in enumerate(steps)
            if step.get("name") == "Validate full extraction attempt"
        )
        assert gate_index == checkout_index + 1, job_name
        assert checkout_index == (1 if job_name == "extract" else 0), job_name
        assert steps[checkout_index]["with"]["ref"] == "${{ env.WORKFLOW_SOURCE_SHA }}"
        assert (
            steps[gate_index]["run"]
            == "python3 .github/scripts/validate_full_extraction_attempt.py"
        )
        expected_role = (
            "primary"
            if job_name == "workflow_guard"
            else (
                "publication_reconcile"
                if job_name == "publish"
                else ("dispatch_reconcile" if job_name == "dispatch_next" else "partial")
            )
        )
        assert steps[gate_index]["env"]["FULL_EXTRACTION_ATTEMPT_GATE_ROLE"] == expected_role

    def dependency_closure(job_name: str) -> set[str]:
        discovered: set[str] = set()
        pending = [job_name]
        while pending:
            current = pending.pop()
            raw_needs = jobs[current].get("needs", [])
            needs = [raw_needs] if isinstance(raw_needs, str) else list(raw_needs)
            for dependency in needs:
                assert dependency in jobs, (current, dependency)
                if dependency not in discovered:
                    discovered.add(dependency)
                    pending.append(dependency)
        return discovered

    for job_name in jobs:
        if job_name != "workflow_guard":
            assert "workflow_guard" in dependency_closure(job_name), job_name

    guard_concurrency = jobs["workflow_guard"]["concurrency"]
    assert guard_concurrency == {
        "group": (
            "full-extraction-attempt-"
            "${{ inputs.chain_id || github.run_id }}-${{ inputs.iteration }}"
        ),
        "cancel-in-progress": False,
    }
    assert "network_mode" not in guard_concurrency["group"]
    assert jobs["extract"]["steps"][0]["name"] == "Initialize lane job budget"
    assert jobs["extract"]["steps"][1].get("uses", "").startswith("actions/checkout@")


@pytest.mark.parametrize(
    ("overrides", "expected_mode"),
    [
        ({}, "fresh"),
        ({"FULL_EXTRACTION_LANE_MANIFEST_JSON_PRESENT": "true"}, "inline"),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "manifest",
                "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "202",
            },
            "lane_source",
        ),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_DIGEST": "a" * 64,
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_ID": "701",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "manifest",
                "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "202",
            },
            "lane_source",
        ),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_OPERATION": "continue",
                "FULL_EXTRACTION_RESUME_SOURCE_RUN_ATTEMPT": "1",
                "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_DIGEST": f"sha256:{'a' * 64}",
                "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_ID": "702",
                "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_NAME": "next-manifest",
                "FULL_EXTRACTION_RESUME_SOURCE_RUN_ID": "203",
            },
            "continue",
        ),
    ],
)
def test_attempt1_accepts_each_exact_source_mode(
    tmp_path: pathlib.Path,
    overrides: dict[str, str],
    expected_mode: str,
) -> None:
    result = _run_attempt_gate(tmp_path, overrides=overrides)

    assert result.returncode == 0, result.stderr or result.stdout
    assert f"mode={expected_mode}" in result.stdout


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"GITHUB_RUN_ID": "0"}, "current workflow run ID must be a positive integer"),
        (
            {"GITHUB_RUN_ATTEMPT": "false"},
            "current workflow run attempt must be a positive integer",
        ),
        (
            {"FULL_EXTRACTION_LANE_MANIFEST_JSON_PRESENT": "maybe"},
            "presence must be exactly true or false",
        ),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "manifest",
                "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "202",
                "FULL_EXTRACTION_RESUME_SOURCE_RUN_ID": "203",
            },
            "mutually exclusive",
        ),
        (
            {
                "FULL_EXTRACTION_LANE_MANIFEST_JSON_PRESENT": "true",
                "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "202",
            },
            "cannot be combined",
        ),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "manifest",
                "FULL_EXTRACTION_RESUME_SOURCE_RUN_ID": "203",
            },
            "cannot be combined with lane artifact metadata",
        ),
        (
            {"FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "orphan"},
            "requires lane_manifest_run_id",
        ),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "manifest",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_ID": "701",
                "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "202",
            },
            "must be provided together",
        ),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "202",
            },
            "requires lane_manifest_artifact_name",
        ),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_DIGEST": "not-a-digest",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_ID": "701",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "manifest",
                "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "202",
            },
            "must be sha256",
        ),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "manifest",
                "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "101",
            },
            "must differ from the current workflow run ID",
        ),
        (
            {
                "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
                "FULL_EXTRACTION_RESUME_SOURCE_RUN_ATTEMPT": "1",
                "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_DIGEST": f"sha256:{'a' * 64}",
                "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_ID": "702",
                "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_NAME": "next-manifest",
                "FULL_EXTRACTION_RESUME_SOURCE_RUN_ID": "invalid",
            },
            "must be a positive integer",
        ),
        (
            {
                "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "manifest",
                "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "202",
            },
            "requires an explicit chain_id",
        ),
    ],
)
def test_attempt1_rejects_mixed_or_invalid_source_modes(
    tmp_path: pathlib.Path,
    overrides: dict[str, str],
    message: str,
) -> None:
    result = _run_attempt_gate(tmp_path, overrides=overrides)

    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize("mode", ["fresh", "inline"])
@pytest.mark.parametrize("reconcile_role", ["dispatch_reconcile", "publication_reconcile"])
def test_attempt2_requires_cross_run_source_except_explicit_reconciliation_roles(
    tmp_path: pathlib.Path,
    mode: str,
    reconcile_role: str,
) -> None:
    overrides = {"GITHUB_RUN_ATTEMPT": "2"}
    if mode == "inline":
        overrides["FULL_EXTRACTION_LANE_MANIFEST_JSON_PRESENT"] = "true"
    rejected = _run_attempt_gate(tmp_path / "partial", overrides=overrides)
    stable = _attempt_gate_pages(
        [
            _attempt_gate_run(
                run_id=101,
                title="Full Extraction chain=fixture iteration=1",
                status="in_progress",
                conclusion=None,
            )
        ]
    )
    accepted = _run_attempt_gate(
        tmp_path / "publication",
        overrides=overrides,
        role=reconcile_role,
        observations=[stable, stable, stable],
    )

    assert rejected.returncode == 1
    assert "full and partial workflow reruns are unsafe" in rejected.stderr
    assert accepted.returncode == 0, accepted.stderr or accepted.stdout


@pytest.mark.parametrize(
    "role",
    ["partial", "primary"],
)
@pytest.mark.parametrize(
    "source_overrides",
    [
        {
            "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
            "FULL_EXTRACTION_LANE_MANIFEST_ARTIFACT_NAME": "manifest",
            "FULL_EXTRACTION_LANE_MANIFEST_RUN_ID": "202",
        },
        {
            "FULL_EXTRACTION_CHAIN_INPUT": "fixture",
            "FULL_EXTRACTION_OPERATION": "continue",
            "FULL_EXTRACTION_RESUME_SOURCE_RUN_ATTEMPT": "1",
            "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_DIGEST": f"sha256:{'a' * 64}",
            "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_ID": "702",
            "FULL_EXTRACTION_RESUME_SOURCE_MANIFEST_ARTIFACT_NAME": "next-manifest",
            "FULL_EXTRACTION_RESUME_SOURCE_RUN_ID": "203",
        },
    ],
)
def test_primary_and_partial_attempt2_reject_before_inventory(
    tmp_path: pathlib.Path,
    source_overrides: dict[str, str],
    role: str,
) -> None:
    result = _run_attempt_gate(
        tmp_path,
        overrides={"GITHUB_RUN_ATTEMPT": "2", **source_overrides},
        role=role,
    )

    assert result.returncode == 1
    assert "full and partial workflow reruns are unsafe" in result.stderr
    assert not (tmp_path / "gh-calls.jsonl").exists()


@pytest.mark.parametrize("role", ["dispatch_reconcile", "publication_reconcile"])
def test_reconciliation_attempt2_runs_stable_duplicate_admission(
    tmp_path: pathlib.Path,
    role: str,
) -> None:
    current = _attempt_gate_run(
        run_id=101,
        title="Full Extraction chain=fixture iteration=1",
        status="in_progress",
        conclusion=None,
    )
    pages = _attempt_gate_pages([current])
    result = _run_attempt_gate(
        tmp_path,
        overrides={"GITHUB_RUN_ATTEMPT": "2"},
        role=role,
        observations=[pages, pages, pages],
    )

    assert result.returncode == 0, result.stderr or result.stdout
    calls = [
        json.loads(line)
        for line in (tmp_path / "gh-calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(calls) == 3
    for call in calls:
        assert call[:5] == ["api", "--method", "GET", "--paginate", "--slurp"]
        assert "/repos/acme/nbadb/actions/workflows/full-extraction.yml/runs" in call
        assert "event=workflow_dispatch" not in call
        assert "per_page=100" in call
        assert "Accept: application/vnd.github+json" in call
        assert "X-GitHub-Api-Version: 2026-03-10" in call


@pytest.mark.parametrize(
    "conclusion",
    ["action_required", "cancelled", "failure", "timed_out"],
)
def test_duplicate_admission_allows_only_explicit_replaceable_conclusions(
    tmp_path: pathlib.Path,
    conclusion: str,
) -> None:
    title = "Full Extraction chain=fixture iteration=1"
    runs = [
        _attempt_gate_run(
            run_id=101,
            title=title,
            status="in_progress",
            conclusion=None,
        ),
        _attempt_gate_run(
            run_id=202,
            title=title,
            status="completed",
            conclusion=conclusion,
        ),
    ]
    pages = _attempt_gate_pages(runs)
    result = _run_attempt_gate(
        tmp_path,
        role="primary",
        observations=[pages, pages, pages],
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Duplicate workflow admission passed" in result.stdout


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [
        ("queued", None),
        ("in_progress", None),
        ("completed", "success"),
        ("completed", None),
        ("completed", "neutral"),
        ("completed", "skipped"),
        ("completed", "stale"),
        ("completed", "unknown"),
    ],
)
def test_duplicate_admission_blocks_every_nonreplaceable_exact_title(
    tmp_path: pathlib.Path,
    status: str,
    conclusion: str | None,
) -> None:
    run = _attempt_gate_run(
        run_id=202,
        title="Full Extraction chain=fixture iteration=1",
        status=status,
        conclusion=conclusion,
    )
    current = _attempt_gate_run(
        run_id=101,
        title="Full Extraction chain=fixture iteration=1",
        status="in_progress",
        conclusion=None,
    )
    pages = _attempt_gate_pages([current, run])
    result = _run_attempt_gate(
        tmp_path,
        role="primary",
        observations=[pages, pages, pages],
    )

    assert result.returncode == 1
    assert "refusing duplicate full-extraction workflow run" in result.stderr


def test_duplicate_admission_filters_events_only_after_complete_normalization(
    tmp_path: pathlib.Path,
) -> None:
    title = "Full Extraction chain=fixture iteration=1"
    non_dispatch_success = _attempt_gate_run(
        run_id=202,
        title=title,
        status="completed",
        conclusion="success",
        event="push",
    )
    dispatch_failure = _attempt_gate_run(
        run_id=203,
        title=title,
        status="completed",
        conclusion="failure",
    )
    current = _attempt_gate_run(
        run_id=101,
        title=title,
        status="in_progress",
        conclusion=None,
    )
    pages = _attempt_gate_pages([current, non_dispatch_success, dispatch_failure])
    accepted = _run_attempt_gate(
        tmp_path / "non-dispatch",
        role="primary",
        observations=[pages, pages, pages],
    )

    malformed_event = dict(non_dispatch_success)
    malformed_event.pop("event")
    malformed_pages = _attempt_gate_pages([current, malformed_event])
    rejected = _run_attempt_gate(
        tmp_path / "malformed-event",
        role="primary",
        observations=[malformed_pages] * 3,
    )

    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    calls = [
        json.loads(line)
        for line in (tmp_path / "non-dispatch" / "gh-calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert all("event=workflow_dispatch" not in call for call in calls)
    assert rejected.returncode == 1
    assert "inventory entry is malformed" in rejected.stderr


def test_duplicate_admission_scans_past_one_thousand_unfiltered_runs(
    tmp_path: pathlib.Path,
) -> None:
    title = "Full Extraction chain=fixture iteration=1"
    runs = [
        _attempt_gate_run(
            run_id=1_000 + index,
            title=f"Unrelated workflow run {index}",
            status="completed",
            conclusion="success",
            event="push",
        )
        for index in range(1_000)
    ]
    runs.append(
        _attempt_gate_run(
            run_id=9_999,
            title=title,
            status="completed",
            conclusion="success",
        )
    )
    runs.append(
        _attempt_gate_run(
            run_id=101,
            title=title,
            status="in_progress",
            conclusion=None,
        )
    )
    pages = [
        {
            "total_count": len(runs),
            "workflow_runs": runs[offset : offset + 100],
        }
        for offset in range(0, len(runs), 100)
    ]

    result = _run_attempt_gate(
        tmp_path,
        role="primary",
        observations=[pages, pages, pages],
    )

    assert result.returncode == 1
    assert "refusing duplicate full-extraction workflow run" in result.stderr
    assert "9999:completed:success" in result.stderr
    calls = [
        json.loads(line)
        for line in (tmp_path / "gh-calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert all("event=workflow_dispatch" not in call for call in calls)


def test_duplicate_admission_requires_complete_stable_paginated_inventory(
    tmp_path: pathlib.Path,
) -> None:
    title = "Full Extraction chain=fixture iteration=1"
    current = _attempt_gate_run(
        run_id=101,
        title=title,
        status="in_progress",
        conclusion=None,
    )
    failed = _attempt_gate_run(
        run_id=202,
        title=title,
        status="completed",
        conclusion="failure",
    )
    stable_pages = [
        {"total_count": 2, "workflow_runs": [current]},
        {"total_count": 2, "workflow_runs": [failed]},
    ]
    accepted = _run_attempt_gate(
        tmp_path / "stable",
        role="primary",
        observations=[
            _attempt_gate_pages([current]),
            stable_pages,
            stable_pages,
        ],
    )
    mutation = _run_attempt_gate(
        tmp_path / "mutation",
        role="primary",
        observations=[
            _attempt_gate_pages([current]),
            stable_pages,
            _attempt_gate_pages([current]),
        ],
    )
    omitted = _run_attempt_gate(
        tmp_path / "omitted",
        role="primary",
        observations=[
            [{"total_count": 2, "workflow_runs": [current]}],
        ]
        * 3,
    )

    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    assert mutation.returncode == 1
    assert "did not stabilize" in mutation.stderr
    assert omitted.returncode == 1
    assert "row count does not match total_count" in omitted.stderr


@pytest.mark.parametrize(
    ("current_run", "message"),
    [
        (None, "does not contain exactly one current workflow run"),
        (
            _attempt_gate_run(
                run_id=101,
                title="Wrong extraction title",
                status="in_progress",
                conclusion=None,
            ),
            "current workflow run inventory identity is invalid",
        ),
        (
            _attempt_gate_run(
                run_id=101,
                title="Full Extraction chain=fixture iteration=1",
                status="in_progress",
                conclusion=None,
                event="push",
            ),
            "current workflow run inventory identity is invalid",
        ),
    ],
)
def test_duplicate_admission_requires_exact_current_run_freshness_sentinel(
    tmp_path: pathlib.Path,
    current_run: dict[str, object] | None,
    message: str,
) -> None:
    pages = _attempt_gate_pages([] if current_run is None else [current_run])
    result = _run_attempt_gate(
        tmp_path,
        role="primary",
        observations=[pages, pages, pages],
    )

    assert result.returncode == 1
    assert message in result.stderr


def test_duplicate_admission_rejects_malformed_or_duplicate_run_ids(
    tmp_path: pathlib.Path,
) -> None:
    title = "Full Extraction chain=fixture iteration=1"
    malformed = _attempt_gate_run(
        run_id=202,
        title=title,
        status="completed",
        conclusion="failure",
    )
    malformed["id"] = "202"
    malformed_pages = _attempt_gate_pages([malformed])
    malformed_result = _run_attempt_gate(
        tmp_path / "malformed",
        role="primary",
        observations=[malformed_pages] * 3,
    )
    duplicate = _attempt_gate_run(
        run_id=202,
        title=title,
        status="completed",
        conclusion="failure",
    )
    duplicate_pages = [
        {"total_count": 2, "workflow_runs": [duplicate]},
        {"total_count": 2, "workflow_runs": [duplicate]},
    ]
    duplicate_result = _run_attempt_gate(
        tmp_path / "duplicate",
        role="primary",
        observations=[duplicate_pages] * 3,
    )

    assert malformed_result.returncode == 1
    assert "inventory entry is malformed" in malformed_result.stderr
    assert duplicate_result.returncode == 1
    assert "repeated a workflow run ID" in duplicate_result.stderr


def _discovery_receipt_resolver() -> str:
    return _helper_embedded_python("DISCOVERY_ARTIFACT_RECEIPT_RESOLVER")


def _discovery_artifact(
    *,
    artifact_id: int,
    name: str,
    source_run_id: int = 202,
    source_sha: str = "a" * 40,
) -> dict[str, object]:
    return {
        "id": artifact_id,
        "name": name,
        "digest": "sha256:" + f"{artifact_id:064x}",
        "size_in_bytes": 2048,
        "expired": False,
        "archive_download_url": (
            f"https://api.github.test/repos/acme/nbadb/actions/artifacts/{artifact_id}/zip"
        ),
        "workflow_run": {
            "id": source_run_id,
            "head_sha": source_sha,
        },
    }


def _run_discovery_receipt_resolver(
    tmp_path: pathlib.Path,
    artifacts: list[object],
    *,
    direct_artifact: object | None = None,
    inventory_observations: list[object] | None = None,
    owner_run: object | None = None,
    rechecked_owner_run: dict[str, object] | None = None,
    total_count: int | None = None,
    source_run_id: str = "202",
    current_run_id: str = "303",
    workflow_source_sha: str = "a" * 40,
) -> tuple[subprocess.CompletedProcess[str], pathlib.Path]:
    default_owner: dict[str, object] = {
        "conclusion": "failure",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": "a" * 40,
        "id": int(source_run_id),
        "path": ".github/workflows/full-extraction.yml",
        "repository": {"full_name": "acme/nbadb"},
        "run_attempt": 1,
        "status": "completed",
        "url": (f"https://api.github.test/repos/acme/nbadb/actions/runs/{source_run_id}"),
        "workflow_id": 99,
    }
    owner: dict[str, object] = dict(default_owner)
    if isinstance(owner_run, dict):
        owner.update(owner_run)  # ty: ignore[no-matching-overload]
    default_inventory = [
        {
            "total_count": len(artifacts) if total_count is None else total_count,
            "artifacts": artifacts,
        }
    ]
    observations = inventory_observations or [default_inventory] * 3
    if direct_artifact is None:
        direct_artifact = next(
            (
                artifact
                for artifact in artifacts
                if isinstance(artifact, dict)
                and artifact.get("name") == "canonical-discovery"
                and artifact.get("expired") is False
            ),
            next(
                (
                    artifact
                    for artifact in artifacts
                    if isinstance(artifact, dict)
                    and artifact.get("name") == "recovery-discovery-run-202-attempt-1"
                    and artifact.get("expired") is False
                ),
                artifacts[0] if artifacts else {},
            ),
        )
    output_path = tmp_path / "github-output.txt"
    recheck_path = tmp_path / "owner-recheck.json"
    recheck_path.parent.mkdir(parents=True, exist_ok=True)
    recheck_path.write_text(
        json.dumps(
            _owner_recheck_snapshot(
                rechecked_owner_run or owner,
                source_sha=workflow_source_sha,
            )
        ),
        encoding="utf-8",
    )
    fixture_env = _gh_fixture_env(
        tmp_path,
        [
            owner,
            *observations,
            direct_artifact,
            owner,
        ],
    )
    result = _run_python(
        _discovery_receipt_resolver(),
        env={
            **fixture_env,
            "CURRENT_RUN_ID": current_run_id,
            "DISCOVERY_ARTIFACT_NAME": "canonical-discovery",
            "DISCOVERY_RECEIPT_POLL_INTERVAL_SECONDS": "0",
            "DISCOVERY_RECOVERY_PREFIX": "recovery-discovery",
            "GITHUB_API_URL": "https://api.github.test",
            "GITHUB_OUTPUT": str(output_path),
            "GITHUB_REPOSITORY": "acme/nbadb",
            "MANIFEST_SOURCE_RUN_ID": source_run_id,
            "OWNER_RECHECK_PATH": str(recheck_path),
            "WORKFLOW_SOURCE_SHA": workflow_source_sha,
        },
        cwd=tmp_path,
    )
    return result, output_path


@pytest.mark.parametrize(
    ("name", "expected_kind"),
    [
        ("canonical-discovery", "canonical"),
        ("recovery-discovery-run-202-attempt-1", "recovery"),
    ],
)
def test_discovery_receipt_resolver_accepts_exact_cross_run_artifact(
    tmp_path: pathlib.Path,
    name: str,
    expected_kind: str,
) -> None:
    artifact = _discovery_artifact(artifact_id=701, name=name)
    result, output_path = _run_discovery_receipt_resolver(tmp_path, [artifact])

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "artifact_id=701",
        f"artifact_name={name}",
        f"artifact_digest={artifact['digest']}",
        f"source_kind={expected_kind}",
        "source_run_id=202",
    ]


def test_discovery_receipt_resolver_prefers_exact_canonical_artifact(
    tmp_path: pathlib.Path,
) -> None:
    canonical = _discovery_artifact(artifact_id=701, name="canonical-discovery")
    recovery = _discovery_artifact(
        artifact_id=702,
        name="recovery-discovery-run-202-attempt-1",
    )
    result, output_path = _run_discovery_receipt_resolver(
        tmp_path,
        [recovery, canonical],
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert output_path.read_text(encoding="utf-8").splitlines()[0] == "artifact_id=701"
    assert "source_kind=canonical" in output_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("case", "artifacts", "message"),
    [
        (
            "ambiguous-canonical",
            [
                _discovery_artifact(artifact_id=701, name="canonical-discovery"),
                _discovery_artifact(artifact_id=702, name="canonical-discovery"),
            ],
            "ambiguous unexpired canonical artifacts",
        ),
        (
            "ambiguous-recovery",
            [
                _discovery_artifact(
                    artifact_id=701,
                    name="recovery-discovery-run-202-attempt-1",
                ),
                _discovery_artifact(
                    artifact_id=702,
                    name="recovery-discovery-run-202-attempt-1",
                ),
            ],
            "ambiguous unexpired current-attempt recovery artifacts",
        ),
        (
            "malformed-recovery-name",
            [
                _discovery_artifact(
                    artifact_id=701,
                    name="recovery-discovery-run-202-attempt-latest",
                )
            ],
            "source discovery recovery artifact name is malformed",
        ),
        (
            "future-recovery-attempt",
            [
                _discovery_artifact(
                    artifact_id=701,
                    name="recovery-discovery-run-202-attempt-2",
                )
            ],
            "artifact attempt exceeds the workflow run attempt",
        ),
        (
            "missing-exact-artifact",
            [_discovery_artifact(artifact_id=701, name="unrelated")],
            "has no exact canonical or current-attempt recovery artifact",
        ),
    ],
)
def test_discovery_receipt_resolver_rejects_ambiguous_or_malformed_inventory(
    tmp_path: pathlib.Path,
    case: str,
    artifacts: list[object],
    message: str,
) -> None:
    case_dir = tmp_path / case
    result, _ = _run_discovery_receipt_resolver(case_dir, artifacts)

    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("digest", "sha256:not-a-digest", "inventory entry is malformed"),
        ("size_in_bytes", 0, "inventory entry is malformed"),
        (
            "expired",
            True,
            "has no exact canonical or current-attempt recovery artifact",
        ),
        (
            "archive_download_url",
            "https://api.github.test/wrong",
            "artifact REST identity is malformed",
        ),
        (
            "workflow_run",
            {"id": 999, "head_sha": "a" * 40},
            "artifact REST identity",
        ),
        (
            "workflow_run",
            {"id": 202, "head_sha": "b" * 40},
            "artifact REST identity",
        ),
    ],
)
def test_discovery_receipt_resolver_rejects_wrong_artifact_provenance(
    tmp_path: pathlib.Path,
    field: str,
    value: object,
    message: str,
) -> None:
    artifact = _discovery_artifact(artifact_id=701, name="canonical-discovery")
    artifact[field] = value
    result, _ = _run_discovery_receipt_resolver(tmp_path, [artifact])

    assert result.returncode == 1
    assert message in result.stderr


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "in_progress"),
        ("conclusion", None),
        ("conclusion", "action_required"),
        ("conclusion", "neutral"),
        ("conclusion", "skipped"),
        ("conclusion", "stale"),
        ("event", "push"),
        ("path", ".github/workflows/other.yml"),
        ("workflow_id", None),
        ("workflow_id", 0),
    ],
)
def test_discovery_receipt_resolver_requires_completed_source_workflow_identity(
    tmp_path: pathlib.Path,
    field: str,
    value: object,
) -> None:
    artifact = _discovery_artifact(artifact_id=701, name="canonical-discovery")
    owner_run: dict[str, object] = {
        "conclusion": "failure",
        "event": "workflow_dispatch",
        "head_sha": "a" * 40,
        "id": 202,
        "path": ".github/workflows/full-extraction.yml",
        "run_attempt": 1,
        "status": "completed",
        "workflow_id": 99,
    }
    owner_run[field] = value
    result, _ = _run_discovery_receipt_resolver(
        tmp_path,
        [artifact],
        owner_run=owner_run,
    )

    assert result.returncode == 1
    assert "source owner recheck snapshot is invalid" in result.stderr


def test_discovery_receipt_resolver_binds_cross_source_owner_artifact(
    tmp_path: pathlib.Path,
) -> None:
    owner_sha = "b" * 40
    artifact = _discovery_artifact(
        artifact_id=701,
        name="canonical-discovery",
        source_sha=owner_sha,
    )
    owner_run = {
        "conclusion": "failure",
        "event": "workflow_dispatch",
        "head_sha": owner_sha,
        "id": 202,
        "path": ".github/workflows/full-extraction.yml",
        "run_attempt": 1,
        "status": "completed",
        "workflow_id": 99,
    }

    result, _ = _run_discovery_receipt_resolver(
        tmp_path,
        [artifact],
        owner_run=owner_run,
        workflow_source_sha="a" * 40,
    )

    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled", "timed_out"])
def test_discovery_receipt_resolver_accepts_executed_source_conclusions(
    tmp_path: pathlib.Path,
    conclusion: str,
) -> None:
    artifact = _discovery_artifact(artifact_id=701, name="canonical-discovery")
    owner_run: dict[str, object] = {
        "conclusion": conclusion,
        "event": "workflow_dispatch",
        "head_sha": "a" * 40,
        "id": 202,
        "path": ".github/workflows/full-extraction.yml",
        "run_attempt": 1,
        "status": "completed",
        "workflow_id": 99,
    }

    result, _ = _run_discovery_receipt_resolver(
        tmp_path,
        [artifact],
        owner_run=owner_run,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_discovery_receipt_resolver_rejects_rerun_after_owner_recheck(
    tmp_path: pathlib.Path,
) -> None:
    artifact = _discovery_artifact(artifact_id=701, name="canonical-discovery")
    rechecked_owner: dict[str, object] = {
        "conclusion": "failure",
        "event": "workflow_dispatch",
        "head_sha": "a" * 40,
        "id": 202,
        "path": ".github/workflows/full-extraction.yml",
        "run_attempt": 1,
        "status": "completed",
        "workflow_id": 99,
    }
    result, output_path = _run_discovery_receipt_resolver(
        tmp_path,
        [artifact],
        owner_run={**rechecked_owner, "run_attempt": 2},
        rechecked_owner_run=rechecked_owner,
    )

    assert result.returncode == 1
    assert "changed after provenance recheck" in result.stderr
    assert not output_path.exists()
    rerun_calls = [
        json.loads(line)
        for line in (tmp_path / "gh-calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rerun_calls) == 1
    assert rerun_calls[0][-1].endswith("/actions/runs/202")
    assert all("/artifacts" not in argument for call in rerun_calls for argument in call)


def test_discovery_receipt_resolver_requires_stable_complete_inventory_and_recheck(
    tmp_path: pathlib.Path,
) -> None:
    canonical = _discovery_artifact(artifact_id=701, name="canonical-discovery")
    unrelated = _discovery_artifact(artifact_id=702, name="unrelated")
    first = [{"total_count": 1, "artifacts": [canonical]}]
    stable = [
        {"total_count": 2, "artifacts": [canonical]},
        {"total_count": 2, "artifacts": [unrelated]},
    ]
    accepted, _ = _run_discovery_receipt_resolver(
        tmp_path / "accepted",
        [canonical, unrelated],
        inventory_observations=[first, stable, stable],
        direct_artifact=canonical,
    )
    mutated, _ = _run_discovery_receipt_resolver(
        tmp_path / "mutated",
        [canonical],
        inventory_observations=[first, stable, first],
        direct_artifact=canonical,
    )
    changed_direct = {**canonical, "size_in_bytes": 4096}
    recheck, _ = _run_discovery_receipt_resolver(
        tmp_path / "recheck",
        [canonical],
        direct_artifact=changed_direct,
    )

    assert accepted.returncode == 0, accepted.stderr or accepted.stdout
    calls = [
        json.loads(line)
        for line in (tmp_path / "accepted" / "gh-calls.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(calls) == 6
    assert calls[0] == [
        "api",
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        "/repos/acme/nbadb/actions/runs/202",
    ]
    for call in calls[1:4]:
        assert call[:5] == ["api", "--method", "GET", "--paginate", "--slurp"]
        assert "/repos/acme/nbadb/actions/runs/202/artifacts" in call
        assert "per_page=100" in call
    assert calls[4] == [
        "api",
        "--method",
        "GET",
        "-H",
        "Accept: application/vnd.github+json",
        "-H",
        "X-GitHub-Api-Version: 2026-03-10",
        "/repos/acme/nbadb/actions/artifacts/701",
    ]
    assert calls[5][-1] == "/repos/acme/nbadb/actions/runs/202"
    assert mutated.returncode == 1
    assert "did not stabilize" in mutated.stderr
    assert recheck.returncode == 1
    assert "changed before exact-ID download" in recheck.stderr


def test_discovery_receipt_resolver_rejects_current_run_and_bad_inventory_count(
    tmp_path: pathlib.Path,
) -> None:
    artifact = _discovery_artifact(artifact_id=701, name="canonical-discovery")
    same_run, _ = _run_discovery_receipt_resolver(
        tmp_path / "same-run",
        [artifact],
        current_run_id="202",
    )
    bad_count, _ = _run_discovery_receipt_resolver(
        tmp_path / "bad-count",
        [artifact],
        total_count=2,
    )

    assert same_run.returncode == 1
    assert "requires a distinct source workflow run" in same_run.stderr
    assert bad_count.returncode == 1
    assert "count does not match total_count" in bad_count.stderr


def _restore_discovery_script() -> str:
    seed = _job_block(_workflow_text(), "discovery_seed")
    restore = _step_block(seed, "Restore prior discovery artifacts")
    return textwrap.dedent(restore.split("        run: |\n", 1)[1])


def _install_restore_test_commands(
    tmp_path: pathlib.Path,
    *,
    real_integrity_check: bool = False,
) -> pathlib.Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    uv = fake_bin / "uv"
    if real_integrity_check:
        uv.write_text(
            (
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                'test "$1" = "run"\n'
                'test "$2" = "python"\n'
                "shift 2\n"
                f'exec "{sys.executable}" "$@"\n'
            ),
            encoding="utf-8",
        )
    else:
        uv.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    uv.chmod(0o755)
    return fake_bin


def _prepare_discovery_restore(
    tmp_path: pathlib.Path,
    *,
    complete_workload: bool,
    matching_manifest: bool = True,
    real_integrity_check: bool = False,
) -> pathlib.Path:
    prior = tmp_path / "prior-discovery"
    plan = tmp_path / "plan-artifact"
    prior.mkdir(parents=True)
    plan.mkdir(parents=True)
    source_sha = "a" * 40
    active_manifest = {
        "chain_id": "fixture-chain",
        "workflow_source_sha": source_sha,
        "coverage_fingerprint": "b" * 64,
    }
    restored_manifest = dict(active_manifest)
    if not matching_manifest:
        restored_manifest["coverage_fingerprint"] = "c" * 64
    artifact_dir = prior / "nba.discovery-artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "fixture.json").write_text("{}\n", encoding="utf-8")
    (prior / "discovery-seed-summary.json").write_text("{}\n", encoding="utf-8")
    (prior / "discovery-manifest.json").write_text(
        json.dumps(restored_manifest),
        encoding="utf-8",
    )
    (plan / "manifest.json").write_text(json.dumps(active_manifest), encoding="utf-8")
    (prior / "nba.player-team-season-workload.player-team-season-workload.json").write_text(
        '{"marker":"source"}\n',
        encoding="utf-8",
    )
    if complete_workload:
        (prior / "nba.player-team-season-workload.generation.parquet").write_text(
            "fixture parquet\n",
            encoding="utf-8",
        )
    return _install_restore_test_commands(
        tmp_path,
        real_integrity_check=real_integrity_check,
    )


def test_discovery_restore_installs_exact_receipt_selected_bundle(
    tmp_path: pathlib.Path,
) -> None:
    fake_bin = _prepare_discovery_restore(tmp_path, complete_workload=True)
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _restore_discovery_script()],
        check=False,
        capture_output=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "DISCOVERY_SOURCE_KIND": "canonical",
        },
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    restored_pointer = (
        tmp_path / "data/nbadb/nba.player-team-season-workload.player-team-season-workload.json"
    )
    assert json.loads(restored_pointer.read_text(encoding="utf-8"))["marker"] == "source"
    assert (tmp_path / "data/nbadb/nba.player-team-season-workload.generation.parquet").is_file()


@pytest.mark.parametrize(
    ("source_kind", "expected_returncode", "message"),
    [
        ("canonical", 1, "Canonical discovery bundle layout is incomplete"),
        ("recovery", 0, "Prior player/team workload artifact is incomplete; ignoring it"),
    ],
)
def test_discovery_restore_handles_incomplete_bundle_by_receipt_kind(
    tmp_path: pathlib.Path,
    source_kind: str,
    expected_returncode: int,
    message: str,
) -> None:
    fake_bin = _prepare_discovery_restore(tmp_path, complete_workload=False)
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _restore_discovery_script()],
        check=False,
        capture_output=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "DISCOVERY_SOURCE_KIND": source_kind,
        },
        text=True,
    )

    assert result.returncode == expected_returncode, result.stderr or result.stdout
    assert message in result.stdout


def test_discovery_restore_rejects_manifest_provenance_mismatch(
    tmp_path: pathlib.Path,
) -> None:
    fake_bin = _prepare_discovery_restore(
        tmp_path,
        complete_workload=True,
        matching_manifest=False,
    )
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _restore_discovery_script()],
        check=False,
        capture_output=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "DISCOVERY_SOURCE_KIND": "canonical",
        },
        text=True,
    )

    assert result.returncode == 1
    assert "coverage_fingerprint does not match the active plan" in result.stderr


def test_discovery_restore_rejects_real_workload_integrity_failure(
    tmp_path: pathlib.Path,
) -> None:
    fake_bin = _prepare_discovery_restore(
        tmp_path,
        complete_workload=True,
        real_integrity_check=True,
    )
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _restore_discovery_script()],
        check=False,
        capture_output=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "DISCOVERY_SOURCE_KIND": "canonical",
        },
        text=True,
    )

    assert result.returncode == 1
    assert "Canonical discovery workload failed integrity validation" in result.stdout
    assert (
        "restored workload pointer or generation failed integrity validation" in result.stderr
        or "marker" in result.stderr
    )


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("symlink", "rejects symbolic links"),
        ("duplicate-manifest", "manifest layout is ambiguous"),
        ("duplicate-artifact-dir", "artifact layout is ambiguous"),
        ("duplicate-pointer", "artifact layout is ambiguous"),
        ("duplicate-parquet", "artifact layout is ambiguous"),
        ("duplicate-summary", "artifact layout is ambiguous"),
        ("duplicate-basename", "duplicate file basenames"),
    ],
)
def test_discovery_restore_rejects_ambiguous_or_unsafe_layouts(
    tmp_path: pathlib.Path,
    case: str,
    message: str,
) -> None:
    fake_bin = _prepare_discovery_restore(tmp_path, complete_workload=True)
    prior = tmp_path / "prior-discovery"
    nested = prior / "nested"
    nested.mkdir()
    if case == "symlink":
        (nested / "link").symlink_to(prior / "discovery-manifest.json")
    elif case == "duplicate-manifest":
        (nested / "discovery-manifest.json").write_text("{}\n", encoding="utf-8")
    elif case == "duplicate-artifact-dir":
        (nested / "nba.discovery-artifacts").mkdir()
    elif case == "duplicate-pointer":
        (nested / "nba.player-team-season-workload.player-team-season-workload.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
    elif case == "duplicate-parquet":
        (nested / "nba.player-team-season-workload.other.parquet").write_text(
            "other\n",
            encoding="utf-8",
        )
    elif case == "duplicate-summary":
        (nested / "discovery-seed-summary.json").write_text("{}\n", encoding="utf-8")
    elif case == "duplicate-basename":
        first = prior / "one"
        second = prior / "two"
        first.mkdir()
        second.mkdir()
        (first / "unrelated.json").write_text("{}\n", encoding="utf-8")
        (second / "unrelated.json").write_text("{}\n", encoding="utf-8")
    else:
        raise AssertionError(case)

    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + _restore_discovery_script()],
        check=False,
        capture_output=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "DISCOVERY_SOURCE_KIND": "recovery",
        },
        text=True,
    )

    assert result.returncode == 1
    assert message in result.stdout
