from __future__ import annotations

from pathlib import Path

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.orchestrate.staging_map import STAGING_MAP


def test_box_game_scoreboard_family_support_matrix_gaps_are_closed() -> None:
    project_root = Path(__file__).resolve().parents[3]
    generator = EndpointCoverageGenerator(
        project_root=project_root, staging_entries=list(STAGING_MAP)
    )

    artifacts = generator.build_artifacts(
        runtime_endpoint_classes={
            "BoxScoreTraditionalV3",
            "BoxScoreAdvancedV3",
            "BoxScoreMiscV3",
            "BoxScoreScoringV3",
            "BoxScoreFourFactorsV3",
            "BoxScoreHustleV2",
            "BoxScorePlayerTrackV3",
            "BoxScoreDefensiveV2",
            "BoxScoreSummaryV2",
            "BoxScoreSummaryV3",
            "ScoreboardV2",
            "ScoreboardV3",
        },
        runtime_version="box-game-scoreboard-family-test",
    )

    endpoints = {
        "box_score_advanced",
        "box_score_defensive",
        "box_score_four_factors",
        "box_score_hustle",
        "box_score_misc",
        "box_score_player_track",
        "box_score_scoring",
        "box_score_summary",
        "box_score_summary_v3",
        "box_score_traditional",
        "scoreboard_v2",
        "scoreboard_v3",
    }
    rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}

    for endpoint_name in sorted(endpoints):
        row = rows[endpoint_name]
        assert row["contract_status"] == "complete", endpoint_name
        assert row["input_schema_missing_staging_keys"] == [], endpoint_name
        assert row["output_schema_missing_tables"] == [], endpoint_name
        assert row["contract_gaps"] == [], endpoint_name
