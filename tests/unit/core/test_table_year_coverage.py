from __future__ import annotations

import duckdb

from nbadb.core.table_year_coverage import build_table_year_coverage


def test_table_year_coverage_marks_present_failed_and_missing_rows() -> None:
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(
            """
            CREATE TABLE stg_league_game_log (
                season_year VARCHAR,
                season_type VARCHAR,
                game_id VARCHAR
            )
            """
        )
        conn.execute(
            """
            INSERT INTO stg_league_game_log VALUES
                ('2024-25', 'Regular Season', '1'),
                ('2024-25', 'Regular Season', '2')
            """
        )
        conn.execute(
            """
            CREATE TABLE _extraction_journal (
                endpoint VARCHAR,
                params VARCHAR,
                status VARCHAR,
                rows_extracted INTEGER,
                completed_at TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO _extraction_journal VALUES
                ('league_game_log', '{"season": "2023-24", "season_type": "Regular Season"}',
                    'failed', 0, NULL),
                ('league_game_log', '{"season": "2022-23", "season_type": "Regular Season"}',
                    'done', 0, TIMESTAMP '2026-01-01 00:00:00')
            """
        )
        coverage = build_table_year_coverage(
            conn,
            [
                {
                    "endpoint_name": "league_game_log",
                    "staging_key": "stg_league_game_log",
                    "result_set_index": 0,
                    "param_pattern": "season",
                    "season": "2024-25",
                    "season_type": "Regular Season",
                    "expected_status": "required",
                    "actual_status": "staged",
                },
                {
                    "endpoint_name": "league_game_log",
                    "staging_key": "stg_league_game_log",
                    "result_set_index": 0,
                    "param_pattern": "season",
                    "season": "2023-24",
                    "season_type": "Regular Season",
                    "expected_status": "required",
                    "actual_status": "staged",
                },
                {
                    "endpoint_name": "league_game_log",
                    "staging_key": "stg_league_game_log",
                    "result_set_index": 0,
                    "param_pattern": "season",
                    "season": "2022-23",
                    "season_type": "Regular Season",
                    "expected_status": "required",
                    "actual_status": "staged",
                },
                {
                    "endpoint_name": "league_game_log",
                    "staging_key": "stg_missing_table",
                    "result_set_index": 0,
                    "param_pattern": "season",
                    "season": "2024-25",
                    "season_type": "Regular Season",
                    "expected_status": "required",
                    "actual_status": "staged",
                },
            ],
        )
    finally:
        conn.close()

    statuses = {
        (row["table_name"], row["season"]): row["coverage_status"] for row in coverage["diff"]
    }
    assert statuses[("stg_league_game_log", "2024-25")] == "present"
    assert statuses[("stg_league_game_log", "2023-24")] == "failed"
    assert statuses[("stg_league_game_log", "2022-23")] == "empty_valid"
    assert statuses[("stg_missing_table", "2024-25")] == "missing_table"
    assert coverage["summary"]["blocking_missing_count"] == 2


def test_table_year_coverage_derives_nba_season_from_game_date() -> None:
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE TABLE stg_schedule (game_date DATE, game_id VARCHAR)")
        conn.execute(
            """
            INSERT INTO stg_schedule VALUES
                (DATE '2024-10-22', '1'),
                (DATE '2025-02-01', '2')
            """
        )
        coverage = build_table_year_coverage(
            conn,
            [
                {
                    "endpoint_name": "schedule",
                    "staging_key": "stg_schedule",
                    "result_set_index": 0,
                    "param_pattern": "date",
                    "season": "2024-25",
                    "season_type": None,
                    "expected_status": "required",
                    "actual_status": "staged",
                }
            ],
        )
    finally:
        conn.close()

    assert coverage["actual"] == [
        {
            "table_name": "stg_schedule",
            "season": "2024-25",
            "season_type": None,
            "row_count": 2,
            "season_source_column": "game_date",
            "season_type_source_column": None,
        }
    ]
    assert coverage["diff"][0]["coverage_status"] == "present"


def test_table_year_coverage_accepts_untyped_season_when_table_has_no_type() -> None:
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE TABLE stg_player_profile (season_year VARCHAR, player_id INTEGER)")
        conn.execute("INSERT INTO stg_player_profile VALUES ('2024-25', 1)")
        coverage = build_table_year_coverage(
            conn,
            [
                {
                    "endpoint_name": "player_profile_v2",
                    "staging_key": "stg_player_profile",
                    "result_set_index": 0,
                    "param_pattern": "season",
                    "season": "2024-25",
                    "season_type": "Regular Season",
                    "expected_status": "required",
                    "actual_status": "staged",
                }
            ],
        )
    finally:
        conn.close()

    assert coverage["diff"][0]["coverage_status"] == "present_untyped"
    assert coverage["diff"][0]["actual_match_scope"] == "season_without_type"
    assert coverage["summary"]["blocking_missing_count"] == 0


def test_table_year_coverage_infers_present_from_journal_for_static_table() -> None:
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE TABLE stg_player_awards (player_id INTEGER, award VARCHAR)")
        conn.execute("INSERT INTO stg_player_awards VALUES (1, 'All-NBA')")
        conn.execute(
            """
            CREATE TABLE _extraction_journal (
                endpoint VARCHAR,
                params VARCHAR,
                status VARCHAR,
                rows_extracted INTEGER,
                completed_at TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO _extraction_journal VALUES
                ('player_awards', '{"season": "2024-25"}',
                    'done', 3, TIMESTAMP '2026-01-01 00:00:00')
            """
        )
        coverage = build_table_year_coverage(
            conn,
            [
                {
                    "endpoint_name": "player_awards",
                    "staging_key": "stg_player_awards",
                    "result_set_index": 0,
                    "param_pattern": "season",
                    "season": "2024-25",
                    "season_type": None,
                    "expected_status": "required",
                    "actual_status": "staged",
                }
            ],
        )
    finally:
        conn.close()

    assert coverage["diff"][0]["coverage_status"] == "present_inferred"
    assert coverage["diff"][0]["actual_match_scope"] == "journal"
    assert coverage["diff"][0]["journal_rows_extracted"] == 3
    assert coverage["summary"]["blocking_missing_count"] == 0
