from __future__ import annotations

import json
import math
import pathlib
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import duckdb
import pytest

from nbadb.core.types import VIDEO_CONTEXT_MEASURES, SeasonType
from nbadb.orchestrate.extraction_contract import (
    EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS,
    EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS,
    PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_1996,
    PLAYER_SEASON_FULL_EXTRACTION_UNSUPPORTED_ENDPOINTS,
    PLAYER_TRACKING_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_2013,
    SEASON_ENDPOINTS_SUPPORTED_FROM_1997,
    SEASON_ENDPOINTS_UNSUPPORTED_AFTER_1969,
    EndpointSupportRule,
    contract_blocking_rules_for_lane,
)
from nbadb.orchestrate.full_extraction_control import (
    FullExtractionChainState,
    FullExtractionLane,
    _artifact_lane_id_for_database,
    _attested_current_lane_artifacts,
    _canonical_contract_blocked_audit_row,
    _compatible_previous_checkpoint_lane_ids,
    _coverage_fingerprint,
    _coverage_hash_for_lane,
    _coverage_units_for_lane,
    _file_sha256,
    _hash_payload,
    _merge_database_paths,
    _metadata_by_lane,
    _metadata_records_by_lane,
    _retry_budget_exhausted,
    _schedule_lanes,
    _workload_scope_contract,
    build_checkpoint_database,
    build_default_manifest,
    build_metadata_audit,
    build_resume_manifest,
    lane_outcome_from_metadata,
    manifest_payload,
    merge_final_database,
    merge_lane_databases,
    normalize_manifest,
    redispatch_manifest_payload,
    validate_checkpoint_artifact,
    validate_manifest,
    validate_workflow_dispatch_manifest_json,
)
from nbadb.orchestrate.full_extraction_control import (
    main as full_extraction_main,
)
from nbadb.orchestrate.seasons import season_range
from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore
from nbadb.orchestrate.workload_profile import (
    EndpointWorkloadProfile,
    WorkloadPlanningSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


TEST_CHAIN_ID = "chain"
TEST_RUN_ID = "12345"
TEST_SOURCE_SHA = "a" * 40
TEST_ARTIFACT_ID = "987654321"
TEST_ARTIFACT_DIGEST = f"sha256:{'c' * 64}"


def _support_row(
    endpoint_name: str,
    param_patterns: list[str],
    earliest_supported_season: int | None,
    *,
    season_type_contract_status: str = "not_applicable",
    declared_supported_season_types: list[str] | None = None,
) -> dict[str, object]:
    return {
        "endpoint_name": endpoint_name,
        "execution_semantics": "historical_backfill"
        if any(
            pattern
            in {"season", "game", "date", "player_season", "team_season", "player_team_season"}
            for pattern in param_patterns
        )
        else "reference_snapshot",
        "param_patterns": param_patterns,
        "earliest_supported_season": earliest_supported_season,
        "season_type_contract_status": season_type_contract_status,
        "declared_supported_season_types": declared_supported_season_types
        or (
            ["Regular Season", "Playoffs", "Pre Season", "All Star"]
            if season_type_contract_status == "supported"
            else []
        ),
    }


def _write_metadata(
    path: Path,
    *,
    lane_id: str,
    status: str,
    raw_status: str | None = None,
    completed_calls: int = 0,
    rows_persisted: int = 0,
    failed_calls: int = 0,
    running_calls: int = 0,
    failure_class: str | None = None,
    endpoints: list[str] | None = None,
    patterns: list[str] | None = None,
    season_start: int | None = None,
    season_end: int | None = None,
) -> None:
    state_artifact_name = (
        f"extraction-lane-{TEST_CHAIN_ID}-{lane_id}"
        if status == "complete"
        else (f"extraction-lane-recovery-{TEST_CHAIN_ID}-{lane_id}-run-{TEST_RUN_ID}-attempt-1")
    )
    payload: dict[str, object] = {
        "lane_id": lane_id,
        "status": status,
        "raw_status": raw_status or status,
        "vpn": {},
        "endpoints": endpoints or [],
        "patterns": patterns or [],
        "season_start": "" if season_start is None else str(season_start),
        "season_end": "" if season_end is None else str(season_end),
        "telemetry": {
            "completed_calls": completed_calls,
            "rows_persisted": rows_persisted,
            "failed_calls": failed_calls,
            "journal_skips": 0,
            "db_telemetry": {"running_calls": running_calls},
        },
    }
    if failure_class is not None:
        payload["failure_class"] = failure_class
    if status == "complete" or completed_calls > 0 or rows_persisted > 0:
        payload["state_artifact"] = {
            "run_id": TEST_RUN_ID,
            "name": state_artifact_name,
            "sha256": "a" * 64,
            "attested": True,
            "uploaded": True,
            "artifact_id": TEST_ARTIFACT_ID,
            "artifact_digest": TEST_ARTIFACT_DIGEST,
            "required": True,
        }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _auth_coordination_metadata(
    lane: FullExtractionLane,
    *,
    raw_status: str = "vpn_auth_circuit_open",
    failure_class: str = "vpn_circuit_deferred",
    iteration: int = 1,
) -> dict[str, Any]:
    zero_progress = {"completed_calls": 0, "rows_persisted": 0}
    vpn_status = raw_status
    return {
        "metadata_schema_version": 3,
        "chain_id": TEST_CHAIN_ID,
        "iteration": str(iteration),
        "source_sha": TEST_SOURCE_SHA,
        "coverage_units_hash": _coverage_hash_for_lane(lane),
        "lane_id": lane.lane_id,
        "lane_index": str(lane.lane_index),
        "lane_name": lane.lane_name,
        "lane_kind": lane.lane_kind,
        "database_sha256": "",
        "status": "needs_resume",
        "raw_status": raw_status,
        "failure_class": failure_class,
        "restore_source": "none",
        "restore_usable": False,
        "restart_mode": "clean-restart",
        "patterns": list(lane.patterns),
        "season_types": list(lane.season_types),
        "context_measures": list(lane.context_measures),
        "endpoints": list(lane.endpoints),
        "season_start": "" if lane.season_start is None else str(lane.season_start),
        "season_end": "" if lane.season_end is None else str(lane.season_end),
        "parent_lane_id": lane.parent_lane_id,
        "split_generation": lane.split_generation,
        "extract_status": "not-run",
        "vpn_status": vpn_status,
        "progress": {**zero_progress, "fingerprint": _hash_payload(zero_progress)},
        "prior_state": None,
        "telemetry": {
            "planned_calls": 0,
            "journal_skips": 0,
            "failed_calls": 0,
            "completed_calls": 0,
            "tables_persisted": 0,
            "rows_persisted": 0,
            "extract_summary_parse_error": "",
            "db_telemetry": {
                "planned_calls": 0,
                "journal_skips": 0,
                "failed_calls": 0,
                "running_calls": 0,
                "completed_calls": 0,
                "tables_persisted": 0,
                "rows_persisted": 0,
            },
        },
        "state_artifact": {
            "run_id": "",
            "name": "",
            "sha256": "",
            "artifact_id": "",
            "artifact_digest": "",
            "required": False,
            "attested": False,
            "uploaded": False,
        },
        "extract_summary": {},
        "vpn": {"status": vpn_status},
    }


def _restored_auth_rejection_metadata(lane: FullExtractionLane) -> dict[str, Any]:
    progress = {
        "completed_calls": lane.last_completed_calls,
        "rows_persisted": lane.last_rows_persisted,
    }
    progress["fingerprint"] = _hash_payload(progress)
    baseline = {
        "planned_calls": lane.last_completed_calls,
        "journal_skips": 0,
        "failed_calls": 0,
        "running_calls": 0,
        "completed_calls": lane.last_completed_calls,
        "tables_persisted": int(lane.last_rows_persisted > 0),
        "rows_persisted": lane.last_rows_persisted,
    }
    payload = _auth_coordination_metadata(
        lane,
        raw_status="vpn_auth_failure",
        failure_class="vpn_egress",
    )
    payload.update(
        {
            "database_sha256": lane.state_artifact_digest,
            "restore_source": "artifact",
            "restore_usable": True,
            "restart_mode": "resume",
            "progress": progress,
            "prior_state": {
                "run_id": lane.state_artifact_run_id,
                "name": lane.state_artifact_name,
                "sha256": lane.state_artifact_digest,
                "progress": progress,
                "telemetry": baseline,
            },
            "state_artifact": {
                "run_id": lane.state_artifact_run_id,
                "name": lane.state_artifact_name,
                "sha256": lane.state_artifact_digest,
                "artifact_id": "",
                "artifact_digest": "",
                "required": False,
                "attested": False,
                "uploaded": False,
            },
        }
    )
    telemetry = payload["telemetry"]
    telemetry.update({field: baseline[field] for field in baseline if field != "running_calls"})
    telemetry["db_telemetry"] = dict(baseline)
    return payload


def _contract_blocked_row(lane: FullExtractionLane) -> dict[str, Any]:
    return _canonical_contract_blocked_audit_row(
        lane.lane_id,
        {
            "lane_kind": lane.lane_kind,
            "endpoints": list(lane.endpoints),
            "patterns": list(lane.patterns),
            "season_start": lane.season_start,
            "season_end": lane.season_end,
            "season_types": list(lane.season_types),
            "context_measures": list(lane.context_measures),
            "coverage_units_hash": _coverage_hash_for_lane(lane),
            "support_rules": [
                rule.to_dict()
                for rule in contract_blocking_rules_for_lane(
                    endpoints=lane.endpoints,
                    patterns=lane.patterns,
                    season_start=lane.season_start,
                    season_end=lane.season_end,
                )
            ],
        },
    )


def _write_attested_metadata(
    path: Path,
    *,
    lane: FullExtractionLane,
    database_path: Path,
    lane_name: str | None = None,
    workload_contract: dict[str, object] | None = None,
    artifact_name: str | None = None,
    chain_id: str = TEST_CHAIN_ID,
    run_id: str = TEST_RUN_ID,
    source_sha: str = TEST_SOURCE_SHA,
) -> None:
    state_artifact_name = artifact_name or f"extraction-lane-{chain_id}-{lane.lane_id}"
    database_sha256 = _file_sha256(database_path)
    payload: dict[str, object] = {
        "metadata_schema_version": 3,
        "chain_id": chain_id,
        "source_sha": source_sha,
        "lane_id": lane.lane_id,
        "lane_index": lane.lane_index,
        "lane_name": lane_name or lane.lane_name,
        "lane_kind": lane.lane_kind,
        "status": "complete",
        "raw_status": "complete",
        "patterns": list(lane.patterns),
        "season_types": list(lane.season_types),
        "context_measures": list(lane.context_measures),
        "endpoints": list(lane.endpoints),
        "season_start": "" if lane.season_start is None else str(lane.season_start),
        "season_end": "" if lane.season_end is None else str(lane.season_end),
        "coverage_units_hash": _coverage_hash_for_lane(lane),
        "database_sha256": database_sha256,
        "state_artifact": {
            "run_id": run_id,
            "name": state_artifact_name,
            "sha256": database_sha256,
            "attested": True,
            "uploaded": True,
            "artifact_id": TEST_ARTIFACT_ID,
            "artifact_digest": TEST_ARTIFACT_DIGEST,
        },
    }
    if workload_contract is not None:
        payload["workload_contract"] = workload_contract
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    artifact_root = next(
        parent for parent in database_path.parents if parent.name == state_artifact_name
    )
    attestation_path = artifact_root / "artifacts/extraction/lane-state-attestation.json"
    attestation_path.parent.mkdir(parents=True, exist_ok=True)
    attestation_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "chain_id": chain_id,
                "source_sha": source_sha,
                "lane_id": lane.lane_id,
                "run_id": run_id,
                "artifact_name": state_artifact_name,
                "coverage_units_hash": _coverage_hash_for_lane(lane),
                "database_sha256": database_sha256,
                "attested": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _lane_artifact_dir(
    root: Path,
    lane: FullExtractionLane,
    *,
    chain_id: str = TEST_CHAIN_ID,
    run_id: str = TEST_RUN_ID,
) -> Path:
    return root / f"run-{run_id}" / f"extraction-lane-{chain_id}-{lane.lane_id}"


def _lane_metadata_path(
    root: Path,
    lane: FullExtractionLane,
    *,
    chain_id: str = TEST_CHAIN_ID,
    run_id: str = TEST_RUN_ID,
) -> Path:
    return (
        root
        / f"run-{run_id}"
        / f"extraction-lane-metadata-{chain_id}-{lane.lane_id}"
        / "lane-metadata.json"
    )


def _write_workload_contract(
    tmp_path: Path,
    *,
    lane: FullExtractionLane,
    params: list[dict[str, object]],
) -> tuple[Path, PlayerTeamSeasonWorkloadStore, dict[str, object]]:
    workload_dir = tmp_path / "workload"
    workload_dir.mkdir(exist_ok=True)
    anchor_path = workload_dir / "nba.duckdb"
    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(anchor_path)
    seasons = season_range(int(lane.season_start), int(lane.season_end))
    covered_pairs = {
        (season, season_type) for season in seasons for season_type in lane.season_types
    }
    store.upsert(
        params,  # type: ignore[arg-type]
        seasons=seasons,
        season_types=list(lane.season_types),
        covered_pairs=covered_pairs,
    )
    _units, contract, errors = _workload_scope_contract(lane, store)
    assert errors == []
    return anchor_path, store, contract


def _build_attested_lane_checkpoint(
    tmp_path: Path,
    *,
    lane: FullExtractionLane,
    journal_rows: list[tuple[str, str]],
    workload_params: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])), encoding="utf-8")
    artifact_dir = _lane_artifact_dir(tmp_path / "lanes", lane)
    artifact_dir.mkdir(parents=True)
    database_path = artifact_dir / "data/nbadb/nba.duckdb"
    database_path.parent.mkdir(parents=True)
    _write_lane_db(
        database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=journal_rows,
    )
    workload_duckdb_path: Path | None = None
    workload_contract: dict[str, object] | None = None
    if set(lane.patterns) == {"player_team_season"}:
        if workload_params is None:
            inferred: dict[tuple[int, int, str, str], dict[str, object]] = {}
            for _endpoint, params_json in journal_rows:
                params = json.loads(params_json)
                key = (
                    int(params["player_id"]),
                    int(params["team_id"]),
                    str(params["season"]),
                    str(params["season_type"]),
                )
                inferred[key] = {
                    "player_id": key[0],
                    "team_id": key[1],
                    "season": key[2],
                    "season_type": key[3],
                }
            workload_params = list(inferred.values())
        workload_duckdb_path, _store, workload_contract = _write_workload_contract(
            tmp_path,
            lane=lane,
            params=workload_params,
        )
    metadata_dir = tmp_path / "metadata"
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, lane),
        lane=lane,
        database_path=database_path,
        workload_contract=workload_contract,
    )
    return _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        workload_duckdb_path=workload_duckdb_path,
    )


def _write_lane_db(
    path: Path, *, alpha_rows: list[int], beta_rows: list[int], journal_rows: list[tuple[str, str]]
) -> None:
    conn = duckdb.connect(str(path))
    conn.execute("CREATE TABLE stg_alpha (value INTEGER)")
    conn.executemany("INSERT INTO stg_alpha VALUES (?)", [(row,) for row in alpha_rows])
    if beta_rows:
        conn.execute("CREATE TABLE stg_beta (value INTEGER)")
        conn.executemany("INSERT INTO stg_beta VALUES (?)", [(row,) for row in beta_rows])
    conn.execute(
        "CREATE TABLE _extraction_journal ("
        "endpoint VARCHAR, params VARCHAR, status VARCHAR, started_at TIMESTAMP, "
        "completed_at TIMESTAMP, rows_extracted BIGINT, error_message VARCHAR, retry_count INTEGER"
        ")"
    )
    if journal_rows:
        conn.executemany(
            "INSERT INTO _extraction_journal VALUES "
            "(?, ?, 'done', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, NULL, 0)",
            journal_rows,
        )
    conn.close()


def _write_checkpoint_report(
    path: Path,
    *,
    database_path: Path,
    lanes: list[FullExtractionLane] | None = None,
    included_lane_ids: list[str] | None = None,
    included_run_ids: list[str] | None = None,
    checkpoint_generation: int = 1,
    workload_integrity: Mapping[str, object] | None = None,
    included_lane_coverage_hashes: dict[str, str] | None = None,
    chain_id: str = TEST_CHAIN_ID,
    run_id: str = TEST_RUN_ID,
    source_sha: str = TEST_SOURCE_SHA,
    coverage_fingerprint: str | None = None,
) -> None:
    lanes = lanes or []
    lane_ids = included_lane_ids or [lane.lane_id for lane in lanes]
    lane_coverage_hashes = included_lane_coverage_hashes or {
        lane.lane_id: _coverage_hash_for_lane(lane) for lane in lanes
    }
    if coverage_fingerprint is None:
        coverage_fingerprint = _coverage_fingerprint(
            [lane for lane in lanes if lane.lane_id in set(lane_ids)]
        )
    path.write_text(
        json.dumps(
            {
                "chain_id": chain_id,
                "run_id": run_id,
                "artifact_name": (
                    f"full-extraction-checkpoint-{chain_id}-iter-{checkpoint_generation}"
                ),
                "source_sha": source_sha,
                "checkpoint_generation": checkpoint_generation,
                "coverage_fingerprint": coverage_fingerprint,
                "included_lane_ids": lane_ids,
                "included_lane_coverage_hashes": lane_coverage_hashes,
                "included_run_ids": included_run_ids or [run_id],
                "manifest_lane_count": len(lanes),
                "database_sha256": _file_sha256(database_path),
                "workload_integrity": workload_integrity,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _build_checkpoint_database(
    *,
    expected_checkpoint_lane_ids: set[str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    manifest_path = pathlib.Path(kwargs["manifest_path"])
    metadata_dir = pathlib.Path(kwargs["metadata_dir"])
    chain_id = str(kwargs.setdefault("chain_id", TEST_CHAIN_ID))
    run_id = str(kwargs.setdefault("run_id", TEST_RUN_ID))
    source_sha = str(kwargs.setdefault("source_sha", TEST_SOURCE_SHA))
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(raw_manifest, dict)
    manifest = normalize_manifest(raw_manifest)
    lanes = list(manifest.lanes)
    previous_report_path = kwargs.get("previous_checkpoint_report_path")
    previous_report: dict[str, Any] = {}
    if previous_report_path is not None and pathlib.Path(previous_report_path).is_file():
        loaded_report = json.loads(pathlib.Path(previous_report_path).read_text(encoding="utf-8"))
        if isinstance(loaded_report, dict):
            previous_report = loaded_report
    previous_generation = int(previous_report.get("checkpoint_generation") or 0)
    previous_lane_ids = {
        str(lane_id) for lane_id in previous_report.get("included_lane_ids", []) if str(lane_id)
    }
    previous_db_path = None
    previous_checkpoint_dir = kwargs.get("previous_checkpoint_dir")
    if previous_checkpoint_dir is not None:
        previous_candidates = sorted(pathlib.Path(previous_checkpoint_dir).rglob("nba.duckdb"))
        if len(previous_candidates) == 1:
            previous_db_path = previous_candidates[0]
    compatible_lane_ids = _compatible_previous_checkpoint_lane_ids(
        lanes,
        previous_included_lane_ids=previous_lane_ids,
        previous_db_path=previous_db_path,
    )
    if expected_checkpoint_lane_ids is None:
        metadata_records = _metadata_records_by_lane(metadata_dir)
        metadata = {
            lane_id: lane_records[-1][1] for lane_id, lane_records in metadata_records.items()
        }
        complete_lane_ids = {
            lane_id
            for lane_id, payload in metadata.items()
            if lane_outcome_from_metadata(payload) == "complete"
        }
        workload_duckdb_path = kwargs.get("workload_duckdb_path")
        workload_store = (
            PlayerTeamSeasonWorkloadStore.from_duckdb_path(pathlib.Path(workload_duckdb_path))
            if workload_duckdb_path is not None
            else None
        )
        _paths, attested_lane_ids, _failures, _run_ids = _attested_current_lane_artifacts(
            artifacts_dir=pathlib.Path(kwargs["lane_artifacts_dir"]),
            metadata_dir=metadata_dir,
            complete_lane_ids=complete_lane_ids,
            metadata=metadata,
            metadata_records=metadata_records,
            lanes_by_id={lane.lane_id: lane for lane in lanes},
            chain_id=chain_id,
            source_sha=source_sha,
            authorized_run_ids={run_id},
            workload_store=workload_store,
        )
        expected_checkpoint_lane_ids = (
            previous_lane_ids | compatible_lane_ids | attested_lane_ids
        ) & {lane.lane_id for lane in lanes}
    checkpoint_lanes = [lane for lane in lanes if lane.lane_id in expected_checkpoint_lane_ids]
    latest_generation = previous_generation + 1
    latest_coverage_hash = _coverage_fingerprint(checkpoint_lanes)
    chain_state = dict(raw_manifest.get("chain_state") or {})
    if previous_generation:
        chain_state.update(
            {
                "previous_checkpoint_run_id": str(previous_report.get("run_id") or ""),
                "previous_checkpoint_artifact_name": str(
                    previous_report.get("artifact_name") or ""
                ),
                "previous_checkpoint_generation": previous_generation,
                "previous_checkpoint_coverage_hash": str(
                    previous_report.get("coverage_fingerprint") or ""
                ),
            }
        )
    chain_state.update(
        {
            "artifact_run_ids": [run_id],
            "latest_checkpoint_run_id": run_id,
            "latest_checkpoint_artifact_name": (
                f"full-extraction-checkpoint-{chain_id}-iter-{latest_generation}"
            ),
            "latest_checkpoint_generation": latest_generation,
            "latest_checkpoint_coverage_hash": latest_coverage_hash,
        }
    )
    raw_manifest.update(
        {
            "chain_id": chain_id,
            "workflow_source_sha": source_sha,
            "chain_state": chain_state,
        }
    )
    manifest_path.write_text(json.dumps(raw_manifest), encoding="utf-8")
    return build_checkpoint_database(**kwargs)


def _workflow_input_block(workflow: str, input_name: str) -> str:
    lines = workflow.splitlines()
    start = next(index for index, line in enumerate(lines) if line == f"      {input_name}:")
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("      ") and not line.startswith("        "):
            break
        block.append(line)
    return "\n".join(block)


def test_build_default_manifest_uses_support_window_thresholds() -> None:
    rows = [
        _support_row("franchise_history", ["static"], None),
        _support_row("common_player_info", ["player"], None),
        _support_row(
            "league_game_log",
            ["season"],
            None,
            season_type_contract_status="supported",
        ),
        _support_row("box_score_traditional", ["game"], 1996),
        _support_row(
            "league_dash_pt_defend",
            ["season"],
            2013,
            season_type_contract_status="supported",
        ),
        _support_row(
            "player_dashboard_by_team",
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
        ),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)

    lanes_by_id = {lane.lane_id: lane for lane in lanes}
    assert lanes_by_id["reference-static"].season_start is None
    assert lanes_by_id["reference-static"].endpoints == ("franchise_history",)
    assert lanes_by_id["reference-player"].endpoints == ("common_player_info",)

    game_lanes = [
        lane for lane in lanes if lane.lane_kind == "historical" and lane.patterns == ("game",)
    ]
    assert "historical-game-box-score-traditional-no-season-type-1996-1999" in lanes_by_id
    assert "historical-game-box-score-traditional-no-season-type-2024-2025" in lanes_by_id
    assert all((lane.season_end - lane.season_start + 1) <= 4 for lane in game_lanes)
    assert {lane.endpoints for lane in game_lanes} == {("box_score_traditional",)}

    season_lanes = [
        lane for lane in lanes if lane.lane_kind == "historical" and lane.patterns == ("season",)
    ]
    assert (
        "historical-season-league-dash-pt-defend-regular-season-playoffs-pre-season-all-star-"
        "2013-2020" in lanes_by_id
    )
    assert all(
        lane.season_types
        == (
            "Regular Season",
            "Playoffs",
            "Pre Season",
            "All Star",
        )
        for lane in season_lanes
    )
    assert {lane.endpoints for lane in season_lanes} == {("league_dash_pt_defend",)}
    assert all((lane.season_end - lane.season_start + 1) <= 8 for lane in season_lanes)

    cross_product_lanes = [lane for lane in lanes if lane.lane_kind == "cross_product"]
    assert (
        "cross-product-player-dashboard-by-team-regular-season-playoffs-pre-season-all-star-"
        "1946-1949" in lanes_by_id
    )
    assert (
        "cross-product-player-dashboard-by-team-regular-season-playoffs-pre-season-all-star-"
        "2022-2025" in lanes_by_id
    )
    assert len(cross_product_lanes) == 20
    assert all((lane.season_end - lane.season_start + 1) <= 4 for lane in cross_product_lanes)
    assert {lane.endpoints for lane in cross_product_lanes} == {("player_dashboard_by_team",)}
    assert all(lane.lane_kind != "cross_product_blocked" for lane in lanes)


def test_chunk_profiles_preserve_coverage_and_contract_blocks() -> None:
    rows = [
        _support_row("scoreboard_v2", ["date"], 1946),
        _support_row("scoreboard_v3", ["date"], 1946),
        _support_row("box_score_traditional", ["game"], 1996),
        _support_row(
            "league_dash_pt_defend",
            ["season"],
            1946,
            season_type_contract_status="supported",
        ),
        _support_row(
            "player_dashboard_by_team",
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
        ),
    ]

    standard = build_default_manifest(support_matrix_rows=rows, chunk_profile="standard")
    balanced = build_default_manifest(support_matrix_rows=rows, chunk_profile="balanced-small")
    micro = build_default_manifest(support_matrix_rows=rows, chunk_profile="micro")

    standard_payload = manifest_payload(standard)
    balanced_payload = manifest_payload(balanced)
    micro_payload = manifest_payload(micro)

    assert balanced_payload["coverage_fingerprint"] == standard_payload["coverage_fingerprint"]
    assert micro_payload["coverage_fingerprint"] == standard_payload["coverage_fingerprint"]
    assert len(balanced) > len(standard)
    assert len(micro) >= len(balanced)
    assert balanced_payload["chunk_profile"] == "balanced-small"
    assert micro_payload["chunk_profile"] == "micro"
    assert balanced_payload["scheduler_diagnostics"]["max_matrix_lanes"] == 256
    assert balanced_payload["scheduler_diagnostics"]["active_wave_count"] >= 1
    assert {
        row["pattern"] for row in balanced_payload["scheduler_diagnostics"]["pattern_cost_summary"]
    } == {"date", "game", "season", "player_team_season"}

    balanced_scoreboard_v2 = [
        lane
        for lane in balanced
        if lane.endpoints == ("scoreboard_v2",) and lane.patterns == ("date",)
    ]
    assert balanced_scoreboard_v2
    assert all(lane.season_start not in {1950, 1954, 1956} for lane in balanced_scoreboard_v2)
    assert all(lane.season_end not in {1950, 1954, 1956} for lane in balanced_scoreboard_v2)
    assert all(lane.season_start == lane.season_end for lane in balanced_scoreboard_v2)

    box_score_lanes = [
        lane
        for lane in balanced
        if lane.endpoints == ("box_score_traditional",) and lane.patterns == ("game",)
    ]
    assert box_score_lanes
    assert all(lane.season_start == lane.season_end for lane in box_score_lanes)
    assert balanced_payload["top_cost_lanes"][0]["planned_wave"] == 0


def test_build_default_manifest_prioritizes_high_cost_lanes_first() -> None:
    rows = [
        _support_row("scoreboard_v2", ["date"], 1946),
        _support_row("box_score_traditional", ["game"], 2024),
    ]
    planning_snapshot = WorkloadPlanningSnapshot(
        endpoint_profiles={
            "scoreboard_v2": EndpointWorkloadProfile(
                endpoint_name="scoreboard_v2",
                endpoint_family="default",
                throughput_tier="cheap_high_volume",
                avg_duration_seconds=1.0,
                p95_duration_seconds=2.0,
                retry_rate=0.0,
                error_rate=0.0,
                avg_rows_per_request=1.0,
                lane_cost=1.0,
                reference_batch_cost=1.0,
                preferred_max_span=1,
            ),
            "box_score_traditional": EndpointWorkloadProfile(
                endpoint_name="box_score_traditional",
                endpoint_family="box_score",
                throughput_tier="expensive_flaky",
                avg_duration_seconds=30.0,
                p95_duration_seconds=60.0,
                retry_rate=0.2,
                error_rate=0.1,
                avg_rows_per_request=1_000.0,
                lane_cost=10.0,
                reference_batch_cost=10.0,
                preferred_max_span=1,
            ),
        },
        cross_product_pair_counts={},
    )

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        planning_snapshot=planning_snapshot,
        chunk_profile="balanced-small",
    )

    assert lanes[0].endpoints == ("box_score_traditional",)
    assert lanes[0].throughput_tier == "expensive_flaky"
    assert lanes[0].estimated_lane_cost > lanes[-1].estimated_lane_cost


def test_full_extraction_workflow_wires_chunk_profiles_and_checkpoints() -> None:
    workflow = (
        pathlib.Path(__file__).resolve().parents[3]
        / ".github"
        / "workflows"
        / "full-extraction.yml"
    ).read_text(encoding="utf-8")

    chunk_profile_block = _workflow_input_block(workflow, "chunk_profile")
    vpn_parallelism_block = _workflow_input_block(workflow, "vpn_parallelism")
    direct_parallelism_block = _workflow_input_block(workflow, "direct_parallelism")
    max_iterations_block = _workflow_input_block(workflow, "max_iterations")

    assert "chunk_profile:" in workflow
    assert 'default: "standard"' in chunk_profile_block
    assert "network_mode:" in workflow
    assert "vpn_parallelism:" in workflow
    assert 'default: "2"' in vpn_parallelism_block
    assert "direct_parallelism:" in workflow
    assert 'default: "2"' in direct_parallelism_block
    assert '- "128"' in direct_parallelism_block
    assert '- "256"' in direct_parallelism_block
    assert "direct_request_profile:" in workflow
    assert "turbo" in workflow
    assert "retry_pipeline_failures:" in workflow
    assert "direct_timeout_cap_minutes:" in workflow
    assert "NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS" in workflow
    assert "NBADB_EXTRACT_MAX_RETRIES=0" in workflow
    assert "NBADB_CIRCUIT_BREAKER_MAX_WAIT=15" in workflow
    assert "NBADB_ADAPTIVE_CHUNK_MIN_SIZE=1" in workflow
    assert "NBADB_ADAPTIVE_CHUNK_MAX_SIZE=100" in workflow
    assert (
        'NBADB_FAMILY_CHUNK_MULTIPLIERS={"default":1.0,"box_score":1.0,'
        '"play_by_play":0.5,"player_history":0.001,"team_history":0.5}'
    ) in workflow
    assert "effective-network-mode:" in workflow
    assert "Resolve effective network mode" in workflow
    assert (
        "Preflight VPN validation returned ${status}; refusing requested VPN extraction" in workflow
    )
    assert "proceeding with VPN extraction for live lane verification" not in workflow
    assert "direct-no-vpn" in workflow
    assert "lane_control:" in workflow
    assert "checkpoint:" in workflow
    assert "dispatch_next:" in workflow
    assert "terminal_replay:" in workflow
    assert "chain:" not in workflow
    assert 'default: "auto"' in max_iterations_block
    matrix_batch_size_block = _workflow_input_block(workflow, "matrix_batch_size")
    assert 'default: "256"' in matrix_batch_size_block
    assert '- "64"' in matrix_batch_size_block
    assert '- "256"' in matrix_batch_size_block
    assert "queue_depth:" not in workflow

    assert "discovery_seed:" in workflow
    assert "full-extraction-discovery-artifacts-${{ env.ACTIVE_CHAIN_ID }}" in workflow
    assert "seed_discovery_artifacts.py" in workflow
    assert "needs: [plan, preflight, discovery_seed]" in workflow
    assert "needs.discovery_seed.result == 'success'" in workflow
    assert "needs: [plan, preflight, discovery_seed, extract, lane_control]" in workflow
    assert (
        "needs: [plan, preflight, extract, terminal_replay, lane_control, checkpoint]" in workflow
    )
    assert "needs: [plan, preflight, lane_control, checkpoint]" in workflow
    assert "needs.checkpoint.result == 'success'" in workflow
    assert "needs.lane_control.outputs.active-lane-count != '0'" in workflow
    assert "needs.lane_control.outputs.active-lane-count == '0'" in workflow
    assert "needs.checkpoint.outputs.terminal-ready == 'true'" in workflow
    assert "needs.checkpoint.outputs.active-lane-count == '0'" in workflow

    assert 'args+=(--chunk-profile "$CHUNK_PROFILE")' in workflow
    assert "--latest-checkpoint-run-id" in workflow
    assert "--latest-checkpoint-artifact-name" in workflow
    assert "full_extraction_control checkpoint" in workflow
    assert '--previous-checkpoint-report-path "$previous_report"' in workflow
    assert "--checkpoint-dir checkpoint-artifact" in workflow
    assert "--checkpoint-report-path checkpoint-artifact/checkpoint-report.json" in workflow
    assert "Prepare checkpoint-first merge" in workflow
    assert "Download chained lane artifacts" not in workflow
    assert "needs.preflight.outputs.effective-network-mode == 'direct'" in workflow
    assert '--chunk-profile "$CHUNK_PROFILE"' in workflow
    assert "RETRY_PIPELINE_FAILURES" in workflow
    assert workflow.count("resume_args+=(--allow-pipeline-failures)") == 2
    assert (
        "needs.plan.result == 'success' && needs.preflight.result == 'success' "
        "&& needs.discovery_seed.result == 'success' && "
        "(needs.vpn_capacity.result == 'success' || "
        "needs.vpn_capacity.result == 'skipped') && "
        "needs.plan.outputs.matrix-lane-count != '0'"
    ) in workflow
    assert "Upload endpoint coverage diagnostics" in workflow
    assert (
        "if: ${{ always() && inputs.lane_manifest_json == '' && "
        "inputs.lane_manifest_run_id == '' && inputs.resume_source_run_id == '' }}"
    ) in workflow
    assert "full-extraction-endpoint-coverage-${{ env.ACTIVE_CHAIN_ID }}" in workflow
    assert 'importlib.metadata.version("nba-api")' in workflow
    assert '--branch "$NBA_API_REF"' in workflow
    assert "Fetching nba_api docs/tools at ${NBA_API_REF}" in workflow
    lane_control_block = workflow.split("  lane_control:", 1)[1].split(
        "  # ─────────────────────────────────────────────────────────────",
        1,
    )[0]
    assert "RETRY_PIPELINE_FAILURES: ${{ inputs.retry_pipeline_failures }}" in lane_control_block
    assert "resume_args=(" in lane_control_block
    assert 'full_extraction_control "${resume_args[@]}"' in lane_control_block
    assert "--allow-missing-attempted-metadata" in lane_control_block
    direct_parallel_expr = (
        "max-parallel: ${{ fromJSON("
        "needs.preflight.outputs.effective-network-mode == 'direct' "
        "&& inputs.direct_parallelism || (needs.preflight.outputs.vpn-auth-source "
        "== 'token' && '1' || inputs.vpn_parallelism)) }}"
    )
    assert direct_parallel_expr in workflow
    assert '-f network_mode="$NETWORK_MODE"' in workflow
    assert '-f direct_parallelism="$DIRECT_PARALLELISM"' in workflow
    assert '-f direct_request_profile="$DIRECT_REQUEST_PROFILE"' in workflow
    assert '-f direct_timeout_cap_minutes="$DIRECT_TIMEOUT_CAP_MINUTES"' in workflow
    assert '-f retry_pipeline_failures="$RETRY_PIPELINE_FAILURES"' in workflow
    assert '-f matrix_batch_size="$MATRIX_BATCH_SIZE"' in workflow
    assert '-f chunk_profile="$CHUNK_PROFILE"' in workflow
    assert "--verify-remote" in workflow


def test_scheduled_update_workflows_publish_only_after_green_extract_and_scan() -> None:
    workflows_dir = pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows"
    daily = (workflows_dir / "daily-update.yml").read_text(encoding="utf-8")
    monthly = (workflows_dir / "monthly-update.yml").read_text(encoding="utf-8")

    assert "steps.daily.outcome == 'success' && steps.scan.outcome == 'success'" in daily
    assert "steps.daily.outcome != 'skipped'" not in daily
    assert "Assert extraction and scan passed" in daily
    assert "Daily extraction did not pass" in daily
    assert "Daily scan did not pass" in daily
    assert "--verify-remote" in daily
    assert "group: nbadb-kaggle-publish" in daily
    assert "steps.monthly.outcome == 'success' && steps.scan.outcome == 'success'" in monthly
    assert "steps.monthly.outcome != 'skipped'" not in monthly
    assert "Assert extraction and scan passed" in monthly
    assert "Monthly extraction did not pass" in monthly
    assert "Monthly scan did not pass" in monthly
    assert "--verify-remote" in monthly
    assert "group: nbadb-kaggle-publish" in monthly


def test_ci_endpoint_contract_uses_installed_nba_api_version() -> None:
    workflow = (
        pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")

    assert 'importlib.metadata.version("nba-api")' in workflow
    assert '--branch "$NBA_API_REF"' in workflow
    assert "Fetching nba_api docs/tools at ${NBA_API_REF}" in workflow


def test_build_default_manifest_chunks_reference_patterns_by_endpoint_load() -> None:
    rows = [
        _support_row("static_players", ["static"], None),
        *[_support_row(f"team_endpoint_{index:02d}", ["team"], None) for index in range(1, 14)],
        *[_support_row(f"player_endpoint_{index:02d}", ["player"], None) for index in range(1, 12)],
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]
    reference_by_id = {lane.lane_id: lane for lane in reference_lanes}

    assert set(reference_by_id) == {
        "reference-static",
        "reference-team-01",
        "reference-team-02",
        "reference-player-01",
        "reference-player-02",
        "reference-player-03",
    }
    assert reference_by_id["reference-static"].endpoints == ("static_players",)
    assert len(reference_by_id["reference-team-01"].endpoints) == 12
    assert len(reference_by_id["reference-team-02"].endpoints) == 1
    assert [
        len(reference_by_id[f"reference-player-{index:02d}"].endpoints) for index in range(1, 4)
    ] == [4, 4, 3]
    assert reference_by_id["reference-static"].timeout_seconds == 1800
    assert all(
        reference_by_id[f"reference-team-{index:02d}"].timeout_seconds == 3000
        for index in range(1, 3)
    )
    assert all(
        reference_by_id[f"reference-player-{index:02d}"].timeout_seconds == 3600
        for index in range(1, 4)
    )


def test_build_default_manifest_isolates_slow_reference_team_endpoints() -> None:
    rows = [
        *[_support_row(f"team_endpoint_{index:02d}", ["team"], None) for index in range(1, 8)],
        _support_row("team_historical_leaders", ["team"], None),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]

    assert [lane.lane_id for lane in reference_lanes] == ["reference-team"]
    expected_primary_team_endpoints = tuple(f"team_endpoint_{index:02d}" for index in range(1, 8))
    assert reference_lanes[0].endpoints == expected_primary_team_endpoints
    assert reference_lanes[0].timeout_seconds == 3000
    assert len(reference_lanes) == 1


def test_build_default_manifest_isolates_slow_reference_player_endpoints() -> None:
    rows = [
        _support_row("common_player_info", ["player"], None),
        _support_row("player_profile_v2", ["player"], None),
        _support_row("player_awards", ["player"], None),
        _support_row("player_career_stats", ["player"], None),
        _support_row("player_compare", ["player"], None),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]

    assert [lane.lane_id for lane in reference_lanes] == [
        "reference-player-01",
        "reference-player-02",
        "reference-player-03",
        "reference-player-04",
        "reference-player-05",
    ]
    assert {(lane.endpoints, lane.timeout_seconds) for lane in reference_lanes} == {
        (("common_player_info",), 9000),
        (("player_profile_v2",), 10800),
        (("player_awards",), 9000),
        (("player_career_stats",), 9000),
        (("player_compare",), 9000),
    }
    assert all(lane.use_vpn is True for lane in reference_lanes)


def test_build_default_manifest_isolates_high_volume_historical_endpoints() -> None:
    rows = [
        _support_row("scoreboard_v2", ["date"], None),
        _support_row("scoreboard_v3", ["date"], None),
        _support_row("video_status", ["date"], None),
        _support_row("box_score_summary", ["game"], 1946),
        _support_row("play_by_play", ["game"], 1996),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)

    date_lanes = [
        lane for lane in lanes if lane.lane_kind == "historical" and lane.patterns == ("date",)
    ]
    assert date_lanes[0].lane_id == "historical-date-scoreboard-v2-no-season-type-1946-1949"
    assert date_lanes[0].endpoints == ("scoreboard_v2",)
    assert {lane.endpoints for lane in date_lanes} == {
        ("scoreboard_v2",),
        ("scoreboard_v3",),
        ("video_status",),
    }
    scoreboard_v2_lanes = [lane for lane in date_lanes if lane.endpoints == ("scoreboard_v2",)]
    assert scoreboard_v2_lanes
    assert all(
        not any(lane.season_start <= blocked <= lane.season_end for blocked in (1950, 1954, 1956))
        for lane in scoreboard_v2_lanes
    )
    assert all((lane.season_end - lane.season_start + 1) <= 4 for lane in date_lanes)

    game_lanes = [
        lane for lane in lanes if lane.lane_kind == "historical" and lane.patterns == ("game",)
    ]
    assert game_lanes[0].lane_id == "historical-game-box-score-summary-no-season-type-1946-1949"
    assert game_lanes[0].endpoints == ("box_score_summary",)
    assert any(
        lane.lane_id == "historical-game-play-by-play-no-season-type-1996-1999"
        for lane in game_lanes
    )
    assert {lane.endpoints for lane in game_lanes} == {("box_score_summary",), ("play_by_play",)}
    assert all((lane.season_end - lane.season_start + 1) <= 4 for lane in game_lanes)
    assert all(len(lane.endpoints) == 1 for lane in date_lanes + game_lanes)


def test_build_default_manifest_routes_player_dashboard_family_to_historical_lanes() -> None:
    rows = [
        _support_row(
            "player_dashboard_clutch",
            ["player_season"],
            None,
            season_type_contract_status="supported",
            declared_supported_season_types=["Regular Season", "Playoffs"],
        ),
        _support_row(
            "player_dash_game_splits",
            ["player_season"],
            None,
            season_type_contract_status="supported",
            declared_supported_season_types=["Regular Season", "Playoffs"],
        ),
        _support_row(
            "player_game_logs_v2",
            ["player_season"],
            None,
            season_type_contract_status="supported",
        ),
        _support_row("player_streak_finder", ["player_season"], None),
        _support_row(
            "shot_chart_detail",
            ["player_season"],
            None,
            season_type_contract_status="supported",
        ),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)

    assert {lane.lane_kind for lane in lanes} == {"historical"}
    assert {lane.patterns for lane in lanes} == {("player_season",)}
    assert all((lane.season_end - lane.season_start + 1) <= 16 for lane in lanes)
    assert all(len(lane.endpoints) == 1 for lane in lanes)
    historical_endpoints = {endpoint for lane in lanes for endpoint in lane.endpoints}
    assert historical_endpoints == {
        "player_dashboard_clutch",
        "player_dash_game_splits",
        "player_game_logs_v2",
        "player_streak_finder",
        "shot_chart_detail",
    }
    first_season_by_endpoint = {
        endpoint: min(lane.season_start for lane in lanes if lane.endpoints == (endpoint,))
        for endpoint in historical_endpoints
    }
    assert first_season_by_endpoint == {
        "player_dashboard_clutch": 1996,
        "player_dash_game_splits": 1996,
        "player_game_logs_v2": 1946,
        "player_streak_finder": 1996,
        "shot_chart_detail": 1996,
    }


@pytest.mark.parametrize(
    ("endpoint_name", "expected_first_supported_season"),
    [
        *((endpoint_name, 1996) for endpoint_name in PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_1996),
        *(
            (endpoint_name, 2013)
            for endpoint_name in PLAYER_TRACKING_PLAYER_SEASON_ENDPOINTS_SUPPORTED_FROM_2013
        ),
    ],
)
def test_build_default_manifest_excludes_known_player_season_contract_gaps_from_initial_plan(
    endpoint_name: str,
    expected_first_supported_season: int,
) -> None:
    rows = [
        _support_row(
            endpoint_name,
            ["player_season"],
            1946,
            season_type_contract_status="supported",
        )
    ]

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        selected_endpoints=[endpoint_name],
    )

    assert lanes
    assert all(endpoint_name in lane.endpoints for lane in lanes)
    assert min(lane.season_start for lane in lanes if lane.season_start is not None) == (
        expected_first_supported_season
    )
    assert all(
        lane.season_start is not None and lane.season_start >= expected_first_supported_season
        for lane in lanes
    )


@pytest.mark.parametrize("endpoint_name", PLAYER_SEASON_FULL_EXTRACTION_UNSUPPORTED_ENDPOINTS)
def test_build_default_manifest_rejects_historical_player_season_contract_gap_endpoint(
    endpoint_name: str,
) -> None:
    rows = [
        _support_row(
            endpoint_name,
            ["player_season"],
            1946,
            season_type_contract_status="supported",
        )
    ]

    with pytest.raises(ValueError, match="produced no runnable lanes"):
        build_default_manifest(
            support_matrix_rows=rows,
            selected_endpoints=[endpoint_name],
        )


def test_build_default_manifest_skips_full_extraction_excluded_endpoints() -> None:
    rows = [
        _support_row("common_team_years", ["static"], None),
        _support_row("team_historical_leaders", ["team"], None),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]

    assert [lane.lane_id for lane in reference_lanes] == ["reference-static"]
    assert reference_lanes[0].endpoints == ("common_team_years",)


def test_build_default_manifest_routes_player_tracking_to_historical_player_season() -> None:
    rows = [
        _support_row("player_dash_game_splits", ["player"], None),
        _support_row(
            "player_dash_pt_pass",
            ["player_season"],
            None,
            season_type_contract_status="supported",
        ),
        _support_row(
            "player_dash_pt_reb",
            ["player_season"],
            None,
            season_type_contract_status="supported",
        ),
        _support_row(
            "player_dash_pt_shot_defend",
            ["player_season"],
            None,
            season_type_contract_status="supported",
        ),
        _support_row(
            "player_dash_pt_shots",
            ["player_season"],
            None,
            season_type_contract_status="supported",
        ),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]
    historical_lanes = [
        lane
        for lane in lanes
        if lane.lane_kind == "historical" and lane.patterns == ("player_season",)
    ]

    assert [lane.lane_id for lane in reference_lanes] == ["reference-player"]
    assert reference_lanes[0].endpoints == ("player_dash_game_splits",)
    assert min(lane.season_start for lane in historical_lanes) == 2013
    assert max(lane.season_end for lane in historical_lanes if lane.season_end is not None) >= 2025
    assert all((lane.season_end - lane.season_start + 1) <= 6 for lane in historical_lanes)
    assert all(len(lane.endpoints) == 1 for lane in historical_lanes)
    assert {endpoint for lane in historical_lanes for endpoint in lane.endpoints} == {
        "player_dash_pt_pass",
        "player_dash_pt_reb",
        "player_dash_pt_shot_defend",
        "player_dash_pt_shots",
    }
    assert {
        endpoint: min(
            lane.season_start for lane in historical_lanes if lane.endpoints == (endpoint,)
        )
        for endpoint in {
            "player_dash_pt_pass",
            "player_dash_pt_reb",
            "player_dash_pt_shot_defend",
            "player_dash_pt_shots",
        }
    } == {
        "player_dash_pt_pass": 2013,
        "player_dash_pt_reb": 2013,
        "player_dash_pt_shot_defend": 2013,
        "player_dash_pt_shots": 2013,
    }
    assert historical_lanes[0].season_types == (
        "Regular Season",
        "Playoffs",
        "Pre Season",
        "All Star",
    )


def test_build_default_manifest_isolates_team_season_endpoints() -> None:
    rows = [
        _support_row(
            "team_dashboard_by_general_splits",
            ["team_season"],
            1946,
            season_type_contract_status="supported",
        ),
        _support_row(
            "team_dashboard_by_shooting_splits",
            ["team_season"],
            1946,
            season_type_contract_status="supported",
        ),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    historical_lanes = [
        lane
        for lane in lanes
        if lane.lane_kind == "historical" and lane.patterns == ("team_season",)
    ]

    assert historical_lanes
    assert all(len(lane.endpoints) == 1 for lane in historical_lanes)
    assert {endpoint for lane in historical_lanes for endpoint in lane.endpoints} == {
        "team_dashboard_by_general_splits",
        "team_dashboard_by_shooting_splits",
    }
    assert min(lane.season_start for lane in historical_lanes) == 1946
    assert all((lane.season_end - lane.season_start + 1) <= 8 for lane in historical_lanes)


def test_build_default_manifest_isolates_cross_product_endpoints() -> None:
    rows = [
        _support_row(
            "video_details",
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
        ),
        _support_row(
            "player_index",
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
        ),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    cross_product_lanes = [lane for lane in lanes if lane.lane_kind == "cross_product"]

    assert cross_product_lanes
    assert all(len(lane.endpoints) == 1 for lane in cross_product_lanes)
    assert {endpoint for lane in cross_product_lanes for endpoint in lane.endpoints} == {
        "player_index",
        "video_details",
    }
    assert {
        lane.lane_id.split("-regular-season", 1)[0]
        for lane in cross_product_lanes
        if lane.endpoints == ("player_index",)
    } == {"cross-product-player-index"}
    video_lanes = [lane for lane in cross_product_lanes if lane.endpoints == ("video_details",)]
    assert video_lanes
    assert min(lane.season_start for lane in video_lanes if lane.season_start is not None) == 2004
    assert all(lane.season_start is not None and lane.season_start >= 2004 for lane in video_lanes)
    assert all("-ctx-" in lane.lane_id for lane in video_lanes)
    assert all(1 <= len(lane.context_measures) <= 3 for lane in video_lanes)
    assert {
        context_measure for lane in video_lanes for context_measure in lane.context_measures
    } == set(VIDEO_CONTEXT_MEASURES)


@pytest.mark.parametrize("endpoint_name", ["video_details", "video_details_asset"])
def test_build_default_manifest_excludes_pre_2004_video_without_losing_measures(
    endpoint_name: str,
) -> None:
    rows = [
        _support_row(
            endpoint_name,
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
        )
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    video_lanes = [lane for lane in lanes if lane.endpoints == (endpoint_name,)]

    assert video_lanes
    assert all(
        lane.season_start is not None and lane.season_end is not None and lane.season_start >= 2004
        for lane in video_lanes
    )
    assert min(lane.season_start for lane in video_lanes if lane.season_start is not None) == 2004
    assert {
        context_measure for lane in video_lanes for context_measure in lane.context_measures
    } == set(VIDEO_CONTEXT_MEASURES)
    assert all(1 <= len(lane.context_measures) <= 3 for lane in video_lanes)

    blocked_rules = contract_blocking_rules_for_lane(
        endpoints=(endpoint_name,),
        patterns=("player_team_season",),
        season_start=1946,
        season_end=2003,
    )
    assert len(blocked_rules) == 1
    assert blocked_rules[0].season_end == 2003
    assert not contract_blocking_rules_for_lane(
        endpoints=(endpoint_name,),
        patterns=("player_team_season",),
        season_start=2004,
        season_end=2004,
    )


def test_build_default_manifest_partitions_play_in_at_2019_boundary() -> None:
    rows = [
        _support_row(
            "video_details",
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
            declared_supported_season_types=[season_type.value for season_type in SeasonType],
        )
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    video_lanes = [lane for lane in lanes if lane.endpoints == ("video_details",)]

    assert video_lanes
    assert all(
        SeasonType.PLAY_IN.value not in lane.season_types
        for lane in video_lanes
        if lane.season_end is not None and lane.season_end < 2019
    )
    assert all(
        SeasonType.PLAY_IN.value in lane.season_types
        for lane in video_lanes
        if lane.season_start is not None and lane.season_start >= 2019
    )
    assert all(
        not (
            unit["season_type"] == SeasonType.PLAY_IN.value
            and isinstance(unit["season"], int)
            and unit["season"] < 2019
        )
        for lane in video_lanes
        for unit in _coverage_units_for_lane(lane)
    )


def test_build_default_manifest_isolates_timeout_prone_reference_team_endpoints() -> None:
    rows = [
        _support_row("common_team_years", ["static"], None),
        _support_row("team_details", ["team"], None),
        _support_row("team_info_common", ["team"], None),
        _support_row("franchise_leaders", ["team"], None),
        _support_row("franchise_players", ["team"], None),
        _support_row("team_year_by_year", ["team"], None),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]
    reference_by_id = {lane.lane_id: lane for lane in reference_lanes}

    assert set(reference_by_id) == {
        "reference-static",
        "reference-team-01",
        "reference-team-02",
        "reference-team-03",
        "reference-team-04",
    }
    assert reference_by_id["reference-static"].endpoints == ("common_team_years",)
    assert reference_by_id["reference-team-01"].endpoints == (
        "team_details",
        "team_info_common",
    )
    assert reference_by_id["reference-team-02"].endpoints == ("franchise_leaders",)
    assert reference_by_id["reference-team-03"].endpoints == ("franchise_players",)
    assert reference_by_id["reference-team-04"].endpoints == ("team_year_by_year",)


def test_build_default_manifest_uses_cost_aware_reference_grouping() -> None:
    rows = [
        _support_row("team_endpoint_01", ["team"], None),
        _support_row("team_endpoint_02", ["team"], None),
        _support_row("team_endpoint_03", ["team"], None),
    ]
    planning_snapshot = WorkloadPlanningSnapshot(
        endpoint_profiles={
            endpoint_name: EndpointWorkloadProfile(
                endpoint_name=endpoint_name,
                endpoint_family="team_history",
                throughput_tier="expensive_flaky",
                avg_duration_seconds=40.0,
                p95_duration_seconds=55.0,
                retry_rate=0.2,
                error_rate=0.1,
                avg_rows_per_request=100.0,
                lane_cost=7.0,
                reference_batch_cost=7.0,
                preferred_max_span=4,
            )
            for endpoint_name in ("team_endpoint_01", "team_endpoint_02", "team_endpoint_03")
        },
        cross_product_pair_counts={},
    )

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        planning_snapshot=planning_snapshot,
    )

    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]
    assert [lane.lane_id for lane in reference_lanes] == [
        "reference-team-01",
        "reference-team-02",
        "reference-team-03",
    ]


def test_build_default_manifest_rejects_selected_discovery_owned_endpoint() -> None:
    rows = [
        _support_row(
            "league_game_log",
            ["season"],
            None,
            season_type_contract_status="supported",
        ),
        _support_row(
            "league_dash_pt_defend",
            ["season"],
            2013,
            season_type_contract_status="supported",
        ),
    ]

    with pytest.raises(ValueError, match="discovery-seed-owned"):
        build_default_manifest(
            support_matrix_rows=rows,
            selected_endpoints=["league_game_log"],
        )


def test_build_default_manifest_rejects_mixed_discovery_owned_selection() -> None:
    rows = [
        _support_row("league_game_log", ["season"], 1946),
        _support_row("player_game_logs_v2", ["player_season"], 1946),
    ]

    with pytest.raises(ValueError, match="discovery-seed-owned.*league_game_log"):
        build_default_manifest(
            support_matrix_rows=rows,
            selected_endpoints=["league_game_log", "player_game_logs_v2"],
        )


def test_build_default_manifest_uses_density_to_shrink_cross_product_bands() -> None:
    rows = [
        _support_row(
            "video_details",
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
        )
    ]
    planning_snapshot = WorkloadPlanningSnapshot(
        endpoint_profiles={
            "video_details": EndpointWorkloadProfile(
                endpoint_name="video_details",
                endpoint_family="default",
                throughput_tier="discovery_bound_cross_product",
                avg_duration_seconds=0.0,
                p95_duration_seconds=0.0,
                retry_rate=0.0,
                error_rate=0.0,
                avg_rows_per_request=0.0,
                lane_cost=6.0,
                reference_batch_cost=6.0,
                preferred_max_span=3,
            )
        },
        cross_product_pair_counts={
            ("2004-05", "Regular Season"): 4_000,
            ("2005-06", "Regular Season"): 4_000,
        },
    )

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        planning_snapshot=planning_snapshot,
    )

    cross_product_spans = sorted(
        {
            (lane.season_start, lane.season_end)
            for lane in lanes
            if lane.lane_kind == "cross_product"
        }
    )
    assert cross_product_spans[0] == (2004, 2004)
    assert cross_product_spans[1][0] == 2005
    assert cross_product_spans[1][1] < 2012


def test_build_default_manifest_rejects_zero_match_filters() -> None:
    rows = [
        _support_row("league_game_log", ["season"], None, season_type_contract_status="supported")
    ]

    with pytest.raises(ValueError, match="matched no support-matrix rows"):
        build_default_manifest(
            support_matrix_rows=rows,
            selected_endpoints=["does_not_exist"],
        )


def test_build_default_manifest_skips_excluded_cross_product_endpoints() -> None:
    rows = [
        _support_row(
            "video_details",
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
        ),
        _support_row(
            "team_vs_player",
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
        ),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)

    assert {lane.lane_kind for lane in lanes} == {"cross_product"}
    assert all("team_vs_player" not in lane.endpoints for lane in lanes)


def test_build_default_manifest_rejects_excluded_cross_product_only_selection() -> None:
    rows = [
        _support_row(
            "team_vs_player",
            ["player_team_season"],
            1946,
            season_type_contract_status="supported",
        )
    ]

    with pytest.raises(ValueError, match="produced no runnable lanes"):
        build_default_manifest(support_matrix_rows=rows)


def test_build_default_manifest_rejects_full_extraction_excluded_only_selection() -> None:
    rows = [_support_row("team_historical_leaders", ["team"], None)]

    with pytest.raises(ValueError, match="produced no runnable lanes"):
        build_default_manifest(support_matrix_rows=rows)


def test_build_default_manifest_projects_canonical_families_to_concrete_routes() -> None:
    rows = [
        _support_row(
            "player_game_logs_v2",
            ["season", "player_season"],
            1946,
            season_type_contract_status="supported",
        ),
        _support_row(
            "player_streak_finder",
            ["season", "player_season"],
            1946,
        ),
    ]
    rows[0]["support_windows"] = [
        {
            "staging_key": "stg_player_game_logs",
            "param_pattern": "season",
            "min_season": None,
            "deprecated_after": None,
            "season_type_capability": "supported",
            "supported_season_types": [
                "Regular Season",
                "Playoffs",
                "Pre Season",
                "All Star",
            ],
        },
        {
            "staging_key": "stg_player_game_logs_v2",
            "param_pattern": "player_season",
            "min_season": None,
            "deprecated_after": None,
            "season_type_capability": "supported",
            "supported_season_types": [
                "Regular Season",
                "Playoffs",
                "Pre Season",
                "All Star",
            ],
        },
    ]
    rows[1]["support_windows"] = [
        {
            "staging_key": "stg_player_game_streak_finder",
            "param_pattern": "season",
            "min_season": None,
            "deprecated_after": None,
            "season_type_capability": "not_applicable",
            "supported_season_types": [],
        },
        {
            "staging_key": "stg_player_streak_finder",
            "param_pattern": "player_season",
            "min_season": None,
            "deprecated_after": None,
            "season_type_capability": "not_applicable",
            "supported_season_types": [],
        },
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    validate_manifest(lanes)

    routes = {
        (endpoint_name, pattern)
        for lane in lanes
        for endpoint_name in lane.endpoints
        for pattern in lane.patterns
    }
    assert {
        ("player_game_logs", "season"),
        ("player_game_logs_v2", "player_season"),
        ("player_game_streak_finder", "season"),
        ("player_streak_finder", "player_season"),
    } <= routes


def test_build_default_manifest_allows_scoreboard_v2_with_documented_gaps() -> None:
    rows = [_support_row("scoreboard_v2", ["date"], 1946)]

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        selected_endpoints=["scoreboard_v2"],
    )

    assert lanes
    assert {lane.endpoints for lane in lanes} == {("scoreboard_v2",)}
    assert {
        "historical-date-scoreboard-v2-no-season-type-1946-1949",
        "historical-date-scoreboard-v2-no-season-type-1951-1953",
        "historical-date-scoreboard-v2-no-season-type-1955-1955",
    }.issubset({lane.lane_id for lane in lanes})
    assert all(
        not any(lane.season_start <= blocked <= lane.season_end for blocked in (1950, 1954, 1956))
        for lane in lanes
    )


def test_build_default_manifest_skips_support_rule_contract_blocked_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nbadb.orchestrate.extraction_contract as extraction_contract

    monkeypatch.setattr(
        extraction_contract,
        "FULL_EXTRACTION_SUPPORT_RULES",
        (
            EndpointSupportRule(
                endpoint_name="documented_zero_row",
                pattern="game",
                classification="contract_blocked",
                reason="Upstream returns no rows for this historical range.",
                evidence="docs/endpoint-analysis/documented_zero_row.md",
                revalidation_command="uv run nbadb endpoint-probe documented_zero_row",
                season_start=1946,
                season_end=2025,
            ),
        ),
    )
    rows = [
        _support_row("documented_zero_row", ["game"], 1946),
        _support_row("box_score_summary", ["game"], 1946),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)

    assert all("documented_zero_row" not in lane.endpoints for lane in lanes)
    assert any("box_score_summary" in lane.endpoints for lane in lanes)


@pytest.mark.parametrize(
    ("endpoint_name", "expected_first_supported_season"),
    [
        *((endpoint_name, 1997) for endpoint_name in SEASON_ENDPOINTS_SUPPORTED_FROM_1997),
        ("schedule_int", 2000),
        ("ist_standings", 2021),
        ("playoff_picture", 1970),
    ],
)
def test_build_default_manifest_excludes_known_season_contract_gaps_from_initial_plan(
    endpoint_name: str,
    expected_first_supported_season: int,
) -> None:
    rows = [_support_row(endpoint_name, ["season"], 1946)]

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        selected_endpoints=[endpoint_name],
    )

    assert lanes
    assert all(endpoint_name in lane.endpoints for lane in lanes)
    assert min(lane.season_start for lane in lanes if lane.season_start is not None) == (
        expected_first_supported_season
    )
    assert all(
        lane.season_start is not None and lane.season_start >= expected_first_supported_season
        for lane in lanes
    )
    assert not any(
        lane.season_start is not None
        and lane.season_end is not None
        and lane.season_start <= blocked_year <= lane.season_end
        for lane in lanes
        for blocked_year in range(1946, expected_first_supported_season)
    )


@pytest.mark.parametrize("endpoint_name", SEASON_ENDPOINTS_UNSUPPORTED_AFTER_1969)
def test_build_default_manifest_rejects_unscoped_season_contract_gap_endpoint(
    endpoint_name: str,
) -> None:
    rows = [_support_row(endpoint_name, ["season"], 1946)]

    with pytest.raises(ValueError, match="produced no runnable lanes"):
        build_default_manifest(
            support_matrix_rows=rows,
            selected_endpoints=[endpoint_name],
        )


def test_build_default_manifest_isolates_season_endpoint_contract_windows() -> None:
    rows = [
        _support_row("playoff_picture", ["season"], 1946),
        _support_row("draft_history", ["season"], 1946),
        _support_row("schedule_int", ["season"], 1946),
        _support_row("ist_standings", ["season"], 1946),
        _support_row("player_career_by_college", ["season"], 1946),
        _support_row("team_game_streak_finder", ["season"], 1946),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)

    assert all(len(lane.endpoints) == 1 for lane in lanes)
    lanes_by_endpoint: dict[str, list[FullExtractionLane]] = {}
    for lane in lanes:
        lanes_by_endpoint.setdefault(lane.endpoints[0], []).append(lane)

    assert min(lane.season_start for lane in lanes_by_endpoint["playoff_picture"]) == 1970
    assert min(lane.season_start for lane in lanes_by_endpoint["draft_history"]) == 1997
    assert min(lane.season_start for lane in lanes_by_endpoint["schedule_int"]) == 2000
    assert min(lane.season_start for lane in lanes_by_endpoint["ist_standings"]) == 2021
    assert "player_career_by_college" not in lanes_by_endpoint
    assert "team_game_streak_finder" not in lanes_by_endpoint


@pytest.mark.parametrize(
    ("endpoint_name", "expected_first_supported_season"),
    [
        ("home_page_leaders", 1950),
        ("home_page_v2", 1950),
        ("league_dash_player_bio_stats", 1950),
        ("player_game_streak_finder", 1970),
    ],
)
def test_concrete_alias_routes_inherit_canonical_support_windows(
    endpoint_name: str,
    expected_first_supported_season: int,
) -> None:
    rows = [_support_row(endpoint_name, ["season"], 1946)]

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        selected_endpoints=[endpoint_name],
    )

    assert min(lane.season_start for lane in lanes if lane.season_start is not None) == (
        expected_first_supported_season
    )


@pytest.mark.parametrize(
    ("endpoint_name", "earliest_supported_season", "expected_first_supported_season"),
    [
        ("box_score_defensive", 2006, 2017),
        ("box_score_matchups", 2006, 2016),
        ("box_score_misc", 1994, 1996),
        ("box_score_player_track", 1994, 1996),
        ("box_score_scoring", 1994, 1996),
        ("box_score_usage", 1946, 1994),
    ],
)
def test_build_default_manifest_excludes_known_box_score_contract_gaps_from_initial_plan(
    endpoint_name: str,
    earliest_supported_season: int,
    expected_first_supported_season: int,
) -> None:
    rows = [_support_row(endpoint_name, ["game"], earliest_supported_season)]

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        selected_endpoints=[endpoint_name],
    )

    assert lanes
    assert min(lane.season_start for lane in lanes if lane.season_start is not None) == (
        expected_first_supported_season
    )
    assert all(
        lane.season_start >= expected_first_supported_season
        for lane in lanes
        if lane.season_start is not None
    )
    assert all(endpoint_name in lane.endpoints for lane in lanes)


def test_build_default_manifest_excludes_1946_win_probability_contract_gap() -> None:
    rows = [_support_row("win_probability", ["game"], 1946)]

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        selected_endpoints=["win_probability"],
    )

    assert lanes
    assert min(lane.season_start for lane in lanes if lane.season_start is not None) == 1947
    assert all(lane.season_start >= 1947 for lane in lanes if lane.season_start is not None)
    assert all("win_probability" in lane.endpoints for lane in lanes)


def test_build_default_manifest_excludes_1949_1950_win_probability_contract_gap() -> None:
    rows = [_support_row("win_probability", ["game"], 1947)]

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        selected_endpoints=["win_probability"],
    )

    covered_seasons = {
        season
        for lane in lanes
        if lane.season_start is not None and lane.season_end is not None
        for season in range(lane.season_start, lane.season_end + 1)
    }
    assert {1947, 1948, 1951}.issubset(covered_seasons)
    assert 1949 not in covered_seasons
    assert 1950 not in covered_seasons
    assert all("win_probability" in lane.endpoints for lane in lanes)


def test_build_resume_manifest_marks_completed_lanes_resume_only(tmp_path: Path) -> None:
    rows = [
        _support_row("franchise_history", ["static"], None),
        _support_row("common_player_info", ["player"], None),
    ]
    lanes = build_default_manifest(support_matrix_rows=rows)
    lanes = [
        replace(
            lane,
            state_artifact_run_id="12345",
            state_artifact_name=(
                "extraction-lane-recovery-chain-reference-static-run-12345-attempt-1"
            ),
            state_artifact_digest="a" * 64,
            last_completed_calls=7,
            last_rows_persisted=11,
        )
        if lane.lane_id == "reference-static"
        else lane
        for lane in lanes
    ]

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(metadata_dir / "reference.json", lane_id="reference-static", status="complete")
    _write_metadata(
        metadata_dir / "player.json",
        lane_id="reference-player",
        status="needs_resume",
    )

    next_lanes, next_chain_state, summary = build_resume_manifest(
        lanes,
        metadata_dir,
        attempted_lane_ids=frozenset({"reference-static", "reference-player"}),
    )

    by_id = {lane.lane_id: lane for lane in next_lanes}
    assert by_id["reference-static"].resume_only is True
    assert by_id["reference-static"].state_artifact_run_id == ""
    assert by_id["reference-static"].last_completed_calls == 0
    assert by_id["reference-static"].last_rows_persisted == 0
    active_lane = by_id["reference-player"]
    assert active_lane.resume_only is False
    assert active_lane.failure_streak == 1
    assert active_lane.last_failure_reason == "needs_resume"
    assert next_chain_state == FullExtractionChainState(scheduler_rotation_cursor=2)
    assert summary == {
        "vpn_quarantined_server_count": 0,
        "active_lane_count": 1,
        "resume_only_lane_count": 1,
        "deferred_lane_count": 0,
        "vpn_auth_circuit_deferred_lane_count": 0,
        "vpn_auth_circuit_check_failed_lane_count": 0,
        "vpn_auth_circuit_rejection_lane_count": 0,
        "blocked_lane_count": 0,
        "split_lane_count": 0,
        "contract_blocked_lane_count": 0,
        "pipeline_failure_retry_count": 0,
        "outcome_counts": {"complete": 1, "needs_resume": 1},
        "failure_reason_counts": {"needs_resume": 1},
        "failure_class_counts": {"timeout_stalled": 1},
        "durable_state_lane_count": 0,
        "scheduler_dispatched_lane_count": 2,
        "scheduler_rotation_cursor": 2,
    }


def test_build_resume_manifest_fails_on_pipeline_failure(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-no-season-type-1996-1999",
        lane_index=0,
        lane_name="Historical game 1996-1999",
        lane_kind="historical",
        season_start=1996,
        season_end=1999,
        patterns=("game",),
        timeout_seconds=7200,
        failure_streak=2,
        last_failure_reason="extract-error",
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id="historical-game-no-season-type-1996-1999",
        status="extract-error",
    )

    with pytest.raises(ValueError, match="Pipeline-failure lane outcomes"):
        build_resume_manifest([lane], metadata_dir)


def test_build_resume_manifest_can_retry_pipeline_failures(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-season-no-season-type-2020-2020",
        lane_index=0,
        lane_name="Historical season 2020",
        lane_kind="historical",
        season_start=2020,
        season_end=2020,
        patterns=("season",),
        endpoints=("draft_history",),
        timeout_seconds=7200,
        failure_streak=2,
        last_failure_reason="extract-error",
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        endpoints=["draft_history"],
        patterns=["season"],
        season_start=2020,
        season_end=2020,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        allow_pipeline_failures=True,
    )

    assert len(next_lanes) == 1
    assert next_lanes[0].resume_only is False
    assert next_lanes[0].failure_streak == 1
    assert next_lanes[0].last_failure_reason == "pipeline_failure"
    assert summary["active_lane_count"] == 1
    assert summary["pipeline_failure_retry_count"] == 1
    assert summary["outcome_counts"] == {"pipeline_failure": 1}
    assert summary["failure_reason_counts"] == {"extract-error": 1}


def test_nondurable_complete_metadata_ignores_stale_application_failure_class(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-season-no-season-type-2020-2020",
        lane_index=0,
        lane_name="Historical season 2020",
        lane_kind="historical",
        season_start=2020,
        season_end=2020,
        patterns=("season",),
        endpoints=("draft_history",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "historical.json").write_text(
        json.dumps(
            {
                "lane_id": lane.lane_id,
                "status": "complete",
                "raw_status": "complete",
                "failure_class": "application",
                "vpn": {},
                "endpoints": list(lane.endpoints),
                "patterns": list(lane.patterns),
                "season_start": str(lane.season_start),
                "season_end": str(lane.season_end),
                "telemetry": {"rows_persisted": 1},
                "state_artifact": {
                    "run_id": "12345",
                    "name": f"extraction-lane-chain-{lane.lane_id}",
                    "sha256": "a" * 64,
                    "attested": True,
                    "uploaded": False,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    next_lanes, _next_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        allow_pipeline_failures=True,
    )

    assert len(next_lanes) == 1
    assert next_lanes[0].resume_only is False
    assert next_lanes[0].last_failure_class == "runner_infrastructure"
    assert next_lanes[0].class_failure_streak == 1
    assert summary["active_lane_count"] == 1
    assert summary["failure_class_counts"] == {"runner_infrastructure": 1}


def test_build_resume_manifest_pipeline_failure_retry_obeys_failure_cap(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-season-no-season-type-2020-2020",
        lane_index=0,
        lane_name="Historical season 2020",
        lane_kind="historical",
        season_start=2020,
        season_end=2020,
        patterns=("season",),
        endpoints=("draft_history",),
        timeout_seconds=7200,
        failure_streak=2,
        last_failure_reason="pipeline_failure",
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    with pytest.raises(ValueError, match="pipeline_failure x3"):
        build_resume_manifest(
            [lane],
            metadata_dir,
            allow_pipeline_failures=True,
        )


@pytest.mark.parametrize(
    "vpn_failure_status",
    ["cancelled", "vpn_auth_failure", "vpn_connect_timeout", "vpn_network_error"],
)
def test_build_resume_manifest_retries_vpn_pipeline_failure(
    tmp_path: Path,
    vpn_failure_status: str,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-date-video-status-no-season-type-1970-1973-split-1972-1972",
        lane_index=0,
        lane_name="Historical date 1970-1973 (video_status) 1972-1972",
        lane_kind="historical",
        season_start=1972,
        season_end=1972,
        patterns=("date",),
        endpoints=("video_status",),
        timeout_seconds=5400,
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    resume_kwargs: dict[str, object] = {}
    if vpn_failure_status == "vpn_auth_failure":
        payload = _auth_coordination_metadata(
            lane,
            raw_status=vpn_failure_status,
            failure_class="vpn_egress",
        )
        (metadata_dir / "historical.json").write_text(
            json.dumps(payload) + "\n",
            encoding="utf-8",
        )
        resume_kwargs = {
            "attempted_lane_ids": frozenset({lane.lane_id}),
            "expected_chain_id": TEST_CHAIN_ID,
            "expected_source_sha": TEST_SOURCE_SHA,
        }
    else:
        _write_metadata(
            metadata_dir / "historical.json",
            lane_id=lane.lane_id,
            status="pipeline_failure",
            raw_status=vpn_failure_status,
            endpoints=["video_status"],
            patterns=["date"],
            season_start=1972,
            season_end=1972,
        )

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane], metadata_dir, **resume_kwargs
    )

    assert len(next_lanes) == 1
    assert next_lanes[0].resume_only is False
    assert next_lanes[0].last_failure_reason == "needs_resume"
    assert summary["active_lane_count"] == 1
    assert summary["outcome_counts"] == {"needs_resume": 1}
    assert summary["failure_reason_counts"] == {vpn_failure_status: 1}


def test_build_resume_manifest_treats_partial_extract_error_as_resumable(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="reference-player-02",
        lane_index=0,
        lane_name="Reference Player 2/5",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("player",),
        endpoints=("player_awards",),
        timeout_seconds=9000,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "player.json",
        lane_id=lane.lane_id,
        status="extract-error",
        rows_persisted=8242,
        failed_calls=3,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes[0].resume_only is False
    assert next_lanes[0].last_failure_reason == "needs_resume"
    assert summary["outcome_counts"] == {"needs_resume": 1}


def test_build_resume_manifest_splits_zero_row_timeout_lanes(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v3-no-season-type-1962-1965",
        lane_index=0,
        lane_name="Historical date 1962-1965",
        lane_kind="historical",
        season_start=1962,
        season_end=1965,
        patterns=("date",),
        endpoints=("scoreboard_v3",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "date.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert [child.season_start for child in next_lanes] == [1962, 1963, 1964, 1965]
    assert summary["split_lane_count"] == 4
    assert summary["outcome_counts"] == {"needs_resume": 1}


def test_build_resume_manifest_splits_single_year_timeout_by_season_type(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id=(
            "historical-player_season-player-game-logs-v2-regular-season-playoffs-"
            "pre-season-all-star-1946-1946"
        ),
        lane_index=0,
        lane_name="Historical player_season 1946-1946 (player_game_logs_v2)",
        lane_kind="historical",
        season_start=1946,
        season_end=1946,
        patterns=("player_season",),
        season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        endpoints=("player_game_logs_v2",),
        timeout_seconds=4800,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "player_game_logs_v2.json",
        lane_id=lane.lane_id,
        status="needs_resume",
        raw_status="extract-timeout",
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
        season_start=1946,
        season_end=1946,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    validate_manifest(next_lanes)
    assert [(child.season_start, child.season_end) for child in next_lanes] == [
        (1946, 1946),
        (1946, 1946),
        (1946, 1946),
        (1946, 1946),
    ]
    assert {child.season_types for child in next_lanes} == {
        ("Regular Season",),
        ("Playoffs",),
        ("Pre Season",),
        ("All Star",),
    }
    parent_slug = lane.lane_id.replace("_", "-")
    assert {child.lane_id for child in next_lanes} == {
        f"{parent_slug}-split-1946-1946-regular-season",
        f"{parent_slug}-split-1946-1946-playoffs",
        f"{parent_slug}-split-1946-1946-pre-season",
        f"{parent_slug}-split-1946-1946-all-star",
    }
    assert all(child.parent_lane_id == lane.lane_id for child in next_lanes)
    assert all(child.split_generation == 1 for child in next_lanes)
    assert summary["active_lane_count"] == 4
    assert summary["split_lane_count"] == 4
    assert summary["outcome_counts"] == {"needs_resume": 1}
    assert summary["failure_reason_counts"] == {"extract-timeout": 1}
    assert (
        manifest_payload(next_lanes)["coverage_fingerprint"]
        == manifest_payload([lane])["coverage_fingerprint"]
    )


def test_video_timeout_split_ids_are_unique_across_season_type_and_context_axes(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-video-multi-axis-2024",
        lane_index=0,
        lane_name="Cross Product Video Multi Axis 2024",
        lane_kind="cross_product",
        season_start=2024,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=("Regular Season", "Playoffs"),
        context_measures=("PTS", "AST"),
        endpoints=("video_details",),
        timeout_seconds=19_800,
        state_artifact_run_id="stale-run",
        state_artifact_name="stale-state",
        state_artifact_digest="a" * 64,
        last_rows_persisted=1,
    )
    first_metadata = tmp_path / "first-metadata"
    first_metadata.mkdir()
    _write_metadata(
        first_metadata / "lane.json",
        lane_id=lane.lane_id,
        status="needs_resume",
        raw_status="extract-timeout",
        rows_persisted=1,
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
        season_start=2024,
        season_end=2024,
    )

    season_type_children, _state, first_summary = build_resume_manifest([lane], first_metadata)

    assert first_summary["split_lane_count"] == 2
    assert all(
        not child.state_artifact_run_id
        and not child.state_artifact_name
        and not child.state_artifact_digest
        for child in season_type_children
    )
    assert all(child.last_completed_calls == 0 for child in season_type_children)
    assert all(child.last_rows_persisted == 0 for child in season_type_children)

    second_metadata = tmp_path / "second-metadata"
    second_metadata.mkdir()
    for child in season_type_children:
        _write_metadata(
            second_metadata / f"{child.lane_id}.json",
            lane_id=child.lane_id,
            status="needs_resume",
            raw_status="extract-timeout",
            rows_persisted=1,
            endpoints=list(child.endpoints),
            patterns=list(child.patterns),
            season_start=2024,
            season_end=2024,
        )

    progressed_children, next_chain_state, second_summary = build_resume_manifest(
        season_type_children,
        second_metadata,
    )

    assert len(progressed_children) == 2
    assert second_summary["split_lane_count"] == 0
    assert all(child.last_rows_persisted == 1 for child in progressed_children)
    assert all(child.state_artifact_run_id == "12345" for child in progressed_children)

    third_metadata = tmp_path / "third-metadata"
    third_metadata.mkdir()
    for child in progressed_children:
        _write_metadata(
            third_metadata / f"{child.lane_id}.json",
            lane_id=child.lane_id,
            status="needs_resume",
            raw_status="extract-timeout",
            rows_persisted=1,
            endpoints=list(child.endpoints),
            patterns=list(child.patterns),
            season_start=2024,
            season_end=2024,
        )

    context_children, _state, third_summary = build_resume_manifest(
        progressed_children,
        third_metadata,
        chain_state=next_chain_state,
        current_iteration=3,
    )

    validate_manifest(context_children)
    child_ids = {child.lane_id for child in context_children}
    assert len(child_ids) == 4
    assert child_ids == {
        "cross-product-video-multi-axis-2024-split-2024-2024-regular-season-pts",
        "cross-product-video-multi-axis-2024-split-2024-2024-regular-season-ast",
        "cross-product-video-multi-axis-2024-split-2024-2024-playoffs-pts",
        "cross-product-video-multi-axis-2024-split-2024-2024-playoffs-ast",
    }
    assert all(
        not child.state_artifact_run_id
        and not child.state_artifact_name
        and not child.state_artifact_digest
        for child in context_children
    )
    assert all(child.last_completed_calls == 0 for child in context_children)
    assert all(child.last_rows_persisted == 0 for child in context_children)
    assert third_summary["split_lane_count"] == 4


def test_build_resume_manifest_allows_missing_attempted_metadata_for_manual_resume(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=0,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        allow_missing_attempted_metadata=True,
    )

    assert next_lanes[0].lane_id == lane.lane_id
    assert next_lanes[0].resume_only is False
    assert next_lanes[0].last_failure_reason == "missing-metadata"
    assert summary["active_lane_count"] == 1
    assert summary["outcome_counts"] == {"needs_resume": 1}
    assert summary["failure_reason_counts"] == {"missing-metadata": 1}


def test_build_resume_manifest_carries_durable_state_and_progress(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-season-2020",
        lane_index=0,
        lane_name="Historical season 2020",
        lane_kind="historical",
        season_start=2020,
        season_end=2020,
        patterns=("season",),
        endpoints=("draft_history",),
        timeout_seconds=3600,
        zero_progress_streak=2,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "lane.json").write_text(
        json.dumps(
            {
                "metadata_schema_version": 2,
                "lane_id": lane.lane_id,
                "status": "needs_resume",
                "raw_status": "extract-timeout",
                "failure_class": "timeout_progress",
                "vpn": {"status": "connected"},
                "progress": {"completed_calls": 12, "rows_persisted": 55},
                "telemetry": {"rows_persisted": 55},
                "state_artifact": {
                    "run_id": "12345",
                    "name": (
                        "extraction-lane-recovery-chain-historical-season-2020-run-12345-attempt-1"
                    ),
                    "sha256": "a" * 64,
                    "attested": True,
                    "uploaded": True,
                    "artifact_id": TEST_ARTIFACT_ID,
                    "artifact_digest": TEST_ARTIFACT_DIGEST,
                },
            }
        ),
        encoding="utf-8",
    )

    next_lanes, _state, summary = build_resume_manifest([lane], metadata_dir)

    assert len(next_lanes) == 1
    resumed = next_lanes[0]
    assert resumed.attempt_count == 1
    assert resumed.last_failure_class == "timeout_progress"
    assert resumed.last_completed_calls == 12
    assert resumed.last_rows_persisted == 55
    assert resumed.zero_progress_streak == 0
    assert resumed.state_artifact_run_id == "12345"
    assert resumed.state_artifact_name == (
        "extraction-lane-recovery-chain-historical-season-2020-run-12345-attempt-1"
    )
    assert resumed.state_artifact_digest == "a" * 64
    assert summary["durable_state_lane_count"] == 1
    assert summary["outcome_counts"] == {"needs_resume": 1}
    assert summary["failure_reason_counts"] == {"extract-timeout": 1}
    validate_manifest(next_lanes)


@pytest.mark.parametrize(
    "state_artifact",
    [
        pytest.param(None, id="missing"),
        pytest.param(["not-an-object"], id="malformed"),
        pytest.param(
            {
                "run_id": "new-run",
                "name": "new-state",
                "sha256": "b" * 64,
            },
            id="attested-flag-missing",
        ),
        pytest.param(
            {
                "run_id": "new-run",
                "name": "new-state",
                "sha256": "b" * 64,
                "attested": False,
            },
            id="explicitly-unattested",
        ),
        pytest.param(
            {
                "run_id": "new-run",
                "sha256": "b" * 64,
                "attested": True,
            },
            id="incomplete",
        ),
    ],
)
def test_diagnostic_metadata_clears_stale_state_and_preserves_vpn_quarantine(
    tmp_path: Path,
    state_artifact: object,
) -> None:
    lane = FullExtractionLane(
        lane_id="reference-player-diagnostic",
        lane_index=0,
        lane_name="Reference Player Diagnostic",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("player",),
        endpoints=("common_player_info",),
        timeout_seconds=3600,
        state_artifact_run_id="stale-run",
        state_artifact_name="stale-state",
        state_artifact_digest="a" * 64,
    )
    payload: dict[str, object] = {
        "metadata_schema_version": 3,
        "lane_id": lane.lane_id,
        "status": "needs_resume",
        "raw_status": "extract-timeout",
        "vpn": {"failed_servers": ["us002.nordvpn.com"]},
        "progress": {"completed_calls": 0, "rows_persisted": 0},
    }
    if state_artifact is not None:
        payload["state_artifact"] = state_artifact
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "diagnostic.json").write_text(json.dumps(payload), encoding="utf-8")

    next_lanes, next_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        chain_state=FullExtractionChainState(vpn_quarantined_servers=("us001.nordvpn.com",)),
    )

    assert len(next_lanes) == 1
    retried = next_lanes[0]
    assert retried.state_artifact_run_id == ""
    assert retried.state_artifact_name == ""
    assert retried.state_artifact_digest == ""
    assert next_state.vpn_quarantined_servers == (
        "us001.nordvpn.com",
        "us002.nordvpn.com",
    )
    assert summary["durable_state_lane_count"] == 0


def test_build_resume_manifest_preserves_progress_then_splits_stalled_timeout(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2020-2023",
        lane_index=0,
        lane_name="Historical game 2020-2023",
        lane_kind="historical",
        season_start=2020,
        season_end=2023,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
        rows_persisted=12,
    )

    next_lanes, next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert len(next_lanes) == 1
    retry_lane = next_lanes[0]
    assert retry_lane.lane_id == lane.lane_id
    assert retry_lane.last_rows_persisted == 12
    assert retry_lane.state_artifact_run_id == "12345"
    assert summary["active_lane_count"] == 1
    assert summary["split_lane_count"] == 0

    stalled_metadata_dir = tmp_path / "stalled-metadata"
    stalled_metadata_dir.mkdir()
    _write_metadata(
        stalled_metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
        rows_persisted=12,
    )
    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [retry_lane],
        stalled_metadata_dir,
        chain_state=next_chain_state,
        current_iteration=2,
    )

    validate_manifest(next_lanes)
    assert [child.season_start for child in next_lanes] == [2020, 2021, 2022, 2023]
    assert [child.season_end for child in next_lanes] == [2020, 2021, 2022, 2023]
    assert all(child.parent_lane_id == lane.lane_id for child in next_lanes)
    assert all(child.split_generation == 1 for child in next_lanes)
    assert all(child.failure_streak == 2 for child in next_lanes)
    assert all(child.class_failure_streak == 2 for child in next_lanes)
    assert all(child.last_failure_class == "timeout_progress" for child in next_lanes)
    assert all(child.last_completed_calls == 0 for child in next_lanes)
    assert all(child.last_rows_persisted == 0 for child in next_lanes)
    assert summary["active_lane_count"] == 4
    assert summary["split_lane_count"] == 4
    assert summary["outcome_counts"] == {"needs_resume": 1}


def test_build_resume_manifest_preserves_progress_before_legacy_reshard(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-1994-2005",
        lane_index=0,
        lane_name="Historical game 1994-2005",
        lane_kind="historical",
        season_start=1994,
        season_end=2005,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    progress_metadata_dir = tmp_path / "progress-metadata"
    progress_metadata_dir.mkdir()
    _write_metadata(
        progress_metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
        rows_persisted=12,
    )

    next_lanes, next_chain_state, summary = build_resume_manifest(
        [lane],
        progress_metadata_dir,
    )

    assert len(next_lanes) == 1
    retry_lane = next_lanes[0]
    assert retry_lane.lane_id == lane.lane_id
    assert retry_lane.last_rows_persisted == 12
    assert retry_lane.state_artifact_run_id == "12345"
    assert retry_lane.state_artifact_name == (
        f"extraction-lane-recovery-chain-{lane.lane_id}-run-12345-attempt-1"
    )
    assert summary["split_lane_count"] == 0
    validate_manifest(next_lanes)

    stalled_metadata_dir = tmp_path / "stalled-metadata"
    stalled_metadata_dir.mkdir()
    _write_metadata(
        stalled_metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
        rows_persisted=12,
    )
    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [retry_lane],
        stalled_metadata_dir,
        chain_state=next_chain_state,
        current_iteration=2,
    )

    validate_manifest(next_lanes)
    assert [child.season_start for child in next_lanes] == [1994, 1998, 2002]
    assert [child.season_end for child in next_lanes] == [1997, 2001, 2005]
    assert all(child.parent_lane_id == lane.lane_id for child in next_lanes)
    assert all(not child.state_artifact_run_id for child in next_lanes)
    assert all(child.last_completed_calls == 0 for child in next_lanes)
    assert all(child.last_rows_persisted == 0 for child in next_lanes)
    assert summary["split_lane_count"] == 3


def test_build_resume_manifest_preserves_high_progress_transport_partial(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-video-details-asset-ctx-01-2004-2011",
        lane_index=0,
        lane_name="Cross Product Video Details Asset 2004-2011",
        lane_kind="cross_product",
        season_start=2004,
        season_end=2011,
        patterns=("player_team_season",),
        season_types=("Regular Season", "Playoffs", "Pre Season", "All Star"),
        context_measures=("AST", "BLK", "FG3A"),
        endpoints=("video_details_asset",),
        timeout_seconds=19_800,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "lane.json",
        lane_id=lane.lane_id,
        status="needs_resume",
        raw_status="extract-error",
        completed_calls=14_918,
        failed_calls=1,
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert len(next_lanes) == 1
    retry_lane = next_lanes[0]
    assert retry_lane.lane_id == lane.lane_id
    assert retry_lane.last_completed_calls == 14_918
    assert retry_lane.state_artifact_run_id == "12345"
    assert retry_lane.state_artifact_name
    assert retry_lane.state_artifact_digest == "a" * 64
    assert retry_lane.last_failure_class == "transport_transient"
    assert retry_lane.class_failure_streak == 1
    assert retry_lane.next_eligible_iteration == 2
    assert summary["active_lane_count"] == 1
    assert summary["split_lane_count"] == 0
    assert summary["durable_state_lane_count"] == 1
    validate_manifest(next_lanes)


def test_validate_manifest_rejects_oversized_lane_with_untrusted_state_pointer() -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-1994-2005",
        lane_index=0,
        lane_name="Historical game 1994-2005",
        lane_kind="historical",
        season_start=1994,
        season_end=2005,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        state_artifact_run_id="stale-run",
        state_artifact_name=(
            "extraction-lane-chain-historical-game-box-score-summary-no-season-type-1994-2005"
        ),
        state_artifact_digest="a" * 64,
    )

    with pytest.raises(ValueError, match="span 12 exceeds lane policy max 4"):
        validate_manifest([lane])


def test_validate_manifest_accepts_oversized_lane_with_canonical_recovery_pointer() -> None:
    lane_id = "historical-game-box-score-summary-no-season-type-1994-2005"
    lane = FullExtractionLane(
        lane_id=lane_id,
        lane_index=0,
        lane_name="Historical game 1994-2005",
        lane_kind="historical",
        season_start=1994,
        season_end=2005,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        state_artifact_run_id="12345",
        state_artifact_name=(f"extraction-lane-recovery-chain-{lane_id}-run-12345-attempt-2"),
        state_artifact_digest="a" * 64,
    )

    validate_manifest([lane])


def test_validate_manifest_rejects_progress_without_recovery_pointer() -> None:
    lane = FullExtractionLane(
        lane_id="reference-player-orphan-progress",
        lane_index=0,
        lane_name="Reference Player Orphan Progress",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("player",),
        endpoints=("common_player_info",),
        timeout_seconds=3600,
        last_completed_calls=1,
    )

    with pytest.raises(ValueError, match="persisted progress counters require"):
        validate_manifest([lane])


@pytest.mark.parametrize(
    "artifact_name",
    [
        "extraction-lane-chain-{lane_id}",
        "extraction-lane-recovery-chain-{lane_id}-run-99999-attempt-1",
        "extraction-lane-recovery-chain-{lane_id}-run-12345-attempt-0",
        "extraction-lane-recovery-chain-other-lane-run-12345-attempt-1",
    ],
)
def test_validate_manifest_rejects_noncanonical_recovery_pointer(artifact_name: str) -> None:
    lane_id = "historical-game-box-score-summary-no-season-type-2020-2023"
    lane = FullExtractionLane(
        lane_id=lane_id,
        lane_index=0,
        lane_name="Historical game 2020-2023",
        lane_kind="historical",
        season_start=2020,
        season_end=2023,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        state_artifact_run_id="12345",
        state_artifact_name=artifact_name.format(lane_id=lane_id),
        state_artifact_digest="a" * 64,
    )

    with pytest.raises(ValueError, match="canonical uploaded recovery artifact"):
        validate_manifest([lane])


@pytest.mark.parametrize(
    ("receipt_field", "receipt_value"),
    [
        ("attested", False),
        ("uploaded", False),
        ("artifact_id", "0"),
        ("artifact_digest", "invalid"),
    ],
)
def test_timeout_progress_requires_durable_artifact_receipt(
    tmp_path: Path,
    receipt_field: str,
    receipt_value: object,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2020-2023",
        lane_index=0,
        lane_name="Historical game 2020-2023",
        lane_kind="historical",
        season_start=2020,
        season_end=2023,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        zero_progress_streak=2,
    )
    metadata_path = tmp_path / f"{receipt_field}.json"
    _write_metadata(
        metadata_path,
        lane_id=lane.lane_id,
        status="extract-timeout",
        completed_calls=10,
    )
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    state_artifact = payload["state_artifact"]
    assert isinstance(state_artifact, dict)
    state_artifact[receipt_field] = receipt_value
    metadata_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], tmp_path)

    assert len(next_lanes) == 4
    assert all(not child.state_artifact_run_id for child in next_lanes)
    assert all(child.last_completed_calls == 0 for child in next_lanes)
    assert all(child.zero_progress_streak == 3 for child in next_lanes)
    assert summary["split_lane_count"] == 4


def test_missing_artifact_receipt_does_not_preserve_reported_progress(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-player-state-upload-failed",
        lane_index=0,
        lane_name="Reference Player State Upload Failed",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("player",),
        endpoints=("common_player_info",),
        timeout_seconds=3600,
        zero_progress_streak=2,
    )
    metadata_path = tmp_path / "missing-receipt.json"
    _write_metadata(
        metadata_path,
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="state-artifact-upload-failed",
        completed_calls=10,
    )
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload.pop("state_artifact")
    metadata_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane],
        tmp_path,
        allow_pipeline_failures=True,
    )

    assert len(next_lanes) == 1
    retry_lane = next_lanes[0]
    assert retry_lane.zero_progress_streak == 3
    assert retry_lane.last_completed_calls == 0
    assert retry_lane.last_rows_persisted == 0
    assert retry_lane.state_artifact_run_id == ""
    assert summary["pipeline_failure_retry_count"] == 1


def test_failed_new_receipt_preserves_previous_durable_state(tmp_path: Path) -> None:
    lane_id = "reference-player-state-upload-failed"
    previous_artifact_name = f"extraction-lane-recovery-chain-{lane_id}-run-12345-attempt-1"
    lane = FullExtractionLane(
        lane_id=lane_id,
        lane_index=0,
        lane_name="Reference Player State Upload Failed",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("player",),
        endpoints=("common_player_info",),
        timeout_seconds=3600,
        zero_progress_streak=2,
        state_artifact_run_id="12345",
        state_artifact_name=previous_artifact_name,
        state_artifact_digest="a" * 64,
        last_completed_calls=5,
        last_rows_persisted=8,
    )
    metadata_path = tmp_path / "failed-new-receipt.json"
    _write_metadata(
        metadata_path,
        lane_id=lane.lane_id,
        status="needs_resume",
        raw_status="extract-timeout",
        completed_calls=10,
        rows_persisted=12,
    )
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    state_artifact = payload["state_artifact"]
    assert isinstance(state_artifact, dict)
    state_artifact["uploaded"] = False
    metadata_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], tmp_path)

    assert len(next_lanes) == 1
    retry_lane = next_lanes[0]
    assert retry_lane.zero_progress_streak == 3
    assert retry_lane.state_artifact_run_id == "12345"
    assert retry_lane.state_artifact_name == previous_artifact_name
    assert retry_lane.state_artifact_digest == "a" * 64
    assert retry_lane.last_completed_calls == 5
    assert retry_lane.last_rows_persisted == 8
    assert summary["durable_state_lane_count"] == 1
    validate_manifest(next_lanes)


def test_timeout_progress_without_state_artifact_fails_closed(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2020-2023",
        lane_index=0,
        lane_name="Historical game 2020-2023",
        lane_kind="historical",
        season_start=2020,
        season_end=2023,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    metadata_path = tmp_path / "missing-artifact.json"
    _write_metadata(
        metadata_path,
        lane_id=lane.lane_id,
        status="extract-timeout",
        completed_calls=10,
    )
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    payload.pop("state_artifact")
    metadata_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Pipeline-failure lane outcomes"):
        build_resume_manifest([lane], tmp_path)


def test_zero_row_timeout_progress_then_stall(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2020-2023",
        lane_index=0,
        lane_name="Historical game 2020-2023",
        lane_kind="historical",
        season_start=2020,
        season_end=2023,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    progress_dir = tmp_path / "progress"
    progress_dir.mkdir()
    _write_metadata(
        progress_dir / "lane.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
        completed_calls=10,
    )

    progressed_lanes, next_chain_state, summary = build_resume_manifest([lane], progress_dir)

    assert len(progressed_lanes) == 1
    assert progressed_lanes[0].last_completed_calls == 10
    assert progressed_lanes[0].last_rows_persisted == 0
    assert progressed_lanes[0].state_artifact_run_id == "12345"
    assert summary["split_lane_count"] == 0

    stalled_dir = tmp_path / "stalled"
    stalled_dir.mkdir()
    _write_metadata(
        stalled_dir / "lane.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
        completed_calls=10,
    )
    split_lanes, _next_chain_state, summary = build_resume_manifest(
        progressed_lanes,
        stalled_dir,
        chain_state=next_chain_state,
        current_iteration=2,
    )

    assert len(split_lanes) == 4
    assert all(child.last_completed_calls == 0 for child in split_lanes)
    assert summary["split_lane_count"] == 4


def test_build_resume_manifest_rejects_regressing_durable_progress(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2020-2023",
        lane_index=0,
        lane_name="Historical game 2020-2023",
        lane_kind="historical",
        season_start=2020,
        season_end=2023,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        last_completed_calls=10,
        last_rows_persisted=100,
    )
    _write_metadata(
        tmp_path / "lane.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
        completed_calls=11,
        rows_persisted=99,
    )

    with pytest.raises(ValueError, match="Durable lane state progress regressed"):
        build_resume_manifest([lane], tmp_path)


def test_build_resume_manifest_blocks_pre_1996_box_score_advanced_contract_gap(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-advanced-no-season-type-1946-1949",
        lane_index=0,
        lane_name="Historical game 1946-1949",
        lane_kind="historical",
        season_start=1946,
        season_end=1949,
        patterns=("game",),
        endpoints=("box_score_advanced",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="extract-error",
        failed_calls=1538,
        endpoints=["box_score_advanced"],
        patterns=["game"],
        season_start=1946,
        season_end=1949,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


@pytest.mark.parametrize(
    ("endpoint_name", "blocked_end", "supported_start"),
    [
        ("box_score_defensive", 2016, 2017),
        ("box_score_four_factors", 1995, 1996),
        ("box_score_matchups", 2015, 2016),
        ("box_score_misc", 1995, 1996),
        ("box_score_player_track", 1995, 1996),
        ("box_score_scoring", 1995, 1996),
        ("box_score_usage", 1993, 1994),
    ],
)
def test_build_resume_manifest_blocks_historical_box_score_contract_gaps(
    tmp_path: Path,
    endpoint_name: str,
    blocked_end: int,
    supported_start: int,
) -> None:
    lane = FullExtractionLane(
        lane_id=f"historical-game-{endpoint_name}-no-season-type-1946-{blocked_end}",
        lane_index=0,
        lane_name=f"Historical game {endpoint_name} 1946-{blocked_end}",
        lane_kind="historical",
        season_start=1946,
        season_end=blocked_end,
        patterns=("game",),
        endpoints=(endpoint_name,),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="extract-error",
        failed_calls=1538,
        endpoints=[endpoint_name],
        patterns=["game"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}

    final_failure_metadata_dir = tmp_path / f"metadata-final-{endpoint_name}"
    final_failure_metadata_dir.mkdir()
    _write_metadata(
        final_failure_metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=1538,
        endpoints=[endpoint_name],
        patterns=["game"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane], final_failure_metadata_dir
    )

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}

    supported_lane = FullExtractionLane(
        lane_id=f"historical-game-{endpoint_name}-no-season-type-{supported_start}-{supported_start}",
        lane_index=1,
        lane_name=f"Historical game {endpoint_name} {supported_start}",
        lane_kind="historical",
        season_start=supported_start,
        season_end=supported_start,
        patterns=("game",),
        endpoints=(endpoint_name,),
        timeout_seconds=7200,
    )
    supported_metadata_dir = tmp_path / f"metadata-{endpoint_name}"
    supported_metadata_dir.mkdir()
    _write_metadata(
        supported_metadata_dir / "historical.json",
        lane_id=supported_lane.lane_id,
        status="extract-error",
        failed_calls=100,
        endpoints=[endpoint_name],
        patterns=["game"],
        season_start=supported_lane.season_start,
        season_end=supported_lane.season_end,
    )

    with pytest.raises(ValueError, match="Pipeline-failure lane outcomes"):
        build_resume_manifest([supported_lane], supported_metadata_dir)


def test_build_resume_manifest_blocks_1946_win_probability_contract_gap(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-win-probability-no-season-type-1946-1946",
        lane_index=0,
        lane_name="Historical game 1946 (win_probability)",
        lane_kind="historical",
        season_start=1946,
        season_end=1946,
        patterns=("game",),
        endpoints=("win_probability",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=350,
        endpoints=["win_probability"],
        patterns=["game"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}

    supported_lane = FullExtractionLane(
        lane_id="historical-game-win-probability-no-season-type-1947-1947",
        lane_index=1,
        lane_name="Historical game 1947 (win_probability)",
        lane_kind="historical",
        season_start=1947,
        season_end=1947,
        patterns=("game",),
        endpoints=("win_probability",),
        timeout_seconds=7200,
    )
    supported_metadata_dir = tmp_path / "metadata-supported"
    supported_metadata_dir.mkdir()
    _write_metadata(
        supported_metadata_dir / "historical.json",
        lane_id=supported_lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=350,
        endpoints=["win_probability"],
        patterns=["game"],
        season_start=supported_lane.season_start,
        season_end=supported_lane.season_end,
    )

    with pytest.raises(ValueError, match="Pipeline-failure lane outcomes"):
        build_resume_manifest([supported_lane], supported_metadata_dir)


@pytest.mark.parametrize("season", [1949, 1950])
def test_build_resume_manifest_blocks_1949_1950_win_probability_contract_gap(
    tmp_path: Path,
    season: int,
) -> None:
    lane = FullExtractionLane(
        lane_id=f"historical-game-win-probability-no-season-type-{season}-{season}",
        lane_index=0,
        lane_name=f"Historical game {season} (win_probability)",
        lane_kind="historical",
        season_start=season,
        season_end=season,
        patterns=("game",),
        endpoints=("win_probability",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / f"metadata-{season}"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=593 if season == 1949 else 381,
        endpoints=["win_probability"],
        patterns=["game"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


def test_build_resume_manifest_keeps_1951_win_probability_pipeline_failures_unclassified(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-win-probability-no-season-type-1951-1951",
        lane_index=0,
        lane_name="Historical game 1951 (win_probability)",
        lane_kind="historical",
        season_start=1951,
        season_end=1951,
        patterns=("game",),
        endpoints=("win_probability",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata-1951"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=100,
        endpoints=["win_probability"],
        patterns=["game"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    with pytest.raises(ValueError, match="Pipeline-failure lane outcomes"):
        build_resume_manifest([lane], metadata_dir)


def test_build_resume_manifest_blocks_1950_scoreboard_v2_contract_gap(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v2-no-season-type-1950-1953-split-1950-1950",
        lane_index=0,
        lane_name="Historical date 1950-1953 (scoreboard_v2) 1950-1950",
        lane_kind="historical",
        season_start=1950,
        season_end=1950,
        patterns=("date",),
        endpoints=("scoreboard_v2",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=132,
        endpoints=["scoreboard_v2"],
        patterns=["date"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}

    unclassified_lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v3-no-season-type-1951-1951",
        lane_index=1,
        lane_name="Historical date 1951 (scoreboard_v3)",
        lane_kind="historical",
        season_start=1951,
        season_end=1951,
        patterns=("date",),
        endpoints=("scoreboard_v3",),
        timeout_seconds=7200,
    )
    unclassified_metadata_dir = tmp_path / "metadata-unclassified"
    unclassified_metadata_dir.mkdir()
    _write_metadata(
        unclassified_metadata_dir / "historical.json",
        lane_id=unclassified_lane.lane_id,
        status="extract-error",
        failed_calls=100,
        endpoints=["scoreboard_v3"],
        patterns=["date"],
        season_start=unclassified_lane.season_start,
        season_end=unclassified_lane.season_end,
    )

    with pytest.raises(ValueError, match="Pipeline-failure lane outcomes"):
        build_resume_manifest([unclassified_lane], unclassified_metadata_dir)


def test_build_resume_manifest_blocks_1954_scoreboard_v2_contract_gap(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v2-no-season-type-1954-1957-split-1954-1954",
        lane_index=17,
        lane_name="Historical date 1954-1957 (scoreboard_v2) 1954-1954",
        lane_kind="historical",
        season_start=1954,
        season_end=1954,
        patterns=("date",),
        endpoints=("scoreboard_v2",),
        timeout_seconds=5400,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=126,
        endpoints=["scoreboard_v2"],
        patterns=["date"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


def test_build_resume_manifest_blocks_1956_scoreboard_v2_contract_gap(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v2-no-season-type-1954-1957-split-1956-1956",
        lane_index=19,
        lane_name="Historical date 1954-1957 (scoreboard_v2) 1956-1956",
        lane_kind="historical",
        season_start=1956,
        season_end=1956,
        patterns=("date",),
        endpoints=("scoreboard_v2",),
        timeout_seconds=5400,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=124,
        endpoints=["scoreboard_v2"],
        patterns=["date"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


@pytest.mark.parametrize(
    ("season_start", "season_end", "lane_id"),
    [
        (1946, 1948, "historical-season-no-season-type-1946-1948"),
        (1949, 1951, "historical-season-no-season-type-1949-1951"),
        (1952, 1954, "historical-season-no-season-type-1952-1954"),
        (1955, 1957, "historical-season-no-season-type-1955-1957"),
        (1958, 1960, "historical-season-no-season-type-1958-1960"),
        (1961, 1963, "historical-season-no-season-type-1961-1963"),
        (1964, 1966, "historical-season-no-season-type-1964-1966"),
        (1967, 1969, "historical-season-no-season-type-1967-1969"),
    ],
)
def test_build_resume_manifest_blocks_early_season_endpoint_contract_gap(
    tmp_path: Path,
    season_start: int,
    season_end: int,
    lane_id: str,
) -> None:
    lane = FullExtractionLane(
        lane_id=lane_id,
        lane_index=3,
        lane_name=f"Historical season {season_start}-{season_end}",
        lane_kind="historical",
        season_start=season_start,
        season_end=season_end,
        patterns=("season",),
        endpoints=EARLY_SEASON_CONTRACT_BLOCKED_ENDPOINTS,
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=48,
        endpoints=list(lane.endpoints),
        patterns=["season"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


@pytest.mark.parametrize("endpoint_name", EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS)
def test_build_resume_manifest_blocks_1946_1949_season_endpoint_contract_gap(
    tmp_path: Path,
    endpoint_name: str,
) -> None:
    lane = FullExtractionLane(
        lane_id=f"historical-season-{endpoint_name}-regular-season-playoffs-1946-1949",
        lane_index=79,
        lane_name=f"Historical season 1946-1949 ({endpoint_name})",
        lane_kind="historical",
        season_start=1946,
        season_end=1949,
        patterns=("season",),
        endpoints=(endpoint_name,),
        timeout_seconds=4800,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=16,
        endpoints=[endpoint_name],
        patterns=["season"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


@pytest.mark.parametrize("endpoint_name", EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS)
def test_build_resume_manifest_keeps_post_1949_season_endpoint_failures_unclassified(
    tmp_path: Path,
    endpoint_name: str,
) -> None:
    lane = FullExtractionLane(
        lane_id=f"historical-season-{endpoint_name}-regular-season-playoffs-1950-1950",
        lane_index=79,
        lane_name=f"Historical season 1950 ({endpoint_name})",
        lane_kind="historical",
        season_start=1950,
        season_end=1950,
        patterns=("season",),
        endpoints=(endpoint_name,),
        timeout_seconds=4800,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=16,
        endpoints=[endpoint_name],
        patterns=["season"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    with pytest.raises(ValueError, match="Pipeline-failure"):
        build_resume_manifest([lane], metadata_dir)


def test_build_resume_manifest_blocks_1946_1949_mixed_supported_endpoint_lane(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-season-run-28710521686-contract-gaps-1946-1949",
        lane_index=79,
        lane_name="Historical season 1946-1949 run 28710521686 contract gaps",
        lane_kind="historical",
        season_start=1946,
        season_end=1949,
        patterns=("season",),
        endpoints=EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS,
        timeout_seconds=4800,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=26,
        endpoints=list(lane.endpoints),
        patterns=["season"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


def test_build_resume_manifest_keeps_1946_1949_mixed_unclassified_endpoint_lane_blocking(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-season-mixed-contract-and-unclassified-1946-1949",
        lane_index=79,
        lane_name="Historical season mixed contract and unclassified 1946-1949",
        lane_kind="historical",
        season_start=1946,
        season_end=1949,
        patterns=("season",),
        endpoints=(
            EARLY_1946_1949_SEASON_CONTRACT_BLOCKED_ENDPOINTS[0],
            "league_leaders",
        ),
        timeout_seconds=4800,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=16,
        endpoints=list(lane.endpoints),
        patterns=["season"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    with pytest.raises(ValueError, match="Pipeline-failure"):
        build_resume_manifest([lane], metadata_dir)


def test_build_resume_manifest_keeps_zero_row_timeout_lanes_resumable_with_1946_1949_rules(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-player-season-regular-season-playoffs-pre-season-all-star-1946-1946",
        lane_index=1,
        lane_name="Historical player season 1946",
        lane_kind="historical",
        season_start=1946,
        season_end=1946,
        patterns=("player_season",),
        endpoints=("player_game_log",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="needs_resume",
        raw_status="extract-timeout",
        failed_calls=778,
        endpoints=list(lane.endpoints),
        patterns=["player_season"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes
    assert summary["contract_blocked_lane_count"] == 0
    assert summary["outcome_counts"] == {"needs_resume": 1}


def test_build_resume_manifest_reclassifies_declared_resume_contract_gap(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-misc-no-season-type-1995-1995",
        lane_index=0,
        lane_name="Historical game 1995",
        lane_kind="historical",
        season_start=1995,
        season_end=1995,
        patterns=("game",),
        endpoints=("box_score_misc",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="needs_resume",
        raw_status="extract-timeout",
        rows_persisted=0,
        failed_calls=1258,
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


@pytest.mark.parametrize(
    ("endpoint_name", "season_start", "season_end"),
    [
        ("draft_history", 1970, 1996),
        ("schedule_int", 1970, 1999),
        ("ist_standings", 1970, 2020),
        ("player_career_by_college", 2024, 2024),
        ("team_game_streak_finder", 2024, 2024),
    ],
)
def test_build_resume_manifest_blocks_post_1969_season_endpoint_contract_gaps(
    tmp_path: Path,
    endpoint_name: str,
    season_start: int,
    season_end: int,
) -> None:
    lane = FullExtractionLane(
        lane_id=f"historical-season-{endpoint_name}-no-season-type-{season_start}-{season_end}",
        lane_index=3,
        lane_name=f"Historical season {endpoint_name} {season_start}-{season_end}",
        lane_kind="historical",
        season_start=season_start,
        season_end=season_end,
        patterns=("season",),
        endpoints=(endpoint_name,),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=3,
        endpoints=[endpoint_name],
        patterns=["season"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


def test_build_resume_manifest_requires_all_lane_endpoints_to_be_contract_blocked(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-mixed-contract-gap-1990",
        lane_index=0,
        lane_name="Historical game mixed contract gap 1990",
        lane_kind="historical",
        season_start=1990,
        season_end=1990,
        patterns=("game",),
        endpoints=("box_score_misc", "box_score_traditional"),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="extract-error",
        failed_calls=100,
        endpoints=list(lane.endpoints),
        patterns=["game"],
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    with pytest.raises(ValueError, match="Pipeline-failure lane outcomes"):
        build_resume_manifest([lane], metadata_dir)


def test_build_resume_manifest_splits_repeated_game_date_timeout_to_one_season(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v3-no-season-type-1962-1965",
        lane_index=0,
        lane_name="Historical date 1962-1965",
        lane_kind="historical",
        season_start=1962,
        season_end=1965,
        patterns=("date",),
        endpoints=("scoreboard_v3",),
        timeout_seconds=7200,
        failure_streak=1,
        last_failure_reason="needs_resume",
        last_rows_persisted=18,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
        rows_persisted=18,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    validate_manifest(next_lanes)
    assert [(child.season_start, child.season_end) for child in next_lanes] == [
        (1962, 1962),
        (1963, 1963),
        (1964, 1964),
        (1965, 1965),
    ]
    assert all(child.parent_lane_id == lane.lane_id for child in next_lanes)
    assert summary["active_lane_count"] == 4
    assert summary["split_lane_count"] == 4


def test_build_resume_manifest_skips_contract_blocked_lanes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import nbadb.orchestrate.extraction_contract as extraction_contract

    monkeypatch.setattr(
        extraction_contract,
        "FULL_EXTRACTION_SUPPORT_RULES",
        (
            EndpointSupportRule(
                endpoint_name="documented_zero_row",
                pattern="game",
                classification="contract_blocked",
                reason="Upstream returns no rows for this historical range.",
                evidence="docs/endpoint-analysis/documented_zero_row.md",
                revalidation_command="uv run nbadb endpoint-probe documented_zero_row",
                season_start=1946,
                season_end=1950,
            ),
        ),
    )
    lane = FullExtractionLane(
        lane_id="historical-game-documented-zero-row-no-season-type-1946-1950",
        lane_index=0,
        lane_name="Historical game 1946-1950",
        lane_kind="historical",
        season_start=1946,
        season_end=1950,
        patterns=("game",),
        endpoints=("documented_zero_row",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "contract.json",
        lane_id=lane.lane_id,
        status="extract-error",
        failed_calls=5,
        endpoints=["documented_zero_row"],
        patterns=["game"],
        season_start=1946,
        season_end=1950,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["active_lane_count"] == 0
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


def test_build_resume_manifest_skips_newly_contract_blocked_unattempted_lane(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id=(
            "historical-player-season-player-next-games-regular-season-playoffs-"
            "pre-season-all-star-1946-1946-split-1946-1946-regular-season"
        ),
        lane_index=0,
        lane_name="Historical player_season 1946-1946 (player_next_games)",
        lane_kind="historical",
        season_start=1946,
        season_end=1946,
        patterns=("player_season",),
        season_types=("Regular Season",),
        endpoints=("player_next_games",),
        timeout_seconds=4800,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset(),
        allow_missing_attempted_metadata=True,
    )

    assert next_lanes == []
    assert summary["active_lane_count"] == 0
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


def test_resume_preserves_metadata_backed_blocked_evidence_pending_checkpoint_commit(
    tmp_path: Path,
) -> None:
    committed_lane = FullExtractionLane(
        lane_id="historical-video-details-no-season-type-1948-1949",
        lane_index=0,
        lane_name="Historical video details 1948-1949",
        lane_kind="historical",
        season_start=1948,
        season_end=1949,
        patterns=("player_team_season",),
        endpoints=("video_details",),
        timeout_seconds=1,
    )
    newly_blocked_lane = replace(
        committed_lane,
        lane_id="historical-video-details-no-season-type-1950-1951",
        lane_name="Historical video details 1950-1951",
        season_start=1950,
        season_end=1951,
    )
    committed_row = _contract_blocked_row(committed_lane)
    committed_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [committed_row],
    }
    previous_state = FullExtractionChainState(
        latest_checkpoint_run_id="12345",
        latest_checkpoint_artifact_name="full-extraction-checkpoint-chain-iter-1",
        latest_checkpoint_generation=1,
        latest_checkpoint_coverage_hash="a" * 64,
        contract_blocked_evidence=(committed_row,),
        contract_blocked_evidence_sha256=_hash_payload(committed_evidence),
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "blocked.json",
        lane_id=newly_blocked_lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-error",
        failed_calls=1,
        endpoints=list(newly_blocked_lane.endpoints),
        patterns=list(newly_blocked_lane.patterns),
        season_start=newly_blocked_lane.season_start,
        season_end=newly_blocked_lane.season_end,
    )

    next_lanes, next_state, summary = build_resume_manifest(
        [newly_blocked_lane],
        metadata_dir,
        chain_state=previous_state,
    )

    pending_row = _contract_blocked_row(newly_blocked_lane)
    pending_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [pending_row],
    }
    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert next_state.contract_blocked_evidence == (committed_row,)
    assert (
        next_state.contract_blocked_evidence_sha256
        == previous_state.contract_blocked_evidence_sha256
    )
    assert next_state.previous_contract_blocked_evidence == ()
    assert next_state.pending_contract_blocked_evidence == (pending_row,)
    assert next_state.pending_contract_blocked_evidence_sha256 == _hash_payload(pending_evidence)

    source_resume = normalize_manifest(
        redispatch_manifest_payload(next_lanes, chain_state=next_state)
    )
    empty_metadata_dir = tmp_path / "source-resume-metadata"
    empty_metadata_dir.mkdir()
    _lanes, resumed_state, _resume_summary = build_resume_manifest(
        list(source_resume.lanes),
        empty_metadata_dir,
        chain_state=source_resume.chain_state,
    )
    assert resumed_state == next_state


def test_resume_merges_metadata_less_blocked_lane_with_validated_pending_evidence(
    tmp_path: Path,
) -> None:
    prior_lane = FullExtractionLane(
        lane_id="historical-video-details-no-season-type-1952-1953",
        lane_index=0,
        lane_name="Historical video details 1952-1953",
        lane_kind="historical",
        season_start=1952,
        season_end=1953,
        patterns=("player_team_season",),
        endpoints=("video_details",),
        timeout_seconds=1,
    )
    new_lane = replace(
        prior_lane,
        lane_id="historical-video-details-no-season-type-1954-1955",
        lane_name="Historical video details 1954-1955",
        season_start=1954,
        season_end=1955,
    )
    prior_row = _contract_blocked_row(prior_lane)
    prior_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [prior_row],
    }
    previous_state = FullExtractionChainState(
        pending_contract_blocked_evidence=(prior_row,),
        pending_contract_blocked_evidence_sha256=_hash_payload(prior_evidence),
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    next_lanes, next_state, summary = build_resume_manifest(
        [new_lane],
        metadata_dir,
        chain_state=previous_state,
        attempted_lane_ids=frozenset(),
        allow_missing_attempted_metadata=True,
    )

    expected_rows = tuple(
        sorted([prior_row, _contract_blocked_row(new_lane)], key=lambda row: row["lane_id"])
    )
    expected_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": list(expected_rows),
    }
    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == 1
    assert next_state.pending_contract_blocked_evidence == expected_rows
    assert next_state.pending_contract_blocked_evidence_sha256 == _hash_payload(expected_evidence)

    with pytest.raises(ValueError, match="Pending contract-blocked evidence digest"):
        build_resume_manifest(
            [new_lane],
            metadata_dir,
            chain_state=replace(
                previous_state,
                pending_contract_blocked_evidence_sha256="b" * 64,
            ),
            attempted_lane_ids=frozenset(),
            allow_missing_attempted_metadata=True,
        )


def test_metadata_less_contract_block_precedes_resume_only_preservation(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-video-details-no-season-type-1956-1957",
        lane_index=0,
        lane_name="Historical video details 1956-1957",
        lane_kind="historical",
        season_start=1956,
        season_end=1957,
        patterns=("player_team_season",),
        endpoints=("video_details",),
        resume_only=True,
        timeout_seconds=1,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    next_lanes, next_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
    )

    expected_row = _contract_blocked_row(lane)
    assert next_lanes == []
    assert summary["resume_only_lane_count"] == 0
    assert summary["contract_blocked_lane_count"] == 1
    assert next_state.pending_contract_blocked_evidence == (expected_row,)


def test_build_resume_manifest_reclassifies_zero_progress_contract_blocked_timeout(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id=(
            "historical-player-season-shot-chart-detail-regular-season-playoffs-"
            "pre-season-all-star-1946-1946-split-1946-1946-regular-season"
        ),
        lane_index=0,
        lane_name="Historical player_season 1946-1946 (shot_chart_detail)",
        lane_kind="historical",
        season_start=1946,
        season_end=1946,
        patterns=("player_season",),
        season_types=("Regular Season",),
        endpoints=("shot_chart_detail",),
        timeout_seconds=4800,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "shot_chart_detail.json",
        lane_id=lane.lane_id,
        status="pipeline_failure",
        raw_status="extract-timeout",
        rows_persisted=0,
        failed_calls=0,
        running_calls=161,
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
        season_start=1946,
        season_end=1946,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    assert next_lanes == []
    assert summary["active_lane_count"] == 0
    assert summary["contract_blocked_lane_count"] == 1
    assert summary["outcome_counts"] == {"contract_blocked": 1}


def test_build_resume_manifest_reclassifies_known_historical_box_score_gaps(
    tmp_path: Path,
) -> None:
    cases = [
        (
            "historical-game-box-score-matchups-no-season-type-2006-2017-split-2014-2014",
            "box_score_matchups",
            2014,
            2014,
            1430,
        ),
        (
            "historical-game-box-score-matchups-no-season-type-2006-2017-split-2015-2015",
            "box_score_matchups",
            2015,
            2015,
            1426,
        ),
        (
            "historical-game-box-score-misc-no-season-type-1994-2005-split-1994-1994",
            "box_score_misc",
            1994,
            1994,
            1181,
        ),
        (
            "historical-game-box-score-misc-no-season-type-1994-2005-split-1995-1995",
            "box_score_misc",
            1995,
            1995,
            1258,
        ),
        (
            "historical-game-box-score-player-track-no-season-type-1994-2005-split-1994-1994",
            "box_score_player_track",
            1994,
            1994,
            1181,
        ),
        (
            "historical-game-box-score-player-track-no-season-type-1994-2005-split-1995-1995",
            "box_score_player_track",
            1995,
            1995,
            1258,
        ),
        (
            "historical-game-box-score-scoring-no-season-type-1994-2005-split-1994-1994",
            "box_score_scoring",
            1994,
            1994,
            1181,
        ),
        (
            "historical-game-box-score-scoring-no-season-type-1994-2005-split-1995-1995",
            "box_score_scoring",
            1995,
            1995,
            1258,
        ),
        (
            "historical-game-box-score-usage-no-season-type-1946-1949",
            "box_score_usage",
            1946,
            1949,
            1538,
        ),
        (
            "historical-game-box-score-usage-no-season-type-1990-1993",
            "box_score_usage",
            1990,
            1993,
            4726,
        ),
    ]
    lanes = [
        FullExtractionLane(
            lane_id=lane_id,
            lane_index=index,
            lane_name=f"Historical game {endpoint} {season_start}-{season_end}",
            lane_kind="historical",
            season_start=season_start,
            season_end=season_end,
            patterns=("game",),
            endpoints=(endpoint,),
            timeout_seconds=7200,
        )
        for index, (lane_id, endpoint, season_start, season_end, _failed_calls) in enumerate(cases)
    ]
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    for lane_id, endpoint, season_start, season_end, failed_calls in cases:
        _write_metadata(
            metadata_dir / f"{lane_id}.json",
            lane_id=lane_id,
            status="pipeline_failure",
            raw_status="extract-error",
            rows_persisted=0,
            failed_calls=failed_calls,
            endpoints=[endpoint],
            patterns=["game"],
            season_start=season_start,
            season_end=season_end,
        )

    next_lanes, _next_chain_state, summary = build_resume_manifest(lanes, metadata_dir)

    assert next_lanes == []
    assert summary["contract_blocked_lane_count"] == len(cases)
    assert summary["active_lane_count"] == 0
    assert summary["outcome_counts"] == {"contract_blocked": len(cases)}


def test_build_resume_manifest_preserves_deferred_unattempted_lanes(tmp_path: Path) -> None:
    attempted_lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-1994-1997",
        lane_index=0,
        lane_name="Historical game 1994-1997",
        lane_kind="historical",
        season_start=1994,
        season_end=1997,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        last_rows_persisted=4,
    )
    deferred_lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-1998-2001",
        lane_index=1,
        lane_name="Historical game 1998-2001",
        lane_kind="historical",
        season_start=1998,
        season_end=2001,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "attempted.json",
        lane_id=attempted_lane.lane_id,
        status="extract-timeout",
        rows_persisted=4,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [attempted_lane, deferred_lane],
        metadata_dir,
        attempted_lane_ids=frozenset({attempted_lane.lane_id}),
    )

    by_id = {lane.lane_id: lane for lane in next_lanes}
    assert by_id[deferred_lane.lane_id].last_failure_reason == ""
    assert by_id[deferred_lane.lane_id].failure_streak == 0
    assert summary["active_lane_count"] == 5
    assert summary["deferred_lane_count"] == 1
    assert summary["failure_reason_counts"] == {"extract-timeout": 1}


def test_build_resume_manifest_defers_auth_circuit_without_spending_retry_budget(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=7,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        attempt_count=4,
        failure_streak=2,
        class_failure_streak=2,
        zero_progress_streak=1,
        last_failure_reason="needs_resume",
        last_failure_class="transport_transient",
        last_completed_calls=31,
        last_rows_persisted=412,
        next_eligible_iteration=3,
        state_artifact_run_id="29460000000",
        state_artifact_name=(
            "extraction-lane-recovery-chain-"
            "historical-game-box-score-summary-no-season-type-2024-2024-run-"
            "29460000000-attempt-1"
        ),
        state_artifact_digest="a" * 64,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    metadata_path = metadata_dir / "circuit-deferred.json"
    metadata_path.write_text(
        json.dumps(_auth_coordination_metadata(lane, iteration=5)) + "\n",
        encoding="utf-8",
    )

    next_lanes, next_chain_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        current_iteration=5,
        expected_chain_id=TEST_CHAIN_ID,
        expected_source_sha=TEST_SOURCE_SHA,
    )

    assert len(next_lanes) == 1
    deferred = next_lanes[0]
    for field_name in (
        "attempt_count",
        "failure_streak",
        "class_failure_streak",
        "zero_progress_streak",
        "last_failure_reason",
        "last_failure_class",
        "last_completed_calls",
        "last_rows_persisted",
        "next_eligible_iteration",
        "state_artifact_run_id",
        "state_artifact_name",
        "state_artifact_digest",
    ):
        assert getattr(deferred, field_name) == getattr(lane, field_name)
    assert summary["active_lane_count"] == 1
    assert summary["deferred_lane_count"] == 1
    assert summary["vpn_auth_circuit_deferred_lane_count"] == 1
    assert summary["vpn_auth_circuit_check_failed_lane_count"] == 0
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 0
    assert summary["outcome_counts"] == {"needs_resume": 1}
    assert summary["failure_reason_counts"] == {"vpn_auth_circuit_open": 1}
    assert summary["failure_class_counts"] == {}
    assert summary["pipeline_failure_retry_count"] == 0
    assert summary["split_lane_count"] == 0
    assert summary["blocked_lane_count"] == 0
    assert summary["durable_state_lane_count"] == 1
    validate_manifest(next_lanes)

    next_payload = manifest_payload(next_lanes, chain_state=next_chain_state)
    assert next_payload["active_lane_count"] == 1
    assert next_payload["resume_only_lane_count"] == 0
    assert [row["lane_id"] for row in next_payload["lanes"]] == [lane.lane_id]
    round_trip = normalize_manifest(
        redispatch_manifest_payload(next_lanes, chain_state=next_chain_state)
    )
    assert round_trip.lanes[0].state_artifact_run_id == lane.state_artifact_run_id
    assert round_trip.lanes[0].last_completed_calls == lane.last_completed_calls


def test_restored_auth_rejection_with_no_new_work_consumes_bounded_vpn_retry(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=7,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        attempt_count=4,
        failure_streak=2,
        class_failure_streak=2,
        zero_progress_streak=1,
        last_failure_reason="needs_resume",
        last_failure_class="transport_transient",
        last_completed_calls=31,
        last_rows_persisted=412,
        next_eligible_iteration=3,
        state_artifact_run_id="29460000000",
        state_artifact_name=(
            "extraction-lane-recovery-chain-"
            "historical-game-box-score-summary-no-season-type-2024-2024-run-"
            "29460000000-attempt-1"
        ),
        state_artifact_digest="a" * 64,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "auth-rejection.json").write_text(
        json.dumps(_restored_auth_rejection_metadata(lane)) + "\n",
        encoding="utf-8",
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        expected_chain_id=TEST_CHAIN_ID,
        expected_source_sha=TEST_SOURCE_SHA,
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
    assert summary["active_lane_count"] == 1
    assert summary["deferred_lane_count"] == 1
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 1
    assert summary["failure_reason_counts"] == {"vpn_auth_failure": 1}
    assert summary["failure_class_counts"] == {"vpn_egress": 1}
    assert summary["pipeline_failure_retry_count"] == 0


@pytest.mark.parametrize("progress_field", ["completed_calls", "rows_persisted"])
def test_restored_auth_rejection_with_new_progress_is_not_circuit_opening(
    tmp_path: Path,
    progress_field: str,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=0,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        attempt_count=3,
        last_completed_calls=31,
        last_rows_persisted=412,
        state_artifact_run_id="29460000000",
        state_artifact_name=(
            "extraction-lane-recovery-chain-"
            "historical-game-box-score-summary-no-season-type-2024-2024-run-"
            "29460000000-attempt-1"
        ),
        state_artifact_digest="a" * 64,
    )
    payload = _restored_auth_rejection_metadata(lane)
    payload["progress"][progress_field] += 1
    payload["progress"]["fingerprint"] = _hash_payload(
        {
            "completed_calls": payload["progress"]["completed_calls"],
            "rows_persisted": payload["progress"]["rows_persisted"],
        }
    )
    payload["telemetry"][progress_field] += 1
    payload["telemetry"]["db_telemetry"][progress_field] += 1
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "progressed-auth-rejection.json").write_text(
        json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    resume_kwargs = {
        "attempted_lane_ids": frozenset({lane.lane_id}),
        "expected_chain_id": TEST_CHAIN_ID,
        "expected_source_sha": TEST_SOURCE_SHA,
    }
    with pytest.raises(ValueError, match="invalid-vpn-auth-rejection-metadata"):
        build_resume_manifest([lane], metadata_dir, **resume_kwargs)

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane], metadata_dir, allow_pipeline_failures=True, **resume_kwargs
    )

    assert next_lanes[0].attempt_count == lane.attempt_count + 1
    assert next_lanes[0].state_artifact_run_id == lane.state_artifact_run_id
    assert next_lanes[0].state_artifact_name == lane.state_artifact_name
    assert next_lanes[0].state_artifact_digest == lane.state_artifact_digest
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 0
    assert summary["failure_reason_counts"] == {"invalid-vpn-auth-rejection-metadata": 1}
    assert summary["failure_class_counts"] == {"runner_infrastructure": 1}


def test_build_resume_manifest_rejects_unattested_auth_circuit_deferral(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2023-2023",
        lane_index=0,
        lane_name="Historical game 2023",
        lane_kind="historical",
        season_start=2023,
        season_end=2023,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        attempt_count=1,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "unattested-circuit.json",
        lane_id=lane.lane_id,
        status="needs_resume",
        raw_status="vpn_auth_circuit_open",
        failure_class="vpn_egress",
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
    )

    assert next_lanes[0].attempt_count == lane.attempt_count + 1
    assert summary["vpn_auth_circuit_deferred_lane_count"] == 0
    assert summary["vpn_auth_circuit_check_failed_lane_count"] == 0
    assert summary["failure_class_counts"] == {"runner_infrastructure": 1}


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("metadata_schema_version", 2),
        ("metadata_schema_version", 4),
        ("chain_id", "other-chain"),
        ("source_sha", "b" * 40),
        ("coverage_units_hash", "c" * 64),
        ("lane_index", "99"),
        ("lane_index", []),
        ("endpoints", ["other_endpoint"]),
        ("season_start", []),
        ("extract_status", "extract-error"),
        ("progress", {"completed_calls": 1, "rows_persisted": 0}),
        ("telemetry", {}),
        ("state_artifact", {}),
        ("vpn", {}),
    ],
)
def test_build_resume_manifest_rejects_stale_or_malformed_auth_circuit_deferral(
    tmp_path: Path,
    field: str,
    invalid_value: object,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2022-2022",
        lane_index=3,
        lane_name="Historical game 2022",
        lane_kind="historical",
        season_start=2022,
        season_end=2022,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        attempt_count=2,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    payload = _auth_coordination_metadata(lane)
    payload[field] = invalid_value
    (metadata_dir / "circuit.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")

    next_lanes, _next_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        expected_chain_id=TEST_CHAIN_ID,
        expected_source_sha=TEST_SOURCE_SHA,
    )

    assert next_lanes[0].attempt_count == lane.attempt_count + 1
    assert summary["vpn_auth_circuit_deferred_lane_count"] == 0
    assert summary["vpn_auth_circuit_check_failed_lane_count"] == 0
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 0
    assert summary["failure_reason_counts"] == {"invalid-vpn-auth-circuit-metadata": 1}
    assert summary["failure_class_counts"] == {"runner_infrastructure": 1}


@pytest.mark.parametrize("missing_field", ["progress", "telemetry", "state_artifact", "vpn"])
def test_build_resume_manifest_rejects_missing_auth_coordination_contract_fields(
    tmp_path: Path,
    missing_field: str,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2022-2022",
        lane_index=0,
        lane_name="Historical game 2022",
        lane_kind="historical",
        season_start=2022,
        season_end=2022,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    payload = _auth_coordination_metadata(lane)
    payload.pop(missing_field)
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "circuit.json").write_text(
        json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    next_lanes, _next_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        expected_chain_id=TEST_CHAIN_ID,
        expected_source_sha=TEST_SOURCE_SHA,
    )

    assert next_lanes[0].attempt_count == 1
    assert summary["vpn_auth_circuit_deferred_lane_count"] == 0
    assert summary["vpn_auth_circuit_check_failed_lane_count"] == 0
    assert summary["failure_reason_counts"] == {"invalid-vpn-auth-circuit-metadata": 1}


def test_auth_circuit_lookup_failure_retries_without_opening_provider_circuit(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=0,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        attempt_count=3,
    )
    payload = _auth_coordination_metadata(
        lane,
        raw_status="vpn_auth_circuit_check_failed",
        failure_class="runner_infrastructure",
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "check-failed.json").write_text(
        json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    next_lanes, _next_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        expected_chain_id=TEST_CHAIN_ID,
        expected_source_sha=TEST_SOURCE_SHA,
    )

    assert next_lanes[0].attempt_count == 4
    assert next_lanes[0].last_failure_class == "runner_infrastructure"
    assert summary["vpn_auth_circuit_deferred_lane_count"] == 0
    assert summary["vpn_auth_circuit_check_failed_lane_count"] == 1
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 0
    assert summary["failure_reason_counts"] == {"vpn_auth_circuit_check_failed": 1}


@pytest.mark.parametrize(
    ("raw_status", "failure_class"),
    [
        ("vpn_auth_circuit_open", "application"),
        ("vpn_auth_circuit_check_failed", "application"),
    ],
)
def test_malformed_reserved_circuit_status_uses_infrastructure_retry_budget(
    tmp_path: Path,
    raw_status: str,
    failure_class: str,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=0,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    payload = _auth_coordination_metadata(
        lane,
        raw_status=raw_status,
        failure_class=failure_class,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "malformed-circuit.json").write_text(
        json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    next_lanes, _next_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        expected_chain_id=TEST_CHAIN_ID,
        expected_source_sha=TEST_SOURCE_SHA,
    )

    assert next_lanes[0].attempt_count == 1
    assert next_lanes[0].last_failure_class == "runner_infrastructure"
    assert summary["blocked_lane_count"] == 0
    assert summary["vpn_auth_circuit_deferred_lane_count"] == 0
    assert summary["vpn_auth_circuit_check_failed_lane_count"] == 0
    assert summary["failure_reason_counts"] == {"invalid-vpn-auth-circuit-metadata": 1}
    assert summary["failure_class_counts"] == {"runner_infrastructure": 1}


def test_build_resume_manifest_counts_all_already_admitted_auth_rejections(
    tmp_path: Path,
) -> None:
    lanes = [
        FullExtractionLane(
            lane_id=f"historical-game-box-score-summary-no-season-type-{year}-{year}",
            lane_index=index,
            lane_name=f"Historical game {year}",
            lane_kind="historical",
            season_start=year,
            season_end=year,
            patterns=("game",),
            endpoints=("box_score_summary",),
            timeout_seconds=7200,
        )
        for index, year in enumerate((2023, 2024))
    ]
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    for lane in lanes:
        payload = _auth_coordination_metadata(
            lane,
            raw_status="vpn_auth_failure",
            failure_class="vpn_egress",
        )
        (metadata_dir / f"{lane.lane_id}.json").write_text(
            json.dumps(payload) + "\n",
            encoding="utf-8",
        )

    next_lanes, _next_state, summary = build_resume_manifest(
        lanes,
        metadata_dir,
        attempted_lane_ids=frozenset(lane.lane_id for lane in lanes),
        expected_chain_id=TEST_CHAIN_ID,
        expected_source_sha=TEST_SOURCE_SHA,
    )

    assert len(next_lanes) == 2
    assert summary["vpn_auth_circuit_deferred_lane_count"] == 0
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 2
    assert summary["failure_reason_counts"] == {"vpn_auth_failure": 2}


def test_build_resume_manifest_rejects_unproven_auth_rejection_for_circuit_open(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=0,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    payload = _auth_coordination_metadata(
        lane,
        raw_status="vpn_auth_failure",
        failure_class="vpn_egress",
    )
    payload["chain_id"] = "other-chain"
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "invalid-rejection.json").write_text(
        json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    next_lanes, _next_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        expected_chain_id=TEST_CHAIN_ID,
        expected_source_sha=TEST_SOURCE_SHA,
    )

    assert next_lanes[0].last_failure_class == "runner_infrastructure"
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 0
    assert summary["failure_reason_counts"] == {"invalid-vpn-auth-rejection-metadata": 1}


def test_build_resume_manifest_rejects_auth_rejection_with_nonzero_work(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=0,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    payload = _auth_coordination_metadata(
        lane,
        raw_status="vpn_auth_failure",
        failure_class="vpn_egress",
    )
    payload["telemetry"]["planned_calls"] = 17
    payload["telemetry"]["failed_calls"] = 2
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "nonzero-auth-rejection.json").write_text(
        json.dumps(payload) + "\n",
        encoding="utf-8",
    )

    next_lanes, _next_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        expected_chain_id=TEST_CHAIN_ID,
        expected_source_sha=TEST_SOURCE_SHA,
    )

    assert next_lanes[0].attempt_count == 1
    assert next_lanes[0].last_failure_class == "runner_infrastructure"
    assert summary["vpn_auth_circuit_rejection_lane_count"] == 0
    assert summary["failure_reason_counts"] == {"invalid-vpn-auth-rejection-metadata": 1}
    assert summary["failure_class_counts"] == {"runner_infrastructure": 1}


def test_build_resume_manifest_applies_chunk_profile_to_deferred_lanes(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v2-no-season-type-1957-1960",
        lane_index=0,
        lane_name="Historical date 1957-1960",
        lane_kind="historical",
        season_start=1957,
        season_end=1960,
        patterns=("date",),
        endpoints=("scoreboard_v2",),
        timeout_seconds=5400,
        chunk_profile="standard",
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset(),
        chunk_profile="micro",
    )

    validate_manifest(next_lanes)
    assert len(next_lanes) == 4
    assert {lane.chunk_profile for lane in next_lanes} == {"micro"}
    assert all(lane.season_start == lane.season_end for lane in next_lanes)
    assert all(
        lane.parent_lane_id == "historical-date-scoreboard-v2-no-season-type-1957-1960"
        for lane in next_lanes
    )
    assert summary["split_lane_count"] == 4
    assert summary["active_lane_count"] == 4
    assert summary["deferred_lane_count"] == 4


def test_build_resume_manifest_treats_corrupt_metadata_as_missing(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-1994-1997",
        lane_index=0,
        lane_name="Historical game 1994-1997",
        lane_kind="historical",
        season_start=1994,
        season_end=1997,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "lane-metadata.json").write_text("", encoding="utf-8")

    next_lanes, _next_chain_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        attempted_lane_ids=frozenset({lane.lane_id}),
        allow_missing_attempted_metadata=True,
    )

    assert next_lanes[0].lane_id == lane.lane_id
    assert next_lanes[0].last_failure_reason == "missing-metadata"
    assert summary["active_lane_count"] == 1
    assert summary["outcome_counts"] == {"needs_resume": 1}
    assert summary["failure_reason_counts"] == {"missing-metadata": 1}


def test_resume_manifest_allows_legacy_completed_lane_spans(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v3-no-season-type-1946-1957",
        lane_index=0,
        lane_name="Historical date 1946-1957",
        lane_kind="historical",
        season_start=1946,
        season_end=1957,
        patterns=("date",),
        endpoints=("scoreboard_v3",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id="historical-date-scoreboard-v3-no-season-type-1946-1957",
        status="complete",
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    validate_manifest(next_lanes)
    assert len(next_lanes) == 1
    assert next_lanes[0].resume_only is True
    assert summary["resume_only_lane_count"] == 1


def test_resume_manifest_reshards_legacy_oversized_failed_lanes(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-season-no-season-type-1946-1963",
        lane_index=0,
        lane_name="Historical season 1946-1963",
        lane_kind="historical",
        season_start=1946,
        season_end=1963,
        patterns=("season",),
        timeout_seconds=7200,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id="historical-season-no-season-type-1946-1963",
        status="extract-error",
    )

    with pytest.raises(ValueError, match="Pipeline-failure lane outcomes"):
        build_resume_manifest([lane], metadata_dir)


def test_validate_manifest_allows_explicit_direct_active_lane() -> None:
    validate_manifest(
        [
            FullExtractionLane(
                lane_id="reference-player",
                lane_index=0,
                lane_name="Reference Player",
                lane_kind="reference",
                season_start=None,
                season_end=None,
                patterns=("player",),
                use_vpn=False,
                resume_only=False,
                timeout_seconds=3600,
            )
        ]
    )


def test_validate_manifest_rejects_explicit_excluded_endpoint() -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-player-vs-player-2024",
        lane_index=0,
        lane_name="Player vs player",
        lane_kind="cross_product",
        season_start=2024,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=("Regular Season",),
        endpoints=("player_vs_player",),
        timeout_seconds=7_200,
    )

    with pytest.raises(ValueError, match="endpoints are excluded.*player_vs_player"):
        validate_manifest([lane])


def test_validate_manifest_rejects_discovery_owned_endpoint_lane() -> None:
    lane = FullExtractionLane(
        lane_id="historical-league-game-log-2024",
        lane_index=0,
        lane_name="League game log",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("season",),
        season_types=("Regular Season",),
        endpoints=("league_game_log",),
        timeout_seconds=7_200,
    )

    with pytest.raises(ValueError, match="owned by discovery_seed"):
        validate_manifest([lane])


def test_validate_manifest_rejects_alias_pattern_without_runtime_route() -> None:
    lane = FullExtractionLane(
        lane_id="historical-player-game-logs-v2-2024",
        lane_index=0,
        lane_name="Player game logs",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("season",),
        season_types=("Regular Season",),
        endpoints=("player_game_logs_v2",),
        timeout_seconds=7_200,
    )

    with pytest.raises(ValueError, match="no executable planner route.*season"):
        validate_manifest([lane])


def test_validate_manifest_rejects_mixed_supported_and_unsupported_patterns() -> None:
    lane = FullExtractionLane(
        lane_id="historical-player-game-logs-v2-mixed-2024",
        lane_index=0,
        lane_name="Player game logs mixed",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("season", "player_season"),
        season_types=("Regular Season",),
        endpoints=("player_game_logs_v2",),
        timeout_seconds=7_200,
    )

    with pytest.raises(ValueError, match="no executable planner route.*season"):
        validate_manifest([lane])


def test_validate_manifest_rejects_unknown_pattern_on_endpointless_lane() -> None:
    lane = FullExtractionLane(
        lane_id="historical-unknown-pattern-2024",
        lane_index=0,
        lane_name="Unknown pattern",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("not_a_pattern",),
        endpoints=(),
        timeout_seconds=7_200,
    )

    with pytest.raises(ValueError, match="unknown extraction patterns: not_a_pattern"):
        validate_manifest([lane])


def test_validate_manifest_rejects_duplicate_lane_ids() -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )

    with pytest.raises(ValueError, match="duplicate lane_id values: reference-static"):
        validate_manifest([lane, replace(lane, lane_index=1)])


def test_metadata_reader_prefers_canonical_lane_metadata_over_attestation(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "extraction-lane-metadata-chain-lane-1"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "lane-metadata.json").write_text(
        json.dumps({"lane_id": "lane-1", "status": "pipeline_failure"}),
        encoding="utf-8",
    )
    (artifact_dir / "lane-state-attestation.json").write_text(
        json.dumps({"lane_id": "lane-1", "schema_version": 1}),
        encoding="utf-8",
    )

    assert _metadata_by_lane(tmp_path) == {
        "lane-1": {"lane_id": "lane-1", "status": "pipeline_failure"}
    }


def test_checkpoint_rejects_duplicate_manifest_lane_ids_before_indexing(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload([lane, replace(lane, lane_index=1)])),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate lane_id values: reference-static"):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=tmp_path / "metadata",
            lane_artifacts_dir=tmp_path / "lanes",
            output_dir=tmp_path / "checkpoint",
            report_path=tmp_path / "checkpoint-report.json",
        )


def test_build_resume_manifest_preserves_and_expands_quarantine_state(tmp_path: Path) -> None:
    rows = [
        _support_row("franchise_history", ["static"], None),
        _support_row("common_player_info", ["player"], None),
    ]
    lanes = build_default_manifest(support_matrix_rows=rows)
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    (metadata_dir / "reference-static.json").write_text(
        json.dumps(
            {
                "lane_id": "reference-static",
                "status": "extract-timeout",
                "vpn": {
                    "failed_servers": [
                        "us123.nordvpn.com",
                        "us456.nordvpn.com",
                        "us123.nordvpn.com",
                    ],
                },
                "telemetry": {"rows_persisted": 3, "failed_calls": 0},
                "state_artifact": {
                    "run_id": "12345",
                    "name": "extraction-lane-chain-reference-static",
                    "sha256": "a" * 64,
                    "required": True,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_metadata(
        metadata_dir / "reference-player.json",
        lane_id="reference-player",
        status="complete",
    )

    next_lanes, next_chain_state, summary = build_resume_manifest(
        lanes,
        metadata_dir,
        chain_state=FullExtractionChainState(vpn_quarantined_servers=("us111.nordvpn.com",)),
    )

    assert next_chain_state == FullExtractionChainState(
        vpn_quarantined_servers=(
            "us111.nordvpn.com",
            "us123.nordvpn.com",
            "us456.nordvpn.com",
        )
    )
    assert summary["vpn_quarantined_server_count"] == 3
    by_id = {lane.lane_id: lane for lane in next_lanes}
    assert by_id["reference-player"].resume_only is True
    assert by_id["reference-static"].last_failure_reason == "needs_resume"


def test_manifest_payload_and_normalize_manifest_preserve_chain_state() -> None:
    blocked_lane = FullExtractionLane(
        lane_id="historical-video-details-no-season-type-1946-1947",
        lane_index=1,
        lane_name="Historical video details 1946-1947",
        lane_kind="historical",
        season_start=1946,
        season_end=1947,
        patterns=("player_team_season",),
        endpoints=("video_details",),
        timeout_seconds=1,
    )
    pending_row = _contract_blocked_row(blocked_lane)
    pending_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [pending_row],
    }
    payload = manifest_payload(
        [
            FullExtractionLane(
                lane_id="reference-static",
                lane_index=0,
                lane_name="Reference Static",
                lane_kind="reference",
                season_start=None,
                season_end=None,
                patterns=("static",),
                timeout_seconds=1800,
            )
        ],
        chain_state=FullExtractionChainState(
            vpn_quarantined_servers=("us101.nordvpn.com", "us202.nordvpn.com"),
            artifact_run_ids=("12345",),
            pending_contract_blocked_evidence=(pending_row,),
            pending_contract_blocked_evidence_sha256=_hash_payload(pending_evidence),
        ),
        chain_id=TEST_CHAIN_ID,
        workflow_source_sha=TEST_SOURCE_SHA.upper(),
    )

    manifest = normalize_manifest(payload)

    assert payload["chain_state"]["pending_contract_blocked_evidence"] == [pending_row]
    assert payload["chain_state"]["pending_contract_blocked_evidence_sha256"] == _hash_payload(
        pending_evidence
    )
    assert manifest.chain_state == FullExtractionChainState(
        vpn_quarantined_servers=("us101.nordvpn.com", "us202.nordvpn.com"),
        artifact_run_ids=("12345",),
        iteration_budget=8,
        pending_contract_blocked_evidence=(pending_row,),
        pending_contract_blocked_evidence_sha256=_hash_payload(pending_evidence),
    )
    assert manifest.lanes[0].lane_id == "reference-static"
    assert manifest.matrix_lane_ids == frozenset({"reference-static"})
    assert manifest.chain_id == TEST_CHAIN_ID
    assert manifest.workflow_source_sha == TEST_SOURCE_SHA

    redispatch = redispatch_manifest_payload(
        list(manifest.lanes),
        chain_state=manifest.chain_state,
        chain_id=manifest.chain_id,
        workflow_source_sha=manifest.workflow_source_sha,
    )
    redispatch_manifest = normalize_manifest(redispatch)
    assert redispatch_manifest.chain_id == TEST_CHAIN_ID
    assert redispatch_manifest.workflow_source_sha == TEST_SOURCE_SHA


def test_manifest_payload_caps_github_matrix_to_active_wave() -> None:
    lanes = [
        FullExtractionLane(
            lane_id="reference-static",
            lane_index=0,
            lane_name="Reference Static",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("static",),
            resume_only=True,
            timeout_seconds=1800,
        ),
        FullExtractionLane(
            lane_id="reference-player-01",
            lane_index=1,
            lane_name="Reference Player 1",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("player",),
            timeout_seconds=3600,
        ),
        FullExtractionLane(
            lane_id="reference-player-02",
            lane_index=2,
            lane_name="Reference Player 2",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("player",),
            timeout_seconds=3600,
        ),
    ]

    payload = manifest_payload(lanes, max_matrix_lanes=1)

    assert payload["lane_count"] == 3
    assert payload["active_lane_count"] == 2
    assert payload["resume_only_lane_count"] == 1
    assert payload["matrix_lane_count"] == 1
    assert payload["deferred_lane_count"] == 1
    assert [row["lane_id"] for row in payload["github_matrix"]["include"]] == [
        "reference-player-01"
    ]


@pytest.mark.parametrize("chunk_profile", ["standard", "balanced-small"])
def test_v3_scheduler_guarantees_weighted_queue_slots(chunk_profile: str) -> None:
    lanes: list[FullExtractionLane] = []
    queue_specs = {
        "fresh": (20, {}),
        "partial": (10, {"attempt_count": 1, "last_completed_calls": 2}),
        "retry": (
            10,
            {
                "attempt_count": 1,
                "last_failure_reason": "pipeline_failure",
                "last_failure_class": "response_contract",
            },
        ),
        "infrastructure": (
            5,
            {
                "attempt_count": 1,
                "last_failure_reason": "missing-metadata",
                "last_failure_class": "runner_infrastructure",
            },
        ),
    }
    for queue_name, (count, overrides) in queue_specs.items():
        for index in range(count):
            lanes.append(
                FullExtractionLane(
                    lane_id=f"{queue_name}-{index:02d}",
                    lane_index=len(lanes),
                    lane_name=f"{queue_name} {index}",
                    lane_kind="historical",
                    season_start=2020,
                    season_end=2020,
                    patterns=("season",),
                    endpoints=(f"endpoint_{queue_name}_{index}",),
                    timeout_seconds=3600,
                    **overrides,
                )
            )

    scheduled = _schedule_lanes(
        lanes,
        chunk_profile=chunk_profile,
        max_matrix_lanes=10,
    )
    first_wave = scheduled[:10]

    assert sum(lane.lane_id.startswith("fresh-") for lane in first_wave) == 5
    assert sum(lane.lane_id.startswith("partial-") for lane in first_wave) == 3
    assert sum(lane.lane_id.startswith("retry-") for lane in first_wave) == 1
    assert sum(lane.lane_id.startswith("infrastructure-") for lane in first_wave) == 1


def test_scheduler_interleaves_endpoint_homogeneous_six_runner_windows() -> None:
    lanes = [
        FullExtractionLane(
            lane_id=f"{endpoint_name}-{index:03d}",
            lane_index=lane_index,
            lane_name=f"{endpoint_name} {index}",
            lane_kind="cross_product",
            season_start=2004 + index,
            season_end=2004 + index,
            patterns=("player_team_season",),
            season_types=("Regular Season",),
            endpoints=(endpoint_name,),
            timeout_seconds=6300,
        )
        for lane_index, (endpoint_name, index) in enumerate(
            [
                *(("video_details_asset", index) for index in range(64)),
                *(("video_details", index) for index in range(64)),
            ]
        )
    ]
    profiles = {
        endpoint_name: EndpointWorkloadProfile(
            endpoint_name=endpoint_name,
            endpoint_family="video",
            throughput_tier="discovery_bound_cross_product",
            avg_duration_seconds=0.0,
            p95_duration_seconds=0.0,
            retry_rate=0.0,
            error_rate=0.0,
            avg_rows_per_request=0.0,
            lane_cost=lane_cost,
            reference_batch_cost=lane_cost,
            preferred_max_span=1,
        )
        for endpoint_name, lane_cost in (
            ("video_details_asset", 10.0),
            ("video_details", 5.0),
        )
    }

    scheduled = _schedule_lanes(
        lanes,
        chunk_profile="standard",
        planning_snapshot=WorkloadPlanningSnapshot(
            endpoint_profiles=profiles,
            cross_product_pair_counts={},
        ),
        max_matrix_lanes=128,
    )

    assert {lane.lane_id for lane in scheduled} == {lane.lane_id for lane in lanes}
    assert _coverage_fingerprint(scheduled) == _coverage_fingerprint(lanes)
    assert {lane.endpoints for lane in scheduled[:6]} == {
        ("video_details_asset",),
        ("video_details",),
    }
    assert [lane.endpoints for lane in scheduled[:6]] == [
        *(("video_details_asset",) for _ in range(5)),
        ("video_details",),
    ]
    last_asset_position = max(
        index for index, lane in enumerate(scheduled) if lane.endpoints == ("video_details_asset",)
    )
    assert all(
        len({lane.endpoints for lane in scheduled[start : start + 6]}) > 1
        for start in range(last_asset_position + 1)
        if start + 6 <= len(scheduled)
    )
    assert [lane.lane_id for lane in scheduled if lane.endpoints == ("video_details_asset",)] == [
        f"video_details_asset-{index:03d}" for index in range(64)
    ]


def test_scheduler_rotation_persists_weighted_fairness_across_short_resume_waves(
    tmp_path: Path,
) -> None:
    lanes: list[FullExtractionLane] = []
    queue_specs = {
        "fresh": (20, {}),
        "partial": (12, {"attempt_count": 1, "last_completed_calls": 1}),
        "retry": (
            4,
            {
                "attempt_count": 1,
                "last_failure_reason": "response-contract",
                "last_failure_class": "response_contract",
            },
        ),
        "infrastructure": (
            4,
            {
                "attempt_count": 1,
                "last_failure_reason": "missing-metadata",
                "last_failure_class": "runner_infrastructure",
            },
        ),
    }
    for queue_name, (count, overrides) in queue_specs.items():
        for index in range(count):
            lanes.append(
                FullExtractionLane(
                    lane_id=f"{queue_name}-{index:02d}",
                    lane_index=len(lanes),
                    lane_name=f"{queue_name} {index}",
                    lane_kind="historical",
                    season_start=2020,
                    season_end=2020,
                    patterns=("season",),
                    endpoints=(f"endpoint_{queue_name}_{index}",),
                    timeout_seconds=3600,
                    **overrides,
                )
            )

    scheduled = _schedule_lanes(
        lanes,
        chunk_profile="standard",
        max_matrix_lanes=3,
    )
    chain_state = FullExtractionChainState()
    selected_queue_names: list[str] = []
    observed_cursors: list[int] = []
    for iteration in range(1, 5):
        payload = manifest_payload(
            scheduled,
            chain_state=chain_state,
            max_matrix_lanes=3,
            current_iteration=iteration,
        )
        manifest = normalize_manifest(payload)
        observed_cursors.append(manifest.chain_state.scheduler_rotation_cursor)
        matrix_lane_ids = [str(row["lane_id"]) for row in payload["github_matrix"]["include"]]
        selected_queue_names.extend(lane_id.split("-", 1)[0] for lane_id in matrix_lane_ids)
        metadata_dir = tmp_path / f"metadata-{iteration}"
        metadata_dir.mkdir()
        for lane_id in matrix_lane_ids:
            _write_metadata(
                metadata_dir / f"{lane_id}.json",
                lane_id=lane_id,
                status="complete",
            )
        scheduled, chain_state, _summary = build_resume_manifest(
            list(manifest.lanes),
            metadata_dir,
            chain_state=manifest.chain_state,
            attempted_lane_ids=manifest.matrix_lane_ids,
            current_iteration=iteration,
            max_matrix_lanes=3,
        )

    first_cycle = selected_queue_names[:10]
    assert observed_cursors == [0, 3, 6, 9]
    assert chain_state.scheduler_rotation_cursor == 2
    assert first_cycle.count("fresh") == 5
    assert first_cycle.count("partial") == 3
    assert first_cycle.count("retry") == 1
    assert first_cycle.count("infrastructure") == 1


def test_manifest_v3_computes_capacity_iteration_budget() -> None:
    lanes = [
        FullExtractionLane(
            lane_id=f"lane-{index:03d}",
            lane_index=index,
            lane_name=f"Lane {index}",
            lane_kind="historical",
            season_start=2020,
            season_end=2020,
            patterns=("season",),
            timeout_seconds=3600,
        )
        for index in range(100)
    ]

    payload = manifest_payload(lanes, max_matrix_lanes=10, current_iteration=7)

    assert payload["manifest_version"] == 3
    assert payload["minimum_remaining_wave_count"] == 10
    assert payload["suggested_remaining_wave_count"] == 80
    assert payload["iteration_budget"] == 86
    assert payload["scheduler_diagnostics"]["queue_counts"] == {
        "fresh": 100,
        "partial": 0,
        "retry": 0,
        "infrastructure": 0,
    }


def test_manifest_v3_never_extends_an_existing_auto_iteration_budget() -> None:
    lane = FullExtractionLane(
        lane_id="lane-001",
        lane_index=0,
        lane_name="Lane 1",
        lane_kind="historical",
        season_start=2020,
        season_end=2020,
        patterns=("season",),
        timeout_seconds=3600,
    )

    payload = manifest_payload(
        [lane],
        chain_state=FullExtractionChainState(iteration_budget=8),
        current_iteration=8,
    )

    assert payload["active_lane_count"] == 1
    assert payload["iteration_budget"] == 8


def test_iteration_budget_accounts_for_matrix_wide_retry_credits() -> None:
    lanes = [
        FullExtractionLane(
            lane_id=f"reference-{index:03d}",
            lane_index=index,
            lane_name=f"Reference {index}",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("static",),
            timeout_seconds=1800,
        )
        for index in range(512)
    ]

    payload = manifest_payload(lanes, max_matrix_lanes=256)

    assert payload["minimum_remaining_wave_count"] == 2
    assert payload["scheduler_diagnostics"]["remaining_dispatch_credits"] == 4096
    assert payload["scheduler_diagnostics"]["maximum_retry_depth"] == 8
    assert payload["suggested_remaining_wave_count"] == 16
    assert payload["iteration_budget"] == 16


def test_timeout_progress_retry_budget_is_bounded() -> None:
    assert _retry_budget_exhausted("timeout_progress", 7) is False
    assert _retry_budget_exhausted("timeout_progress", 8) is True


def test_alternating_retry_classes_hit_cumulative_zero_progress_ceiling(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )

    for result_index in range(12):
        metadata_dir = tmp_path / f"metadata-{result_index + 1}"
        metadata_dir.mkdir()
        raw_status = "vpn_network_error" if result_index % 2 == 0 else "cancelled"
        _write_metadata(
            metadata_dir / "lane.json",
            lane_id=lane.lane_id,
            status="pipeline_failure",
            raw_status=raw_status,
        )
        if result_index == 11:
            with pytest.raises(ValueError, match="chain safety cap"):
                build_resume_manifest(
                    [lane],
                    metadata_dir,
                    current_iteration=result_index + 1,
                )
            break

        next_lanes, _chain_state, _summary = build_resume_manifest(
            [lane],
            metadata_dir,
            current_iteration=result_index + 1,
        )
        lane = next_lanes[0]
        assert lane.attempt_count == result_index + 1
        assert lane.zero_progress_streak == result_index + 1
        assert lane.class_failure_streak == 1


def test_retry_budget_is_checked_before_timeout_split(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-budget-2020-2023",
        lane_index=0,
        lane_name="Historical game budget 2020-2023",
        lane_kind="historical",
        season_start=2020,
        season_end=2023,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
        class_failure_streak=7,
        last_failure_class="timeout_progress",
        last_rows_persisted=1,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "lane.json",
        lane_id=lane.lane_id,
        status="extract-timeout",
        rows_persisted=1,
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    with pytest.raises(ValueError, match="chain safety cap"):
        build_resume_manifest([lane], metadata_dir)


def test_zero_row_completed_calls_are_resumable_only_with_attested_state() -> None:
    payload = {
        "status": "extract-error",
        "raw_status": "extract-error",
        "vpn": {"status": "connected"},
        "progress": {"completed_calls": 12, "rows_persisted": 0},
        "telemetry": {
            "rows_persisted": 0,
            "journal_skips": 0,
            "db_telemetry": {"running_calls": 0},
        },
        "state_artifact": {
            "run_id": "12345",
            "name": "extraction-lane-chain-lane",
            "sha256": "a" * 64,
            "required": True,
        },
    }

    assert lane_outcome_from_metadata(payload) == "needs_resume"

    payload.pop("state_artifact")
    assert lane_outcome_from_metadata(payload) == "pipeline_failure"


def test_complete_metadata_without_durable_receipt_remains_retryable(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static-receipt",
        lane_index=0,
        lane_name="Reference static receipt",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    payload = {
        "lane_id": lane.lane_id,
        "status": "complete",
        "raw_status": "complete",
        "vpn": {},
        "state_artifact": {
            "run_id": "12345",
            "name": f"extraction-lane-chain-{lane.lane_id}",
            "sha256": "a" * 64,
            "attested": True,
            "uploaded": False,
        },
    }
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "lane.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert lane_outcome_from_metadata(payload) == "pipeline_failure"

    lanes, _chain_state, summary = build_resume_manifest(
        [lane],
        metadata_dir,
        allow_pipeline_failures=True,
    )

    assert summary["active_lane_count"] == 1
    assert summary["resume_only_lane_count"] == 0
    assert summary["failure_class_counts"] == {"runner_infrastructure": 1}
    assert lanes[0].resume_only is False
    assert lanes[0].last_failure_class == "runner_infrastructure"
    assert lanes[0].state_artifact_run_id == ""


def test_scheduler_uses_configured_matrix_batch_for_planned_waves() -> None:
    rows = [_support_row("scoreboard_v2", ["date"], 1946)]

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        chunk_profile="micro",
        max_matrix_lanes=10,
    )
    payload = manifest_payload(lanes, max_matrix_lanes=10)

    assert payload["planned_wave_count"] == math.ceil(len(lanes) / 10)
    assert all(lane.planned_wave == lane.lane_index // 10 for lane in lanes)


def test_redispatch_manifest_payload_round_trips() -> None:
    lanes = [
        FullExtractionLane(
            lane_id="reference-player",
            lane_index=7,
            lane_name="Reference Player 3/15",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("player",),
            endpoints=("common_player_info", "player_profile_v2"),
            resume_only=True,
            timeout_seconds=4_200,
            failure_streak=2,
            last_failure_reason="extract-timeout",
        )
    ]
    chain_state = FullExtractionChainState(
        vpn_quarantined_servers=("us101.nordvpn.com", "us202.nordvpn.com"),
        artifact_run_ids=("12345", "23456"),
    )

    redispatch_payload = redispatch_manifest_payload(lanes, chain_state=chain_state)
    manifest = normalize_manifest(redispatch_payload)

    assert "pending_contract_blocked_evidence" not in redispatch_payload["chain_state"]
    assert "pending_contract_blocked_evidence_sha256" not in redispatch_payload["chain_state"]
    assert manifest.chain_state == chain_state
    assert manifest.lanes[0].coverage_units_hash
    assert manifest.lanes == (
        FullExtractionLane(
            lane_id="reference-player",
            lane_index=0,
            lane_name="reference-player",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("player",),
            season_types=(),
            endpoints=("common_player_info", "player_profile_v2"),
            use_vpn=True,
            resume_only=True,
            timeout_seconds=4_200,
            failure_streak=2,
            last_failure_reason="extract-timeout",
            coverage_units_hash=manifest.lanes[0].coverage_units_hash,
            attempt_count=1,
            class_failure_streak=2,
            last_failure_class="timeout_stalled",
        ),
    )


def test_redispatch_manifest_payload_preserves_non_default_use_vpn() -> None:
    payload = redispatch_manifest_payload(
        [
            FullExtractionLane(
                lane_id="reference-static",
                lane_index=0,
                lane_name="Reference Static",
                lane_kind="reference",
                season_start=None,
                season_end=None,
                patterns=("static",),
                use_vpn=False,
                timeout_seconds=1_800,
            )
        ]
    )

    manifest = normalize_manifest(payload)

    assert payload["lanes"][0]["use_vpn"] is False
    assert manifest.lanes[0].use_vpn is False


def test_redispatch_manifest_payload_is_smaller_than_full_manifest() -> None:
    lanes = [
        FullExtractionLane(
            lane_id="reference-player",
            lane_index=7,
            lane_name="Reference Player 3/15",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("player",),
            endpoints=("common_player_info", "player_profile_v2"),
            resume_only=True,
            timeout_seconds=4_200,
            failure_streak=2,
            last_failure_reason="extract-timeout",
        )
    ]

    full_payload = manifest_payload(lanes)
    redispatch_payload = redispatch_manifest_payload(lanes)

    assert "github_matrix" not in redispatch_payload
    assert "lane_name" not in redispatch_payload["lanes"][0]
    assert len(json.dumps(redispatch_payload, separators=(",", ":"))) < len(
        json.dumps(full_payload, separators=(",", ":"))
    )


def test_workflow_dispatch_manifest_json_guard_rejects_oversized_payload() -> None:
    with pytest.raises(ValueError, match="too large for workflow_dispatch"):
        validate_workflow_dispatch_manifest_json("x" * 61_000)


def test_metadata_audit_summarizes_status_and_zero_row_lanes(tmp_path: Path) -> None:
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    contract_lane = FullExtractionLane(
        lane_id="historical-game-box-score-misc-no-season-type-1995-1995",
        lane_index=0,
        lane_name="Historical game box score misc 1995-1995",
        lane_kind="historical",
        season_start=1995,
        season_end=1995,
        patterns=("game",),
        endpoints=("box_score_misc",),
    )
    support_rules = [
        rule.to_dict()
        for rule in contract_blocking_rules_for_lane(
            endpoints=contract_lane.endpoints,
            patterns=contract_lane.patterns,
            season_start=contract_lane.season_start,
            season_end=contract_lane.season_end,
        )
    ]
    (metadata_dir / "complete.json").write_text(
        json.dumps(
            {
                "lane_id": "reference-static",
                "lane_kind": "reference",
                "status": "complete",
                "vpn_status": "connected",
                "vpn": {},
                "endpoints": ["common_team_years"],
                "state_artifact": {
                    "run_id": "12345",
                    "name": "extraction-lane-chain-reference-static",
                    "sha256": "a" * 64,
                    "attested": True,
                    "uploaded": True,
                    "artifact_id": TEST_ARTIFACT_ID,
                    "artifact_digest": TEST_ARTIFACT_DIGEST,
                },
                "telemetry": {
                    "rows_persisted": 12,
                    "failed_calls": 0,
                    "journal_skips": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    (metadata_dir / "timeout.json").write_text(
        json.dumps(
            {
                "lane_id": contract_lane.lane_id,
                "lane_kind": contract_lane.lane_kind,
                "status": "contract_blocked",
                "raw_status": "extract-error",
                "vpn_status": "connected",
                "vpn": {},
                "endpoints": list(contract_lane.endpoints),
                "patterns": list(contract_lane.patterns),
                "season_start": str(contract_lane.season_start),
                "season_end": str(contract_lane.season_end),
                "season_types": list(contract_lane.season_types),
                "context_measures": list(contract_lane.context_measures),
                "coverage_units_hash": _coverage_hash_for_lane(contract_lane),
                "support_rules": support_rules,
                "telemetry": {
                    "rows_persisted": 0,
                    "failed_calls": 4,
                    "zero_row_reason": "contract_blocked",
                },
            }
        ),
        encoding="utf-8",
    )

    audit = build_metadata_audit(metadata_dir)

    assert audit["status_counts"] == {"complete": 1, "contract_blocked": 1}
    assert audit["outcome_counts"] == {"complete": 1, "contract_blocked": 1}
    assert audit["vpn_status_counts"] == {"connected": 2}
    assert audit["rows_persisted"] == 12
    assert audit["failed_calls"] == 4
    assert audit["journal_skips"] == 1
    assert audit["zero_row_lanes"] == [
        {
            "lane_id": contract_lane.lane_id,
            "status": "contract_blocked",
            "raw_status": "extract-error",
            "reason": "contract_blocked",
            "failure_class": "",
            "endpoints": ["box_score_misc"],
        }
    ]
    assert audit["contract_blocked_lanes"] == [
        {
            "lane_id": contract_lane.lane_id,
            "status": "contract_blocked",
            "kind": contract_lane.lane_kind,
            "endpoints": list(contract_lane.endpoints),
            "patterns": list(contract_lane.patterns),
            "season_start": contract_lane.season_start,
            "season_end": contract_lane.season_end,
            "season_types": list(contract_lane.season_types),
            "context_measures": list(contract_lane.context_measures),
            "coverage_units_hash": _coverage_hash_for_lane(contract_lane),
            "support_rules": support_rules,
        }
    ]
    assert audit["pipeline_failure_lanes"] == []


@pytest.mark.parametrize("tampered_field", ["support_rules", "coverage_units_hash"])
def test_metadata_audit_rejects_tampered_contract_blocked_evidence(
    tmp_path: Path,
    tampered_field: str,
) -> None:
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-misc-no-season-type-1995-1995",
        lane_index=0,
        lane_name="Historical game box score misc 1995-1995",
        lane_kind="historical",
        season_start=1995,
        season_end=1995,
        patterns=("game",),
        endpoints=("box_score_misc",),
    )
    support_rules = [
        rule.to_dict()
        for rule in contract_blocking_rules_for_lane(
            endpoints=lane.endpoints,
            patterns=lane.patterns,
            season_start=lane.season_start,
            season_end=lane.season_end,
        )
    ]
    coverage_units_hash = _coverage_hash_for_lane(lane)
    if tampered_field == "support_rules":
        support_rules[0]["evidence"] = "tampered"
    else:
        coverage_units_hash = ("0" if coverage_units_hash[0] != "0" else "1") + (
            coverage_units_hash[1:]
        )
    (metadata_dir / "tampered.json").write_text(
        json.dumps(
            {
                "lane_id": lane.lane_id,
                "lane_kind": lane.lane_kind,
                "status": "contract_blocked",
                "raw_status": "extract-error",
                "vpn_status": "connected",
                "vpn": {},
                "endpoints": list(lane.endpoints),
                "patterns": list(lane.patterns),
                "season_start": str(lane.season_start),
                "season_end": str(lane.season_end),
                "season_types": list(lane.season_types),
                "context_measures": list(lane.context_measures),
                "coverage_units_hash": coverage_units_hash,
                "support_rules": support_rules,
                "telemetry": {
                    "rows_persisted": 0,
                    "failed_calls": 1,
                    "zero_row_reason": "contract_blocked",
                },
            }
        ),
        encoding="utf-8",
    )

    audit = build_metadata_audit(metadata_dir)

    assert audit["status_counts"] == {"pipeline_failure": 1}
    assert audit["contract_blocked_lanes"] == []
    assert [row["lane_id"] for row in audit["pipeline_failure_lanes"]] == [lane.lane_id]


def test_validate_manifest_rejects_oversize_lane() -> None:
    with pytest.raises(ValueError, match="exceeds lane policy max"):
        validate_manifest(
            [
                FullExtractionLane(
                    lane_id="cross-product-test-1946-1960",
                    lane_index=0,
                    lane_name="Cross product test",
                    lane_kind="cross_product",
                    season_start=1946,
                    season_end=1960,
                    patterns=("player_team_season",),
                    timeout_seconds=7200,
                )
            ]
        )


def test_merge_lane_databases_merges_without_special_base(tmp_path: Path) -> None:
    lane_a = tmp_path / "lane-a"
    lane_b = tmp_path / "lane-b"
    lane_a.mkdir()
    lane_b.mkdir()

    _write_lane_db(
        lane_a / "nba.duckdb",
        alpha_rows=[1, 2],
        beta_rows=[],
        journal_rows=[("endpoint_a", "{}")],
    )
    _write_lane_db(
        lane_b / "nba.duckdb",
        alpha_rows=[2, 3],
        beta_rows=[9],
        journal_rows=[("endpoint_a", "{}"), ("endpoint_b", '{"season": "2024-25"}')],
    )

    output_dir = tmp_path / "merged"
    summary = merge_lane_databases(artifacts_dir=tmp_path, output_dir=output_dir)

    assert summary["merged_database_count"] == 2
    assert summary["merged_table_operations"] == 3
    assert summary["table_reports"]["stg_alpha"]["source_rows"] == 4
    assert summary["table_reports"]["stg_alpha"]["inserted_rows"] == 3
    assert summary["table_reports"]["stg_alpha"]["duplicate_rows"] == 1
    assert summary["table_reports"]["stg_beta"]["source_rows"] == 1
    assert summary["table_reports"]["stg_beta"]["inserted_rows"] == 1
    assert summary["journal_report"]["source_rows"] == 3
    assert summary["journal_report"]["inserted_rows"] == 2
    assert summary["journal_report"]["duplicate_rows"] == 1
    assert summary["journal_report"]["delete_batch_count"] == 0
    assert summary["journal_report"]["insert_batch_count"] == 1

    conn = duckdb.connect(str(output_dir / "nba.duckdb"))
    try:
        alpha_values = [
            row[0] for row in conn.execute("SELECT value FROM stg_alpha ORDER BY value").fetchall()
        ]
        beta_values = [
            row[0] for row in conn.execute("SELECT value FROM stg_beta ORDER BY value").fetchall()
        ]
        journal_rows = conn.execute(
            "SELECT endpoint, params FROM _extraction_journal ORDER BY endpoint, params"
        ).fetchall()
    finally:
        conn.close()

    assert alpha_values == [1, 2, 3]
    assert beta_values == [9]
    assert journal_rows == [("endpoint_a", "{}"), ("endpoint_b", '{"season": "2024-25"}')]


def test_merge_lane_databases_preserves_duplicate_row_multiplicity(tmp_path: Path) -> None:
    lane_a = tmp_path / "lane-a"
    lane_b = tmp_path / "lane-b"
    lane_a.mkdir()
    lane_b.mkdir()
    _write_lane_db(
        lane_a / "nba.duckdb",
        alpha_rows=[1, 1],
        beta_rows=[],
        journal_rows=[("endpoint_a", "{}")],
    )
    _write_lane_db(
        lane_b / "nba.duckdb",
        alpha_rows=[1, 1, 1, 2],
        beta_rows=[],
        journal_rows=[("endpoint_b", "{}")],
    )

    summary = merge_lane_databases(
        artifacts_dir=tmp_path,
        output_dir=tmp_path / "merged",
    )

    conn = duckdb.connect(summary["output_path"], read_only=True)
    try:
        alpha_values = [
            row[0] for row in conn.execute("SELECT value FROM stg_alpha ORDER BY value").fetchall()
        ]
    finally:
        conn.close()

    assert alpha_values == [1, 1, 1, 2]
    assert summary["table_reports"]["stg_alpha"]["source_rows"] == 6
    assert summary["table_reports"]["stg_alpha"]["inserted_rows"] == 4
    assert summary["table_reports"]["stg_alpha"]["duplicate_rows"] == 2


def test_checkpoint_merge_preserves_base_and_delta_duplicate_multiplicity(
    tmp_path: Path,
) -> None:
    base_database_path = tmp_path / "base.duckdb"
    delta_database_path = tmp_path / "delta.duckdb"
    _write_lane_db(
        base_database_path,
        alpha_rows=[1, 1, 2],
        beta_rows=[],
        journal_rows=[("base_endpoint", "{}")],
    )
    _write_lane_db(
        delta_database_path,
        alpha_rows=[1, 1, 1, 2, 3, 3],
        beta_rows=[],
        journal_rows=[("delta_endpoint", "{}")],
    )

    summary = _merge_database_paths(
        db_paths=[delta_database_path],
        output_dir=tmp_path / "checkpoint",
        base_database_path=base_database_path,
    )

    conn = duckdb.connect(summary["output_path"], read_only=True)
    try:
        alpha_values = [
            row[0] for row in conn.execute("SELECT value FROM stg_alpha ORDER BY value").fetchall()
        ]
    finally:
        conn.close()

    assert alpha_values == [1, 1, 1, 2, 3, 3]
    assert summary["table_reports"]["stg_alpha"]["source_rows"] == 6
    assert summary["table_reports"]["stg_alpha"]["inserted_rows"] == 3
    assert summary["table_reports"]["stg_alpha"]["duplicate_rows"] == 3


def test_checkpoint_merge_preserves_maximum_multiplicity_across_multiple_deltas(
    tmp_path: Path,
) -> None:
    base_database_path = tmp_path / "base.duckdb"
    _write_lane_db(
        base_database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("base_endpoint", "{}")],
    )
    delta_paths: list[Path] = []
    for index, rows in enumerate(([1, 1], [1, 1, 1], [1, 1])):
        delta_path = tmp_path / f"delta-{index}.duckdb"
        _write_lane_db(
            delta_path,
            alpha_rows=list(rows),
            beta_rows=[],
            journal_rows=[(f"delta_endpoint_{index}", "{}")],
        )
        delta_paths.append(delta_path)

    summary = _merge_database_paths(
        db_paths=delta_paths,
        output_dir=tmp_path / "checkpoint",
        base_database_path=base_database_path,
    )

    conn = duckdb.connect(summary["output_path"], read_only=True)
    try:
        alpha_values = [
            row[0] for row in conn.execute("SELECT value FROM stg_alpha ORDER BY value").fetchall()
        ]
    finally:
        conn.close()

    assert alpha_values == [1, 1, 1]
    assert summary["table_reports"]["stg_alpha"]["source_rows"] == 7
    assert summary["table_reports"]["stg_alpha"]["inserted_rows"] == 2
    assert summary["table_reports"]["stg_alpha"]["duplicate_rows"] == 5


def test_checkpoint_merge_batches_all_delta_journal_keys_once(tmp_path: Path) -> None:
    params = '{"season": "2024-25"}'
    base_database_path = tmp_path / "base.duckdb"
    _write_lane_db(
        base_database_path,
        alpha_rows=[99],
        beta_rows=[],
        journal_rows=[("shared_endpoint", params)],
    )
    conn = duckdb.connect(str(base_database_path))
    conn.execute("UPDATE _extraction_journal SET status = 'base'")
    conn.close()

    delta_paths: list[Path] = []
    for index in range(12):
        delta_path = tmp_path / f"delta-{index:02d}.duckdb"
        _write_lane_db(
            delta_path,
            alpha_rows=[index],
            beta_rows=[],
            journal_rows=[("shared_endpoint", params)],
        )
        conn = duckdb.connect(str(delta_path))
        conn.execute(
            "UPDATE _extraction_journal SET status = ?",
            [f"current-{index:02d}"],
        )
        conn.close()
        delta_paths.append(delta_path)

    summary = _merge_database_paths(
        db_paths=list(reversed(delta_paths)),
        output_dir=tmp_path / "checkpoint",
        base_database_path=base_database_path,
    )

    journal_report = summary["journal_report"]
    assert journal_report["source_count"] == 12
    assert journal_report["source_rows"] == 12
    assert journal_report["inserted_rows"] == 1
    assert journal_report["duplicate_rows"] == 11
    assert journal_report["replaced_base_rows"] == 1
    assert journal_report["delete_batch_count"] == 1
    assert journal_report["insert_batch_count"] == 1

    conn = duckdb.connect(summary["output_path"], read_only=True)
    try:
        journal_rows = conn.execute(
            "SELECT endpoint, params, status FROM _extraction_journal"
        ).fetchall()
    finally:
        conn.close()
    assert journal_rows == [("shared_endpoint", params, "current-11")]


@pytest.mark.parametrize(
    ("location", "field", "value", "expected_error"),
    [
        ("metadata", "chain_id", "other-chain", "metadata_chain_id_mismatch"),
        ("metadata", "source_sha", "b" * 40, "metadata_source_sha_mismatch"),
        ("metadata", "lane_id", "other-lane", "metadata_lane_id_mismatch"),
        (
            "metadata",
            "coverage_units_hash",
            "b" * 64,
            "metadata_coverage_units_hash_mismatch",
        ),
        ("metadata", "database_sha256", "b" * 64, "metadata_database_sha256_mismatch"),
        (
            "state_artifact",
            "run_id",
            "99999",
            "metadata_state_artifact_run_id_unauthorized",
        ),
        (
            "state_artifact",
            "name",
            "extraction-lane-chain-other-lane",
            "metadata_state_artifact_name_mismatch",
        ),
        (
            "state_artifact",
            "attested",
            False,
            "metadata_state_artifact_not_attested",
        ),
        (
            "state_artifact_missing",
            "uploaded",
            None,
            "metadata_state_artifact_not_uploaded",
        ),
        (
            "state_artifact",
            "artifact_id",
            "0",
            "metadata_state_artifact_id_invalid",
        ),
        (
            "state_artifact",
            "artifact_digest",
            "sha256:not-a-digest",
            "metadata_state_artifact_digest_invalid",
        ),
        (
            "state_artifact",
            "sha256",
            "b" * 64,
            "metadata_state_artifact_sha256_mismatch",
        ),
        ("attestation", "run_id", "99999", "lane_state_attestation_run_id_mismatch"),
        (
            "attestation",
            "artifact_name",
            "extraction-lane-chain-other-lane",
            "lane_state_attestation_artifact_name_mismatch",
        ),
        (
            "attestation",
            "attested",
            False,
            "lane_state_attestation_not_attested",
        ),
    ],
)
def test_current_lane_provenance_rejects_tampered_bindings(
    tmp_path: Path,
    location: str,
    field: str,
    value: object,
    expected_error: str,
) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    artifacts_dir = tmp_path / "lanes"
    artifact_dir = _lane_artifact_dir(artifacts_dir, lane)
    artifact_dir.mkdir(parents=True)
    database_path = artifact_dir / "nba.duckdb"
    _write_lane_db(
        database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    metadata_dir = tmp_path / "metadata"
    metadata_path = _lane_metadata_path(metadata_dir, lane)
    _write_attested_metadata(
        metadata_path,
        lane=lane,
        database_path=database_path,
    )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    attestation_path = artifact_dir / "artifacts/extraction/lane-state-attestation.json"
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    if location == "metadata":
        metadata[field] = value
    elif location == "state_artifact":
        metadata["state_artifact"][field] = value
    elif location == "state_artifact_missing":
        metadata["state_artifact"].pop(field)
    else:
        attestation[field] = value
        attestation_path.write_text(json.dumps(attestation), encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    _paths, attested_lane_ids, failures, _run_ids = _attested_current_lane_artifacts(
        artifacts_dir=artifacts_dir,
        metadata_dir=metadata_dir,
        complete_lane_ids={lane.lane_id},
        metadata={lane.lane_id: metadata},
        metadata_records={lane.lane_id: [(metadata_path, metadata)]},
        lanes_by_id={lane.lane_id: lane},
        chain_id=TEST_CHAIN_ID,
        source_sha=TEST_SOURCE_SHA,
        authorized_run_ids={TEST_RUN_ID},
    )

    assert attested_lane_ids == set()
    assert expected_error in failures[lane.lane_id]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("chain_id", "other-chain", "chain_id does not match"),
        ("run_id", "54321", "run_id does not match"),
        ("artifact_name", "full-extraction-checkpoint-chain-iter-2", "artifact_name"),
        ("checkpoint_generation", 2, "checkpoint_generation"),
        ("source_sha", "b" * 40, "source_sha does not match"),
        ("coverage_fingerprint", "b" * 64, "coverage_fingerprint"),
        ("database_sha256", "b" * 64, "database digest"),
        ("included_lane_coverage_hashes", {}, "hash inventory"),
    ],
)
def test_pre_inventory_checkpoint_verifier_rejects_tampered_report(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir()
    database_path = checkpoint_dir / "nba.duckdb"
    _write_lane_db(
        database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    coverage_fingerprint = _coverage_fingerprint([lane])
    report_path = checkpoint_dir / "checkpoint-report.json"
    _write_checkpoint_report(
        report_path,
        database_path=database_path,
        lanes=[lane],
        coverage_fingerprint=coverage_fingerprint,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report[field] = value
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest = manifest_payload(
        [lane],
        chain_state=FullExtractionChainState(
            latest_checkpoint_run_id=TEST_RUN_ID,
            latest_checkpoint_artifact_name="full-extraction-checkpoint-chain-iter-1",
            latest_checkpoint_generation=1,
            latest_checkpoint_coverage_hash=coverage_fingerprint,
        ),
    )
    manifest.update(
        {
            "chain_id": TEST_CHAIN_ID,
            "workflow_source_sha": TEST_SOURCE_SHA,
        }
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_checkpoint_artifact(
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=TEST_CHAIN_ID,
            source_sha=TEST_SOURCE_SHA,
        )


def test_pre_inventory_checkpoint_verifier_binds_canonical_blocked_evidence(
    tmp_path: Path,
) -> None:
    included_lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    blocked_lane = FullExtractionLane(
        lane_id="historical-video-blocked-1946-1947",
        lane_index=1,
        lane_name="Historical video blocked 1946-1947",
        lane_kind="historical",
        season_start=1946,
        season_end=1947,
        patterns=("player_team_season",),
        endpoints=("video_details",),
        timeout_seconds=1,
    )
    blocked_row = _canonical_contract_blocked_audit_row(
        blocked_lane.lane_id,
        {
            "lane_kind": blocked_lane.lane_kind,
            "endpoints": list(blocked_lane.endpoints),
            "patterns": list(blocked_lane.patterns),
            "season_start": blocked_lane.season_start,
            "season_end": blocked_lane.season_end,
            "season_types": [],
            "context_measures": [],
            "coverage_units_hash": _coverage_hash_for_lane(blocked_lane),
        },
    )
    evidence = {"schema_version": 1, "contract_blocked_lanes": [blocked_row]}
    evidence_digest = _hash_payload(evidence)

    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir()
    database_path = checkpoint_dir / "nba.duckdb"
    _write_lane_db(
        database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    coverage_fingerprint = _coverage_fingerprint([included_lane])
    report_path = checkpoint_dir / "checkpoint-report.json"
    _write_checkpoint_report(
        report_path,
        database_path=database_path,
        lanes=[included_lane],
        coverage_fingerprint=coverage_fingerprint,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update(
        {
            "contract_blocked_lane_count": 1,
            "contract_blocked_evidence": evidence,
            "contract_blocked_evidence_sha256": evidence_digest,
        }
    )
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest = manifest_payload(
        [included_lane],
        chain_state=FullExtractionChainState(
            latest_checkpoint_run_id=TEST_RUN_ID,
            latest_checkpoint_artifact_name="full-extraction-checkpoint-chain-iter-1",
            latest_checkpoint_generation=1,
            latest_checkpoint_coverage_hash=coverage_fingerprint,
            contract_blocked_evidence=(blocked_row,),
            contract_blocked_evidence_sha256=evidence_digest,
        ),
    )
    manifest.update({"chain_id": TEST_CHAIN_ID, "workflow_source_sha": TEST_SOURCE_SHA})
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    verified = validate_checkpoint_artifact(
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
        checkpoint_report_path=report_path,
        chain_id=TEST_CHAIN_ID,
        source_sha=TEST_SOURCE_SHA,
    )
    assert verified["contract_blocked_lane_count"] == 1
    assert verified["contract_blocked_evidence_sha256"] == evidence_digest

    tampered_report = json.loads(json.dumps(report))
    tampered_report["contract_blocked_evidence"]["contract_blocked_lanes"][0]["season_end"] = 1948
    report_path.write_text(json.dumps(tampered_report), encoding="utf-8")
    with pytest.raises(ValueError, match="contract-blocked"):
        validate_checkpoint_artifact(
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=TEST_CHAIN_ID,
            source_sha=TEST_SOURCE_SHA,
        )

    alternate_blocked_lane = replace(
        blocked_lane,
        lane_id="historical-video-blocked-1947-1948",
        season_start=1947,
        season_end=1948,
    )
    alternate_blocked_row = _canonical_contract_blocked_audit_row(
        alternate_blocked_lane.lane_id,
        {
            "lane_kind": alternate_blocked_lane.lane_kind,
            "endpoints": list(alternate_blocked_lane.endpoints),
            "patterns": list(alternate_blocked_lane.patterns),
            "season_start": alternate_blocked_lane.season_start,
            "season_end": alternate_blocked_lane.season_end,
            "season_types": [],
            "context_measures": [],
            "coverage_units_hash": _coverage_hash_for_lane(alternate_blocked_lane),
        },
    )
    alternate_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [alternate_blocked_row],
    }
    report["contract_blocked_evidence"] = alternate_evidence
    report["contract_blocked_evidence_sha256"] = _hash_payload(alternate_evidence)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="latest chain-state commitment"):
        validate_checkpoint_artifact(
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=TEST_CHAIN_ID,
            source_sha=TEST_SOURCE_SHA,
        )

    report["contract_blocked_evidence"] = evidence
    report["contract_blocked_evidence_sha256"] = evidence_digest
    report_path.write_text(json.dumps(report), encoding="utf-8")
    manifest["chain_state"]["contract_blocked_evidence_sha256"] = "b" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(
        ValueError,
        match="digest does not match the latest chain-state commitment",
    ):
        validate_checkpoint_artifact(
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=TEST_CHAIN_ID,
            source_sha=TEST_SOURCE_SHA,
        )


@pytest.mark.parametrize(
    ("pointer_update", "message"),
    [
        ({"latest_checkpoint_coverage_hash": ""}, "must set run ID"),
        ({"latest_checkpoint_run_id": "not-numeric"}, "positive integer"),
        ({"latest_checkpoint_generation": True}, "represented as an integer"),
        (
            {"latest_checkpoint_artifact_name": "full-extraction-checkpoint-other-iter-1"},
            "artifact name must be",
        ),
    ],
)
def test_pre_inventory_checkpoint_verifier_rejects_tampered_pointer(
    tmp_path: Path,
    pointer_update: dict[str, object],
    message: str,
) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir()
    database_path = checkpoint_dir / "nba.duckdb"
    _write_lane_db(
        database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    coverage_fingerprint = _coverage_fingerprint([lane])
    report_path = checkpoint_dir / "checkpoint-report.json"
    _write_checkpoint_report(
        report_path,
        database_path=database_path,
        lanes=[lane],
        coverage_fingerprint=coverage_fingerprint,
    )
    chain_state = {
        "latest_checkpoint_run_id": TEST_RUN_ID,
        "latest_checkpoint_artifact_name": "full-extraction-checkpoint-chain-iter-1",
        "latest_checkpoint_generation": 1,
        "latest_checkpoint_coverage_hash": coverage_fingerprint,
        **pointer_update,
    }
    manifest = manifest_payload([lane])
    manifest.update(
        {
            "chain_id": TEST_CHAIN_ID,
            "workflow_source_sha": TEST_SOURCE_SHA,
            "chain_state": chain_state,
        }
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        validate_checkpoint_artifact(
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=report_path,
            chain_id=TEST_CHAIN_ID,
            source_sha=TEST_SOURCE_SHA,
        )


def test_full_extraction_no_network_terminal_checkpoint_simulator(tmp_path: Path) -> None:
    reference_lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    historical_lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=1,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=5400,
    )
    manifest = manifest_payload([reference_lane, historical_lane], max_matrix_lanes=2)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    chain_id = "local-sim"
    run_id = "1001"
    metadata_dir = tmp_path / "metadata"
    artifacts_dir = tmp_path / "artifacts"
    reference_artifact = _lane_artifact_dir(
        artifacts_dir, reference_lane, chain_id=chain_id, run_id=run_id
    )
    historical_artifact = _lane_artifact_dir(
        artifacts_dir, historical_lane, chain_id=chain_id, run_id=run_id
    )
    reference_artifact.mkdir(parents=True)
    historical_artifact.mkdir(parents=True)
    reference_database = reference_artifact / "nba.duckdb"
    historical_database = historical_artifact / "nba.duckdb"
    _write_lane_db(
        reference_database,
        alpha_rows=[1, 2],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    _write_lane_db(
        historical_database,
        alpha_rows=[3],
        beta_rows=[9],
        journal_rows=[
            (
                "box_score_summary",
                '{"game_id": "0022400001", "season": "2024-25"}',
            )
        ],
    )
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, reference_lane, chain_id=chain_id, run_id=run_id),
        lane=reference_lane,
        database_path=reference_database,
        chain_id=chain_id,
        run_id=run_id,
    )
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, historical_lane, chain_id=chain_id, run_id=run_id),
        lane=historical_lane,
        database_path=historical_database,
        chain_id=chain_id,
        run_id=run_id,
    )

    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_report_path = checkpoint_dir / "checkpoint-report.json"
    checkpoint_report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=artifacts_dir,
        output_dir=checkpoint_dir,
        report_path=checkpoint_report_path,
        chain_id=chain_id,
        run_id=run_id,
    )

    assert checkpoint_report["terminal_ready"] is True
    assert checkpoint_report["manifest_lane_count"] == 2
    assert checkpoint_report["active_lane_count"] == 0
    assert checkpoint_report["complete_lane_count"] == 2
    assert checkpoint_report["coverage_fingerprint"] == manifest["coverage_fingerprint"]
    assert checkpoint_report["database_sha256"] == _file_sha256(checkpoint_dir / "nba.duckdb")
    assert checkpoint_report["included_lane_coverage_hashes"] == {
        reference_lane.lane_id: _coverage_hash_for_lane(reference_lane),
        historical_lane.lane_id: _coverage_hash_for_lane(historical_lane),
    }

    final_dir = tmp_path / "final"
    final_report = merge_final_database(
        artifacts_dir=artifacts_dir,
        output_dir=final_dir,
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
        checkpoint_report_path=checkpoint_report_path,
        allow_artifact_fallback=True,
    )

    assert final_report["merge_mode"] == "checkpoint"
    assert final_report["coverage_fingerprint"] == manifest["coverage_fingerprint"]
    assert final_report["table_row_counts"]["stg_alpha"] == 3
    assert final_report["journal_row_count"] == 2


def test_checkpoint_manifest_lane_count_includes_current_and_prior_blocked_evidence(
    tmp_path: Path,
) -> None:
    included_lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    prior_blocked_lane = FullExtractionLane(
        lane_id="historical-video-details-no-season-type-1946-1947",
        lane_index=1,
        lane_name="Historical video details 1946-1947",
        lane_kind="historical",
        season_start=1946,
        season_end=1947,
        patterns=("player_team_season",),
        endpoints=("video_details",),
        timeout_seconds=1,
    )
    current_blocked_lane = replace(
        prior_blocked_lane,
        lane_id="historical-video-details-no-season-type-1948-1949",
        lane_name="Historical video details 1948-1949",
        season_start=1948,
        season_end=1949,
    )
    prior_row = _contract_blocked_row(prior_blocked_lane)
    committed_rows = tuple(
        sorted(
            [prior_row, _contract_blocked_row(current_blocked_lane)],
            key=lambda row: row["lane_id"],
        )
    )
    prior_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [prior_row],
    }
    committed_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": list(committed_rows),
    }
    chain_state = FullExtractionChainState(
        contract_blocked_evidence=committed_rows,
        contract_blocked_evidence_sha256=_hash_payload(committed_evidence),
        previous_contract_blocked_evidence=(prior_row,),
        previous_contract_blocked_evidence_sha256=_hash_payload(prior_evidence),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload([included_lane], chain_state=chain_state)),
        encoding="utf-8",
    )
    artifacts_dir = tmp_path / "artifacts"
    artifact_dir = _lane_artifact_dir(artifacts_dir, included_lane)
    artifact_dir.mkdir(parents=True)
    database_path = artifact_dir / "nba.duckdb"
    _write_lane_db(
        database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    metadata_dir = tmp_path / "metadata"
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, included_lane),
        lane=included_lane,
        database_path=database_path,
    )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=artifacts_dir,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
    )

    assert report["terminal_ready"] is True
    assert report["manifest_lane_count"] == 3
    assert report["complete_lane_count"] == 1
    assert report["contract_blocked_lane_count"] == 2
    assert report["manifest_lane_count"] == (
        report["complete_lane_count"] + report["contract_blocked_lane_count"]
    )


def test_checkpoint_rejects_manifest_lane_already_accounted_as_contract_blocked(
    tmp_path: Path,
) -> None:
    blocked_lane = FullExtractionLane(
        lane_id="historical-video-details-no-season-type-1946-1947",
        lane_index=0,
        lane_name="Historical video details 1946-1947",
        lane_kind="historical",
        season_start=1946,
        season_end=1947,
        patterns=("player_team_season",),
        endpoints=("video_details",),
        timeout_seconds=1,
    )
    blocked_row = _contract_blocked_row(blocked_lane)
    evidence = {"schema_version": 1, "contract_blocked_lanes": [blocked_row]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest_payload(
                [blocked_lane],
                chain_state=FullExtractionChainState(
                    contract_blocked_evidence=(blocked_row,),
                    contract_blocked_evidence_sha256=_hash_payload(evidence),
                ),
            )
        ),
        encoding="utf-8",
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    with pytest.raises(ValueError, match="overlap committed contract-blocked evidence"):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            output_dir=tmp_path / "checkpoint",
            report_path=tmp_path / "checkpoint-report.json",
        )


def test_full_extraction_checkpoint_flags_complete_metadata_without_lane_db(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=0,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=5400,
    )
    manifest = manifest_payload([lane], max_matrix_lanes=1)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "complete.json",
        lane_id=lane.lane_id,
        status="complete",
        rows_persisted=3,
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
        season_start=lane.season_start,
        season_end=lane.season_end,
    )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "missing-lane-artifacts",
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="local-sim",
        run_id="1001",
    )

    assert report["terminal_ready"] is False
    assert report["active_lane_count"] == 1
    assert report["complete_lane_count"] == 0
    assert report["missing_lane_ids"] == [lane.lane_id]
    assert report["skipped_complete_lane_ids"] == [lane.lane_id]


def test_checkpoint_rejects_complete_metadata_for_empty_lane_database(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])), encoding="utf-8")
    artifact_dir = _lane_artifact_dir(tmp_path / "lanes", lane)
    artifact_dir.mkdir(parents=True)
    database_path = artifact_dir / "nba.duckdb"
    duckdb.connect(str(database_path)).close()
    metadata_dir = tmp_path / "metadata"
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, lane),
        lane=lane,
        database_path=database_path,
    )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
    )

    assert report["terminal_ready"] is False
    assert report["active_lane_count"] == 1
    assert report["attested_current_lane_ids"] == []
    assert report["current_lane_attestation_failures"][lane.lane_id] == [
        "journal_missing_columns:endpoint,params,status"
    ]


def test_checkpoint_rejects_complete_metadata_with_wrong_lane_contract(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])), encoding="utf-8")
    artifact_dir = _lane_artifact_dir(tmp_path / "lanes", lane)
    artifact_dir.mkdir(parents=True)
    database_path = artifact_dir / "nba.duckdb"
    _write_lane_db(
        database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    metadata_dir = tmp_path / "metadata"
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, lane),
        lane=lane,
        database_path=database_path,
        lane_name="Wrong Lane",
    )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
    )

    assert report["terminal_ready"] is False
    assert report["attested_current_lane_ids"] == []
    assert (
        "metadata_lane_name_mismatch" in report["current_lane_attestation_failures"][lane.lane_id]
    )


def test_checkpoint_accepts_schema_v3_static_reference_coverage(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[("franchise_history", "{}")],
    )

    assert report["terminal_ready"] is True
    assert report["attested_current_lane_ids"] == [lane.lane_id]
    assert report["current_lane_attestation_failures"] == {}


def test_checkpoint_accepts_schema_v3_player_reference_coverage(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="reference-player",
        lane_index=0,
        lane_name="Reference Player",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("player",),
        endpoints=("player_endpoint_a", "player_endpoint_b"),
        timeout_seconds=3600,
    )

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[
            ("player_endpoint_a", '{"player_id": 1}'),
            ("player_endpoint_a", '{"player_id": 2}'),
            ("player_endpoint_b", '{"player_id": 1}'),
            ("player_endpoint_b", '{"player_id": 2}'),
            ("unrelated_endpoint", '{"player_id": 3}'),
        ],
    )

    assert report["terminal_ready"] is True
    assert report["attested_current_lane_ids"] == [lane.lane_id]
    assert report["current_lane_attestation_failures"] == {}


def test_checkpoint_rejects_schema_v3_journal_missing_manifest_season(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-season-draft-history-no-season-type-2020-2021",
        lane_index=0,
        lane_name="Historical season 2020-2021 (draft_history)",
        lane_kind="historical",
        season_start=2020,
        season_end=2021,
        patterns=("season",),
        endpoints=("draft_history",),
        timeout_seconds=3600,
    )

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[("draft_history", '{"season": "2020-21"}')],
    )

    failures = report["current_lane_attestation_failures"][lane.lane_id]
    assert report["terminal_ready"] is False
    assert any(error.startswith("journal_missing_manifest_coverage:1:") for error in failures)


def test_checkpoint_rejects_schema_v3_journal_missing_manifest_season_type(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-season-league-dash-team-stats-2020",
        lane_index=0,
        lane_name="Historical season 2020 (league_dash_team_stats)",
        lane_kind="historical",
        season_start=2020,
        season_end=2020,
        patterns=("season",),
        season_types=("Regular Season", "Playoffs"),
        endpoints=("league_dash_team_stats",),
        timeout_seconds=3600,
    )

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[
            (
                "league_dash_team_stats",
                '{"season": "2020-21", "season_type": "Regular Season"}',
            )
        ],
    )

    failures = report["current_lane_attestation_failures"][lane.lane_id]
    assert report["terminal_ready"] is False
    assert any(error.startswith("journal_missing_manifest_coverage:1:") for error in failures)


def test_checkpoint_rejects_schema_v3_journal_missing_game_unit(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-adversarial-2024",
        lane_index=0,
        lane_name="Historical game adversarial 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("game_endpoint_a", "game_endpoint_b"),
        timeout_seconds=5400,
    )

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[
            ("game_endpoint_a", '{"game_id": "0022400001"}'),
            ("game_endpoint_a", '{"game_id": "0022400002"}'),
            ("game_endpoint_b", '{"game_id": "0022400001"}'),
        ],
    )

    failures = report["current_lane_attestation_failures"][lane.lane_id]
    assert report["terminal_ready"] is False
    assert not any(error.startswith("journal_missing_manifest_coverage:") for error in failures)
    assert any(error.startswith("journal_missing_parameter_coverage:1:") for error in failures)


def test_checkpoint_rejects_schema_v3_journal_missing_player_unit(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-player-season-adversarial-2020-2021",
        lane_index=0,
        lane_name="Historical player season adversarial 2020-2021",
        lane_kind="historical",
        season_start=2020,
        season_end=2021,
        patterns=("player_season",),
        season_types=("Regular Season",),
        endpoints=("player_endpoint",),
        timeout_seconds=5400,
    )

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[
            (
                "player_endpoint",
                '{"player_id": 1, "season": "2020-21", "season_type": "Regular Season"}',
            ),
            (
                "player_endpoint",
                '{"player_id": 1, "season": "2021-22", "season_type": "Regular Season"}',
            ),
            (
                "player_endpoint",
                '{"player_id": 2, "season": "2020-21", "season_type": "Regular Season"}',
            ),
        ],
    )

    failures = report["current_lane_attestation_failures"][lane.lane_id]
    assert report["terminal_ready"] is False
    assert not any(error.startswith("journal_missing_manifest_coverage:") for error in failures)
    assert any(error.startswith("journal_missing_parameter_coverage:1:") for error in failures)


def test_checkpoint_rejects_schema_v3_journal_missing_workload_unit(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-adversarial-2020",
        lane_index=0,
        lane_name="Cross product adversarial 2020",
        lane_kind="cross_product",
        season_start=2020,
        season_end=2020,
        patterns=("player_team_season",),
        season_types=("Regular Season",),
        context_measures=("PTS",),
        endpoints=("video_details", "video_details_asset"),
        timeout_seconds=5400,
    )
    first_workload = (
        '{"context_measure": "PTS", "player_id": 1, "team_id": 10, '
        '"season": "2020-21", "season_type": "Regular Season"}'
    )
    second_workload = (
        '{"context_measure": "PTS", "player_id": 2, "team_id": 20, '
        '"season": "2020-21", "season_type": "Regular Season"}'
    )

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[
            ("video_details", first_workload),
            ("video_details", second_workload),
            ("video_details_asset", first_workload),
        ],
    )

    failures = report["current_lane_attestation_failures"][lane.lane_id]
    assert report["terminal_ready"] is False
    assert not any(error.startswith("journal_missing_manifest_coverage:") for error in failures)
    assert any(error.startswith("journal_missing_parameter_coverage:1:") for error in failures)


def test_checkpoint_rejects_workload_unit_absent_from_entire_journal(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-player-index-2024",
        lane_index=0,
        lane_name="Cross product player index 2024",
        lane_kind="cross_product",
        season_start=2024,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=(SeasonType.REGULAR.value,),
        endpoints=("player_index",),
        timeout_seconds=5400,
    )
    first = {
        "player_id": 1,
        "team_id": 10,
        "season": "2024-25",
        "season_type": SeasonType.REGULAR.value,
    }
    second = {
        "player_id": 2,
        "team_id": 20,
        "season": "2024-25",
        "season_type": SeasonType.REGULAR.value,
    }

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[("player_index", json.dumps(first))],
        workload_params=[first, second],
    )

    failures = report["current_lane_attestation_failures"][lane.lane_id]
    assert report["terminal_ready"] is False
    assert any(error.startswith("journal_missing_parameter_coverage:1:") for error in failures)


def test_checkpoint_rejects_unexpected_journal_workload_identity(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-player-index-unexpected-2024",
        lane_index=0,
        lane_name="Cross product player index unexpected 2024",
        lane_kind="cross_product",
        season_start=2024,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=(SeasonType.REGULAR.value,),
        endpoints=("player_index",),
        timeout_seconds=5400,
    )
    expected = {
        "player_id": 1,
        "team_id": 10,
        "season": "2024-25",
        "season_type": SeasonType.REGULAR.value,
    }
    unexpected = {**expected, "player_id": 99, "team_id": 990}

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[
            ("player_index", json.dumps(expected)),
            ("player_index", json.dumps(unexpected)),
        ],
        workload_params=[expected],
    )

    failures = report["current_lane_attestation_failures"][lane.lane_id]
    assert report["terminal_ready"] is False
    assert any(error.startswith("journal_unexpected_workload_identities:1:") for error in failures)


def test_checkpoint_accepts_attested_empty_workload_scope(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-player-index-empty-2024",
        lane_index=0,
        lane_name="Cross product player index empty 2024",
        lane_kind="cross_product",
        season_start=2024,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=(SeasonType.REGULAR.value,),
        endpoints=("player_index",),
        timeout_seconds=5400,
    )

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[],
        workload_params=[],
    )

    assert report["terminal_ready"] is True
    assert report["workload_contract_errors"] == []
    assert report["workload_integrity"] is not None


def test_checkpoint_carries_lane_across_append_only_workload_generation_growth(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-player-index-regular-season-2024-2024",
        lane_index=0,
        lane_name="Cross product player index 2024",
        lane_kind="cross_product",
        season_start=2024,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=(SeasonType.REGULAR.value,),
        endpoints=("player_index",),
        timeout_seconds=5400,
    )
    params = {
        "player_id": 1,
        "team_id": 10,
        "season": "2024-25",
        "season_type": SeasonType.REGULAR.value,
    }
    first_report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[("player_index", json.dumps(params))],
        workload_params=[params],
    )
    first_integrity = first_report["workload_integrity"]
    assert (
        first_report["included_lane_workload_contracts"][lane.lane_id]["integrity"]
        == first_integrity
    )

    workload_anchor = tmp_path / "workload" / "nba.duckdb"
    workload_store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(workload_anchor)
    workload_store.upsert(
        [
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2025-26",
                "season_type": SeasonType.REGULAR.value,
            }
        ],
        seasons=["2025-26"],
        season_types=[SeasonType.REGULAR.value],
    )

    next_manifest_path = tmp_path / "next-manifest.json"
    next_manifest_path.write_text(
        json.dumps(manifest_payload([replace(lane, resume_only=True)])) + "\n",
        encoding="utf-8",
    )
    metadata_dir = tmp_path / "next-metadata"
    metadata_dir.mkdir()
    next_report = _build_checkpoint_database(
        manifest_path=next_manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "no-current-lanes",
        previous_checkpoint_dir=tmp_path / "checkpoint",
        previous_checkpoint_report_path=tmp_path / "checkpoint-report.json",
        output_dir=tmp_path / "next-checkpoint",
        report_path=tmp_path / "next-checkpoint-report.json",
        workload_duckdb_path=workload_anchor,
    )

    assert next_report["terminal_ready"] is True
    assert next_report["complete_lane_count"] == 1
    assert next_report["workload_integrity"] != first_integrity
    assert (
        next_report["included_lane_workload_contracts"][lane.lane_id]["integrity"]
        == next_report["workload_integrity"]
    )


def test_checkpoint_carries_non_workload_lane_into_first_workload_wave(
    tmp_path: Path,
) -> None:
    static_lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Static reference",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("common_all_players",),
        timeout_seconds=900,
    )
    first_report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=static_lane,
        journal_rows=[("common_all_players", "{}")],
    )
    assert first_report["workload_integrity"] is None
    assert first_report["included_lane_workload_contracts"] == {}

    workload_lane = FullExtractionLane(
        lane_id="cross-product-player-index-regular-season-2024-2024",
        lane_index=1,
        lane_name="Cross product player index 2024",
        lane_kind="cross_product",
        season_start=2024,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=(SeasonType.REGULAR.value,),
        endpoints=("player_index",),
        timeout_seconds=5400,
    )
    workload_params = [
        {
            "player_id": 1,
            "team_id": 10,
            "season": "2024-25",
            "season_type": SeasonType.REGULAR.value,
        }
    ]
    workload_anchor, _store, _contract = _write_workload_contract(
        tmp_path,
        lane=workload_lane,
        params=workload_params,
    )
    next_manifest_path = tmp_path / "next-manifest.json"
    next_manifest_path.write_text(
        json.dumps(manifest_payload([replace(static_lane, resume_only=True), workload_lane]))
        + "\n",
        encoding="utf-8",
    )
    metadata_dir = tmp_path / "next-metadata"
    metadata_dir.mkdir()

    next_report = _build_checkpoint_database(
        manifest_path=next_manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "no-current-lanes",
        previous_checkpoint_dir=tmp_path / "checkpoint",
        previous_checkpoint_report_path=tmp_path / "checkpoint-report.json",
        output_dir=tmp_path / "next-checkpoint",
        report_path=tmp_path / "next-checkpoint-report.json",
        workload_duckdb_path=workload_anchor,
    )

    assert next_report["terminal_ready"] is False
    assert next_report["complete_lane_count"] == 1
    assert next_report["active_lane_count"] == 1
    assert next_report["included_lane_ids"] == [static_lane.lane_id]
    assert next_report["workload_integrity"] is not None
    assert next_report["included_lane_workload_contracts"] == {}


def test_checkpoint_accepts_attested_empty_pair_within_populated_lane(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-player-index-mixed-2023-2024",
        lane_index=0,
        lane_name="Cross product player index mixed 2023-2024",
        lane_kind="cross_product",
        season_start=2023,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=(SeasonType.REGULAR.value,),
        endpoints=("player_index",),
        timeout_seconds=5400,
    )
    populated = {
        "player_id": 1,
        "team_id": 10,
        "season": "2023-24",
        "season_type": SeasonType.REGULAR.value,
    }

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[("player_index", json.dumps(populated))],
        workload_params=[populated],
    )

    assert report["terminal_ready"] is True
    assert report["current_lane_attestation_failures"] == {}


def test_checkpoint_rejects_video_lane_missing_a_context_measure(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-video-context-adversarial-2024",
        lane_index=0,
        lane_name="Cross product video context adversarial 2024",
        lane_kind="cross_product",
        season_start=2024,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=(SeasonType.REGULAR.value,),
        context_measures=("PTS", "AST"),
        endpoints=("video_details",),
        timeout_seconds=5400,
    )
    pts_only = (
        '{"context_measure": "PTS", "player_id": 1, "team_id": 10, '
        '"season": "2024-25", "season_type": "Regular Season"}'
    )

    report = _build_attested_lane_checkpoint(
        tmp_path,
        lane=lane,
        journal_rows=[("video_details", pts_only)],
    )

    failures = report["current_lane_attestation_failures"][lane.lane_id]
    assert report["terminal_ready"] is False
    assert any(error.startswith("journal_missing_manifest_coverage:1:") for error in failures)
    assert any(error.startswith("journal_missing_parameter_coverage:1:") for error in failures)


def test_checkpoint_rejects_supported_lane_falsely_declared_contract_blocked(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-2024",
        lane_index=0,
        lane_name="Historical game box score summary 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=5400,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])), encoding="utf-8")
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "lane.json").write_text(
        json.dumps(
            {
                "lane_id": lane.lane_id,
                "status": "contract_blocked",
                "raw_status": "contract_blocked",
                "vpn": {},
                "patterns": list(lane.patterns),
                "endpoints": list(lane.endpoints),
                "season_start": str(lane.season_start),
                "season_end": str(lane.season_end),
                "support_rules": [
                    {
                        "endpoint_name": "box_score_summary",
                        "pattern": "game",
                        "classification": "contract_blocked",
                        "reason": "self declared",
                        "evidence": "self declared",
                        "revalidation_command": "false",
                        "season_start": 2024,
                        "season_end": 2024,
                    }
                ],
                "telemetry": {"rows_persisted": 0, "failed_calls": 1},
            }
        ),
        encoding="utf-8",
    )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
    )

    assert report["terminal_ready"] is False
    assert report["contract_blocked_lane_count"] == 0
    assert report["active_lane_count"] == 1
    assert report["missing_lane_ids"] == [lane.lane_id]


def test_checkpoint_rejects_contract_blocked_lane_with_mismatched_rule_evidence(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-misc-1995",
        lane_index=0,
        lane_name="Historical game box score misc 1995",
        lane_kind="historical",
        season_start=1995,
        season_end=1995,
        patterns=("game",),
        endpoints=("box_score_misc",),
        timeout_seconds=5400,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])), encoding="utf-8")
    support_rules = [
        rule.to_dict()
        for rule in contract_blocking_rules_for_lane(
            endpoints=lane.endpoints,
            patterns=lane.patterns,
            season_start=lane.season_start,
            season_end=lane.season_end,
        )
    ]
    support_rules[0]["evidence"] = "tampered evidence"
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    (metadata_dir / "lane.json").write_text(
        json.dumps(
            {
                "metadata_schema_version": 3,
                "lane_id": lane.lane_id,
                "status": "contract_blocked",
                "raw_status": "extract-error",
                "vpn": {},
                "patterns": list(lane.patterns),
                "endpoints": list(lane.endpoints),
                "season_start": str(lane.season_start),
                "season_end": str(lane.season_end),
                "support_rules": support_rules,
                "telemetry": {"rows_persisted": 0, "failed_calls": 1},
            }
        ),
        encoding="utf-8",
    )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
    )

    assert report["terminal_ready"] is False
    assert report["contract_blocked_lane_count"] == 0
    assert report["missing_lane_ids"] == [lane.lane_id]


def test_checkpoint_rejects_physically_swapped_lane_databases(tmp_path: Path) -> None:
    lanes = [
        FullExtractionLane(
            lane_id="reference-a",
            lane_index=0,
            lane_name="Reference A",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("static",),
            endpoints=("endpoint_a",),
            timeout_seconds=1800,
        ),
        FullExtractionLane(
            lane_id="reference-b",
            lane_index=1,
            lane_name="Reference B",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("static",),
            endpoints=("endpoint_b",),
            timeout_seconds=1800,
        ),
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload(lanes)), encoding="utf-8")
    artifact_root = tmp_path / "lanes"
    artifact_a = _lane_artifact_dir(artifact_root, lanes[0])
    artifact_b = _lane_artifact_dir(artifact_root, lanes[1])
    artifact_a.mkdir(parents=True)
    artifact_b.mkdir(parents=True)
    original_a = artifact_a / "nba.duckdb"
    original_b = artifact_b / "nba.duckdb"
    _write_lane_db(
        original_a,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("endpoint_a", "{}")],
    )
    _write_lane_db(
        original_b,
        alpha_rows=[2],
        beta_rows=[],
        journal_rows=[("endpoint_b", "{}")],
    )
    metadata_dir = tmp_path / "metadata"
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, lanes[0]),
        lane=lanes[0],
        database_path=original_a,
    )
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, lanes[1]),
        lane=lanes[1],
        database_path=original_b,
    )
    swap_path = tmp_path / "swap.duckdb"
    original_a.replace(swap_path)
    original_b.replace(original_a)
    swap_path.replace(original_b)

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=artifact_root,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
    )

    assert report["terminal_ready"] is False
    assert report["active_lane_count"] == 2
    assert report["attested_current_lane_ids"] == []
    for lane in lanes:
        assert (
            "metadata_database_sha256_mismatch"
            in report["current_lane_attestation_failures"][lane.lane_id]
        )


def test_checkpoint_discovers_database_in_github_artifact_layout(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
        resume_only=True,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])), encoding="utf-8")

    artifact_dir = (
        tmp_path
        / "lanes"
        / "run-12345"
        / f"extraction-lane-{TEST_CHAIN_ID}-{lane.lane_id}"
        / "data"
        / "nbadb"
    )
    artifact_dir.mkdir(parents=True)
    database_path = artifact_dir / "nba.duckdb"
    _write_lane_db(
        database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    metadata_dir = tmp_path / "metadata"
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, lane),
        lane=lane,
        database_path=database_path,
    )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
    )

    assert report["terminal_ready"] is True
    assert report["active_lane_count"] == 0
    assert report["included_lane_ids"] == [lane.lane_id]
    assert report["current_lane_attestation_failures"] == {}


def test_artifact_lane_identity_requires_lane_artifact_ancestor(tmp_path: Path) -> None:
    lane_id = "reference-static"
    artifacts_dir = tmp_path / "lanes"
    unrelated_path = artifacts_dir / f"run-{lane_id}" / "data" / "nbadb" / "nba.duckdb"
    artifact_path = (
        artifacts_dir
        / "run-12345"
        / f"extraction-lane-chain-{lane_id}"
        / "data"
        / "nbadb"
        / "nba.duckdb"
    )

    assert (
        _artifact_lane_id_for_database(
            db_path=unrelated_path,
            artifacts_dir=artifacts_dir,
            ordered_lane_ids=[lane_id],
        )
        is None
    )
    assert (
        _artifact_lane_id_for_database(
            db_path=artifact_path,
            artifacts_dir=artifacts_dir,
            ordered_lane_ids=[lane_id],
        )
        == lane_id
    )
    assert (
        _artifact_lane_id_for_database(
            db_path=(
                artifacts_dir / "extraction-lane-chain-foo-bar" / "data" / "nbadb" / "nba.duckdb"
            ),
            artifacts_dir=artifacts_dir,
            ordered_lane_ids=["foo-bar", "bar"],
        )
        is None
    )


def test_checkpoint_uses_exact_artifact_names_for_overlapping_suffixes(tmp_path: Path) -> None:
    lanes = [
        FullExtractionLane(
            lane_id="bar",
            lane_index=0,
            lane_name="Bar",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("static",),
            endpoints=("endpoint_bar",),
            timeout_seconds=1800,
            resume_only=True,
        ),
        FullExtractionLane(
            lane_id="foo-bar",
            lane_index=1,
            lane_name="Foo Bar",
            lane_kind="reference",
            season_start=None,
            season_end=None,
            patterns=("static",),
            endpoints=("endpoint_foo_bar",),
            timeout_seconds=1800,
            resume_only=True,
        ),
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload(lanes)), encoding="utf-8")
    metadata_dir = tmp_path / "metadata"
    artifacts_dir = tmp_path / "lanes"

    for lane in lanes:
        artifact_name = f"extraction-lane-foo-{lane.lane_id}"
        database_dir = artifacts_dir / "run-12345" / artifact_name / "data" / "nbadb"
        database_dir.mkdir(parents=True)
        database_path = database_dir / "nba.duckdb"
        _write_lane_db(
            database_path,
            alpha_rows=[lane.lane_index],
            beta_rows=[],
            journal_rows=[(lane.endpoints[0], "{}")],
        )
        _write_attested_metadata(
            _lane_metadata_path(metadata_dir, lane, chain_id="foo"),
            lane=lane,
            database_path=database_path,
            artifact_name=artifact_name,
            chain_id="foo",
        )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=artifacts_dir,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="foo",
    )

    assert report["terminal_ready"] is True
    assert report["included_lane_ids"] == ["bar", "foo-bar"]
    assert report["current_lane_attestation_failures"] == {}


def test_checkpoint_rejects_duplicate_declared_artifact_database(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
        resume_only=True,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])), encoding="utf-8")
    metadata_dir = tmp_path / "metadata"
    artifacts_dir = tmp_path / "lanes"
    artifact_name = f"extraction-lane-{TEST_CHAIN_ID}-{lane.lane_id}"
    database_paths: list[Path] = []
    for run_id in (TEST_RUN_ID, "67890"):
        database_dir = artifacts_dir / f"run-{run_id}" / artifact_name / "data" / "nbadb"
        database_dir.mkdir(parents=True)
        database_path = database_dir / "nba.duckdb"
        _write_lane_db(
            database_path,
            alpha_rows=[1],
            beta_rows=[],
            journal_rows=[("franchise_history", "{}")],
        )
        database_paths.append(database_path)
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, lane),
        lane=lane,
        database_path=database_paths[0],
        artifact_name=artifact_name,
    )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=artifacts_dir,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
    )

    assert report["terminal_ready"] is False
    assert report["included_lane_ids"] == []
    assert report["current_lane_attestation_failures"] == {
        lane.lane_id: ["lane_database_ambiguous:2"]
    }


def test_checkpoint_rejects_previous_lanes_outside_narrowed_manifest(
    tmp_path: Path,
) -> None:
    retained_lane = FullExtractionLane(
        lane_id="reference-a",
        lane_index=0,
        lane_name="Reference A",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("endpoint_a",),
        timeout_seconds=1800,
        resume_only=True,
    )
    removed_lane = replace(
        retained_lane,
        lane_id="reference-b",
        lane_index=1,
        lane_name="Reference B",
        endpoints=("endpoint_b",),
    )
    manifest_path = tmp_path / "narrowed-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload([retained_lane])) + "\n",
        encoding="utf-8",
    )
    previous_checkpoint_dir = tmp_path / "previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    previous_database_path = previous_checkpoint_dir / "nba.duckdb"
    _write_lane_db(
        previous_database_path,
        alpha_rows=[1, 2],
        beta_rows=[],
        journal_rows=[("endpoint_a", "{}"), ("endpoint_b", "{}")],
    )
    previous_report_path = tmp_path / "previous-report.json"
    _write_checkpoint_report(
        previous_report_path,
        database_path=previous_database_path,
        lanes=[retained_lane, removed_lane],
        coverage_fingerprint=_coverage_fingerprint([retained_lane, removed_lane]),
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    output_dir = tmp_path / "checkpoint"

    with pytest.raises(
        ValueError,
        match="lanes outside the current manifest: reference-b",
    ):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            previous_checkpoint_dir=previous_checkpoint_dir,
            previous_checkpoint_report_path=previous_report_path,
            output_dir=output_dir,
            report_path=tmp_path / "checkpoint-report.json",
            run_id="67890",
        )

    assert not output_dir.exists()


def test_checkpoint_database_merges_previous_checkpoint_and_current_lanes(
    tmp_path: Path,
) -> None:
    previous_lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
        resume_only=True,
    )
    current_lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2016-2016",
        lane_index=1,
        lane_name="Historical game 2016",
        lane_kind="historical",
        season_start=2016,
        season_end=2016,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=5400,
    )
    lanes = [previous_lane, current_lane]
    manifest_path = tmp_path / "next-manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload(lanes)) + "\n", encoding="utf-8")

    previous_checkpoint_dir = tmp_path / "previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    previous_database_path = previous_checkpoint_dir / "nba.duckdb"
    _write_lane_db(
        previous_database_path,
        alpha_rows=[1, 2],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    previous_database_bytes = previous_database_path.read_bytes()
    previous_report_path = tmp_path / "previous-report.json"
    _write_checkpoint_report(
        previous_report_path,
        database_path=previous_database_path,
        lanes=[previous_lane],
    )

    metadata_dir = tmp_path / "metadata"
    lane_artifacts_dir = tmp_path / "lanes"
    current_run_id = "67890"
    current_artifact = _lane_artifact_dir(lane_artifacts_dir, current_lane, run_id=current_run_id)
    current_artifact.mkdir(parents=True)
    current_database_path = current_artifact / "nba.duckdb"
    _write_lane_db(
        current_database_path,
        alpha_rows=[2, 3],
        beta_rows=[9],
        journal_rows=[
            ("franchise_history", "{}"),
            (
                "box_score_summary",
                '{"game_id": "0021600001", "season": "2016-17"}',
            ),
        ],
    )
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, current_lane, run_id=current_run_id),
        lane=current_lane,
        database_path=current_database_path,
        run_id=current_run_id,
    )

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=lane_artifacts_dir,
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_report_path,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id=current_run_id,
    )

    assert report["checkpoint_generation"] == 2
    assert report["included_lane_ids"] == sorted([previous_lane.lane_id, current_lane.lane_id])
    assert report["included_run_ids"] == [TEST_RUN_ID, current_run_id]
    assert report["complete_lane_count"] == 2
    assert report["active_lane_count"] == 0
    assert report["terminal_ready"] is True
    assert report["table_row_counts"] == {"stg_alpha": 3, "stg_beta": 1}
    assert report["journal_row_count"] == 2
    assert report["merge_summary"]["base_database_copied"] is True
    assert report["merge_summary"]["merged_delta_database_count"] == 1
    assert previous_database_path.read_bytes() == previous_database_bytes

    conn = duckdb.connect(str(tmp_path / "checkpoint" / "nba.duckdb"))
    try:
        alpha_values = [
            row[0] for row in conn.execute("SELECT value FROM stg_alpha ORDER BY value").fetchall()
        ]
        journal_rows = conn.execute(
            "SELECT endpoint, params FROM _extraction_journal ORDER BY endpoint, params"
        ).fetchall()
    finally:
        conn.close()

    assert alpha_values == [1, 2, 3]
    assert journal_rows == [
        (
            "box_score_summary",
            '{"game_id": "0021600001", "season": "2016-17"}',
        ),
        ("franchise_history", "{}"),
    ]


def test_checkpoint_database_zero_delta_copies_previous_checkpoint(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
        resume_only=True,
    )
    manifest_path = tmp_path / "next-manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])) + "\n", encoding="utf-8")

    previous_checkpoint_dir = tmp_path / "previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    previous_database_path = previous_checkpoint_dir / "nba.duckdb"
    _write_lane_db(
        previous_database_path,
        alpha_rows=[1, 2],
        beta_rows=[9],
        journal_rows=[("franchise_history", "{}")],
    )
    previous_database_bytes = previous_database_path.read_bytes()
    previous_report_path = tmp_path / "previous-report.json"
    _write_checkpoint_report(
        previous_report_path,
        database_path=previous_database_path,
        lanes=[lane],
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    output_dir = tmp_path / "checkpoint"

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "no-current-lanes",
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_report_path,
        output_dir=output_dir,
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id="67890",
    )

    output_database_path = output_dir / "nba.duckdb"
    assert report["terminal_ready"] is True
    assert report["table_row_counts"] == {"stg_alpha": 2, "stg_beta": 1}
    assert report["journal_row_count"] == 1
    assert report["merge_summary"]["copy_fast_path"] is True
    assert report["merge_summary"]["merged_delta_database_count"] == 0
    assert report["merge_summary"]["merged_table_operations"] == 0
    assert output_database_path.read_bytes() == previous_database_bytes
    assert previous_database_path.read_bytes() == previous_database_bytes
    assert output_database_path.stat().st_ino != previous_database_path.stat().st_ino


def test_checkpoint_database_current_journal_wins_independent_of_path_sort(
    tmp_path: Path,
) -> None:
    previous_lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("shared_endpoint",),
        timeout_seconds=1800,
        resume_only=True,
    )
    current_lane = FullExtractionLane(
        lane_id="historical-game-shared-endpoint-no-season-type-2024-2024",
        lane_index=1,
        lane_name="Historical shared endpoint 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("shared_endpoint",),
        timeout_seconds=5400,
    )
    manifest_path = tmp_path / "next-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload([previous_lane, current_lane])) + "\n",
        encoding="utf-8",
    )

    params = '{"game_id": "0022400001", "season": "2024-25"}'
    previous_checkpoint_dir = tmp_path / "a-previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    previous_database_path = previous_checkpoint_dir / "nba.duckdb"
    _write_lane_db(
        previous_database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("shared_endpoint", params)],
    )
    conn = duckdb.connect(str(previous_database_path))
    try:
        conn.execute(
            "UPDATE _extraction_journal "
            "SET status = 'base', rows_extracted = 99, error_message = 'base artifact'"
        )
    finally:
        conn.close()
    previous_database_bytes = previous_database_path.read_bytes()

    previous_report_path = tmp_path / "previous-report.json"
    _write_checkpoint_report(
        previous_report_path,
        database_path=previous_database_path,
        lanes=[previous_lane],
    )
    metadata_dir = tmp_path / "metadata"
    lane_artifacts_dir = tmp_path / "z-current-lanes"
    current_run_id = "67890"
    current_artifact = _lane_artifact_dir(lane_artifacts_dir, current_lane, run_id=current_run_id)
    current_artifact.mkdir(parents=True)
    current_database_path = current_artifact / "nba.duckdb"
    _write_lane_db(
        current_database_path,
        alpha_rows=[2],
        beta_rows=[],
        journal_rows=[("shared_endpoint", params)],
    )
    _write_attested_metadata(
        _lane_metadata_path(metadata_dir, current_lane, run_id=current_run_id),
        lane=current_lane,
        database_path=current_database_path,
        run_id=current_run_id,
    )
    assert previous_database_path < current_database_path

    report = _build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=lane_artifacts_dir,
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_report_path,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id=current_run_id,
    )

    conn = duckdb.connect(report["output_path"], read_only=True)
    try:
        journal_rows = conn.execute(
            "SELECT endpoint, params, status, rows_extracted, error_message "
            "FROM _extraction_journal"
        ).fetchall()
    finally:
        conn.close()

    assert report["terminal_ready"] is True
    assert report["journal_row_count"] == 1
    assert report["merge_summary"]["journal_report"]["replaced_base_rows"] == 1
    assert report["merge_summary"]["journal_report"]["delete_batch_count"] == 1
    assert report["merge_summary"]["journal_report"]["insert_batch_count"] == 1
    assert journal_rows == [("shared_endpoint", params, "done", 1, None)]
    assert previous_database_path.read_bytes() == previous_database_bytes


def test_checkpoint_database_rejects_reused_reference_lane_id_with_new_coverage(
    tmp_path: Path,
) -> None:
    previous_lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
        resume_only=True,
    )
    current_lane = replace(
        previous_lane,
        endpoints=("all_time_leaders_grid",),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload([current_lane])) + "\n",
        encoding="utf-8",
    )
    previous_checkpoint_dir = tmp_path / "previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    previous_database_path = previous_checkpoint_dir / "nba.duckdb"
    _write_lane_db(
        previous_database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    previous_report_path = tmp_path / "previous-report.json"
    _write_checkpoint_report(
        previous_report_path,
        database_path=previous_database_path,
        lanes=[previous_lane],
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    output_dir = tmp_path / "checkpoint"

    with pytest.raises(ValueError, match="coverage identity mismatch"):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            previous_checkpoint_dir=previous_checkpoint_dir,
            previous_checkpoint_report_path=previous_report_path,
            output_dir=output_dir,
            report_path=tmp_path / "checkpoint-report.json",
        )

    assert not (output_dir / "nba.duckdb").exists()


def test_checkpoint_database_rejects_previous_database_without_report(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
        resume_only=True,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])) + "\n", encoding="utf-8")
    previous_checkpoint_dir = tmp_path / "previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    _write_lane_db(
        previous_checkpoint_dir / "nba.duckdb",
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    with pytest.raises(ValueError, match="directory and report path must be provided together"):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            previous_checkpoint_dir=previous_checkpoint_dir,
            output_dir=tmp_path / "checkpoint",
            report_path=tmp_path / "checkpoint-report.json",
        )


def test_checkpoint_database_rejects_tampered_previous_database(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
        resume_only=True,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])) + "\n", encoding="utf-8")
    previous_checkpoint_dir = tmp_path / "previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    previous_database_path = previous_checkpoint_dir / "nba.duckdb"
    _write_lane_db(
        previous_database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    previous_report_path = tmp_path / "previous-report.json"
    _write_checkpoint_report(
        previous_report_path,
        database_path=previous_database_path,
        lanes=[lane],
    )
    conn = duckdb.connect(str(previous_database_path))
    conn.execute("INSERT INTO stg_alpha VALUES (2)")
    conn.close()
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    with pytest.raises(ValueError, match="digest does not match"):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            previous_checkpoint_dir=previous_checkpoint_dir,
            previous_checkpoint_report_path=previous_report_path,
            output_dir=tmp_path / "checkpoint",
            report_path=tmp_path / "checkpoint-report.json",
        )


def test_checkpoint_database_does_not_trust_previous_lane_ids_without_previous_db(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2024-2024",
        lane_index=0,
        lane_name="Historical game 2024",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=5400,
    )
    manifest_path = tmp_path / "next-manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])) + "\n", encoding="utf-8")
    previous_report_path = tmp_path / "previous-report.json"
    previous_report_path.write_text(
        json.dumps(
            {
                "chain_id": TEST_CHAIN_ID,
                "run_id": TEST_RUN_ID,
                "artifact_name": (f"full-extraction-checkpoint-{TEST_CHAIN_ID}-iter-1"),
                "source_sha": TEST_SOURCE_SHA,
                "checkpoint_generation": 1,
                "coverage_fingerprint": _coverage_fingerprint([lane]),
                "included_lane_ids": [lane.lane_id],
                "included_lane_coverage_hashes": {lane.lane_id: _coverage_hash_for_lane(lane)},
                "included_run_ids": [TEST_RUN_ID],
                "database_sha256": "b" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    with pytest.raises(
        ValueError,
        match="Previous checkpoint artifact must contain exactly one nba.duckdb",
    ):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            previous_checkpoint_dir=tmp_path / "missing-checkpoint",
            previous_checkpoint_report_path=previous_report_path,
            output_dir=tmp_path / "checkpoint",
            report_path=tmp_path / "checkpoint-report.json",
            chain_id="chain",
            run_id="67890",
        )


def test_checkpoint_rejects_legacy_cross_product_lane_outside_manifest(
    tmp_path: Path,
) -> None:
    lanes = [
        FullExtractionLane(
            lane_id="cross-product-player-index-regular-season-2024-2024",
            lane_index=0,
            lane_name="Cross Product Historical 2024 (player_index)",
            lane_kind="cross_product",
            season_start=2024,
            season_end=2024,
            patterns=("player_team_season",),
            season_types=("Regular Season",),
            endpoints=("player_index",),
            timeout_seconds=6300,
        ),
        FullExtractionLane(
            lane_id="cross-product-video-details-regular-season-2024-2024",
            lane_index=1,
            lane_name="Cross Product Historical 2024 (video_details)",
            lane_kind="cross_product",
            season_start=2024,
            season_end=2024,
            patterns=("player_team_season",),
            season_types=("Regular Season",),
            endpoints=("video_details",),
            timeout_seconds=6300,
        ),
    ]
    workload_duckdb_path, workload_store, _workload_contract = _write_workload_contract(
        tmp_path,
        lane=lanes[0],
        params=[],
    )
    manifest_path = tmp_path / "next-manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload(lanes)) + "\n", encoding="utf-8")

    previous_checkpoint_dir = tmp_path / "previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    _write_lane_db(
        previous_checkpoint_dir / "nba.duckdb",
        alpha_rows=[1, 2],
        beta_rows=[],
        journal_rows=[
            ("player_index", '{"season": "2024-25"}'),
            ("video_details", '{"season": "2024-25"}'),
        ],
    )
    legacy_lane_id = "cross-product-regular-season-2024-2024"
    previous_report_path = tmp_path / "previous-report.json"
    _write_checkpoint_report(
        previous_report_path,
        database_path=previous_checkpoint_dir / "nba.duckdb",
        included_lane_ids=[legacy_lane_id],
        included_lane_coverage_hashes={legacy_lane_id: "b" * 64},
        workload_integrity=workload_store.integrity_attestation(),
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    output_dir = tmp_path / "checkpoint"
    with pytest.raises(ValueError, match=f"current manifest: {legacy_lane_id}"):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            previous_checkpoint_dir=previous_checkpoint_dir,
            previous_checkpoint_report_path=previous_report_path,
            output_dir=output_dir,
            report_path=tmp_path / "checkpoint-report.json",
            workload_duckdb_path=workload_duckdb_path,
            chain_id="chain",
            run_id="67890",
        )
    assert not output_dir.exists()


def test_checkpoint_rejects_legacy_historical_lane_outside_manifest(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-player_season-player-game-log-regular-season-2024-2024",
        lane_index=0,
        lane_name="Historical player season 2024 (player_game_log)",
        lane_kind="historical",
        season_start=2024,
        season_end=2024,
        patterns=("player_season",),
        season_types=("Regular Season",),
        endpoints=("player_game_log",),
        timeout_seconds=7200,
    )
    manifest_path = tmp_path / "next-manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])) + "\n", encoding="utf-8")

    previous_checkpoint_dir = tmp_path / "previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    _write_lane_db(
        previous_checkpoint_dir / "nba.duckdb",
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("player_game_log", '{"season": "2024-25"}')],
    )
    legacy_lane_id = "historical-player_season-regular-season-2024-2024"
    previous_report_path = tmp_path / "previous-report.json"
    _write_checkpoint_report(
        previous_report_path,
        database_path=previous_checkpoint_dir / "nba.duckdb",
        included_lane_ids=[legacy_lane_id],
        included_lane_coverage_hashes={legacy_lane_id: "b" * 64},
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    output_dir = tmp_path / "checkpoint"
    with pytest.raises(ValueError, match=f"current manifest: {legacy_lane_id}"):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            previous_checkpoint_dir=previous_checkpoint_dir,
            previous_checkpoint_report_path=previous_report_path,
            output_dir=output_dir,
            report_path=tmp_path / "checkpoint-report.json",
            chain_id="chain",
            run_id="67890",
        )
    assert not output_dir.exists()


def test_checkpoint_database_does_not_map_legacy_lane_without_previous_db(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="cross-product-player-index-regular-season-2024-2024",
        lane_index=0,
        lane_name="Cross Product Historical 2024 (player_index)",
        lane_kind="cross_product",
        season_start=2024,
        season_end=2024,
        patterns=("player_team_season",),
        season_types=("Regular Season",),
        endpoints=("player_index",),
        timeout_seconds=6300,
    )
    manifest_path = tmp_path / "next-manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])) + "\n", encoding="utf-8")
    previous_report_path = tmp_path / "previous-report.json"
    previous_report_path.write_text(
        json.dumps(
            {
                "chain_id": TEST_CHAIN_ID,
                "run_id": TEST_RUN_ID,
                "artifact_name": (f"full-extraction-checkpoint-{TEST_CHAIN_ID}-iter-1"),
                "source_sha": TEST_SOURCE_SHA,
                "checkpoint_generation": 1,
                "coverage_fingerprint": _coverage_fingerprint([]),
                "included_lane_ids": ["cross-product-regular-season-2024-2024"],
                "included_lane_coverage_hashes": {
                    "cross-product-regular-season-2024-2024": "b" * 64
                },
                "included_run_ids": [TEST_RUN_ID],
                "database_sha256": "b" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    with pytest.raises(
        ValueError,
        match="Previous checkpoint artifact must contain exactly one nba.duckdb",
    ):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            previous_checkpoint_dir=tmp_path / "missing-checkpoint",
            previous_checkpoint_report_path=previous_report_path,
            output_dir=tmp_path / "checkpoint",
            report_path=tmp_path / "checkpoint-report.json",
            chain_id="chain",
            run_id="67890",
        )


def test_checkpoint_rejects_legacy_lane_before_endpoint_evidence_mapping(
    tmp_path: Path,
) -> None:
    lanes = [
        FullExtractionLane(
            lane_id="cross-product-player-index-regular-season-2024-2024",
            lane_index=0,
            lane_name="Cross Product Historical 2024 (player_index)",
            lane_kind="cross_product",
            season_start=2024,
            season_end=2024,
            patterns=("player_team_season",),
            season_types=("Regular Season",),
            endpoints=("player_index",),
            timeout_seconds=6300,
        ),
        FullExtractionLane(
            lane_id="cross-product-video-details-regular-season-2024-2024",
            lane_index=1,
            lane_name="Cross Product Historical 2024 (video_details)",
            lane_kind="cross_product",
            season_start=2024,
            season_end=2024,
            patterns=("player_team_season",),
            season_types=("Regular Season",),
            endpoints=("video_details",),
            timeout_seconds=6300,
        ),
    ]
    manifest_path = tmp_path / "next-manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload(lanes)) + "\n", encoding="utf-8")

    previous_checkpoint_dir = tmp_path / "previous-checkpoint"
    previous_checkpoint_dir.mkdir()
    _write_lane_db(
        previous_checkpoint_dir / "nba.duckdb",
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("player_index", '{"season": "2024-25"}')],
    )
    previous_report_path = tmp_path / "previous-report.json"
    _write_checkpoint_report(
        previous_report_path,
        database_path=previous_checkpoint_dir / "nba.duckdb",
        included_lane_ids=["cross-product-regular-season-2024-2024"],
        included_lane_coverage_hashes={"cross-product-regular-season-2024-2024": "b" * 64},
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    output_dir = tmp_path / "checkpoint"
    with pytest.raises(
        ValueError,
        match="current manifest: cross-product-regular-season-2024-2024",
    ):
        _build_checkpoint_database(
            manifest_path=manifest_path,
            metadata_dir=metadata_dir,
            lane_artifacts_dir=tmp_path / "lanes",
            previous_checkpoint_dir=previous_checkpoint_dir,
            previous_checkpoint_report_path=previous_report_path,
            output_dir=output_dir,
            report_path=tmp_path / "checkpoint-report.json",
            chain_id="chain",
            run_id="67890",
        )
    assert not output_dir.exists()


def test_merge_final_database_uses_terminal_checkpoint(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
        resume_only=True,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest = manifest_payload([lane])
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir()
    _write_lane_db(
        checkpoint_dir / "nba.duckdb",
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    checkpoint_report_path = tmp_path / "checkpoint-report.json"
    checkpoint_report_path.write_text(
        json.dumps(
            {
                "terminal_ready": True,
                "checkpoint_generation": 3,
                "coverage_fingerprint": manifest["coverage_fingerprint"],
                "database_sha256": _file_sha256(checkpoint_dir / "nba.duckdb"),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = merge_final_database(
        artifacts_dir=tmp_path / "empty-lanes",
        output_dir=tmp_path / "final",
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
        checkpoint_report_path=checkpoint_report_path,
    )

    assert summary["merge_mode"] == "checkpoint"
    assert summary["checkpoint_generation"] == 3
    assert summary["table_row_counts"]["stg_alpha"] == 1
    assert (tmp_path / "final" / "nba.duckdb").exists()


def test_merge_final_database_falls_back_on_checkpoint_mismatch(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
        resume_only=True,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload([lane])) + "\n", encoding="utf-8")
    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_dir.mkdir()
    _write_lane_db(
        checkpoint_dir / "nba.duckdb",
        alpha_rows=[99],
        beta_rows=[],
        journal_rows=[("bad", "{}")],
    )
    checkpoint_report_path = tmp_path / "checkpoint-report.json"
    checkpoint_report_path.write_text(
        json.dumps(
            {
                "terminal_ready": True,
                "coverage_fingerprint": "mismatch",
                "database_sha256": _file_sha256(checkpoint_dir / "nba.duckdb"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    lane_artifacts_dir = tmp_path / "lanes"
    lane_artifact = lane_artifacts_dir / f"extraction-lane-chain-{lane.lane_id}"
    lane_artifact.mkdir(parents=True)
    _write_lane_db(
        lane_artifact / "nba.duckdb",
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )

    with pytest.raises(RuntimeError, match="Terminal checkpoint validation failed"):
        merge_final_database(
            artifacts_dir=lane_artifacts_dir,
            output_dir=tmp_path / "rejected",
            manifest_path=manifest_path,
            checkpoint_dir=checkpoint_dir,
            checkpoint_report_path=checkpoint_report_path,
        )

    summary = merge_final_database(
        artifacts_dir=lane_artifacts_dir,
        output_dir=tmp_path / "final",
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
        checkpoint_report_path=checkpoint_report_path,
        allow_artifact_fallback=True,
    )

    assert summary["merge_mode"] == "lane_artifacts"
    assert "coverage fingerprint mismatch" in summary["fallback_reason"]
    assert summary["merged_database_count"] == 1

    conn = duckdb.connect(str(tmp_path / "final" / "nba.duckdb"))
    try:
        alpha_values = [row[0] for row in conn.execute("SELECT value FROM stg_alpha").fetchall()]
    finally:
        conn.close()

    assert alpha_values == [1]


def test_merge_lane_databases_rejects_schema_mismatch_and_cleans_target(
    tmp_path: Path,
) -> None:
    lane_a = tmp_path / "lane-a"
    lane_b = tmp_path / "lane-b"
    lane_a.mkdir()
    lane_b.mkdir()

    _write_lane_db(
        lane_a / "nba.duckdb",
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("endpoint_a", "{}")],
    )

    conn = duckdb.connect(str(lane_b / "nba.duckdb"))
    try:
        conn.execute("CREATE TABLE stg_alpha (value VARCHAR)")
        conn.execute("INSERT INTO stg_alpha VALUES ('one')")
        conn.execute(
            """
            CREATE TABLE _extraction_journal (
                endpoint VARCHAR,
                params VARCHAR,
                status VARCHAR,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER
            )
            """
        )
    finally:
        conn.close()

    output_dir = tmp_path / "merged"
    with pytest.raises(ValueError, match="Schema mismatch while merging stg_alpha"):
        merge_lane_databases(artifacts_dir=tmp_path, output_dir=output_dir)

    assert not (output_dir / "nba.duckdb").exists()


def test_full_extraction_terminal_control_plane_handoff_e2e(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    completed_reference = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    completed_historical = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2016-2016",
        lane_index=1,
        lane_name="Historical game 2016",
        lane_kind="historical",
        season_start=2016,
        season_end=2016,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=5400,
    )
    contract_gap = FullExtractionLane(
        lane_id="historical-game-box-score-misc-no-season-type-1994-2005-split-1995-1995",
        lane_index=2,
        lane_name="Historical game box_score_misc 1995",
        lane_kind="historical",
        season_start=1995,
        season_end=1995,
        patterns=("game",),
        endpoints=("box_score_misc",),
        timeout_seconds=5400,
    )
    lanes = [completed_reference, completed_historical, contract_gap]
    contract_gap_row = _contract_blocked_row(contract_gap)
    pending_contract_gap_evidence = {
        "schema_version": 1,
        "contract_blocked_lanes": [contract_gap_row],
    }
    artifacts_dir = tmp_path / "artifacts" / "full-extraction"
    artifacts_dir.mkdir(parents=True)
    manifest_path = artifacts_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest_payload(
                lanes,
                chain_state=FullExtractionChainState(
                    vpn_quarantined_servers=("us111.nordvpn.com",),
                    artifact_run_ids=("26385964741",),
                ),
                chain_id=TEST_CHAIN_ID,
                workflow_source_sha=TEST_SOURCE_SHA,
            )
        )
        + "\n",
        encoding="utf-8",
    )

    metadata_dir = tmp_path / "lane-metadata"
    metadata_dir.mkdir()
    (metadata_dir / "reference-static.json").write_text(
        json.dumps(
            {
                "lane_id": completed_reference.lane_id,
                "lane_kind": "reference",
                "status": "complete",
                "raw_status": "complete",
                "vpn": {},
                "vpn_status": "connected",
                "endpoints": list(completed_reference.endpoints),
                "patterns": list(completed_reference.patterns),
                "state_artifact": {
                    "run_id": "26480824507",
                    "name": f"extraction-lane-chain-{completed_reference.lane_id}",
                    "sha256": "a" * 64,
                    "attested": True,
                    "uploaded": True,
                    "artifact_id": TEST_ARTIFACT_ID,
                    "artifact_digest": TEST_ARTIFACT_DIGEST,
                },
                "telemetry": {
                    "rows_persisted": 5,
                    "failed_calls": 0,
                    "journal_skips": 0,
                    "db_telemetry": {"running_calls": 0},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (metadata_dir / "historical-complete.json").write_text(
        json.dumps(
            {
                "lane_id": completed_historical.lane_id,
                "lane_kind": "historical",
                "status": "complete",
                "raw_status": "complete",
                "vpn": {},
                "vpn_status": "connected",
                "endpoints": list(completed_historical.endpoints),
                "patterns": list(completed_historical.patterns),
                "season_start": "2016",
                "season_end": "2016",
                "state_artifact": {
                    "run_id": "26480824507",
                    "name": f"extraction-lane-chain-{completed_historical.lane_id}",
                    "sha256": "a" * 64,
                    "attested": True,
                    "uploaded": True,
                    "artifact_id": TEST_ARTIFACT_ID,
                    "artifact_digest": TEST_ARTIFACT_DIGEST,
                },
                "telemetry": {
                    "rows_persisted": 7,
                    "failed_calls": 0,
                    "journal_skips": 0,
                    "db_telemetry": {"running_calls": 0},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (metadata_dir / "contract-gap.json").write_text(
        json.dumps(
            {
                "lane_id": contract_gap.lane_id,
                "lane_kind": "historical",
                "status": "pipeline_failure",
                "raw_status": "extract-error",
                "vpn": {},
                "vpn_status": "connected",
                "endpoints": list(contract_gap.endpoints),
                "patterns": list(contract_gap.patterns),
                "season_start": "1995",
                "season_end": "1995",
                "season_types": list(contract_gap.season_types),
                "context_measures": list(contract_gap.context_measures),
                "coverage_units_hash": _coverage_hash_for_lane(contract_gap),
                "support_rules": [
                    rule.to_dict()
                    for rule in contract_blocking_rules_for_lane(
                        endpoints=contract_gap.endpoints,
                        patterns=contract_gap.patterns,
                        season_start=contract_gap.season_start,
                        season_end=contract_gap.season_end,
                    )
                ],
                "telemetry": {
                    "rows_persisted": 0,
                    "failed_calls": 1258,
                    "journal_skips": 0,
                    "zero_row_reason": "contract_gap",
                    "db_telemetry": {"running_calls": 0},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    next_manifest_path = artifacts_dir / "next-manifest.json"
    assert (
        full_extraction_main(
            [
                "resume",
                "--lane-manifest-path",
                str(manifest_path),
                "--metadata-dir",
                str(metadata_dir),
                "--completed-artifact-run-id",
                "26480824507",
                "--output-path",
                str(next_manifest_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    next_payload = json.loads(next_manifest_path.read_text(encoding="utf-8"))
    next_manifest = normalize_manifest(next_payload)
    validate_manifest(list(next_manifest.lanes))
    assert next_payload["active_lane_count"] == 0
    assert next_payload["chain_id"] == TEST_CHAIN_ID
    assert next_payload["workflow_source_sha"] == TEST_SOURCE_SHA
    assert next_payload["matrix_lane_count"] == 0
    assert next_payload["resume_only_lane_count"] == 2
    assert next_payload["resume_summary"]["contract_blocked_lane_count"] == 1
    assert next_payload["resume_summary"]["outcome_counts"] == {
        "complete": 2,
        "contract_blocked": 1,
    }
    assert next_manifest.chain_state == FullExtractionChainState(
        vpn_quarantined_servers=("us111.nordvpn.com",),
        artifact_run_ids=("26385964741", "26480824507"),
        scheduler_rotation_cursor=3,
        iteration_budget=8,
        pending_contract_blocked_evidence=(contract_gap_row,),
        pending_contract_blocked_evidence_sha256=_hash_payload(pending_contract_gap_evidence),
    )
    assert [lane.lane_id for lane in next_manifest.lanes] == [
        completed_reference.lane_id,
        completed_historical.lane_id,
    ]
    assert all(lane.resume_only for lane in next_manifest.lanes)

    redispatch_json = json.dumps(
        redispatch_manifest_payload(
            list(next_manifest.lanes),
            chain_state=next_manifest.chain_state,
            chain_id=next_manifest.chain_id,
            workflow_source_sha=next_manifest.workflow_source_sha,
        ),
        separators=(",", ":"),
    )
    validate_workflow_dispatch_manifest_json(redispatch_json)
    redispatch_manifest = normalize_manifest(json.loads(redispatch_json))
    assert redispatch_manifest.chain_state == next_manifest.chain_state
    assert redispatch_manifest.chain_id == TEST_CHAIN_ID
    assert redispatch_manifest.workflow_source_sha == TEST_SOURCE_SHA

    audit_path = artifacts_dir / "extraction-audit.json"
    assert (
        full_extraction_main(
            [
                "audit",
                "--metadata-dir",
                str(metadata_dir),
                "--output-path",
                str(audit_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["blockers"] == []
    assert audit["rows_persisted"] == 12
    assert audit["failed_calls"] == 1258
    assert [row["lane_id"] for row in audit["contract_blocked_lanes"]] == [contract_gap.lane_id]

    lane_artifacts_dir = tmp_path / "lanes"
    reference_artifact = (
        lane_artifacts_dir
        / "run-26480824507"
        / (f"extraction-lane-chain-{completed_reference.lane_id}")
    )
    historical_artifact = (
        lane_artifacts_dir
        / "run-26480824507"
        / (f"extraction-lane-chain-{completed_historical.lane_id}")
    )
    reference_artifact.mkdir(parents=True)
    historical_artifact.mkdir(parents=True)
    _write_lane_db(
        reference_artifact / "nba.duckdb",
        alpha_rows=[1, 2],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    _write_lane_db(
        historical_artifact / "nba.duckdb",
        alpha_rows=[2, 3],
        beta_rows=[9],
        journal_rows=[
            ("franchise_history", "{}"),
            ("box_score_summary", '{"season": "2016-17"}'),
        ],
    )
    output_dir = tmp_path / "merged"
    assert (
        full_extraction_main(
            [
                "merge",
                "--artifacts-dir",
                str(lane_artifacts_dir),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    merge_summary = json.loads(capsys.readouterr().out)
    assert merge_summary["merged_database_count"] == 2
    assert merge_summary["table_reports"]["stg_alpha"]["inserted_rows"] == 3
    assert merge_summary["journal_report"]["inserted_rows"] == 2

    conn = duckdb.connect(str(output_dir / "nba.duckdb"))
    try:
        alpha_values = [
            row[0] for row in conn.execute("SELECT value FROM stg_alpha ORDER BY value").fetchall()
        ]
        beta_values = [
            row[0] for row in conn.execute("SELECT value FROM stg_beta ORDER BY value").fetchall()
        ]
        journal_rows = conn.execute(
            "SELECT endpoint, params FROM _extraction_journal ORDER BY endpoint, params"
        ).fetchall()
    finally:
        conn.close()

    assert alpha_values == [1, 2, 3]
    assert beta_values == [9]
    assert journal_rows == [
        ("box_score_summary", '{"season": "2016-17"}'),
        ("franchise_history", "{}"),
    ]


def test_full_extraction_nonterminal_redispatch_handoff_e2e(tmp_path: Path) -> None:
    completed_lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    timeout_lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v3-no-season-type-1962-1965",
        lane_index=1,
        lane_name="Historical date 1962-1965",
        lane_kind="historical",
        season_start=1962,
        season_end=1965,
        patterns=("date",),
        endpoints=("scoreboard_v3",),
        timeout_seconds=7200,
    )
    deferred_lane = FullExtractionLane(
        lane_id="historical-game-box-score-summary-no-season-type-2020-2023",
        lane_index=2,
        lane_name="Historical game 2020-2023",
        lane_kind="historical",
        season_start=2020,
        season_end=2023,
        patterns=("game",),
        endpoints=("box_score_summary",),
        timeout_seconds=7200,
    )
    payload = manifest_payload(
        [completed_lane, timeout_lane, deferred_lane],
        chain_state=FullExtractionChainState(vpn_quarantined_servers=("us001.nordvpn.com",)),
        max_matrix_lanes=2,
    )
    manifest = normalize_manifest(payload)
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "complete.json",
        lane_id=completed_lane.lane_id,
        status="complete",
        rows_persisted=4,
        endpoints=list(completed_lane.endpoints),
        patterns=list(completed_lane.patterns),
    )
    (metadata_dir / "timeout.json").write_text(
        json.dumps(
            {
                "lane_id": timeout_lane.lane_id,
                "status": "extract-timeout",
                "raw_status": "extract-timeout",
                "vpn": {"failed_servers": ["us002.nordvpn.com", "us002.nordvpn.com"]},
                "endpoints": list(timeout_lane.endpoints),
                "patterns": list(timeout_lane.patterns),
                "season_start": "1962",
                "season_end": "1965",
                "telemetry": {
                    "rows_persisted": 8,
                    "failed_calls": 0,
                    "journal_skips": 0,
                    "db_telemetry": {"running_calls": 0},
                },
                "state_artifact": {
                    "run_id": "12345",
                    "name": f"extraction-lane-chain-{timeout_lane.lane_id}",
                    "sha256": "a" * 64,
                    "required": True,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    next_lanes, next_chain_state, summary = build_resume_manifest(
        list(manifest.lanes),
        metadata_dir,
        chain_state=manifest.chain_state,
        attempted_lane_ids=manifest.matrix_lane_ids,
        completed_artifact_run_id="26480824507",
    )

    validate_manifest(next_lanes)
    assert summary["outcome_counts"] == {"complete": 1, "needs_resume": 1}
    assert summary["failure_reason_counts"] == {"extract-timeout": 1}
    assert summary["resume_only_lane_count"] == 1
    assert summary["active_lane_count"] == 5
    assert summary["deferred_lane_count"] == 1
    assert summary["split_lane_count"] == 4
    assert next_chain_state == FullExtractionChainState(
        vpn_quarantined_servers=("us001.nordvpn.com", "us002.nordvpn.com"),
        artifact_run_ids=("26480824507",),
        scheduler_rotation_cursor=2,
        iteration_budget=36,
    )

    child_lanes = [lane for lane in next_lanes if lane.parent_lane_id == timeout_lane.lane_id]
    assert [(lane.season_start, lane.season_end) for lane in child_lanes] == [
        (1962, 1962),
        (1963, 1963),
        (1964, 1964),
        (1965, 1965),
    ]
    by_id = {lane.lane_id: lane for lane in next_lanes}
    assert by_id[completed_lane.lane_id].resume_only is True
    assert by_id[deferred_lane.lane_id].last_failure_reason == ""
    assert by_id[deferred_lane.lane_id].failure_streak == 0

    next_payload = manifest_payload(next_lanes, chain_state=next_chain_state)
    redispatch_json = json.dumps(
        redispatch_manifest_payload(next_lanes, chain_state=next_chain_state),
        separators=(",", ":"),
    )
    validate_workflow_dispatch_manifest_json(redispatch_json)
    round_tripped = normalize_manifest(json.loads(redispatch_json))
    validate_manifest(list(round_tripped.lanes))
    assert next_payload["active_lane_count"] == 5
    assert next_payload["resume_only_lane_count"] == 1
    assert next_payload["matrix_lane_count"] == 5
    assert round_tripped.chain_state == next_chain_state


def test_resume_manifest_preserves_and_updates_checkpoint_state(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="reference-static",
        lane_index=0,
        lane_name="Reference Static",
        lane_kind="reference",
        season_start=None,
        season_end=None,
        patterns=("static",),
        endpoints=("franchise_history",),
        timeout_seconds=1800,
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "complete.json",
        lane_id=lane.lane_id,
        status="complete",
        rows_persisted=5,
        endpoints=list(lane.endpoints),
        patterns=list(lane.patterns),
    )

    _next_lanes, next_chain_state, _summary = build_resume_manifest(
        [lane],
        metadata_dir,
        chain_state=FullExtractionChainState(
            artifact_run_ids=("old-run",),
            latest_checkpoint_run_id="old-run",
            latest_checkpoint_artifact_name="checkpoint-old",
            latest_checkpoint_generation=1,
            latest_checkpoint_coverage_hash="old-hash",
        ),
        completed_artifact_run_id="new-run",
        latest_checkpoint_run_id="new-run",
        latest_checkpoint_artifact_name="checkpoint-new",
        latest_checkpoint_generation=2,
        latest_checkpoint_coverage_hash="new-hash",
    )

    assert next_chain_state == FullExtractionChainState(
        artifact_run_ids=("new-run",),
        latest_checkpoint_run_id="new-run",
        latest_checkpoint_artifact_name="checkpoint-new",
        latest_checkpoint_generation=2,
        latest_checkpoint_coverage_hash="new-hash",
        previous_checkpoint_run_id="old-run",
        previous_checkpoint_artifact_name="checkpoint-old",
        previous_checkpoint_generation=1,
        previous_checkpoint_coverage_hash="old-hash",
    )
