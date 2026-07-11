from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pytest

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
        "PATTERNS": "season",
        "ENDPOINTS": "draft_history",
        "SEASON_TYPES": "Regular Season",
        "SEASON_START": "2020",
        "SEASON_END": "2020",
        "COVERAGE_UNITS_HASH": "b" * 64,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(tmp_path)
    return summary_path


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
        "name": "extraction-lane-chain-1-lane-1",
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
