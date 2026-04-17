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

    player_vs_player = rows["player_vs_player"]
    assert player_vs_player["contract_status"] == "complete"
    assert player_vs_player["input_schema_missing_staging_keys"] == []
    assert player_vs_player["output_schema_missing_tables"] == []
    assert player_vs_player["contract_gaps"] == []
    assert player_vs_player["model_exclusion_reasons"] == []
