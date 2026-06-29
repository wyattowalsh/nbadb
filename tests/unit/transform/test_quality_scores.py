from __future__ import annotations

import duckdb

from nbadb.orchestrate.journal import PipelineJournal
from nbadb.transform.quality import DataQualityMonitor


def test_record_table_quality_checks_scores_populated_table() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE agg_player_season (player_id INTEGER, total_pts DOUBLE)")
    conn.execute("INSERT INTO agg_player_season VALUES (1, 25.0)")

    monitor = DataQualityMonitor(conn)
    score = monitor.record_table_quality_checks(
        "agg_player_season",
        row_count=1,
        key_columns=["player_id"],
    )

    assert score == 1.0
    assert monitor.summarize_table_quality(["agg_player_season"]) == {"agg_player_season": 1.0}


def test_record_table_quality_checks_penalizes_empty_table() -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE fact_player_game_traditional (player_id INTEGER, pts DOUBLE)")

    monitor = DataQualityMonitor(conn)
    score = monitor.record_table_quality_checks(
        "fact_player_game_traditional",
        row_count=0,
        key_columns=["player_id"],
    )

    assert score == 0.0


def test_record_table_metadata_persists_quality_score(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> None:
    duckdb_memory_with_pipeline_tables.execute(
        "CREATE TABLE agg_player_season (player_id INTEGER, total_pts DOUBLE)"
    )
    duckdb_memory_with_pipeline_tables.execute("INSERT INTO agg_player_season VALUES (1, 25.0)")
    journal = PipelineJournal(duckdb_memory_with_pipeline_tables)
    monitor = DataQualityMonitor(duckdb_memory_with_pipeline_tables)
    score = monitor.record_table_quality_checks(
        "agg_player_season",
        row_count=10,
        key_columns=["player_id"],
    )
    journal.record_table_metadata("agg_player_season", 10, "hash", quality_score=score)
    metadata = journal.get_table_metadata("agg_player_season")
    assert metadata is not None
    assert metadata[3] == score
