from __future__ import annotations

import json
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.orchestrate.extraction_contract import EndpointSupportRule
from nbadb.orchestrate.full_extraction_control import (
    FullExtractionChainState,
    FullExtractionLane,
    build_default_manifest,
    build_metadata_audit,
    build_resume_manifest,
    manifest_payload,
    merge_lane_databases,
    normalize_manifest,
    redispatch_manifest_payload,
    validate_manifest,
    validate_workflow_dispatch_manifest_json,
)
from nbadb.orchestrate.workload_profile import EndpointWorkloadProfile, WorkloadPlanningSnapshot

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
    assert {lane.endpoints for lane in date_lanes} == {("scoreboard_v2",), ("video_status",)}
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


def test_build_resume_manifest_splits_repeated_game_date_timeout_to_one_season(
    tmp_path: Path,
) -> None:
    lane = FullExtractionLane(
        lane_id="historical-date-scoreboard-v2-no-season-type-1962-1965",
        lane_index=0,
        lane_name="Historical date 1962-1965",
        lane_kind="historical",
        season_start=1962,
        season_end=1965,
        patterns=("date",),
        endpoints=("scoreboard_v2",),
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


def test_validate_manifest_rejects_active_lane_without_vpn() -> None:
    with pytest.raises(ValueError, match="active lanes must require VPN"):
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
