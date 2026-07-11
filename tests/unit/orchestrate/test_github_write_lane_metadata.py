from __future__ import annotations

import json
import types
from pathlib import Path

import duckdb
import pytest

from nbadb.orchestrate.extraction_contract import (
    EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS,
    EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS,
    SEASON_ENDPOINTS_UNSUPPORTED_AFTER_1969,
    EndpointSupportRule,
)

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
        "NETWORK_MODE": "vpn",
        "EFFECTIVE_NETWORK_MODE": "vpn",
        "DIRECT_EGRESS_REASON": "",
        "VPN_SERVER": "us11547.nordvpn.com",
        "VPN_INTERFACE": "tun0",
        "VPN_EXIT_IP": "216.183.125.141",
        "VPN_ATTEMPTED_SERVERS_JSON": '["us11547.nordvpn.com"]',
        "VPN_FAILED_SERVERS_JSON": "[]",
        "COVERAGE_UNITS_HASH": "b" * 64,
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


def test_build_payload_accepts_complete_zero_row_done_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("STATUS", "complete")
    monkeypatch.setenv("ENDPOINTS", "scoreboard_v2,box_score_summary")
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    con = duckdb.connect(str(db_path))
    con.execute(
        "create table _extraction_journal "
        "(endpoint varchar, params varchar, status varchar, rows_extracted bigint)"
    )
    con.execute(
        "insert into _extraction_journal values "
        "('scoreboard_v2', '{}', 'done', 0), "
        "('box_score_summary', '{}', 'done', 0)"
    )
    con.close()

    payload = module.build_payload()

    assert payload["metadata_schema_version"] == 3
    assert payload["status"] == "complete"
    assert payload["coverage_units_hash"] == "b" * 64
    assert len(payload["database_sha256"]) == 64
    assert payload["database_sha256"] == payload["state_artifact"]["sha256"]
    assert payload["telemetry"]["rows_persisted"] == 0
    assert payload["telemetry"]["zero_row_reason"] == "expected_empty"
    assert payload["telemetry"]["completion_evidence_errors"] == []
    assert payload["telemetry"]["db_telemetry"]["done_endpoints"] == [
        "box_score_summary",
        "scoreboard_v2",
    ]


def test_build_payload_rejects_complete_without_readable_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("STATUS", "complete")
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["database_sha256"] == ""
    assert payload["telemetry"]["completion_evidence_errors"] == [
        "database_unreadable",
        "journal_missing",
        "no_completed_journal_calls",
        "missing_endpoint_evidence:scoreboard_v2",
        "database_sha256_missing_or_invalid",
    ]


def test_build_payload_rejects_complete_with_running_journal_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("STATUS", "complete")
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    con = duckdb.connect(str(db_path))
    con.execute(
        "create table _extraction_journal "
        "(endpoint varchar, params varchar, status varchar, rows_extracted bigint)"
    )
    con.execute(
        "insert into _extraction_journal values "
        "('scoreboard_v2', '{}', 'done', 0), "
        "('scoreboard_v2', '{\"retry\": true}', 'running', 0)"
    )
    con.close()

    payload = module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["telemetry"]["completion_evidence_errors"] == ["running_journal_calls"]


def test_build_payload_rejects_complete_without_every_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("STATUS", "complete")
    monkeypatch.setenv("ENDPOINTS", "scoreboard_v2,box_score_summary")
    monkeypatch.chdir(tmp_path)

    db_path = tmp_path / "data" / "nbadb" / "nba.duckdb"
    db_path.parent.mkdir(parents=True)
    con = duckdb.connect(str(db_path))
    con.execute(
        "create table _extraction_journal "
        "(endpoint varchar, params varchar, status varchar, rows_extracted bigint)"
    )
    con.execute("insert into _extraction_journal values ('scoreboard_v2', '{}', 'done', 0)")
    con.close()

    payload = module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["telemetry"]["completion_evidence_errors"] == [
        "missing_endpoint_evidence:box_score_summary"
    ]


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


def test_build_payload_marks_direct_no_vpn_zero_row_failure(
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
    monkeypatch.setenv("STATUS", "extract-error")
    monkeypatch.setenv("EXTRACT_STATUS", "extract-error")
    monkeypatch.setenv("NETWORK_MODE", "direct")
    monkeypatch.setenv("EFFECTIVE_NETWORK_MODE", "direct")
    monkeypatch.setenv("DIRECT_EGRESS_REASON", "vpn-unavailable-or-bypassed")
    monkeypatch.delenv("VPN_STATUS", raising=False)
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["network_mode"] == "direct"
    assert payload["effective_network_mode"] == "direct"
    assert payload["direct_egress_reason"] == "vpn-unavailable-or-bypassed"
    assert payload["vpn_status"] == "direct-no-vpn"
    assert payload["vpn"]["status"] == "direct-no-vpn"
    assert payload["telemetry"]["zero_row_reason"] == "direct_no_data"
    assert payload["artifact_requirements"] == {
        "lane_metadata": True,
        "vpn_diagnostics": False,
    }


def test_build_payload_marks_direct_zero_progress_timeout_as_pipeline_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("NETWORK_MODE", "direct")
    monkeypatch.setenv("EFFECTIVE_NETWORK_MODE", "direct")
    monkeypatch.setenv("VPN_STATUS", "direct-no-vpn")
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
            ('player_dash_team_perf', '{"player_id": 76007, "season": "1946-47"}', 'running', 0)
        """
    )
    con.close()

    payload = module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["raw_status"] == "extract-timeout"
    assert payload["telemetry"]["rows_persisted"] == 0
    assert payload["telemetry"]["failed_calls"] == 0
    assert payload["telemetry"]["zero_row_reason"] == "zero_progress_timeout"
    assert payload["telemetry"]["db_telemetry"]["running_calls"] == 1


def test_build_payload_marks_mixed_failed_running_direct_timeout_as_pipeline_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("NETWORK_MODE", "direct")
    monkeypatch.setenv("EFFECTIVE_NETWORK_MODE", "direct")
    monkeypatch.setenv("VPN_STATUS", "direct-no-vpn")
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
            ('player_dash_game_splits', '{"player_id": 2, "season": "1996-97"}', 'failed', 0),
            ('player_dash_game_splits', '{"player_id": 3, "season": "1996-97"}', 'running', 0)
        """
    )
    con.close()

    payload = module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["raw_status"] == "extract-timeout"
    assert payload["telemetry"]["failed_calls"] == 1
    assert payload["telemetry"]["rows_persisted"] == 0
    assert payload["telemetry"]["zero_row_reason"] == "zero_progress_timeout"
    assert payload["telemetry"]["db_telemetry"]["running_calls"] == 1


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
    assert payload["failure_class"] == "runner_infrastructure"
    assert payload["telemetry"]["rows_persisted"] == 0
    assert payload["telemetry"]["zero_row_reason"] == "running_without_durable_progress"
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


@pytest.mark.parametrize(
    ("season_start", "season_end", "lane_id"),
    [
        ("1961", "1963", "historical-season-no-season-type-1961-1963"),
        ("1964", "1966", "historical-season-no-season-type-1964-1966"),
        ("1967", "1969", "historical-season-no-season-type-1967-1969"),
    ],
)
def test_build_payload_classifies_early_season_lane_as_contract_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    season_start: str,
    season_end: str,
    lane_id: str,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 0,
                    "failed_extractions": 48,
                    "skipped_extractions": 0,
                    "tables_updated": 0,
                },
                "progress": {
                    "patterns": [{"total": 75}],
                    "totals": {"rows_extracted": 0, "failed": 48},
                },
            }
        ),
        encoding="utf-8",
    )
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv("LANE_ID", lane_id)
    monkeypatch.setenv("NAME", f"Historical season {season_start}-{season_end}")
    monkeypatch.setenv("PATTERNS", "season")
    monkeypatch.setenv("ENDPOINTS", ",".join(EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS))
    monkeypatch.setenv("SEASON_START", season_start)
    monkeypatch.setenv("SEASON_END", season_end)
    monkeypatch.setenv("STATUS", "extract-error")
    monkeypatch.setenv("EXTRACT_STATUS", "extract-error")
    monkeypatch.setenv("EXTRACT_EXIT_CODE", "1")
    monkeypatch.setenv("EFFECTIVE_NETWORK_MODE", "direct")
    monkeypatch.setenv("VPN_STATUS", "direct-no-vpn")
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "contract_blocked"
    assert payload["telemetry"]["zero_row_reason"] == "contract_blocked"
    assert len(payload["support_rules"]) == len(EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS)


@pytest.mark.parametrize("endpoint_name", EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS)
def test_build_payload_classifies_1946_1949_season_endpoint_as_contract_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    endpoint_name: str,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 0,
                    "failed_extractions": 16,
                    "skipped_extractions": 0,
                    "tables_updated": 0,
                },
                "progress": {
                    "patterns": [{"total": 16}],
                    "totals": {"rows_extracted": 0, "failed": 16},
                },
            }
        ),
        encoding="utf-8",
    )
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv(
        "LANE_ID",
        f"historical-season-{endpoint_name}-regular-season-playoffs-1946-1949",
    )
    monkeypatch.setenv("NAME", f"Historical season 1946-1949 ({endpoint_name})")
    monkeypatch.setenv("PATTERNS", "season")
    monkeypatch.setenv("ENDPOINTS", endpoint_name)
    monkeypatch.setenv("SEASON_START", "1946")
    monkeypatch.setenv("SEASON_END", "1949")
    monkeypatch.setenv("STATUS", "extract-error")
    monkeypatch.setenv("EXTRACT_STATUS", "extract-error")
    monkeypatch.setenv("EXTRACT_EXIT_CODE", "1")
    monkeypatch.setenv("EFFECTIVE_NETWORK_MODE", "direct")
    monkeypatch.setenv("VPN_STATUS", "direct-no-vpn")
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "contract_blocked"
    assert payload["telemetry"]["zero_row_reason"] == "contract_blocked"
    assert [rule["endpoint_name"] for rule in payload["support_rules"]] == [endpoint_name]


def test_build_payload_keeps_post_1949_season_endpoint_error_as_pipeline_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    endpoint_name = EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS[0]
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 0,
                    "failed_extractions": 16,
                    "skipped_extractions": 0,
                    "tables_updated": 0,
                },
                "progress": {
                    "patterns": [{"total": 16}],
                    "totals": {"rows_extracted": 0, "failed": 16},
                },
            }
        ),
        encoding="utf-8",
    )
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv(
        "LANE_ID",
        f"historical-season-{endpoint_name}-regular-season-playoffs-1950-1950",
    )
    monkeypatch.setenv("NAME", f"Historical season 1950 ({endpoint_name})")
    monkeypatch.setenv("PATTERNS", "season")
    monkeypatch.setenv("ENDPOINTS", endpoint_name)
    monkeypatch.setenv("SEASON_START", "1950")
    monkeypatch.setenv("SEASON_END", "1950")
    monkeypatch.setenv("STATUS", "extract-error")
    monkeypatch.setenv("EXTRACT_STATUS", "extract-error")
    monkeypatch.setenv("EXTRACT_EXIT_CODE", "1")
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "pipeline_failure"
    assert payload["telemetry"]["zero_row_reason"] == "contract_gap"
    assert payload["support_rules"] == []


@pytest.mark.parametrize(
    ("endpoint_name", "season_start", "season_end"),
    [
        ("draft_history", "1970", "1996"),
        ("schedule_int", "1970", "1999"),
        ("ist_standings", "1970", "2020"),
        *(
            (endpoint_name, "2024", "2024")
            for endpoint_name in SEASON_ENDPOINTS_UNSUPPORTED_AFTER_1969
        ),
    ],
)
def test_build_payload_classifies_post_1969_season_endpoint_as_contract_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    endpoint_name: str,
    season_start: str,
    season_end: str,
) -> None:
    module = _load_module()
    summary_path = tmp_path / "artifacts" / "extraction" / "extract-summary.json"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(
        json.dumps(
            {
                "result": {
                    "rows_total": 0,
                    "failed_extractions": 3,
                    "skipped_extractions": 0,
                    "tables_updated": 0,
                },
                "progress": {
                    "patterns": [{"total": 3}],
                    "totals": {"rows_extracted": 0, "failed": 3},
                },
            }
        ),
        encoding="utf-8",
    )
    _set_required_env(monkeypatch, summary_path)
    monkeypatch.setenv(
        "LANE_ID",
        f"historical-season-{endpoint_name}-no-season-type-{season_start}-{season_end}",
    )
    monkeypatch.setenv("NAME", f"Historical season {endpoint_name}")
    monkeypatch.setenv("PATTERNS", "season")
    monkeypatch.setenv("ENDPOINTS", endpoint_name)
    monkeypatch.setenv("SEASON_START", season_start)
    monkeypatch.setenv("SEASON_END", season_end)
    monkeypatch.setenv("STATUS", "extract-error")
    monkeypatch.setenv("EXTRACT_STATUS", "extract-error")
    monkeypatch.setenv("EXTRACT_EXIT_CODE", "1")
    monkeypatch.setenv("EFFECTIVE_NETWORK_MODE", "direct")
    monkeypatch.setenv("VPN_STATUS", "direct-no-vpn")
    monkeypatch.chdir(tmp_path)

    payload = module.build_payload()

    assert payload["status"] == "contract_blocked"
    assert payload["telemetry"]["zero_row_reason"] == "contract_blocked"
    assert [rule["endpoint_name"] for rule in payload["support_rules"]] == [endpoint_name]


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
