from __future__ import annotations

import json
import pathlib
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.orchestrate.extraction_contract import EndpointSupportRule
from nbadb.orchestrate.full_extraction_control import (
    FullExtractionChainState,
    FullExtractionLane,
    build_checkpoint_database,
    build_default_manifest,
    build_metadata_audit,
    build_resume_manifest,
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
            "db_telemetry": {"running_calls": 0},
        },
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


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
    conn.executemany(
        "INSERT INTO _extraction_journal VALUES "
        "(?, ?, 'done', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, NULL, 0)",
        journal_rows,
    )
    conn.close()


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

    assert [lane.lane_id for lane in lanes[:2]] == ["reference-static", "reference-player"]
    assert lanes[0].season_start is None
    assert lanes[0].endpoints == ("franchise_history",)
    assert lanes[1].endpoints == ("common_player_info",)

    game_lanes = [
        lane for lane in lanes if lane.lane_kind == "historical" and lane.patterns == ("game",)
    ]
    assert game_lanes[0].lane_id == (
        "historical-game-box-score-traditional-no-season-type-1996-1999"
    )
    assert game_lanes[-1].lane_id == (
        "historical-game-box-score-traditional-no-season-type-2024-2025"
    )
    assert all((lane.season_end - lane.season_start + 1) <= 4 for lane in game_lanes)
    assert {lane.endpoints for lane in game_lanes} == {("box_score_traditional",)}

    season_lanes = [
        lane for lane in lanes if lane.lane_kind == "historical" and lane.patterns == ("season",)
    ]
    assert season_lanes[0].lane_id == (
        "historical-season-regular-season-playoffs-pre-season-all-star-1946-1953"
    )
    assert season_lanes[-1].lane_id == (
        "historical-season-regular-season-playoffs-pre-season-all-star-2021-2025"
    )
    assert season_lanes[0].season_types == (
        "Regular Season",
        "Playoffs",
        "Pre Season",
        "All Star",
    )
    assert all((lane.season_end - lane.season_start + 1) <= 8 for lane in season_lanes)

    cross_product_lanes = [lane for lane in lanes if lane.lane_kind == "cross_product"]
    assert cross_product_lanes[0].lane_id == (
        "cross-product-regular-season-playoffs-pre-season-all-star-1946-1949"
    )
    assert cross_product_lanes[-1].lane_id == (
        "cross-product-regular-season-playoffs-pre-season-all-star-2022-2025"
    )
    assert len(cross_product_lanes) == 20
    assert all((lane.season_end - lane.season_start + 1) <= 4 for lane in cross_product_lanes)
    assert all(lane.lane_kind != "cross_product_blocked" for lane in lanes)


def test_chunk_profiles_preserve_coverage_and_contract_blocks() -> None:
    rows = [
        _support_row("scoreboard_v2", ["date"], 1946),
        _support_row("scoreboard_v3", ["date"], 1946),
        _support_row("box_score_traditional", ["game"], 1996),
        _support_row(
            "league_game_log",
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


def test_full_extraction_workflow_wires_chunk_profiles_and_checkpoints() -> None:
    workflow = (
        pathlib.Path(__file__).resolve().parents[3]
        / ".github"
        / "workflows"
        / "full-extraction.yml"
    ).read_text(encoding="utf-8")

    assert "chunk_profile:" in workflow
    assert 'default: "balanced-small"' in workflow
    assert "network_mode:" in workflow
    assert "direct_parallelism:" in workflow
    assert "direct_timeout_cap_minutes:" in workflow
    assert "NBADB_DIRECT_LANE_TIMEOUT_CAP_SECONDS" in workflow
    assert "effective-network-mode:" in workflow
    assert "Resolve effective network mode" in workflow
    assert "direct-no-vpn" in workflow
    assert "lane_control:" in workflow
    assert "checkpoint:" in workflow
    assert "dispatch_next:" in workflow
    assert "chain:" not in workflow

    assert "needs: [plan, preflight, extract, lane_control]" in workflow
    assert "needs: [plan, preflight, extract, lane_control, checkpoint]" in workflow
    assert "needs: [plan, preflight, lane_control, checkpoint]" in workflow
    assert "needs.checkpoint.result == 'success'" in workflow
    assert "needs.lane_control.outputs.active-lane-count != '0'" in workflow
    assert "needs.lane_control.outputs.active-lane-count == '0'" in workflow

    assert 'args+=(--chunk-profile "$CHUNK_PROFILE")' in workflow
    assert "--latest-checkpoint-run-id" in workflow
    assert "--latest-checkpoint-artifact-name" in workflow
    assert "full_extraction_control checkpoint" in workflow
    assert '--previous-checkpoint-report-path "$previous_report"' in workflow
    assert "--checkpoint-dir checkpoint-artifact" in workflow
    assert "--checkpoint-report-path checkpoint-artifact/checkpoint-report.json" in workflow
    assert "needs.preflight.outputs.effective-network-mode == 'direct'" in workflow
    assert '--chunk-profile "$CHUNK_PROFILE"' in workflow
    direct_parallel_expr = (
        "max-parallel: ${{ fromJSON("
        "needs.preflight.outputs.effective-network-mode == 'direct' "
        "&& inputs.direct_parallelism || inputs.vpn_parallelism) }}"
    )
    assert direct_parallel_expr in workflow
    assert '-f network_mode="$NETWORK_MODE"' in workflow
    assert '-f direct_parallelism="$DIRECT_PARALLELISM"' in workflow
    assert '-f direct_timeout_cap_minutes="$DIRECT_TIMEOUT_CAP_MINUTES"' in workflow
    assert '-f chunk_profile="$CHUNK_PROFILE"' in workflow


def test_build_default_manifest_chunks_reference_patterns_by_endpoint_load() -> None:
    rows = [
        _support_row("static_players", ["static"], None),
        *[_support_row(f"team_endpoint_{index:02d}", ["team"], None) for index in range(1, 14)],
        *[_support_row(f"player_endpoint_{index:02d}", ["player"], None) for index in range(1, 12)],
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]

    assert [lane.lane_id for lane in reference_lanes] == [
        "reference-static",
        "reference-team-01",
        "reference-team-02",
        "reference-player-01",
        "reference-player-02",
        "reference-player-03",
    ]
    assert reference_lanes[0].endpoints == ("static_players",)
    assert len(reference_lanes[1].endpoints) == 12
    assert len(reference_lanes[2].endpoints) == 1
    assert [len(lane.endpoints) for lane in reference_lanes[3:]] == [4, 4, 3]
    assert [lane.timeout_seconds for lane in reference_lanes] == [
        1800,
        3000,
        3000,
        3600,
        3600,
        3600,
    ]


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
    assert min(lane.season_start for lane in lanes if lane.season_start is not None) == 1946
    assert all((lane.season_end - lane.season_start + 1) <= 16 for lane in lanes)
    historical_endpoints = {endpoint for lane in lanes for endpoint in lane.endpoints}
    assert historical_endpoints == {
        "player_dashboard_clutch",
        "player_dash_game_splits",
        "player_game_logs_v2",
        "player_streak_finder",
        "shot_chart_detail",
    }


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
    assert len(historical_lanes) == 14
    assert min(lane.season_start for lane in historical_lanes) == 1946
    assert max(lane.season_end for lane in historical_lanes if lane.season_end is not None) >= 2025
    assert all((lane.season_end - lane.season_start + 1) <= 6 for lane in historical_lanes)
    assert {endpoint for lane in historical_lanes for endpoint in lane.endpoints} == {
        "player_dash_pt_pass",
        "player_dash_pt_reb",
        "player_dash_pt_shot_defend",
        "player_dash_pt_shots",
    }
    assert historical_lanes[0].season_types == (
        "Regular Season",
        "Playoffs",
        "Pre Season",
        "All Star",
    )
    assert historical_lanes[0].endpoints == (
        "player_dash_pt_pass",
        "player_dash_pt_reb",
        "player_dash_pt_shot_defend",
        "player_dash_pt_shots",
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

    assert [lane.lane_id for lane in reference_lanes] == [
        "reference-static",
        "reference-team-01",
        "reference-team-02",
        "reference-team-03",
        "reference-team-04",
    ]
    assert reference_lanes[0].endpoints == ("common_team_years",)
    assert reference_lanes[1].endpoints == ("team_details", "team_info_common")
    assert reference_lanes[2].endpoints == ("franchise_leaders",)
    assert reference_lanes[3].endpoints == ("franchise_players",)
    assert reference_lanes[4].endpoints == ("team_year_by_year",)


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


def test_build_default_manifest_keeps_selected_endpoints_scoped() -> None:
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

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        selected_endpoints=["league_game_log"],
    )

    assert lanes[0].lane_id == (
        "historical-season-regular-season-playoffs-pre-season-all-star-1946-1953"
    )
    assert lanes[-1].lane_id == (
        "historical-season-regular-season-playoffs-pre-season-all-star-2018-2025"
    )
    assert len(lanes) == 10
    assert all((lane.season_end - lane.season_start + 1) <= 8 for lane in lanes)


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

    cross_product_lanes = [lane for lane in lanes if lane.lane_kind == "cross_product"]
    assert cross_product_lanes[0].season_start == 1946
    assert cross_product_lanes[0].season_end == 1946
    assert cross_product_lanes[1].season_start == 1947
    assert cross_product_lanes[1].season_end < 1954


def test_build_default_manifest_rejects_zero_match_filters() -> None:
    rows = [
        _support_row("league_game_log", ["season"], None, season_type_contract_status="supported")
    ]

    with pytest.raises(ValueError, match="matched no support-matrix rows"):
        build_default_manifest(
            support_matrix_rows=rows,
            selected_endpoints=["does_not_exist"],
        )


def test_build_default_manifest_skips_blocked_cross_product_endpoints() -> None:
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
            season_type_contract_status="blocked",
        ),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)

    assert {lane.lane_kind for lane in lanes} == {"cross_product"}
    assert all("team_vs_player" not in lane.endpoints for lane in lanes)


def test_build_default_manifest_rejects_blocked_only_selection() -> None:
    rows = [
        _support_row(
            "team_vs_player",
            ["player_team_season"],
            1946,
            season_type_contract_status="blocked",
        )
    ]

    with pytest.raises(ValueError, match="produced no runnable lanes"):
        build_default_manifest(support_matrix_rows=rows)


def test_build_default_manifest_rejects_full_extraction_excluded_only_selection() -> None:
    rows = [_support_row("team_historical_leaders", ["team"], None)]

    with pytest.raises(ValueError, match="produced no runnable lanes"):
        build_default_manifest(support_matrix_rows=rows)


def test_build_default_manifest_allows_scoreboard_v2_with_documented_gaps() -> None:
    rows = [_support_row("scoreboard_v2", ["date"], 1946)]

    lanes = build_default_manifest(
        support_matrix_rows=rows,
        selected_endpoints=["scoreboard_v2"],
    )

    assert lanes
    assert {lane.endpoints for lane in lanes} == {("scoreboard_v2",)}
    assert [lane.lane_id for lane in lanes[:3]] == [
        "historical-date-scoreboard-v2-no-season-type-1946-1949",
        "historical-date-scoreboard-v2-no-season-type-1951-1953",
        "historical-date-scoreboard-v2-no-season-type-1955-1955",
    ]
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
    assert next_chain_state == FullExtractionChainState()
    assert summary == {
        "vpn_quarantined_server_count": 0,
        "active_lane_count": 1,
        "resume_only_lane_count": 1,
        "deferred_lane_count": 0,
        "blocked_lane_count": 0,
        "split_lane_count": 0,
        "contract_blocked_lane_count": 0,
        "outcome_counts": {"complete": 1, "needs_resume": 1},
        "failure_reason_counts": {"needs_resume": 1},
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
    assert all(child.failure_streak == 0 for child in next_lanes)
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
                "lane_id": "historical-game-box-score-summary-no-season-type-1994-2005",
                "lane_kind": "historical",
                "status": "contract_blocked",
                "raw_status": "extract-error",
                "vpn_status": "connected",
                "vpn": {},
                "endpoints": ["box_score_summary"],
                "support_rules": [
                    {
                        "endpoint_name": "box_score_summary",
                        "pattern": "game",
                        "classification": "contract_blocked",
                        "reason": "test rule",
                        "evidence": "tests",
                        "revalidation_command": "pytest",
                        "season_start": 1994,
                        "season_end": 2005,
                    }
                ],
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
            "lane_id": "historical-game-box-score-summary-no-season-type-1994-2005",
            "status": "contract_blocked",
            "raw_status": "extract-error",
            "reason": "contract_blocked",
            "endpoints": ["box_score_summary"],
        }
    ]
    assert [row["lane_id"] for row in audit["contract_blocked_lanes"]] == [
        "historical-game-box-score-summary-no-season-type-1994-2005"
    ]
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
    _write_lane_db(
        previous_checkpoint_dir / "nba.duckdb",
        alpha_rows=[1, 2],
        beta_rows=[],
        journal_rows=[("franchise_history", "{}")],
    )
    previous_report_path = tmp_path / "previous-report.json"
    previous_report_path.write_text(
        json.dumps(
            {
                "checkpoint_generation": 1,
                "included_lane_ids": [previous_lane.lane_id],
                "included_run_ids": ["old-run"],
            }
        )
        + "\n",
        encoding="utf-8",
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
    assert report["table_row_counts"]["stg_alpha"] == 3
    assert report["journal_row_count"] == 2

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
        json.dumps({"terminal_ready": True, "coverage_fingerprint": "mismatch"}) + "\n",
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

    summary = merge_final_database(
        artifacts_dir=lane_artifacts_dir,
        output_dir=tmp_path / "final",
        manifest_path=manifest_path,
        checkpoint_dir=checkpoint_dir,
        checkpoint_report_path=checkpoint_report_path,
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
        artifact_run_ids=("old-run", "new-run"),
        latest_checkpoint_run_id="new-run",
        latest_checkpoint_artifact_name="checkpoint-new",
        latest_checkpoint_generation=2,
        latest_checkpoint_coverage_hash="new-hash",
    )
