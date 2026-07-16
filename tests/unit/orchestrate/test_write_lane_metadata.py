from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore

if TYPE_CHECKING:
    from types import ModuleType

    from nbadb.orchestrate.full_extraction_control import FullExtractionLane


def _load_module() -> ModuleType:
    path = Path(__file__).parents[3] / ".github" / "scripts" / "write_lane_metadata.py"
    spec = importlib.util.spec_from_file_location("write_lane_metadata", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def metadata_module() -> ModuleType:
    return _load_module()


def _set_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, status: str) -> Path:
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text("{}\n", encoding="utf-8")
    values = {
        "CHAIN_ID": "chain-1",
        "ITERATION": "2",
        "LANE_ID": "lane-1",
        "LANE_INDEX": "0",
        "NAME": "Lane 1",
        "KIND": "historical",
        "SOURCE_REF": "main",
        "SOURCE_SHA": "abc123",
        "STATUS": status,
        "CACHE_HIT": "false",
        "RESTORE_SOURCE": "none",
        "RESTORE_USABLE": "false",
        "RESTART_MODE": "clean-restart",
        "RESUME_ONLY": "false",
        "TIMEOUT_SECONDS": "3600",
        "EFFECTIVE_TIMEOUT_SECONDS": "3600",
        "EXTRACT_SUMMARY_PATH": str(summary_path),
        "NETWORK_MODE": "vpn",
        "EFFECTIVE_NETWORK_MODE": "vpn",
        "VPN_STATUS": "connected",
        "GITHUB_RUN_ID": "12345",
        "RECOVERY_ARTIFACT_NAME": ("extraction-lane-recovery-chain-1-lane-1-run-12345-attempt-1"),
        "PATTERNS": "season",
        "ENDPOINTS": "draft_history",
        "SEASON_TYPES": "Regular Season",
        "SEASON_START": "2020",
        "SEASON_END": "2020",
        "COVERAGE_UNITS_HASH": "b" * 64,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CONTEXT_MEASURES", raising=False)
    monkeypatch.chdir(tmp_path)
    return summary_path


def _write_workload(
    db_path: Path,
    params: list[dict[str, int | str]],
    *,
    seasons: list[str],
    season_types: list[str],
) -> PlayerTeamSeasonWorkloadStore:
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(db_path)
    store.upsert(params, seasons=seasons, season_types=season_types)
    return store


def _set_auth_failure_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> FullExtractionLane:
    from nbadb.orchestrate import full_extraction_control as resume_control

    lane = resume_control.FullExtractionLane(
        lane_id="lane-1",
        lane_index=0,
        lane_name="Lane 1",
        lane_kind="historical",
        season_start=2020,
        season_end=2020,
        patterns=("season",),
        endpoints=("draft_history",),
        season_types=("Regular Season",),
        timeout_seconds=3600,
    )
    _set_env(monkeypatch, tmp_path, status="vpn_auth_failure")
    monkeypatch.setenv("SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("COVERAGE_UNITS_HASH", resume_control._coverage_hash_for_lane(lane))
    monkeypatch.setenv("EXTRACT_STATUS", "not-run")
    monkeypatch.setenv("VPN_STATUS", "vpn_auth_failure")
    monkeypatch.setenv("VPN_SERVER", "us-test-1")
    return lane


def _set_restored_auth_failure_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> FullExtractionLane:
    lane = _set_auth_failure_env(monkeypatch, tmp_path)
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "create table _extraction_journal "
        "(endpoint varchar, params varchar, status varchar, rows_extracted bigint)"
    )
    conn.execute("insert into _extraction_journal values ('draft_history', '{}', 'done', 5)")
    conn.execute("create table stg_example(value integer)")
    conn.execute("insert into stg_example values (1), (2)")
    conn.execute("checkpoint")
    conn.close()

    run_id = "9988"
    artifact_name = "extraction-lane-recovery-chain-1-lane-1-run-9988-attempt-1"
    database_sha256 = hashlib.sha256(db_path.read_bytes()).hexdigest()
    attestation_path = tmp_path / "artifacts" / "extraction" / "lane-state-attestation.json"
    attestation_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "source_sha": "a" * 40,
                "chain_id": "chain-1",
                "lane_id": lane.lane_id,
                "run_id": run_id,
                "artifact_name": artifact_name,
                "coverage_units_hash": os.environ["COVERAGE_UNITS_HASH"],
                "database_sha256": database_sha256,
                "attested": True,
                "expected_empty": False,
                "workload_contract": None,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("RESTORE_SOURCE", "artifact")
    monkeypatch.setenv("RESTORE_USABLE", "true")
    monkeypatch.setenv("RESTART_MODE", "resume")
    return replace(
        lane,
        attempt_count=3,
        failure_streak=2,
        class_failure_streak=1,
        zero_progress_streak=1,
        last_failure_reason="needs_resume",
        last_failure_class="transport_transient",
        last_completed_calls=1,
        last_rows_persisted=5,
        next_eligible_iteration=2,
        state_artifact_run_id=run_id,
        state_artifact_name=artifact_name,
        state_artifact_digest=database_sha256,
    )


def test_context_measures_default_to_empty_for_existing_payloads(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-error")

    payload = metadata_module.build_payload()

    assert payload["season_types"] == ["Regular Season"]
    assert payload["endpoints"] == ["draft_history"]
    assert payload["context_measures"] == []


def test_context_measures_parses_csv(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-error")
    monkeypatch.setenv("CONTEXT_MEASURES", "PTS,AST,REB")

    payload = metadata_module.build_payload()

    assert payload["context_measures"] == ["PTS", "AST", "REB"]


@pytest.mark.parametrize(
    "vpn_status",
    ["vpn_auth_failure", "vpn_connect_timeout", "vpn_network_error"],
)
def test_vpn_producer_failures_are_classified_as_vpn_egress(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    vpn_status: str,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-error")
    monkeypatch.setenv("VPN_STATUS", vpn_status)
    monkeypatch.setenv("VPN_SERVER", "us-test-1")
    monkeypatch.setenv("VPN_INTERFACE", "nordlynx")
    monkeypatch.setenv("VPN_EXIT_IP", "203.0.113.1")
    monkeypatch.setenv("NORDVPN_TOKEN", "must-not-be-serialized")

    payload = metadata_module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["failure_class"] == "vpn_egress"
    assert payload["vpn_status"] == vpn_status
    assert payload["vpn"] == {
        "status": vpn_status,
        "server": "us-test-1",
        "interface": "nordlynx",
        "exit_ip": "203.0.113.1",
        "attempted_servers": [],
        "failed_servers": [],
    }
    assert "must-not-be-serialized" not in json.dumps(payload, sort_keys=True)


def test_zero_work_vpn_auth_failure_writer_is_accepted_by_resume_manifest(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nbadb.orchestrate import full_extraction_control as resume_control

    lane = _set_auth_failure_env(monkeypatch, tmp_path)
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    assert metadata_module.main() == 0

    metadata_dir = tmp_path / "artifacts" / "extraction"
    payload = json.loads((metadata_dir / "lane-metadata.json").read_text(encoding="utf-8"))
    assert payload["status"] == "needs_resume"
    assert payload["raw_status"] == "vpn_auth_failure"
    assert payload["failure_class"] == "vpn_egress"
    assert payload["extract_status"] == "not-run"
    assert payload["database_sha256"] == ""
    assert payload["progress"] == {
        "completed_calls": 0,
        "rows_persisted": 0,
        "fingerprint": metadata_module._progress_fingerprint(
            completed_calls=0,
            rows_persisted=0,
        ),
    }
    assert payload["prior_state"] is None
    telemetry = payload["telemetry"]
    assert {
        key: telemetry[key]
        for key in (
            "planned_calls",
            "journal_skips",
            "failed_calls",
            "completed_calls",
            "tables_persisted",
            "rows_persisted",
        )
    } == {
        "planned_calls": 0,
        "journal_skips": 0,
        "failed_calls": 0,
        "completed_calls": 0,
        "tables_persisted": 0,
        "rows_persisted": 0,
    }
    assert telemetry["db_telemetry"] == {
        "planned_calls": 0,
        "journal_skips": 0,
        "failed_calls": 0,
        "running_calls": 0,
        "completed_calls": 0,
        "tables_persisted": 0,
        "rows_persisted": 0,
    }
    assert payload["state_artifact"] == {
        "run_id": "",
        "name": "",
        "sha256": "",
        "artifact_id": "",
        "artifact_digest": "",
        "required": False,
        "attested": False,
        "uploaded": False,
    }
    assert not (metadata_dir / "lane-state-attestation.json").exists()
    assert github_output.read_text(encoding="utf-8").splitlines() == [
        "final-outcome=needs_resume",
        "snapshot-attested=false",
    ]

    next_lanes, _next_state, summary = resume_control.build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        current_iteration=2,
        expected_chain_id="chain-1",
        expected_source_sha="a" * 40,
    )

    assert len(next_lanes) == 1
    retry_lane = next_lanes[0]
    assert retry_lane.attempt_count == lane.attempt_count + 1
    assert retry_lane.failure_streak == 1
    assert retry_lane.class_failure_streak == 1
    assert retry_lane.zero_progress_streak == 1
    assert retry_lane.last_failure_reason == "needs_resume"
    assert retry_lane.last_failure_class == "vpn_egress"
    assert summary["deferred_lane_count"] == 1
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 1
    assert summary["failure_reason_counts"] == {"vpn_auth_failure": 1}
    assert summary["failure_class_counts"] == {"vpn_egress": 1}


def test_restored_vpn_auth_failure_with_no_new_work_preserves_prior_state(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nbadb.orchestrate import full_extraction_control as resume_control

    lane = _set_restored_auth_failure_env(monkeypatch, tmp_path)
    github_output = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    assert metadata_module.main() == 0

    metadata_dir = tmp_path / "artifacts" / "extraction"
    payload = json.loads((metadata_dir / "lane-metadata.json").read_text(encoding="utf-8"))
    expected_progress = {
        "completed_calls": lane.last_completed_calls,
        "rows_persisted": lane.last_rows_persisted,
        "fingerprint": metadata_module._progress_fingerprint(
            completed_calls=lane.last_completed_calls,
            rows_persisted=lane.last_rows_persisted,
        ),
    }
    assert payload["status"] == "needs_resume"
    assert payload["raw_status"] == "vpn_auth_failure"
    assert payload["progress"] == expected_progress
    assert payload["database_sha256"] == lane.state_artifact_digest
    assert payload["prior_state"] == {
        "run_id": lane.state_artifact_run_id,
        "name": lane.state_artifact_name,
        "sha256": lane.state_artifact_digest,
        "progress": expected_progress,
        "telemetry": {
            "planned_calls": 1,
            "journal_skips": 0,
            "failed_calls": 0,
            "running_calls": 0,
            "completed_calls": 1,
            "tables_persisted": 1,
            "rows_persisted": 5,
        },
    }
    assert payload["state_artifact"] == {
        "run_id": lane.state_artifact_run_id,
        "name": lane.state_artifact_name,
        "sha256": lane.state_artifact_digest,
        "artifact_id": "",
        "artifact_digest": "",
        "required": False,
        "attested": False,
        "uploaded": False,
    }
    assert not (metadata_dir / "lane-state-attestation.json").exists()
    assert github_output.read_text(encoding="utf-8").splitlines() == [
        "final-outcome=needs_resume",
        "snapshot-attested=false",
    ]

    next_lanes, _next_state, summary = resume_control.build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        current_iteration=2,
        expected_chain_id="chain-1",
        expected_source_sha="a" * 40,
    )

    assert len(next_lanes) == 1
    retry_lane = next_lanes[0]
    assert retry_lane.attempt_count == lane.attempt_count + 1
    assert retry_lane.failure_streak == lane.failure_streak + 1
    assert retry_lane.class_failure_streak == 1
    assert retry_lane.zero_progress_streak == lane.zero_progress_streak + 1
    assert retry_lane.last_failure_reason == "needs_resume"
    assert retry_lane.last_failure_class == "vpn_egress"
    assert retry_lane.last_completed_calls == lane.last_completed_calls
    assert retry_lane.last_rows_persisted == lane.last_rows_persisted
    assert retry_lane.state_artifact_run_id == lane.state_artifact_run_id
    assert retry_lane.state_artifact_name == lane.state_artifact_name
    assert retry_lane.state_artifact_digest == lane.state_artifact_digest
    assert summary["deferred_lane_count"] == 1
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 1
    assert summary["failure_reason_counts"] == {"vpn_auth_failure": 1}
    assert summary["failure_class_counts"] == {"vpn_egress": 1}


def test_restored_vpn_auth_failure_rejects_post_restore_progress(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nbadb.orchestrate import full_extraction_control as resume_control

    lane = _set_restored_auth_failure_env(monkeypatch, tmp_path)
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "insert into _extraction_journal values "
        "('draft_history', '{\"season\":\"2020-21\"}', 'done', 2)"
    )
    conn.execute("checkpoint")
    conn.close()

    assert metadata_module.main() == 0

    metadata_dir = tmp_path / "artifacts" / "extraction"
    payload = json.loads((metadata_dir / "lane-metadata.json").read_text(encoding="utf-8"))
    assert payload["status"] == "pipeline_failure"
    assert payload["raw_status"] == "vpn_auth_failure"
    assert payload["progress"]["completed_calls"] == lane.last_completed_calls + 1
    assert payload["progress"]["rows_persisted"] == lane.last_rows_persisted + 2
    assert payload["prior_state"] is None
    assert payload["state_artifact"]["name"] != lane.state_artifact_name

    next_lanes, _next_state, summary = resume_control.build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        current_iteration=2,
        expected_chain_id="chain-1",
        expected_source_sha="a" * 40,
    )

    assert next_lanes[0].attempt_count == lane.attempt_count + 1
    assert next_lanes[0].state_artifact_run_id == lane.state_artifact_run_id
    assert next_lanes[0].state_artifact_name == lane.state_artifact_name
    assert next_lanes[0].state_artifact_digest == lane.state_artifact_digest
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 0
    assert summary["failure_reason_counts"] == {"invalid-vpn-auth-rejection-metadata": 1}
    assert summary["failure_class_counts"] == {"runner_infrastructure": 1}


def test_partial_vpn_auth_failure_writer_metadata_cannot_open_auth_circuit(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nbadb.orchestrate import full_extraction_control as resume_control

    lane = _set_auth_failure_env(monkeypatch, tmp_path)
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "create table _extraction_journal (endpoint varchar, status varchar, rows_extracted bigint)"
    )
    conn.execute("insert into _extraction_journal values ('draft_history', 'done', 1)")
    conn.close()

    assert metadata_module.main() == 0

    metadata_dir = tmp_path / "artifacts" / "extraction"
    payload = json.loads((metadata_dir / "lane-metadata.json").read_text(encoding="utf-8"))
    assert payload["status"] == "pipeline_failure"
    assert payload["progress"]["completed_calls"] == 1
    assert payload["progress"]["rows_persisted"] == 1
    assert payload["state_artifact"]["required"] is True
    assert payload["state_artifact"]["attested"] is True

    next_lanes, _next_state, summary = resume_control.build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        current_iteration=2,
        expected_chain_id="chain-1",
        expected_source_sha="a" * 40,
    )

    assert next_lanes[0].attempt_count == lane.attempt_count + 1
    assert next_lanes[0].last_failure_class == "runner_infrastructure"
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 0
    assert summary["failure_reason_counts"] == {"invalid-vpn-auth-rejection-metadata": 1}
    assert summary["failure_class_counts"] == {"runner_infrastructure": 1}


def test_metadata_v2_records_durable_progress_and_artifact(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-timeout")
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("create table _extraction_journal(status varchar, rows_extracted bigint)")
    conn.execute("insert into _extraction_journal values ('done', 5), ('running', 0)")
    conn.execute("create table stg_example(value integer)")
    conn.execute("insert into stg_example values (1), (2)")
    conn.close()

    payload = metadata_module.build_payload()

    assert payload["metadata_schema_version"] == 3
    assert payload["status"] == "needs_resume"
    assert payload["failure_class"] == "timeout_progress"
    assert payload["progress"]["completed_calls"] == 1
    assert payload["progress"]["rows_persisted"] == 5
    assert len(payload["progress"]["fingerprint"]) == 64
    assert payload["state_artifact"] == {
        "run_id": "12345",
        "name": "extraction-lane-recovery-chain-1-lane-1-run-12345-attempt-1",
        "sha256": payload["state_artifact"]["sha256"],
        "attested": False,
        "required": True,
        "retention_days": 30,
    }
    assert len(payload["state_artifact"]["sha256"]) == 64
    assert payload["coverage_units_hash"] == "b" * 64
    assert payload["database_sha256"] == payload["state_artifact"]["sha256"]


def test_zero_progress_timeout_is_stalled_not_running_progress(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-timeout")
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("create table _extraction_journal(status varchar, rows_extracted bigint)")
    conn.execute("insert into _extraction_journal values ('running', 0)")
    conn.close()

    payload = metadata_module.build_payload()

    assert payload["progress"]["completed_calls"] == 0
    assert payload["failure_class"] == "timeout_stalled"
    assert payload["telemetry"]["zero_row_reason"] == "running_without_durable_progress"


def test_extract_error_preserves_response_contract_root_counts(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    summary_path = _set_env(monkeypatch, tmp_path, status="extract-error")
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "failed_extractions": 2,
                    "errors": [
                        "ep[{}]: [response_contract:JSONDecodeError]",
                        "ep[{}]: [response_contract:JSONDecodeError]",
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    payload = metadata_module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["failure_class"] == "response_contract"
    assert payload["root_error_type"] == "JSONDecodeError"
    assert payload["root_error_type_counts"] == {"JSONDecodeError": 2}


def test_extract_error_with_completed_zero_row_calls_requires_resume(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    summary_path = _set_env(monkeypatch, tmp_path, status="extract-error")
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "failed_extractions": 1,
                    "errors": ["ep[{}]: [transport_transient:TimeoutError]"],
                }
            }
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("create table _extraction_journal(status varchar, rows_extracted bigint)")
    conn.execute("insert into _extraction_journal values ('done', 0), ('failed', 0)")
    conn.close()

    payload = metadata_module.build_payload()

    assert payload["status"] == "needs_resume"
    assert payload["progress"]["completed_calls"] == 1
    assert payload["progress"]["rows_persisted"] == 0
    assert payload["state_artifact"]["required"] is True
    assert len(payload["state_artifact"]["sha256"]) == 64


def test_checkpoint_duckdb_folds_wal_into_attested_database(
    metadata_module: ModuleType,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "nba.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute("PRAGMA disable_checkpoint_on_shutdown")
    conn.execute(
        "create table _extraction_journal(endpoint varchar, params varchar, status varchar)"
    )
    conn.execute("insert into _extraction_journal values ('video_details', '{}', 'done')")
    conn.close()
    wal_path = Path(f"{db_path}.wal")
    assert wal_path.is_file() and wal_path.stat().st_size > 0

    metadata_module._checkpoint_duckdb(db_path)

    assert not wal_path.exists()
    copied_path = tmp_path / "copied.duckdb"
    copied_path.write_bytes(db_path.read_bytes())
    copied = duckdb.connect(str(copied_path), read_only=True)
    try:
        assert copied.execute("select status from _extraction_journal").fetchall() == [("done",)]
    finally:
        copied.close()


def test_main_emits_snapshot_attestation_only_after_metadata_and_hash(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-timeout")
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("create table _extraction_journal(status varchar, rows_extracted bigint)")
    conn.execute("insert into _extraction_journal values ('done', 0)")
    conn.close()

    assert metadata_module.main() == 0

    metadata_path = tmp_path / "artifacts" / "extraction" / "lane-metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    attestation = json.loads(
        (tmp_path / "artifacts" / "extraction" / "lane-state-attestation.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(payload["database_sha256"]) == 64
    assert payload["database_sha256"] == payload["state_artifact"]["sha256"]
    assert payload["state_artifact"]["attested"] is True
    assert attestation == {
        "schema_version": 3,
        "source_sha": "abc123",
        "chain_id": "chain-1",
        "lane_id": "lane-1",
        "run_id": "12345",
        "artifact_name": "extraction-lane-recovery-chain-1-lane-1-run-12345-attempt-1",
        "coverage_units_hash": "b" * 64,
        "database_sha256": payload["database_sha256"],
        "attested": True,
        "expected_empty": False,
        "workload_contract": None,
    }
    assert not Path(f"{db_path}.wal").exists()
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "final-outcome=needs_resume",
        "snapshot-attested=true",
    ]


@pytest.mark.parametrize("run_id", ["", "0", "00123", "not-a-run-id"])
def test_main_does_not_attest_without_positive_run_id(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    run_id: str,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-timeout")
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("create table _extraction_journal(status varchar, rows_extracted bigint)")
    conn.execute("insert into _extraction_journal values ('done', 0)")
    conn.close()

    assert metadata_module.main() == 0

    metadata_path = tmp_path / "artifacts" / "extraction" / "lane-metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["state_artifact"]["attested"] is False
    assert not (metadata_path.parent / "lane-state-attestation.json").exists()


def test_writer_attestation_is_accepted_by_checkpoint_consumer(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from nbadb.orchestrate import full_extraction_control as checkpoint_control

    lane = checkpoint_control.FullExtractionLane(
        lane_id="lane-1",
        lane_index=0,
        lane_name="Lane 1",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("common_all_players",),
        timeout_seconds=3600,
    )
    coverage_hash = checkpoint_control._coverage_hash_for_lane(lane)
    _set_env(monkeypatch, tmp_path, status="complete")
    monkeypatch.setenv("KIND", lane.lane_kind)
    monkeypatch.setenv("PATTERNS", ",".join(lane.patterns))
    monkeypatch.setenv("ENDPOINTS", ",".join(lane.endpoints))
    monkeypatch.setenv("SEASON_TYPES", "")
    monkeypatch.setenv("SEASON_START", "")
    monkeypatch.setenv("SEASON_END", "")
    monkeypatch.setenv("COVERAGE_UNITS_HASH", coverage_hash)

    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "create table _extraction_journal "
        "(endpoint varchar, params varchar, status varchar, rows_extracted bigint)"
    )
    conn.execute("insert into _extraction_journal values ('common_all_players', '{}', 'done', 1)")
    conn.close()

    assert metadata_module.main() == 0

    run_id = "12345"
    artifact_name = "extraction-lane-chain-1-lane-1"
    metadata_artifact_name = "extraction-lane-metadata-chain-1-lane-1"
    source_dir = tmp_path / "artifacts" / "extraction"
    metadata_dir = tmp_path / "checkpoint-metadata"
    metadata_path = metadata_dir / f"run-{run_id}" / metadata_artifact_name / "lane-metadata.json"
    metadata_path.parent.mkdir(parents=True)
    shutil.copy2(source_dir / "lane-metadata.json", metadata_path)
    finalized_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    finalized_payload["state_artifact"].update(
        {
            "uploaded": True,
            "artifact_id": "67890",
            "artifact_digest": f"sha256:{'c' * 64}",
        }
    )
    metadata_path.write_text(json.dumps(finalized_payload) + "\n", encoding="utf-8")

    lane_artifacts_dir = tmp_path / "checkpoint-lanes"
    lane_artifact_dir = lane_artifacts_dir / f"run-{run_id}" / artifact_name
    lane_artifact_dir.mkdir(parents=True)
    checkpoint_db_path = lane_artifact_dir / "nba.duckdb"
    shutil.copy2(db_path, checkpoint_db_path)
    shutil.copy2(
        source_dir / "lane-state-attestation.json",
        lane_artifact_dir / "lane-state-attestation.json",
    )
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert (
        checkpoint_control._validate_current_lane_artifact(
            lane=lane,
            metadata=payload,
            metadata_path=metadata_path,
            metadata_dir=metadata_dir,
            db_path=checkpoint_db_path,
            artifacts_dir=lane_artifacts_dir,
            chain_id="chain-1",
            source_sha="abc123",
            authorized_run_ids={run_id},
        )
        == []
    )


def test_main_does_not_attest_when_checkpoint_fails(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-timeout")
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("create table _extraction_journal(status varchar, rows_extracted bigint)")
    conn.close()

    def fail_checkpoint(_path: Path) -> None:
        raise RuntimeError("checkpoint failed")

    monkeypatch.setattr(metadata_module, "_checkpoint_duckdb", fail_checkpoint)

    with pytest.raises(RuntimeError, match="checkpoint failed"):
        metadata_module.main()

    assert not output_path.exists()
    assert not (tmp_path / "artifacts" / "extraction" / "lane-metadata.json").exists()


def test_main_does_not_attest_when_atomic_metadata_publish_fails(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-timeout")
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute("create table _extraction_journal(status varchar, rows_extracted bigint)")
    conn.execute("insert into _extraction_journal values ('done', 0)")
    conn.close()

    def fail_replace(_self: Path, _target: Path) -> Path:
        raise OSError("metadata publish failed")

    monkeypatch.setattr(metadata_module.Path, "replace", fail_replace)

    with pytest.raises(OSError, match="metadata publish failed"):
        metadata_module.main()

    assert not output_path.exists()
    assert not (tmp_path / "artifacts" / "extraction" / "lane-metadata.json").exists()


def test_main_writes_diagnostics_metadata_without_attesting_missing_database(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-error")
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    assert metadata_module.main() == 0

    metadata_path = tmp_path / "artifacts" / "extraction" / "lane-metadata.json"
    assert metadata_path.is_file()
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pipeline_failure"
    assert payload["state_artifact"]["attested"] is False
    assert not (tmp_path / "artifacts" / "extraction" / "lane-state-attestation.json").exists()
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "final-outcome=pipeline_failure",
        "snapshot-attested=false",
    ]


def test_complete_lane_with_untrusted_snapshot_is_downgraded_to_pipeline_failure(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="complete")
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "create table _extraction_journal (endpoint varchar, status varchar, rows_extracted bigint)"
    )
    conn.execute("insert into _extraction_journal values ('draft_history', 'done', 1)")
    conn.close()
    marker = tmp_path / "artifacts" / "extraction" / "lane-state-untrusted"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("cache binding mismatch\n", encoding="utf-8")

    assert metadata_module.main() == 0

    metadata_path = marker.parent / "lane-metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pipeline_failure"
    assert payload["raw_status"] == "snapshot-unattested"
    assert payload["state_artifact"]["attested"] is False
    assert payload["telemetry"]["completion_evidence_errors"] == [
        "snapshot_unattested:restored lane state was rejected as untrusted"
    ]
    assert not (marker.parent / "lane-state-attestation.json").exists()
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "final-outcome=pipeline_failure",
        "snapshot-attested=false",
    ]


def test_player_team_season_workload_contract_binds_exact_base_units(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="complete")
    monkeypatch.setenv("PATTERNS", "player_team_season")
    monkeypatch.setenv("ENDPOINTS", "video_details")
    monkeypatch.setenv("SEASON_START", "2020")
    monkeypatch.setenv("SEASON_END", "2021")
    monkeypatch.setenv("SEASON_TYPES", "Regular Season")
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.execute(
        "create table _extraction_journal(endpoint varchar, status varchar, rows_extracted bigint)"
    )
    conn.execute("insert into _extraction_journal values ('video_details', 'done', 2)")
    conn.close()
    store = _write_workload(
        db_path,
        [
            {
                "season": "2021-22",
                "season_type": "Regular Season",
                "player_id": 2,
                "team_id": 20,
            },
            {
                "season": "2020-21",
                "season_type": "Regular Season",
                "player_id": 1,
                "team_id": 10,
            },
        ],
        seasons=["2020-21", "2021-22"],
        season_types=["Regular Season"],
    )
    expected_units = [
        [2020, "Regular Season", 1, 10],
        [2021, "Regular Season", 2, 20],
    ]
    expected_digest = hashlib.sha256(
        json.dumps(
            expected_units,
            separators=(",", ":"),
            sort_keys=False,
        ).encode()
    ).hexdigest()

    payload = metadata_module.build_payload()

    assert payload["status"] == "complete"
    assert payload["expected_empty"] is False
    assert payload["workload_contract"] == {
        "integrity": store.integrity_attestation(),
        "requested_pairs": [
            {
                "season": "2020-21",
                "season_type": "Regular Season",
                "row_count": 1,
            },
            {
                "season": "2021-22",
                "season_type": "Regular Season",
                "row_count": 1,
            },
        ],
        "expected_base_unit_count": 2,
        "expected_base_units_sha256": expected_digest,
        "expected_empty": False,
    }


def test_player_team_season_contract_uses_explicit_workload_source(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="extract-error")
    monkeypatch.setenv("PATTERNS", "player_team_season")
    monkeypatch.setenv("ENDPOINTS", "video_details")
    workload_db_path = tmp_path / "discovery-artifact" / "nba.duckdb"
    workload_db_path.parent.mkdir(parents=True)
    store = _write_workload(
        workload_db_path,
        [
            {
                "season": "2020-21",
                "season_type": "Regular Season",
                "player_id": 1,
                "team_id": 10,
            }
        ],
        seasons=["2020-21"],
        season_types=["Regular Season"],
    )
    monkeypatch.setenv("WORKLOAD_DUCKDB_PATH", str(workload_db_path))

    payload = metadata_module.build_payload()

    assert payload["workload_contract"]["integrity"] == store.integrity_attestation()
    assert payload["workload_contract_error"] == ""


def test_failed_player_team_lane_writes_diagnostics_without_workload_sidecars(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="failed-before-extract")
    monkeypatch.setenv("PATTERNS", "player_team_season")
    monkeypatch.setenv("ENDPOINTS", "video_details")

    assert metadata_module.main() == 0

    metadata_path = tmp_path / "artifacts" / "extraction" / "lane-metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pipeline_failure"
    assert payload["workload_contract"] is None
    assert "sidecars are missing or invalid" in payload["workload_contract_error"]
    assert payload["state_artifact"]["attested"] is False
    assert not (metadata_path.parent / "lane-state-attestation.json").exists()


def test_attested_empty_workload_allows_complete_snapshot_without_journal(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="complete")
    monkeypatch.setenv("PATTERNS", "player_team_season")
    monkeypatch.setenv("ENDPOINTS", "video_details")
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.close()
    store = _write_workload(
        db_path,
        [],
        seasons=["2020-21"],
        season_types=["Regular Season"],
    )
    empty_digest = hashlib.sha256(b"[]").hexdigest()

    assert metadata_module.main() == 0

    payload = json.loads(
        (tmp_path / "artifacts" / "extraction" / "lane-metadata.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "complete"
    assert payload["expected_empty"] is True
    assert payload["workload_contract"] == {
        "integrity": store.integrity_attestation(),
        "requested_pairs": [
            {
                "season": "2020-21",
                "season_type": "Regular Season",
                "row_count": 0,
            }
        ],
        "expected_base_unit_count": 0,
        "expected_base_units_sha256": empty_digest,
        "expected_empty": True,
    }
    assert payload["telemetry"]["completion_evidence_errors"] == []
    assert payload["telemetry"]["db_telemetry"]["journal_present"] is False
    attestation = json.loads(
        (tmp_path / "artifacts" / "extraction" / "lane-state-attestation.json").read_text(
            encoding="utf-8"
        )
    )
    assert attestation["expected_empty"] is True
    assert attestation["database_sha256"] == payload["database_sha256"]
    assert attestation["workload_contract"] == payload["workload_contract"]
    assert payload["state_artifact"]["attested"] is True
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "final-outcome=complete",
        "snapshot-attested=true",
    ]


def test_player_team_season_workload_contract_fails_closed_on_missing_scope(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="complete")
    monkeypatch.setenv("PATTERNS", "player_team_season")
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.close()
    _write_workload(
        db_path,
        [],
        seasons=["2019-20"],
        season_types=["Regular Season"],
    )

    with pytest.raises(ValueError, match="does not cover requested pairs"):
        metadata_module.build_payload()


@pytest.mark.parametrize("sidecar_state", ["missing", "invalid"])
def test_player_team_season_workload_contract_rejects_unattested_sidecars(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    sidecar_state: str,
) -> None:
    _set_env(monkeypatch, tmp_path, status="complete")
    monkeypatch.setenv("PATTERNS", "player_team_season")
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.close()
    if sidecar_state == "invalid":
        store = _write_workload(
            db_path,
            [],
            seasons=["2020-21"],
            season_types=["Regular Season"],
        )
        generation_path = store.artifact_path
        assert generation_path is not None
        generation_path.write_bytes(b"corrupt")

    with pytest.raises(ValueError, match="sidecars are missing or invalid"):
        metadata_module.build_payload()


def test_player_team_season_workload_contract_requires_isolated_pattern(
    metadata_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _set_env(monkeypatch, tmp_path, status="complete")
    monkeypatch.setenv("PATTERNS", "player_team_season,season")
    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    conn = duckdb.connect(str(db_path))
    conn.close()

    with pytest.raises(ValueError, match="requires an isolated pattern lane"):
        metadata_module.build_payload()
