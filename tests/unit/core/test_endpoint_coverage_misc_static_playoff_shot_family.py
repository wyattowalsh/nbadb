from __future__ import annotations

from pathlib import Path

from nbadb.core.endpoint_coverage import EndpointCoverageGenerator
from nbadb.orchestrate.staging_map import STAGING_MAP


def test_misc_static_playoff_shot_support_matrix_gaps_are_closed() -> None:
    project_root = Path(__file__).resolve().parents[3]
    generator = EndpointCoverageGenerator(
        project_root=project_root,
        staging_entries=list(STAGING_MAP),
    )

    artifacts = generator.build_artifacts()

    endpoints = {
        "league_game_finder",
        "league_season_matchups",
        "matchups_rollup",
        "play_by_play",
        "playoff_picture",
        "schedule",
        "shot_chart_detail",
        "shot_chart_league_wide",
        "shot_chart_lineup",
        "static_players",
        "static_teams",
        "team_game_streak_finder",
    }
    rows = {row["endpoint_name"]: row for row in artifacts["support_matrix"]}

    for endpoint_name in sorted(endpoints):
        row = rows[endpoint_name]
        assert row["contract_status"] == "complete", endpoint_name
        assert row["input_schema_missing_staging_keys"] == [], endpoint_name
        assert row["output_schema_missing_tables"] == [], endpoint_name
        assert row["contract_gaps"] == [], endpoint_name

    shot_chart = rows["shot_chart_detail"]
    assert shot_chart["param_patterns"] == ["player_season"]
    assert shot_chart["earliest_supported_season"] == 1946
    assert shot_chart["season_type_contract_status"] == "supported"
    assert shot_chart["declared_supported_season_types"] == [
        "Regular Season",
        "Playoffs",
        "Pre Season",
        "All Star",
    ]
