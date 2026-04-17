from __future__ import annotations

from pathlib import Path

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.orchestrate.staging_map import STAGING_MAP


def test_team_heavy_support_matrix_chunk_is_complete() -> None:
    project_root = Path(__file__).resolve().parents[3]
    generator = EndpointCoverageGenerator(
        project_root=project_root, staging_entries=list(STAGING_MAP)
    )

    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={
            "TeamDetails",
            "TeamEstimatedMetrics",
            "TeamGameLogs",
            "TeamHistoricalLeaders",
            "TeamInfoCommon",
            "TeamPlayerDashboard",
            "TeamPlayerOnOffDetails",
            "TeamPlayerOnOffSummary",
            "TeamYearByYearStats",
        },
        runtime_version="team-heavy-family-test",
    )
    rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}

    complete_endpoints = {
        "team_details",
        "team_estimated_metrics",
        "team_game_logs",
        "team_historical_leaders",
        "team_info_common",
        "team_player_dashboard",
        "team_player_on_off_details",
        "team_player_on_off_summary",
        "team_year_by_year",
    }

    for endpoint_name in sorted(complete_endpoints):
        row = rows[endpoint_name]
        assert row["contract_status"] == "complete", endpoint_name
        assert row["input_schema_missing_staging_keys"] == [], endpoint_name
        assert row["output_schema_missing_tables"] == [], endpoint_name
