from __future__ import annotations

import json
import types
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from nbadb.orchestrate.extraction_contract import EndpointSupportRule

if TYPE_CHECKING:
    import pytest

MODULE_PATH = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "write_lane_metadata.py"
MODULE_CODE = compile(MODULE_PATH.read_text(encoding="utf-8"), str(MODULE_PATH), "exec")


def _load_module():
    module = types.ModuleType("github_write_lane_metadata")
    module.__file__ = str(MODULE_PATH)
    exec(MODULE_CODE, module.__dict__)
    return module


def _set_required_env(monkeypatch: pytest.MonkeyPatch, summary_path: Path) -> None:
    values = {
        "RESUME_ONLY": "false",
        "VPN_STATUS": "connected",
        "EXTRACT_SUMMARY_PATH": str(summary_path),
        "CHAIN_ID": "25930066284",
        "ITERATION": "2",
        "LANE_ID": "historical-date-scoreboard-v2-no-season-type-1958-1969-split-1962-1965",
        "LANE_INDEX": "14",
        "NAME": "Historical date 1958-1969 (scoreboard_v2) 1962-1965",
        "KIND": "historical",
        "SOURCE_REF": "main",
        "SOURCE_SHA": "653018dec9c487d84dcfd0e94ec67a59d9402c52",
        "STATUS": "extract-timeout",
        "CACHE_HIT": "false",
        "RESTORE_SOURCE": "none",
        "RESTORE_USABLE": "false",
        "RESTART_MODE": "clean-restart",
        "TIMEOUT_SECONDS": "7200",
        "EFFECTIVE_TIMEOUT_SECONDS": "7200",
        "PATTERNS": "date",
        "SEASON_TYPES": "",
        "ENDPOINTS": "scoreboard_v2",
        "SEASON_START": "1962",
        "SEASON_END": "1965",
        "PARENT_LANE_ID": "historical-date-scoreboard-v2-no-season-type-1958-1969",
        "SPLIT_GENERATION": "1",
        "STARTED_AT": "2026-05-21T08:43:49Z",
        "FINISHED_AT": "2026-05-21T10:43:59Z",
        "EXTRACT_STATUS": "extract-timeout",
        "EXTRACT_EXIT_CODE": "124",
        "VPN_SERVER": "us11547.nordvpn.com",
        "VPN_INTERFACE": "tun0",
        "VPN_EXIT_IP": "216.183.125.141",
        "VPN_ATTEMPTED_SERVERS_JSON": '["us11547.nordvpn.com"]',
        "VPN_FAILED_SERVERS_JSON": "[]",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_build_payload_uses_duckdb_fallback_when_timeout_summary_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        create table _extraction_journal (
            endpoint varchar,
            params varchar,
            status varchar,
            rows_extracted bigint
        )
        """
    )
    con.execute(
        """
        insert into _extraction_journal values
            ('scoreboard_v2', '{}', 'done', 18),
            ('scoreboard_v2', '{}', 'done', 9),
            ('scoreboard_v2', '{}', 'running', 0)
        """
    )
    con.execute("create table stg_scoreboard (id integer)")
    con.execute("insert into stg_scoreboard values (1), (2), (3)")
    con.execute("create table stg_scoreboard_available (id integer)")
    con.execute("insert into stg_scoreboard_available values (1), (2)")
    con.close()

    payload = module.build_payload()

    assert payload["status"] == "needs_resume"
    assert payload["raw_status"] == "extract-timeout"
    assert payload["telemetry"]["planned_calls"] == 3
    assert payload["telemetry"]["rows_persisted"] == 27
    assert payload["telemetry"]["tables_persisted"] == 2
    assert payload["telemetry"]["zero_row_reason"] == ""
    assert payload["telemetry"]["db_telemetry"]["running_calls"] == 1
    assert payload["vpn"]["attempted_servers"] == ["us11547.nordvpn.com"]


def test_build_payload_marks_zero_row_timeout_resumable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 0,
                    "failed_extractions": 0,
                    "skipped_extractions": 0,
                    "tables_updated": 0,
                },
                "progress": {"patterns": [{"total": 1}], "totals": {}},
            }
        ),
        encoding="utf-8",
    )
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("STATUS", "extract-timeout")
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "needs_resume"
    assert payload["telemetry"]["zero_row_reason"] == "unknown"


def test_build_payload_marks_partial_extract_error_resumable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 8242,
                    "failed_extractions": 3,
                    "skipped_extractions": 0,
                    "tables_updated": 1,
                },
                "progress": {"patterns": [{"total": 5126}], "totals": {}},
            }
        ),
        encoding="utf-8",
    )
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("STATUS", "extract-error")
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "needs_resume"
    assert payload["telemetry"]["rows_persisted"] == 8242
    assert payload["telemetry"]["failed_calls"] == 3


def test_build_payload_marks_running_extract_error_resumable_from_duckdb(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("STATUS", "extract-error")
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    con = duckdb.connect(str(db_path))
    con.execute(
        """
        create table _extraction_journal (
            endpoint varchar,
            params varchar,
            status varchar,
            rows_extracted bigint
        )
        """
    )
    con.execute(
        """
        insert into _extraction_journal values
            ('scoreboard_v2', '{}', 'running', 0)
        """
    )
    con.close()

    payload = module.build_payload()

    assert payload["status"] == "needs_resume"
    assert payload["raw_status"] == "extract-error"
    assert payload["telemetry"]["rows_persisted"] == 0
    assert payload["telemetry"]["zero_row_reason"] == "zero_row_progress"
    assert payload["telemetry"]["db_telemetry"]["running_calls"] == 1


def test_build_payload_ignores_malformed_vpn_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("VPN_ATTEMPTED_SERVERS_JSON", "not json")
    monkeypatch.setenv("VPN_FAILED_SERVERS_JSON", "{}")
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["vpn"]["attempted_servers"] == []
    assert payload["vpn"]["failed_servers"] == []


def test_main_writes_lane_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 4,
                    "failed_extractions": 1,
                    "skipped_extractions": 0,
                    "tables_updated": 1,
                },
                "progress": {
                    "patterns": [{"total": 5}],
                    "totals": {"rows_extracted": 4},
                },
            }
        ),
        encoding="utf-8",
    )
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.chdir(tmp_path)

    assert module.main() == 0

    payload = json.loads(
        (tmp_path / "artifacts" / "extraction" / "lane-metadata.json").read_text(encoding="utf-8")
    )
    assert payload["telemetry"]["planned_calls"] == 5
    assert payload["telemetry"]["rows_persisted"] == 4
    assert payload["telemetry"]["failed_calls"] == 1
    assert payload["status"] == "needs_resume"
    assert payload["artifact_requirements"] == {
        "lane_metadata": True,
        "vpn_diagnostics": True,
    }


def test_build_payload_classifies_documented_zero_row_as_contract_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import nbadb.orchestrate.extraction_contract as extraction_contract

    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 0,
                    "failed_extractions": 2,
                    "skipped_extractions": 0,
                    "tables_updated": 0,
                },
                "progress": {
                    "patterns": [{"total": 2}],
                    "totals": {"rows_extracted": 0, "failed": 2},
                },
            }
        ),
        encoding="utf-8",
    )
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("ENDPOINTS", "scoreboard_v2")
    monkeypatch.setenv("PATTERNS", "date")
    monkeypatch.setenv("SEASON_START", "1962")
    monkeypatch.setenv("SEASON_END", "1965")
    monkeypatch.setenv("STATUS", "extract-error")
    monkeypatch.setattr(
        extraction_contract,
        "FULL_EXTRACTION_SUPPORT_RULES",
        (
            EndpointSupportRule(
                endpoint_name="scoreboard_v2",
                pattern="date",
                classification="contract_blocked",
                reason="Upstream date endpoint is unavailable for this range.",
                evidence="docs/endpoint-analysis/scoreboard_v2.md",
                revalidation_command="uv run nbadb endpoint-probe scoreboard_v2",
                season_start=1962,
                season_end=1965,
            ),
        ),
    )
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "contract_blocked"
    assert payload["telemetry"]["zero_row_reason"] == "contract_blocked"
    assert payload["support_rules"][0]["endpoint_name"] == "scoreboard_v2"


def test_build_payload_keeps_undocumented_zero_row_error_as_pipeline_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 0,
                    "failed_extractions": 1,
                    "skipped_extractions": 0,
                    "tables_updated": 0,
                },
                "progress": {"patterns": [{"total": 1}], "totals": {"failed": 1}},
            }
        ),
        encoding="utf-8",
    )
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("STATUS", "extract-error")
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["telemetry"]["zero_row_reason"] == "contract_gap"
