from __future__ import annotations

import json
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.orchestrate.full_extraction_control import (
    FullExtractionLane,
    build_default_manifest,
    build_resume_manifest,
    merge_lane_databases,
    validate_manifest,
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


def _write_metadata(path: Path, *, lane_id: str, status: str) -> None:
    path.write_text(json.dumps({"lane_id": lane_id, "status": status}) + "\n", encoding="utf-8")


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
    assert [lane.lane_id for lane in game_lanes] == [
        "historical-game-no-season-type-1996-2007",
        "historical-game-no-season-type-2008-2019",
        "historical-game-no-season-type-2020-2025",
    ]
    assert all((lane.season_end - lane.season_start + 1) <= 12 for lane in game_lanes)

    season_lanes = [
        lane for lane in lanes if lane.lane_kind == "historical" and lane.patterns == ("season",)
    ]
    assert [lane.lane_id for lane in season_lanes] == [
        "historical-season-regular-season-playoffs-pre-season-all-star-1946-1963",
        "historical-season-regular-season-playoffs-pre-season-all-star-1964-1981",
        "historical-season-regular-season-playoffs-pre-season-all-star-1982-1999",
        "historical-season-regular-season-playoffs-pre-season-all-star-2000-2012",
        "historical-season-regular-season-playoffs-pre-season-all-star-2013-2025",
    ]
    assert season_lanes[0].season_types == (
        "Regular Season",
        "Playoffs",
        "Pre Season",
        "All Star",
    )
    assert all((lane.season_end - lane.season_start + 1) <= 18 for lane in season_lanes)

    cross_product_lanes = [lane for lane in lanes if lane.lane_kind == "cross_product"]
    assert cross_product_lanes[0].lane_id == (
        "cross-product-regular-season-playoffs-pre-season-all-star-1946-1953"
    )
    assert cross_product_lanes[-1].lane_id == (
        "cross-product-regular-season-playoffs-pre-season-all-star-2018-2025"
    )
    assert len(cross_product_lanes) == 10
    assert all((lane.season_end - lane.season_start + 1) <= 8 for lane in cross_product_lanes)
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
    assert [len(lane.endpoints) for lane in reference_lanes[3:]] == [5, 5, 1]
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

    assert [lane.lane_id for lane in reference_lanes] == [
        "reference-team-01",
        "reference-team-02",
    ]
    expected_primary_team_endpoints = tuple(f"team_endpoint_{index:02d}" for index in range(1, 8))
    assert reference_lanes[0].endpoints == expected_primary_team_endpoints
    assert reference_lanes[0].timeout_seconds == 3000
    assert reference_lanes[1].endpoints == ("team_historical_leaders",)
    assert reference_lanes[1].timeout_seconds == 4200


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

    assert [lane.lane_id for lane in lanes] == [
        "historical-season-regular-season-playoffs-pre-season-all-star-1946-1963",
        "historical-season-regular-season-playoffs-pre-season-all-star-1964-1981",
        "historical-season-regular-season-playoffs-pre-season-all-star-1982-1999",
        "historical-season-regular-season-playoffs-pre-season-all-star-2000-2017",
        "historical-season-regular-season-playoffs-pre-season-all-star-2018-2025",
    ]


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


def test_build_resume_manifest_marks_completed_lanes_resume_only(tmp_path: Path) -> None:
    rows = [
        _support_row("franchise_history", ["static"], None),
        _support_row("league_game_log", ["season"], None),
    ]
    lanes = build_default_manifest(support_matrix_rows=rows)

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(metadata_dir / "reference.json", lane_id="reference-static", status="complete")
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id="historical-season-no-season-type-1946-1963",
        status="incomplete",
    )

    next_lanes, summary = build_resume_manifest(lanes, metadata_dir)

    by_id = {lane.lane_id: lane for lane in next_lanes}
    assert by_id["reference-static"].resume_only is True
    active_lane = by_id["historical-season-no-season-type-1946-1963"]
    assert active_lane.resume_only is False
    assert active_lane.failure_streak == 1
    assert active_lane.last_failure_reason == "incomplete"
    assert summary == {
        "active_lane_count": 5,
        "resume_only_lane_count": 1,
        "blocked_lane_count": 0,
        "failure_reason_counts": {"incomplete": 1, "missing-metadata": 4},
    }


def test_build_resume_manifest_stops_after_repeated_failure_cap(tmp_path: Path) -> None:
    lane = FullExtractionLane(
        lane_id="historical-game-no-season-type-1996-2007",
        lane_index=0,
        lane_name="Historical game 1996-2007",
        lane_kind="historical",
        season_start=1996,
        season_end=2007,
        patterns=("game",),
        timeout_seconds=7200,
        failure_streak=2,
        last_failure_reason="extract-timeout",
    )

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    _write_metadata(
        metadata_dir / "historical.json",
        lane_id="historical-game-no-season-type-1996-2007",
        status="extract-timeout",
    )

    with pytest.raises(ValueError, match="chain safety cap"):
        build_resume_manifest([lane], metadata_dir)


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
    assert summary["merged_table_operations"] >= 2

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
