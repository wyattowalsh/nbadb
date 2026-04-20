from __future__ import annotations

from pathlib import Path

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.orchestrate.staging_map import STAGING_MAP


def test_league_tracking_playoff_family_support_matrix_gaps_are_closed() -> None:
    project_root = Path(__file__).resolve().parents[3]
    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=list(STAGING_MAP),
    )

    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={
            "BoxScoreUsageV3",
            "CommonPlayoffSeries",
            "DraftCombineDrillResults",
            "DraftCombineNonStationaryShooting",
            "DraftCombinePlayerAnthro",
            "DraftCombineSpotShooting",
            "ISTStandings",
            "LeagueDashOppPtShot",
            "LeagueDashPlayerBioStats",
            "LeagueDashPlayerClutch",
            "LeagueDashPlayerPtShot",
            "LeagueDashPlayerShotLocations",
            "LeagueDashPlayerStats",
            "LeagueDashPtDefend",
            "LeagueDashPtStats",
            "LeagueDashPtTeamDefend",
            "LeagueDashTeamClutch",
            "LeagueDashTeamPtShot",
            "LeagueDashTeamShotLocations",
            "LeagueHustleStatsPlayer",
            "LeagueHustleStatsTeam",
        },
        runtime_version="league-support-family-test",
    )

    endpoints = {
        "box_score_usage",
        "common_playoff_series",
        "draft_combine_drill_results",
        "draft_combine_non_stationary_shooting",
        "draft_combine_player_anthro",
        "draft_combine_spot_shooting",
        "ist_standings",
        "league_dash_opp_pt_shot",
        "league_dash_player_bio",
        "league_dash_player_clutch",
        "league_dash_player_pt_shot",
        "league_dash_player_shot_locations",
        "league_dash_player_stats",
        "league_dash_pt_defend",
        "league_dash_pt_stats",
        "league_dash_pt_team_defend",
        "league_dash_team_clutch",
        "league_dash_team_pt_shot",
        "league_dash_team_shot_locations",
        "league_hustle_player",
        "league_hustle_team",
    }
    rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}

    for endpoint_name in sorted(endpoints):
        row = rows[endpoint_name]
        assert row["contract_status"] == "complete", endpoint_name
        assert row["input_schema_missing_staging_keys"] == [], endpoint_name
        assert row["output_schema_missing_tables"] == [], endpoint_name
        assert row["contract_gaps"] == [], endpoint_name
