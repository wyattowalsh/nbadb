from __future__ import annotations

import duckdb

from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore
from nbadb.orchestrate.workload_profile import build_workload_planning_snapshot


def test_build_workload_planning_snapshot_reads_metrics_and_cross_product_density(tmp_path) -> None:
    db_path = tmp_path / "planner.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE _pipeline_metrics (
                endpoint VARCHAR NOT NULL,
                run_timestamp TIMESTAMP,
                duration_seconds FLOAT,
                rows_extracted BIGINT,
                error_count INT DEFAULT 0,
                PRIMARY KEY (endpoint, run_timestamp)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE _extraction_journal (
                endpoint VARCHAR,
                params VARCHAR,
                status VARCHAR,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            INSERT INTO _pipeline_metrics VALUES
                ('player_awards', CURRENT_TIMESTAMP, 35.0, 12, 1),
                ('player_awards', CURRENT_TIMESTAMP + INTERVAL 1 SECOND, 45.0, 10, 0),
                ('league_game_log', CURRENT_TIMESTAMP + INTERVAL 2 SECOND, 2.0, 2000, 0)
            """
        )
        conn.execute(
            """
            INSERT INTO _extraction_journal VALUES
                ('player_awards', '{"player_id": 1}', 'done', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 12, NULL, 2),
                ('player_awards', '{"player_id": 2}', 'done', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 10, NULL, 1),
                ('league_game_log', '{"season": "2024-25"}', 'done', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 2000, NULL, 0)
            """
        )
    finally:
        conn.close()

    store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(db_path)
    store.upsert(
        [
            {
                "player_id": 1,
                "team_id": 10,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
            {
                "player_id": 2,
                "team_id": 20,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
        ],
        seasons=["2024-25"],
        season_types=["Regular Season"],
    )

    snapshot = build_workload_planning_snapshot(
        [
            {
                "endpoint_name": "player_awards",
                "param_patterns": ["player"],
            },
            {
                "endpoint_name": "league_game_log",
                "param_patterns": ["season"],
            },
            {
                "endpoint_name": "video_details",
                "param_patterns": ["player_team_season"],
            },
        ],
        duckdb_path=db_path,
    )

    awards = snapshot.endpoint_profiles["player_awards"]
    assert awards.endpoint_family == "player_history"
    assert awards.throughput_tier == "expensive_flaky"
    assert awards.avg_duration_seconds == 40.0
    assert awards.retry_rate > 0.0

    game_log = snapshot.endpoint_profiles["league_game_log"]
    assert game_log.throughput_tier == "cheap_high_volume"

    video_details = snapshot.endpoint_profiles["video_details"]
    assert video_details.throughput_tier == "discovery_bound_cross_product"
    assert snapshot.cross_product_pair_counts == {("2024-25", "Regular Season"): 2}
