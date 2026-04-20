from __future__ import annotations

from pathlib import Path

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.orchestrate.staging_map import STAGING_MAP


def test_final_exception_endpoints_are_support_matrix_complete() -> None:
    project_root = Path(__file__).resolve().parents[3]
    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=list(STAGING_MAP),
    )

    artifacts = generator.build_artifacts()
    rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}

    targets = {
        "draft_board",
        "dunk_score_leaders",
        "gravity_leaders",
        "schedule_int",
        "synergy_play_types",
        "play_by_play_v2",
        "player_index",
        "player_vs_player",
        "video_details",
        "video_details_asset",
        "video_events",
        "video_events_asset",
        "video_status",
    }

    for endpoint_name in sorted(targets):
        row = rows[endpoint_name]
        assert row["contract_status"] == "complete", endpoint_name
        assert row["contract_gaps"] == [], endpoint_name
        assert row["input_schema_missing_staging_keys"] == [], endpoint_name
        assert row["output_schema_missing_tables"] == [], endpoint_name

    assert rows["video_details"]["season_type_contract_status"] == "supported"
    assert rows["video_details_asset"]["season_type_contract_status"] == "supported"
