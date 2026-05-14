from __future__ import annotations

from pathlib import Path

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.orchestrate.staging_map import STAGING_MAP


def test_player_support_matrix_family_chunk() -> None:
    project_root = Path(__file__).resolve().parents[3]
    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=list(STAGING_MAP),
    )

    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={
            "LeaguePlayerOnDetails",
            "PlayerCareerByCollege",
            "PlayerCareerByCollegeRollup",
            "PlayerCareerStats",
            "PlayerCompare",
            "PlayerDashPtPass",
            "PlayerDashPtReb",
            "PlayerDashPtShotDefend",
            "PlayerDashPtShots",
            "PlayerDashboardByShootingSplits",
            "PlayerEstimatedMetrics",
            "PlayerGameLog",
            "PlayerGameLogs",
            "PlayerGameStreakFinder",
            "PlayerNextNGames",
            "PlayerProfileV2",
            "PlayerVsPlayer",
            "WinProbabilityPBP",
        },
        runtime_version="player-support-matrix-family-test",
    )
    rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}

    complete_endpoints = {
        "league_player_on_details",
        "player_career_by_college",
        "player_career_stats",
        "player_college_rollup",
        "player_compare",
        "player_dash_pt_pass",
        "player_dash_pt_reb",
        "player_dash_pt_shot_defend",
        "player_dash_pt_shots",
        "player_dash_shooting_splits",
        "player_estimated_metrics",
        "player_game_log",
        "player_game_logs_v2",
        "player_next_games",
        "player_profile_v2",
        "player_streak_finder",
        "win_probability",
    }

    for endpoint_name in sorted(complete_endpoints):
        row = rows[endpoint_name]
        assert row["contract_status"] == "complete", endpoint_name
        assert row["input_schema_missing_staging_keys"] == [], endpoint_name
        assert row["output_schema_missing_tables"] == [], endpoint_name
        assert row["contract_gaps"] == [], endpoint_name

    for endpoint_name in (
        "player_dash_pt_pass",
        "player_dash_pt_reb",
        "player_dash_pt_shot_defend",
        "player_dash_pt_shots",
    ):
        row = rows[endpoint_name]
        assert row["param_patterns"] == ["player_season"], endpoint_name
        assert row["earliest_supported_season"] == 1946, endpoint_name
        assert row["season_type_contract_status"] == "supported", endpoint_name
        assert row["declared_supported_season_types"] == [
            "Regular Season",
            "Playoffs",
            "Pre Season",
            "All Star",
        ], endpoint_name

    split_row = rows["player_dash_shooting_splits"]
    assert split_row["param_patterns"] == ["player_season"]
    assert split_row["earliest_supported_season"] == 1946

    game_logs_row = rows["player_game_logs_v2"]
    assert game_logs_row["param_patterns"] == ["player_season", "season"]
    assert game_logs_row["earliest_supported_season"] == 1946
    assert game_logs_row["season_type_contract_status"] == "supported"
    assert game_logs_row["declared_supported_season_types"] == [
        "Regular Season",
        "Playoffs",
        "Pre Season",
        "All Star",
    ]

    next_games_row = rows["player_next_games"]
    assert next_games_row["param_patterns"] == ["player_season"]
    assert next_games_row["earliest_supported_season"] == 1946

    streak_row = rows["player_streak_finder"]
    assert streak_row["param_patterns"] == ["player_season", "season"]
    assert streak_row["earliest_supported_season"] == 1946

    player_vs_player = rows["player_vs_player"]
    assert player_vs_player["contract_status"] == "complete"
    assert player_vs_player["input_schema_missing_staging_keys"] == []
    assert player_vs_player["output_schema_missing_tables"] == []
    assert player_vs_player["contract_gaps"] == []
    assert player_vs_player["downstream_status"] == "modeled"
