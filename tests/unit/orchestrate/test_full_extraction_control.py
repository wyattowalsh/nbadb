from __future__ import annotations

import json
from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.orchestrate.full_extraction_control import (
    FullExtractionChainState,
    FullExtractionLane,
    build_default_manifest,
    build_resume_manifest,
    manifest_payload,
    merge_lane_databases,
    normalize_manifest,
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

    assert [lane.lane_id for lane in lanes[:5]] == [
        "reference-static",
        "reference-player-01",
        "reference-player-02",
        "reference-player-03",
        "reference-player-04",
    ]
    assert lanes[0].season_start is None
    assert lanes[0].endpoints == ("franchise_history",)
    assert all(lane.endpoints == ("common_player_info",) for lane in lanes[1:5])
    assert [lane.player_shard_index for lane in lanes[1:5]] == [0, 1, 2, 3]
    assert all(lane.player_shard_count == 4 for lane in lanes[1:5])

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
        _support_row("player_streak_finder", ["player"], None),
        _support_row("player_dashboard_clutch", ["player"], None),
        _support_row("player_awards", ["player"], None),
        _support_row("player_career_stats", ["player"], None),
        _support_row("player_compare", ["player"], None),
        _support_row("player_dash_game_splits", ["player"], None),
        _support_row("player_dash_general_splits", ["player"], None),
        _support_row("player_dash_last_n_games", ["player"], None),
        _support_row("player_dash_shooting_splits", ["player"], None),
        _support_row("player_dash_team_perf", ["player"], None),
        _support_row("player_dash_yoy", ["player"], None),
        _support_row("player_next_games", ["player"], None),
        _support_row("shot_chart_detail", ["player"], None),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]

    assert [lane.lane_id for lane in reference_lanes] == [
        *(f"reference-player-{index:02d}" for index in range(1, 40))
    ]
    assert {(lane.endpoints, lane.timeout_seconds) for lane in reference_lanes} == {
        (("common_player_info",), 3000),
        (("player_profile_v2",), 5400),
        (("player_streak_finder",), 5400),
        (("player_dashboard_clutch",), 4800),
        (("player_awards",), 2400),
        (("player_career_stats",), 2400),
        (("player_compare",), 2400),
        (("player_dash_game_splits",), 4200),
        (("player_dash_general_splits",), 4200),
        (("player_dash_last_n_games",), 4200),
        (("player_dash_shooting_splits",), 4200),
        (("player_dash_team_perf",), 4200),
        (("player_dash_yoy",), 4200),
        (("player_next_games",), 4200),
        (("shot_chart_detail",), 7200),
    }
    common_player_info_lanes = [
        lane for lane in reference_lanes if lane.endpoints == ("common_player_info",)
    ]
    assert len(common_player_info_lanes) == 4
    assert [lane.player_shard_index for lane in common_player_info_lanes] == [0, 1, 2, 3]
    assert all(lane.player_shard_count == 4 for lane in common_player_info_lanes)
    player_awards_lanes = [lane for lane in reference_lanes if lane.endpoints == ("player_awards",)]
    assert len(player_awards_lanes) == 16
    assert [lane.player_shard_index for lane in player_awards_lanes] == list(range(16))
    assert all(lane.player_shard_count == 16 for lane in player_awards_lanes)
    player_career_stats_lanes = [
        lane for lane in reference_lanes if lane.endpoints == ("player_career_stats",)
    ]
    assert len(player_career_stats_lanes) == 4
    assert [lane.player_shard_index for lane in player_career_stats_lanes] == [0, 1, 2, 3]
    assert all(lane.player_shard_count == 4 for lane in player_career_stats_lanes)
    player_compare_lanes = [
        lane for lane in reference_lanes if lane.endpoints == ("player_compare",)
    ]
    assert len(player_compare_lanes) == 4
    assert [lane.player_shard_index for lane in player_compare_lanes] == [0, 1, 2, 3]
    assert all(lane.player_shard_count == 4 for lane in player_compare_lanes)
    assert all(lane.use_vpn is True for lane in reference_lanes)


def test_build_default_manifest_skips_full_extraction_excluded_endpoints() -> None:
    rows = [
        _support_row("common_team_years", ["static"], None),
        _support_row("team_historical_leaders", ["team"], None),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]

    assert [lane.lane_id for lane in reference_lanes] == ["reference-static"]
    assert reference_lanes[0].endpoints == ("common_team_years",)


def test_build_default_manifest_skips_full_extraction_excluded_player_tracking_endpoints() -> None:
    rows = [
        _support_row("player_dash_game_splits", ["player"], None),
        _support_row("player_dash_pt_pass", ["player"], None),
        _support_row("player_dash_pt_reb", ["player"], None),
        _support_row("player_dash_pt_shot_defend", ["player"], None),
        _support_row("player_dash_pt_shots", ["player"], None),
    ]

    lanes = build_default_manifest(support_matrix_rows=rows)
    reference_lanes = [lane for lane in lanes if lane.lane_kind == "reference"]

    assert [lane.lane_id for lane in reference_lanes] == ["reference-player"]
    assert reference_lanes[0].endpoints == ("player_dash_game_splits",)


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


def test_build_default_manifest_rejects_full_extraction_excluded_only_selection() -> None:
    rows = [_support_row("team_historical_leaders", ["team"], None)]

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

    next_lanes, next_chain_state, summary = build_resume_manifest(lanes, metadata_dir)

    by_id = {lane.lane_id: lane for lane in next_lanes}
    assert by_id["reference-static"].resume_only is True
    active_lane = by_id["historical-season-no-season-type-1946-1963"]
    assert active_lane.resume_only is False
    assert active_lane.failure_streak == 1
    assert active_lane.last_failure_reason == "incomplete"
    assert next_chain_state == FullExtractionChainState()
    assert summary == {
        "vpn_quarantined_server_count": 0,
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


def test_validate_manifest_rejects_partial_player_shard_configuration() -> None:
    with pytest.raises(ValueError, match="player_shard_index/player_shard_count"):
        validate_manifest(
            [
                FullExtractionLane(
                    lane_id="reference-player-01",
                    lane_index=0,
                    lane_name="Reference Player 1/18",
                    lane_kind="reference",
                    season_start=None,
                    season_end=None,
                    patterns=("player",),
                    use_vpn=True,
                    resume_only=False,
                    timeout_seconds=3000,
                    player_shard_index=0,
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
                "status": "vpn_connect_timeout",
                "vpn": {
                    "failed_servers": [
                        "us123.nordvpn.com",
                        "us456.nordvpn.com",
                        "us123.nordvpn.com",
                    ]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    for shard_index in range(1, 5):
        _write_metadata(
            metadata_dir / f"reference-player-{shard_index:02d}.json",
            lane_id=f"reference-player-{shard_index:02d}",
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
    assert all(
        by_id[f"reference-player-{shard_index:02d}"].resume_only is True
        for shard_index in range(1, 5)
    )
    assert by_id["reference-static"].last_failure_reason == "vpn_connect_timeout"


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
                player_shard_index=0,
                player_shard_count=4,
            )
        ],
        chain_state=FullExtractionChainState(
            vpn_quarantined_servers=("us101.nordvpn.com", "us202.nordvpn.com")
        ),
    )

    manifest = normalize_manifest(payload)

    assert manifest.chain_state == FullExtractionChainState(
        vpn_quarantined_servers=("us101.nordvpn.com", "us202.nordvpn.com")
    )
    assert manifest.lanes[0].lane_id == "reference-static"
    assert manifest.lanes[0].player_shard_index == 0
    assert manifest.lanes[0].player_shard_count == 4


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
