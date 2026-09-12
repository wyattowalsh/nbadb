from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from dataclasses import replace

import duckdb

from nbadb.contracts.assurance_admission import AssuranceAdmission
from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.orchestrate.full_extraction_control import (
    FullExtractionChainState,
    FullExtractionLane,
    _coverage_hash_for_lane,
    _create_exact_extraction_journal,
    build_checkpoint_database,
    manifest_payload,
)
from nbadb.orchestrate.operation_authority import (
    ExactArtifactMemberV1,
    NetworkMode,
    OperationAuthorityV1,
    OperationKind,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_FIXTURE_PATH = _REPO_ROOT / "tests" / "fixtures" / "full-extraction" / "smoke.json"
_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "full-extraction.yml"
_METADATA_SCRIPT = _REPO_ROOT / ".github" / "scripts" / "write_lane_metadata.py"


def _assurance_admission(source_sha: str) -> AssuranceAdmission:
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


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_operation_authority(
    path: pathlib.Path,
    *,
    operation: OperationKind,
    chain_id: str,
    run_id: str,
    source_sha: str,
    manifest_lane_count: int,
    vpn_parallelism: int = 2,
    continuation_source: ExactArtifactMemberV1 | None = None,
) -> OperationAuthorityV1:
    """Bind one exact operation authority to the checked workflow and runtime."""

    authority = OperationAuthorityV1(
        repository="fixture/nbadb",
        workflow_path=".github/workflows/full-extraction.yml",
        workflow_content_sha256=hashlib.sha256(_WORKFLOW_PATH.read_bytes()).hexdigest(),
        workflow_commit_sha=source_sha,
        source_sha=source_sha,
        trusted_ref="refs/heads/main",
        run_id=int(run_id),
        run_attempt=1,
        event="workflow_dispatch",
        actor="fixture-actor",
        chain_id=chain_id,
        iteration=1,
        operation=operation,
        requested_network_mode=NetworkMode.VPN,
        requested_vpn_parallelism=vpn_parallelism,
        requested_direct_parallelism=0,
        max_iterations=64,
        retry_pipeline_failures=True,
        allow_re_extraction=False,
        manifest_lane_count=manifest_lane_count,
        continuation_source=continuation_source,
    )
    path.write_text(json.dumps(authority.to_dict()), encoding="utf-8")
    return authority


def _actions_runtime_env(
    *,
    run_id: str,
    source_sha: str,
) -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": "fixture/nbadb",
        "GITHUB_RUN_ID": run_id,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "fixture-actor",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": source_sha,
        "WORKFLOW_SOURCE_SHA": source_sha,
    }


def _run(
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
    assert result.returncode == 0, (
        f"command failed ({result.returncode}): {' '.join(command)}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _job_block(workflow: str, job_name: str) -> str:
    jobs = workflow.split("\njobs:\n", 1)[1]
    marker = f"  {job_name}:\n"
    start = jobs.index(marker)
    remainder = jobs[start + len(marker) :]
    next_job = re.search(r"(?m)^  [a-z][a-z0-9_-]*:\n", remainder)
    end = start + len(marker) + (next_job.start() if next_job else len(remainder))
    return jobs[start:end]


def _write_synthetic_lane_database(path: pathlib.Path, fixture: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    try:
        connection.execute("CREATE TABLE stg_fixture (entity_id BIGINT, label VARCHAR)")
        connection.executemany(
            "INSERT INTO stg_fixture VALUES (?, ?)",
            fixture["staging_rows"],
        )
        _create_exact_extraction_journal(connection)
        journal = fixture["journal"]
        assert isinstance(journal, dict)
        endpoint = journal.get("endpoint")
        params = journal.get("params")
        if type(endpoint) is not str or type(params) is not str:
            raise AssertionError("fixture journal must include string endpoint and params")
        connection.execute(
            """
            INSERT INTO _extraction_journal (
                endpoint,
                params,
                status,
                started_at,
                completed_at,
                rows_extracted,
                error_message,
                retry_count
            )
            VALUES (?, ?, 'done', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 2, NULL, 0)
            """,
            [endpoint, params],
        )
    finally:
        connection.close()


def test_maximum_width_checkpoint_attests_and_merges_256_lanes(
    tmp_path: pathlib.Path,
) -> None:
    lane_count = 256
    artifacts_dir = tmp_path / "lanes"
    metadata_dir = tmp_path / "metadata"
    lanes: list[FullExtractionLane] = []
    chain_id = "maximum-width"
    run_id = "256"
    source_sha = "a" * 40

    for index in range(lane_count):
        lane = FullExtractionLane(
            lane_id=f"benchmark-static-{index:03d}",
            lane_index=index,
            lane_name=f"Benchmark Static {index:03d}",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("static",),
            endpoints=("franchise_history",),
            use_vpn=False,
            timeout_seconds=1800,
        )
        lane = replace(lane, coverage_units_hash=_coverage_hash_for_lane(lane))
        lanes.append(lane)

        artifact_name = f"extraction-lane-{chain_id}-{lane.lane_id}"
        lane_dir = artifacts_dir / f"run-{run_id}" / artifact_name
        lane_dir.mkdir(parents=True)
        database_path = lane_dir / "nba.duckdb"
        connection = duckdb.connect(str(database_path))
        try:
            _create_exact_extraction_journal(connection)
            connection.execute(
                """
                INSERT INTO _extraction_journal (
                    endpoint,
                    params,
                    status,
                    started_at,
                    completed_at,
                    rows_extracted,
                    error_message,
                    retry_count
                )
                VALUES (?, ?, 'done', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, NULL, 0)
                """,
                ["franchise_history", json.dumps({"lane": index})],
            )
            connection.execute("CREATE TABLE stg_max_width (lane_index INTEGER, payload VARCHAR)")
            connection.execute(
                "INSERT INTO stg_max_width VALUES (?, ?)",
                [index, f"lane-{index:03d}"],
            )
        finally:
            connection.close()

        digest = _sha256(database_path)
        metadata_artifact_name = f"extraction-lane-metadata-{chain_id}-{lane.lane_id}"
        lane_metadata_dir = metadata_dir / f"run-{run_id}" / metadata_artifact_name
        lane_metadata_dir.mkdir(parents=True)
        (lane_metadata_dir / "lane-metadata.json").write_text(
            json.dumps(
                {
                    "metadata_schema_version": 3,
                    "lane_id": lane.lane_id,
                    "lane_index": lane.lane_index,
                    "lane_name": lane.lane_name,
                    "lane_kind": lane.lane_kind,
                    "status": "complete",
                    "raw_status": "complete",
                    "patterns": list(lane.patterns),
                    "season_types": list(lane.season_types),
                    "endpoints": list(lane.endpoints),
                    "season_start": "",
                    "season_end": "",
                    "coverage_units_hash": lane.coverage_units_hash,
                    "database_sha256": digest,
                    "source_sha": source_sha,
                    "chain_id": chain_id,
                    "state_artifact": {
                        "attested": True,
                        "uploaded": True,
                        "artifact_id": str(1000 + index),
                        "artifact_digest": f"sha256:{index:064x}",
                        "run_id": run_id,
                        "name": artifact_name,
                        "sha256": digest,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (lane_dir / "lane-state-attestation.json").write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "source_sha": source_sha,
                    "chain_id": chain_id,
                    "lane_id": lane.lane_id,
                    "run_id": run_id,
                    "artifact_name": artifact_name,
                    "coverage_units_hash": lane.coverage_units_hash,
                    "database_sha256": digest,
                    "attested": True,
                    "expected_empty": False,
                    "workload_contract": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    manifest_path = tmp_path / "manifest.json"
    manifest = manifest_payload(
        lanes,
        assurance_admission=_assurance_admission(source_sha),
        chain_id=chain_id,
        chain_state=FullExtractionChainState(
            artifact_run_ids=(run_id,),
        ),
        max_matrix_lanes=lane_count,
    )
    manifest_path.write_text(
        json.dumps(manifest) + "\n",
        encoding="utf-8",
    )
    checkpoint_dir = tmp_path / "checkpoint"
    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=artifacts_dir,
        output_dir=checkpoint_dir,
        report_path=tmp_path / "checkpoint-report.json",
        chain_id=chain_id,
        run_id=run_id,
        source_sha=source_sha,
        checkpoint_generation=1,
        checkpoint_artifact_name=f"full-extraction-checkpoint-{chain_id}-iter-1",
    )

    checkpoint_path = checkpoint_dir / "nba.duckdb"
    connection = duckdb.connect(str(checkpoint_path), read_only=True)
    try:
        width_row = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT lane_index) FROM stg_max_width"
        ).fetchone()
        journal_row = connection.execute("SELECT COUNT(*) FROM _extraction_journal").fetchone()
    finally:
        connection.close()
    if width_row is None or journal_row is None:
        raise AssertionError("checkpoint counts must be present")
    row_count, distinct_count = width_row
    journal_count = journal_row[0]

    assert report["terminal_ready"] is True
    assert report["complete_lane_count"] == lane_count
    assert len(report["attested_current_lane_ids"]) == lane_count
    assert report["current_lane_attestation_failures"] == {}
    assert row_count == distinct_count == journal_count == lane_count
    assert report["database_sha256"] == _sha256(checkpoint_path)


def test_extract_offline_control_fixture_runs_under_exact_operation_authority(
    tmp_path: pathlib.Path,
) -> None:
    fixture = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    chain_id = str(fixture["chain_id"])
    terminal_replay = fixture["terminal_replay"]
    assert isinstance(terminal_replay, dict)
    source_run_id = str(terminal_replay["source_run_id"])
    source_sha = "0" * 40
    fixture["manifest"]["provider_authority"] = expected_nba_api_provider_authority()
    fixture["manifest"]["manifest_version"] = 5
    fixture["manifest"]["chain_id"] = chain_id
    fixture["manifest"]["workflow_source_sha"] = source_sha
    fixture["manifest"]["assurance_admission"] = _assurance_admission(source_sha).to_dict()
    lane = fixture["manifest"]["lanes"][0]
    lane_id = str(lane["lane_id"])
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    commands: list[list[str]] = []

    runtime_env = _actions_runtime_env(run_id=source_run_id, source_sha=source_sha)
    extract_authority_path = workspace / "extract-operation-authority.json"
    extract_authority = _write_operation_authority(
        extract_authority_path,
        operation=OperationKind.EXTRACT,
        chain_id=chain_id,
        run_id=source_run_id,
        source_sha=source_sha,
        manifest_lane_count=1,
    )
    planned_manifest = workspace / "planned-manifest.json"
    plan_command = [
        sys.executable,
        "-m",
        "nbadb.orchestrate.full_extraction_control",
        "plan",
        "--operation-authority-path",
        str(extract_authority_path),
        "--lane-manifest-json",
        json.dumps(fixture["manifest"]),
        "--chain-id",
        chain_id,
        "--workflow-source-sha",
        source_sha,
        "--max-matrix-lanes",
        "1",
        "--vpn-slot-count",
        "2",
        "--output-path",
        str(planned_manifest),
    ]
    commands.append(plan_command)
    _run(plan_command, cwd=_REPO_ROOT, env=runtime_env)
    planned = json.loads(planned_manifest.read_text(encoding="utf-8"))
    assert planned["lane_count"] == 1
    assert planned["matrix_lane_count"] == 1
    assert planned["deferred_lane_count"] == 0
    assert len(planned["github_matrix"]["include"]) == 1
    assert planned["operation"] == "extract"
    assert planned["operation_authority"] == extract_authority.to_dict()
    assert planned["operation_authority_sha256"] == extract_authority.authority_sha256
    # Authorized planning must not fabricate FreeExecution authority of any kind.
    assert "free_execution_admission" not in planned
    assert "free_execution_intent_manifest" not in planned
    assert planned["assurance_admission"] == _assurance_admission(source_sha).to_dict()

    # The remaining commands exercise offline checkpoint/merge fixtures directly. They do
    # not model workflow reachability beyond the authority-validated plan above.

    lane_db = workspace / "data" / "nbadb" / "nba.duckdb"
    _write_synthetic_lane_database(lane_db, fixture)
    extract_summary = workspace / "extract-summary.json"
    extract_summary.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 2,
                    "failed_extractions": 0,
                    "skipped_extractions": 0,
                    "tables_updated": 1,
                },
                "progress": {
                    "patterns": [{"total": 1}],
                    "totals": {"rows_extracted": 2, "failed": 0, "skipped": 0},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    metadata_output = workspace / "github-output.txt"
    metadata_env = {
        "CACHE_HIT": "false",
        "CHAIN_ID": chain_id,
        "COVERAGE_UNITS_HASH": str(planned["lanes"][0]["coverage_units_hash"]),
        "EFFECTIVE_NETWORK_MODE": "direct",
        "EFFECTIVE_TIMEOUT_SECONDS": "1800",
        "ENDPOINTS": "franchise_history",
        "EXTRACT_EXIT_CODE": "0",
        "EXTRACT_STATUS": "success",
        "EXTRACT_SUMMARY_PATH": str(extract_summary),
        "FINISHED_AT": "2026-07-11T00:00:01Z",
        "GITHUB_OUTPUT": str(metadata_output),
        "GITHUB_RUN_ID": source_run_id,
        "ITERATION": "1",
        "KIND": "reference",
        "LANE_ID": lane_id,
        "LANE_INDEX": "0",
        "NAME": "Reference Static Fixture",
        "NETWORK_MODE": "direct",
        "PATTERNS": "static",
        "RESTART_MODE": "fresh",
        "RESTORE_SOURCE": "none",
        "RESTORE_USABLE": "false",
        "RESUME_ONLY": "false",
        "SOURCE_REF": "main",
        "SOURCE_SHA": source_sha,
        "STARTED_AT": "2026-07-11T00:00:00Z",
        "STATUS": "complete",
        "TIMEOUT_SECONDS": "1800",
        "VPN_STATUS": "direct-no-vpn",
    }
    metadata_command = [sys.executable, str(_METADATA_SCRIPT)]
    commands.append(metadata_command)
    _run(metadata_command, cwd=workspace, env=metadata_env)
    generated_metadata = workspace / "artifacts" / "extraction" / "lane-metadata.json"
    metadata = json.loads(generated_metadata.read_text(encoding="utf-8"))
    assert metadata["status"] == "complete"
    assert metadata["telemetry"]["rows_persisted"] == 2
    metadata["state_artifact"].update(
        {
            "uploaded": True,
            "artifact_id": "98765",
            "artifact_digest": f"sha256:{'d' * 64}",
        }
    )
    generated_metadata.write_text(json.dumps(metadata) + "\n", encoding="utf-8")

    metadata_artifact_name = f"extraction-lane-metadata-{chain_id}-{lane_id}"
    metadata_dir = workspace / "lane-metadata" / f"run-{source_run_id}" / metadata_artifact_name
    metadata_dir.mkdir(parents=True)
    shutil.copy2(generated_metadata, metadata_dir / "lane-metadata.json")
    artifact_name = f"extraction-lane-{chain_id}-{lane_id}"
    lane_artifact = workspace / "lanes" / f"run-{source_run_id}" / artifact_name
    lane_artifact.mkdir(parents=True)
    shutil.copy2(lane_db, lane_artifact / "nba.duckdb")
    shutil.copy2(
        workspace / "artifacts" / "extraction" / "lane-state-attestation.json",
        lane_artifact / "lane-state-attestation.json",
    )

    terminal_manifest = workspace / "terminal-manifest.json"
    continue_authority_path = workspace / "continue-operation-authority.json"
    _write_operation_authority(
        continue_authority_path,
        operation=OperationKind.CONTINUE,
        chain_id=chain_id,
        run_id=source_run_id,
        source_sha=source_sha,
        manifest_lane_count=1,
        continuation_source=ExactArtifactMemberV1(
            repository="fixture/nbadb",
            run_id=202,
            run_attempt=1,
            artifact_id=703,
            artifact_name=f"full-extraction-manifest-{chain_id}",
            artifact_digest=f"sha256:{'f' * 64}",
            artifact_size_bytes=4096,
            member_path="manifest.json",
            member_sha256="e" * 64,
            member_size_bytes=128,
        ),
    )
    resume_command = [
        sys.executable,
        "-m",
        "nbadb.orchestrate.full_extraction_control",
        "resume",
        "--operation-authority-path",
        str(continue_authority_path),
        "--lane-manifest-path",
        str(planned_manifest),
        "--metadata-dir",
        str(workspace / "lane-metadata"),
        "--completed-artifact-run-id",
        source_run_id,
        "--iteration",
        "1",
        "--max-matrix-lanes",
        "1",
        "--output-path",
        str(terminal_manifest),
    ]
    commands.append(resume_command)
    _run(resume_command, cwd=workspace, env=runtime_env)
    terminal = json.loads(terminal_manifest.read_text(encoding="utf-8"))
    assert terminal["active_lane_count"] == 0
    assert terminal["matrix_lane_count"] == 0
    assert terminal["resume_only_lane_count"] == 1

    checkpoint_dir = workspace / "checkpoint"
    checkpoint_report = checkpoint_dir / "checkpoint-report.json"
    checkpoint_command = [
        sys.executable,
        "-m",
        "nbadb.orchestrate.full_extraction_control",
        "checkpoint",
        "--lane-manifest-path",
        str(terminal_manifest),
        "--metadata-dir",
        str(workspace / "lane-metadata"),
        "--artifacts-dir",
        str(workspace / "lanes"),
        "--output-dir",
        str(checkpoint_dir),
        "--report-path",
        str(checkpoint_report),
        "--chain-id",
        chain_id,
        "--run-id",
        source_run_id,
        "--source-sha",
        source_sha,
        "--checkpoint-generation",
        str(terminal_replay["checkpoint_generation"]),
        "--checkpoint-artifact-name",
        str(terminal_replay["checkpoint_artifact_name"]),
    ]
    commands.append(checkpoint_command)
    _run(checkpoint_command, cwd=workspace)
    checkpoint = json.loads(checkpoint_report.read_text(encoding="utf-8"))
    assert checkpoint["terminal_ready"] is True
    assert checkpoint["complete_lane_count"] == 1
    assert checkpoint["active_lane_count"] == 0
    assert checkpoint["run_id"] == source_run_id
    assert checkpoint["checkpoint_generation"] == terminal_replay["checkpoint_generation"]
    assert (
        terminal_replay["checkpoint_artifact_name"]
        == f"full-extraction-checkpoint-{chain_id}-iter-1"
    )

    final_dir = workspace / "final"
    merge_command = [
        sys.executable,
        "-m",
        "nbadb.orchestrate.full_extraction_control",
        "merge",
        "--artifacts-dir",
        str(workspace / "lanes"),
        "--output-dir",
        str(final_dir),
        "--manifest-path",
        str(terminal_manifest),
        "--checkpoint-dir",
        str(checkpoint_dir),
        "--checkpoint-report-path",
        str(checkpoint_report),
    ]
    commands.append(merge_command)
    merge_result = _run(merge_command, cwd=workspace)
    assert json.loads(merge_result.stdout)["merge_mode"] == "checkpoint"

    export_command = [sys.executable, "-m", "nbadb", "export", "--data-dir", str(final_dir)]
    commands.append(export_command)
    _run(export_command, cwd=workspace)
    assert (final_dir / "nba.sqlite").is_file()
    assert (final_dir / "parquet" / "stg_fixture" / "stg_fixture.parquet").is_file()
    assert (final_dir / "csv" / "stg_fixture.csv").is_file()

    connection = duckdb.connect(str(final_dir / "nba.duckdb"), read_only=True)
    try:
        assert connection.execute(
            "SELECT entity_id, label FROM stg_fixture ORDER BY entity_id"
        ).fetchall() == [(1, "alpha"), (2, "beta")]
    finally:
        connection.close()

    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    plan_job = _job_block(workflow, "plan")
    blocked_job = _job_block(workflow, "free_execution_blocked")
    replay_job = _job_block(workflow, "terminal_replay")
    merge_job = _job_block(workflow, "merge")
    publish_job = _job_block(workflow, "publish")
    # The free_execution_blocked job stops the chain for any authority or collector
    # state other than the exact validated/admitted set, including unknown statuses.
    assert "needs.plan.outputs.operation-authority-status != 'validated'" in blocked_job
    assert "free-execution-collector-authenticated != 'true'" in blocked_job
    assert "free-execution-mutations-authorized != 'true'" in blocked_job
    assert "operation-authority-status == 'capacity_blocked'" not in blocked_job
    assert "not authentically admitted" in blocked_job
    assert "exit 1" in blocked_job
    assert "enable-cache: false" in plan_job
    assert "enable-cache: true" not in plan_job
    assert "prune-cache:" not in plan_job
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
    for step_name, required_conditions in upload_conditions.items():
        step_start = plan_job.index(f"      - name: {step_name}\n")
        next_step = plan_job.find("\n      - ", step_start + 1)
        step = plan_job[step_start : next_step if next_step >= 0 else None]
        for condition in required_conditions:
            assert condition in step, step_name
    # Every provider or mutation job re-asserts the validated operation authority and
    # the full authenticated collector set.
    for job in (replay_job, merge_job, publish_job):
        header = job.split("    runs-on:", 1)[0]
        assert "needs.plan.outputs.operation-authority-status == 'validated'" in header
        assert "free-execution-collector-status == 'admitted'" in header
        assert "free-execution-collector-authenticated == 'true'" in header
        assert "free-execution-runtime-context-status == 'authenticated'" in header
        assert "free-execution-storage-mutations-allowed == 'true'" in header
        assert "free-execution-provider-calls-allowed == 'true'" in header
        assert "free-execution-mutations-authorized == 'true'" in header
    for assurance_step in (
        "Merge lane databases",
        "Transform and load",
        "Append live snapshot",
        "Scan data quality",
        "Export all formats",
    ):
        step_start = merge_job.index(f"      - name: {assurance_step}\n")
        next_step = merge_job.find("\n      - ", step_start + 1)
        step = merge_job[step_start : next_step if next_step >= 0 else None]
        assert "inputs.publish" not in step
    assert "contents: read" in merge_job
    assert "contents: write" not in merge_job
    assert "KAGGLE_USERNAME" not in merge_job
    assert "Refresh checked-in metadata" not in merge_job
    assert "Upload to Kaggle" not in merge_job
    assert "- name: Record non-publishing canary outcome" in merge_job
    canary_start = merge_job.index("      - name: Record non-publishing canary outcome\n")
    canary_next = merge_job.find("\n      - ", canary_start + 1)
    canary_step = merge_job[canary_start : canary_next if canary_next >= 0 else None]
    assert "if:" not in canary_step
    assert "**Publish requested:** false" in canary_step
    assert "needs.plan.outputs.active-lane-count == '0'" in replay_job
    assert "needs.plan.outputs.matrix-lane-count == '0'" in replay_job
    assert "source checkpoint database SHA-256 does not match" in replay_job
    # Publication stays delegated to the exact handoff publication workflow: the
    # in-workflow publish job is disabled behind its legacy false gate.
    assert "if: ${{ false && " in publish_job
    assert "needs.publication_preflight.result == 'success'" in publish_job
    assert "needs.merge.result == 'success'" in publish_job
    assert "contents: write" in publish_job
    assert publish_job.index("Revalidate frozen publication source") < publish_job.index(
        "Upload to Kaggle"
    )
    assert publish_job.index("Upload to Kaggle") < publish_job.index("Refresh checked-in metadata")
    assert all("nbadb upload" not in " ".join(command) for command in commands)
