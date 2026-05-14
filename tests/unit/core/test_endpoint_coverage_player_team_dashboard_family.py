from __future__ import annotations

from pathlib import Path

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.orchestrate.staging_map import STAGING_MAP


def test_player_team_dashboard_family_support_matrix_chunk() -> None:
    project_root = Path(__file__).resolve().parents[3]
    generator = EndpointCoverageGenerator(
        project_root=project_root, staging_entries=list(STAGING_MAP)
    )

    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={
            "CommonPlayerInfo",
            "FantasyWidget",
            "FranchiseHistory",
            "FranchiseLeaders",
            "FranchisePlayers",
            "GLAlumBoxScoreSimilarityScore",
            "HustleStatsBoxScore",
            "InfographicFanDuelPlayer",
            "LeagueDashLineups",
            "LeagueDashPlayerStats",
            "LeagueDashTeamStats",
            "PlayerDashboardByClutch",
            "PlayerDashboardByGameSplits",
            "PlayerDashboardByGeneralSplits",
            "PlayerDashboardByLastNGames",
            "PlayerDashboardByTeamPerformance",
            "PlayerDashboardByYearOverYear",
            "PlayerFantasyProfileBarGraph",
            "TeamDashboardByGeneralSplits",
            "TeamDashboardByShootingSplits",
        },
        runtime_version="player-team-dashboard-family-test",
    )
    rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}

    complete_endpoints = {
        "common_player_info",
        "fantasy_widget",
        "franchise_history",
        "franchise_leaders",
        "franchise_players",
        "gl_alum_box_score_similarity_score",
        "hustle_stats_box_score",
        "infographic_fanduel_player",
        "league_dash_lineups",
        "league_dash_player_stats",
        "league_dash_team_stats",
        "player_dash_game_splits",
        "player_dash_general_splits",
        "player_dash_last_n_games",
        "player_dash_team_perf",
        "player_dash_yoy",
        "player_dashboard_clutch",
        "player_fantasy_profile",
        "team_dashboard_general_splits",
        "team_dashboard_shooting_splits",
    }

    for endpoint_name in sorted(complete_endpoints):
        row = rows[endpoint_name]
        assert row["contract_status"] == "complete", endpoint_name
        assert row["input_schema_missing_staging_keys"] == [], endpoint_name
        assert row["output_schema_missing_tables"] == [], endpoint_name

    for endpoint_name in (
        "player_dash_game_splits",
        "player_dash_general_splits",
        "player_dash_last_n_games",
        "player_dash_team_perf",
        "player_dash_yoy",
        "player_dashboard_clutch",
    ):
        row = rows[endpoint_name]
        assert row["param_patterns"] == ["player_season"], endpoint_name
        assert row["earliest_supported_season"] == 1946, endpoint_name
