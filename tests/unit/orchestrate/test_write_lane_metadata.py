from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore

if TYPE_CHECKING:
    from types import ModuleType


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
    assert attestation == {
        "schema_version": 1,
        "source_sha": "abc123",
        "chain_id": "chain-1",
        "lane_id": "lane-1",
        "coverage_units_hash": "b" * 64,
        "database_sha256": payload["database_sha256"],
        "expected_empty": False,
    }
    assert not Path(f"{db_path}.wal").exists()
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "final-outcome=needs_resume",
        "snapshot-attested=true",
    ]


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

    assert (tmp_path / "artifacts" / "extraction" / "lane-metadata.json").is_file()
    assert not (tmp_path / "artifacts" / "extraction" / "lane-state-attestation.json").exists()
    assert not output_path.exists()


def test_main_never_reattests_state_rejected_by_restore(
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
    marker = tmp_path / "artifacts" / "extraction" / "lane-state-untrusted"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("cache binding mismatch\n", encoding="utf-8")

    assert metadata_module.main() == 0

    assert not output_path.exists()
    assert not (marker.parent / "lane-state-attestation.json").exists()


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
