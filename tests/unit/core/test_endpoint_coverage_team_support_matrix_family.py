from __future__ import annotations

from pathlib import Path

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.orchestrate.staging_map import STAGING_MAP


def test_team_support_matrix_family_chunk_is_complete() -> None:
    project_root = Path(__file__).resolve().parents[3]
    generator = EndpointCoverageGenerator(
        project_root=project_root, staging_entries=list(STAGING_MAP)
    )

    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={
            "TeamAndPlayersVs",
            "TeamDashLineups",
            "TeamDashPtPass",
            "TeamDashPtReb",
            "TeamDashPtShots",
            "TeamVsPlayer",
        },
        runtime_version="team-support-matrix-family-test",
    )
    rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}

    complete_endpoints = {
        "team_and_players_vs",
        "team_dash_lineups",
        "team_dash_pt_pass",
        "team_dash_pt_reb",
        "team_dash_pt_shots",
        "team_vs_player",
    }

    for endpoint_name in sorted(complete_endpoints):
        row = rows[endpoint_name]
        assert row["contract_status"] == "complete", endpoint_name
        assert row["input_schema_missing_staging_keys"] == [], endpoint_name
        assert row["output_schema_missing_tables"] == [], endpoint_name

    expected_supported_season_types = ["Regular Season", "Playoffs", "Pre Season"]
    for endpoint_name in ("team_and_players_vs", "team_vs_player"):
        row = rows[endpoint_name]
        assert row["season_type_contract_status"] == "supported", endpoint_name
        assert row["declared_supported_season_types"] == expected_supported_season_types, (
            endpoint_name
        )
        assert row["contract_gaps"] == [], endpoint_name

    extraction_rows = {row["endpoint_name"]: row for row in artifacts["extraction_matrix"]}
    for endpoint_name in ("team_and_players_vs", "team_vs_player"):
        row = extraction_rows[endpoint_name]
        assert row["extractability_status"] == "excluded", endpoint_name
        assert row["exclusion"]["classification"] == "contract_not_modeled_yet", endpoint_name
