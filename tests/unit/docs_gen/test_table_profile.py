from __future__ import annotations

import json

import duckdb

from nbadb.docs_gen.table_profile import generate_table_profile_json


def test_table_profile_includes_bounded_column_statistics(tmp_path) -> None:
    db_path = tmp_path / "profile.duckdb"
    conn = duckdb.connect(str(db_path))
    try:
        conn.execute("""
            CREATE TABLE fact_profile_sample (
                game_id VARCHAR,
                pts INTEGER,
                game_date DATE,
                tipoff_time TIME,
                season_type VARCHAR
            )
        """)
        conn.execute("""
            INSERT INTO fact_profile_sample VALUES
                ('001', 10, DATE '2024-10-22', TIME '19:30:00', 'Regular Season'),
                ('002', 20, DATE '2024-10-23', TIME '20:00:00', 'Regular Season'),
                ('003', NULL, DATE '2024-10-24', TIME '21:15:00', 'Playoffs')
        """)
    finally:
        conn.close()

    profiles = json.loads(generate_table_profile_json(db_path))

    profile = next(item for item in profiles if item["table"] == "fact_profile_sample")
    columns = {column["name"]: column for column in profile["columns"]}

    assert columns["pts"]["nonNullCount"] == 2
    assert columns["pts"]["distinctCount"] == 2
    assert columns["pts"]["min"] == 10
    assert columns["pts"]["max"] == 20
    assert columns["pts"]["p50"] == 15.0
    assert columns["pts"]["p95"] == 19.5
    assert columns["game_date"]["min"] == "2024-10-22"
    assert columns["game_date"]["max"] == "2024-10-24"
    assert columns["tipoff_time"]["min"] == "19:30:00"
    assert columns["tipoff_time"]["max"] == "21:15:00"
    assert columns["season_type"]["topValues"] == [
        {"value": "Regular Season", "count": 2},
        {"value": "Playoffs", "count": 1},
    ]
