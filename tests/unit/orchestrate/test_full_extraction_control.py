from __future__ import annotations

import json
import math
import pathlib
from dataclasses import replace
from typing import TYPE_CHECKING

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
    _coverage_hash_for_lane,
    _coverage_units_for_lane,
    _file_sha256,
    _merge_database_paths,
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
    from pathlib import Path


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
    rows_persisted: int = 0,
    failed_calls: int = 0,
    running_calls: int = 0,
    endpoints: list[str] | None = None,
    patterns: list[str] | None = None,
    season_start: int | None = None,
    season_end: int | None = None,
) -> None:
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
            "rows_persisted": rows_persisted,
            "failed_calls": failed_calls,
            "journal_skips": 0,
            "db_telemetry": {"running_calls": running_calls},
        },
    }
    if rows_persisted > 0:
        payload["state_artifact"] = {
            "run_id": "12345",
            "name": f"extraction-lane-chain-{lane_id}",
            "sha256": "a" * 64,
            "required": True,
        }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_attested_metadata(
    path: Path,
    *,
    lane: FullExtractionLane,
    database_path: Path,
    lane_name: str | None = None,
    workload_contract: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "metadata_schema_version": 3,
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
        "database_sha256": _file_sha256(database_path),
        "state_artifact": {"sha256": _file_sha256(database_path)},
    }
    if workload_contract is not None:
        payload["workload_contract"] = workload_contract
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


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
    artifact_dir = tmp_path / "lanes" / f"extraction-lane-chain-{lane.lane_id}"
    artifact_dir.mkdir(parents=True)
    database_path = artifact_dir / "nba.duckdb"
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
    metadata_dir.mkdir()
    _write_attested_metadata(
        metadata_dir / "lane.json",
        lane=lane,
        database_path=database_path,
        workload_contract=workload_contract,
    )
    return build_checkpoint_database(
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
    workload_integrity: dict[str, object] | None = None,
) -> None:
    lanes = lanes or []
    lane_ids = included_lane_ids or [lane.lane_id for lane in lanes]
    path.write_text(
        json.dumps(
            {
                "checkpoint_generation": checkpoint_generation,
                "included_lane_ids": lane_ids,
                "included_lane_coverage_hashes": {
                    lane.lane_id: _coverage_hash_for_lane(lane) for lane in lanes
                },
                "included_run_ids": included_run_ids or ["old-run"],
                "database_sha256": _file_sha256(database_path),
                "workload_integrity": workload_integrity,
            }
        )
        + "\n",
        encoding="utf-8",
    )


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
    direct_parallelism_block = _workflow_input_block(workflow, "direct_parallelism")
    max_iterations_block = _workflow_input_block(workflow, "max_iterations")

    assert "chunk_profile:" in workflow
    assert 'default: "standard"' in chunk_profile_block
    assert "network_mode:" in workflow
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
    assert all("-ctx-" in lane.lane_id for lane in video_lanes)
    assert all(1 <= len(lane.context_measures) <= 3 for lane in video_lanes)
    assert {
        context_measure for lane in video_lanes for context_measure in lane.context_measures
    } == set(VIDEO_CONTEXT_MEASURES)


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
            ("1946-47", "Regular Season"): 4_000,
            ("1947-48", "Regular Season"): 4_000,
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
    assert cross_product_spans[0] == (1946, 1946)
    assert cross_product_spans[1][0] == 1947
    assert cross_product_spans[1][1] < 1954


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
    ["cancelled", "vpn_auth_failure", "vpn_connect_timeout"],
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

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

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


def test_build_resume_manifest_allows_missing_attempted_metadata_for_manual_resume(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-box-score-defensive-no-season-type-1946-1949",
        lane_index=0,
        lane_name="Historical game 1946-1949",
        lane_kind="historical",
        season_start=1946,
        season_end=1949,
        patterns=("game",),
        endpoints=("box_score_defensive",),
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
                    "name": "extraction-lane-chain-lane",
                    "sha256": "a" * 64,
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
    assert resumed.state_artifact_name == "extraction-lane-chain-lane"
    assert resumed.state_artifact_digest == "a" * 64
    assert summary["durable_state_lane_count"] == 1
    assert summary["outcome_counts"] == {"needs_resume": 1}
    assert summary["failure_reason_counts"] == {"extract-timeout": 1}


def test_build_resume_manifest_splits_timeout_lanes(tmp_path: Path) -> None:
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
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id="historical-game-box-score-summary-no-season-type-1994-2005",
        status="extract-timeout",
        rows_persisted=12,
    )

    next_lanes, _next_chain_state, summary = build_resume_manifest([lane], metadata_dir)

    validate_manifest(next_lanes)
    assert [child.season_start for child in next_lanes] == [1994, 1998, 2002]
    assert [child.season_end for child in next_lanes] == [1997, 2001, 2005]
    assert all(child.parent_lane_id == lane.lane_id for child in next_lanes)
    assert all(child.split_generation == 1 for child in next_lanes)
    assert all(child.failure_streak == 1 for child in next_lanes)
    assert all(child.class_failure_streak == 1 for child in next_lanes)
    assert all(child.last_failure_class == "timeout_progress" for child in next_lanes)
    assert summary["active_lane_count"] == 3
    assert summary["split_lane_count"] == 3
    assert summary["outcome_counts"] == {"needs_resume": 1}


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
        ),
    )

    manifest = normalize_manifest(payload)

    assert manifest.chain_state == FullExtractionChainState(
        vpn_quarantined_servers=("us101.nordvpn.com", "us202.nordvpn.com"),
        artifact_run_ids=("12345",),
        iteration_budget=8,
    )
    assert manifest.lanes[0].lane_id == "reference-static"
    assert manifest.matrix_lane_ids == frozenset({"reference-static"})


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
    contract_lane_id = "historical-game-box-score-misc-no-season-type-1995-1995"
    support_rules = [
        rule.to_dict()
        for rule in contract_blocking_rules_for_lane(
            endpoints=("box_score_misc",),
            patterns=("game",),
            season_start=1995,
            season_end=1995,
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
                "lane_id": contract_lane_id,
                "lane_kind": "historical",
                "status": "contract_blocked",
                "raw_status": "extract-error",
                "vpn_status": "connected",
                "vpn": {},
                "endpoints": ["box_score_misc"],
                "patterns": ["game"],
                "season_start": "1995",
                "season_end": "1995",
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
            "lane_id": contract_lane_id,
            "status": "contract_blocked",
            "raw_status": "extract-error",
            "reason": "contract_blocked",
            "failure_class": "",
            "endpoints": ["box_score_misc"],
        }
    ]
    assert [row["lane_id"] for row in audit["contract_blocked_lanes"]] == [contract_lane_id]
    assert audit["pipeline_failure_lanes"] == []


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

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "reference.json",
        lane_id=reference_lane.lane_id,
        status="complete",
        rows_persisted=2,
        endpoints=list(reference_lane.endpoints),
        patterns=list(reference_lane.patterns),
    )
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id=historical_lane.lane_id,
        status="complete",
        rows_persisted=3,
        endpoints=list(historical_lane.endpoints),
        patterns=list(historical_lane.patterns),
        season_start=historical_lane.season_start,
        season_end=historical_lane.season_end,
    )

    artifacts_dir = tmp_path / "artifacts"
    reference_artifact = artifacts_dir / f"extraction-lane-chain-{reference_lane.lane_id}"
    historical_artifact = artifacts_dir / f"extraction-lane-chain-{historical_lane.lane_id}"
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
        alpha_rows=[3],
        beta_rows=[9],
        journal_rows=[("box_score_summary", '{"season": "2024-25"}')],
    )

    checkpoint_dir = tmp_path / "checkpoint"
    checkpoint_report_path = checkpoint_dir / "checkpoint-report.json"
    checkpoint_report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=artifacts_dir,
        output_dir=checkpoint_dir,
        report_path=checkpoint_report_path,
        chain_id="local-sim",
        run_id="run-1",
    )

    assert checkpoint_report["terminal_ready"] is True
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

    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "missing-lane-artifacts",
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="local-sim",
        run_id="run-1",
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
    artifact_dir = tmp_path / "lanes" / f"extraction-lane-chain-{lane.lane_id}"
    artifact_dir.mkdir(parents=True)
    database_path = artifact_dir / "nba.duckdb"
    duckdb.connect(str(database_path)).close()
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_attested_metadata(
        metadata_dir / "lane.json",
        lane=lane,
        database_path=database_path,
    )

    report = build_checkpoint_database(
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
    artifact_dir = tmp_path / "lanes" / f"extraction-lane-chain-{lane.lane_id}"
    artifact_dir.mkdir(parents=True)
    database_path = artifact_dir / "nba.duckdb"
    _write_lane_db(
        database_path,
        alpha_rows=[1],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_attested_metadata(
        metadata_dir / "lane.json",
        lane=lane,
        database_path=database_path,
        lane_name="Wrong Lane",
    )

    report = build_checkpoint_database(
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

    report = build_checkpoint_database(
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

    report = build_checkpoint_database(
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
    original_a = tmp_path / "original-a.duckdb"
    original_b = tmp_path / "original-b.duckdb"
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
    metadata_dir.mkdir()
    _write_attested_metadata(
        metadata_dir / "a.json",
        lane=lanes[0],
        database_path=original_a,
    )
    _write_attested_metadata(
        metadata_dir / "b.json",
        lane=lanes[1],
        database_path=original_b,
    )
    artifact_root = tmp_path / "lanes"
    artifact_a = artifact_root / f"extraction-lane-chain-{lanes[0].lane_id}"
    artifact_b = artifact_root / f"extraction-lane-chain-{lanes[1].lane_id}"
    artifact_a.mkdir(parents=True)
    artifact_b.mkdir(parents=True)
    original_b.replace(artifact_a / "nba.duckdb")
    original_a.replace(artifact_b / "nba.duckdb")

    report = build_checkpoint_database(
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
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "current.json",
        lane_id=current_lane.lane_id,
        status="complete",
        rows_persisted=3,
        endpoints=list(current_lane.endpoints),
        patterns=list(current_lane.patterns),
        season_start=current_lane.season_start,
        season_end=current_lane.season_end,
    )
    lane_artifacts_dir = tmp_path / "lanes"
    current_artifact = lane_artifacts_dir / f"extraction-lane-chain-{current_lane.lane_id}"
    current_artifact.mkdir(parents=True)
    _write_lane_db(
        current_artifact / "nba.duckdb",
        alpha_rows=[2, 3],
        beta_rows=[9],
        journal_rows=[
            ("franchise_history", "{}"),
            ("box_score_summary", '{"season": "2016-17"}'),
        ],
    )

    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=lane_artifacts_dir,
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_report_path,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id="current-run",
    )

    assert report["checkpoint_generation"] == 2
    assert report["included_lane_ids"] == sorted([previous_lane.lane_id, current_lane.lane_id])
    assert report["included_run_ids"] == ["old-run", "current-run"]
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
        ("box_score_summary", '{"season": "2016-17"}'),
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

    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "no-current-lanes",
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_report_path,
        output_dir=output_dir,
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id="current-run",
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

    params = '{"season": "2024-25"}'
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
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "current.json",
        lane_id=current_lane.lane_id,
        status="complete",
        rows_persisted=1,
        endpoints=list(current_lane.endpoints),
        patterns=list(current_lane.patterns),
        season_start=current_lane.season_start,
        season_end=current_lane.season_end,
    )
    lane_artifacts_dir = tmp_path / "z-current-lanes"
    current_artifact = lane_artifacts_dir / f"extraction-lane-chain-{current_lane.lane_id}"
    current_artifact.mkdir(parents=True)
    current_database_path = current_artifact / "nba.duckdb"
    _write_lane_db(
        current_database_path,
        alpha_rows=[2],
        beta_rows=[],
        journal_rows=[("shared_endpoint", params)],
    )
    assert previous_database_path < current_database_path

    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=lane_artifacts_dir,
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_report_path,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id="current-run",
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
        build_checkpoint_database(
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

    with pytest.raises(ValueError, match="no readable checkpoint report"):
        build_checkpoint_database(
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
        build_checkpoint_database(
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
                "checkpoint_generation": 1,
                "included_lane_ids": [lane.lane_id],
                "included_run_ids": ["old-run"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        previous_checkpoint_dir=tmp_path / "missing-checkpoint",
        previous_checkpoint_report_path=previous_report_path,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id="current-run",
    )

    assert report["terminal_ready"] is False
    assert report["complete_lane_count"] == 0
    assert report["active_lane_count"] == 1
    assert report["included_lane_ids"] == []
    assert report["included_run_ids"] == ["current-run"]
    assert report["missing_lane_ids"] == [lane.lane_id]


def test_checkpoint_database_maps_legacy_cross_product_lane_ids(
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
        workload_integrity=workload_store.integrity_attestation(),
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_report_path,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        workload_duckdb_path=workload_duckdb_path,
        chain_id="chain",
        run_id="current-run",
    )

    assert report["terminal_ready"] is True
    assert report["active_lane_count"] == 0
    assert report["complete_lane_count"] == 2
    assert report["compatible_previous_lane_ids"] == sorted(lane.lane_id for lane in lanes)
    assert report["included_lane_ids"] == sorted(
        [legacy_lane_id, *[lane.lane_id for lane in lanes]]
    )


def test_checkpoint_database_maps_legacy_historical_endpoint_group_lane_ids(
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
    )
    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()

    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_report_path,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id="current-run",
    )

    assert report["terminal_ready"] is True
    assert report["active_lane_count"] == 0
    assert report["complete_lane_count"] == 1
    assert report["compatible_previous_lane_ids"] == [lane.lane_id]
    assert report["included_lane_ids"] == sorted([legacy_lane_id, lane.lane_id])


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
                "checkpoint_generation": 1,
                "included_lane_ids": ["cross-product-regular-season-2024-2024"],
                "included_run_ids": ["old-run"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        previous_checkpoint_dir=tmp_path / "missing-checkpoint",
        previous_checkpoint_report_path=previous_report_path,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id="current-run",
    )

    assert report["terminal_ready"] is False
    assert report["active_lane_count"] == 1
    assert report["complete_lane_count"] == 0
    assert report["compatible_previous_lane_ids"] == []
    assert report["missing_lane_ids"] == [lane.lane_id]


def test_checkpoint_database_does_not_map_legacy_lane_missing_endpoint_evidence(
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
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    report = build_checkpoint_database(
        manifest_path=manifest_path,
        metadata_dir=metadata_dir,
        lane_artifacts_dir=tmp_path / "lanes",
        previous_checkpoint_dir=previous_checkpoint_dir,
        previous_checkpoint_report_path=previous_report_path,
        output_dir=tmp_path / "checkpoint",
        report_path=tmp_path / "checkpoint-report.json",
        chain_id="chain",
        run_id="current-run",
    )

    assert report["terminal_ready"] is False
    assert report["active_lane_count"] == 1
    assert report["complete_lane_count"] == 1
    assert report["compatible_previous_lane_ids"] == [lanes[0].lane_id]
    assert report["missing_lane_ids"] == [lanes[1].lane_id]


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
    )
    assert [lane.lane_id for lane in next_manifest.lanes] == [
        completed_reference.lane_id,
        completed_historical.lane_id,
    ]
    assert all(lane.resume_only for lane in next_manifest.lanes)

    redispatch_json = json.dumps(
        redispatch_manifest_payload(
            list(next_manifest.lanes), chain_state=next_manifest.chain_state
        ),
        separators=(",", ":"),
    )
    validate_workflow_dispatch_manifest_json(redispatch_json)
    assert normalize_manifest(json.loads(redispatch_json)).chain_state == next_manifest.chain_state

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
