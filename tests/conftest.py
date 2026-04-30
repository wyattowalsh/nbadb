from __future__ import annotations

import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from nbadb.core.config import NbaDbSettings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Prevent LRU cache contamination across tests (HR-A-018)."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def settings(tmp_data_dir: Path) -> NbaDbSettings:
    return NbaDbSettings(
        data_dir=tmp_data_dir,
        log_dir=tmp_data_dir / "logs",
    )


@pytest.fixture
def sample_player_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "player_id": [201566, 203507, 1629029],
            "player_name": [
                "Russell Westbrook",
                "Giannis Antetokounmpo",
                "Luka Doncic",
            ],
            "team_id": [1610612743, 1610612749, 1610612742],
            "pts": [18.4, 30.4, 33.9],
        }
    )


@pytest.fixture
def sample_game_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["0022400001", "0022400002", "0022400003"],
            "game_date": ["2024-10-22", "2024-10-22", "2024-10-23"],
            "home_team_id": [1610612747, 1610612738, 1610612744],
            "visitor_team_id": [1610612750, 1610612752, 1610612746],
        }
    )


@pytest.fixture
def sample_game_log_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["0022400001", "0022400002"],
            "game_date": ["2024-10-22", "2024-10-23"],
            "season_year": ["2024-25", "2024-25"],
            "season_type": ["Regular Season", "Regular Season"],
            "home_team_id": [1610612747, 1610612738],
            "visitor_team_id": [1610612750, 1610612752],
            "matchup": ["LAL vs. MIN", "BOS vs. NYK"],
        }
    )


@pytest.fixture
def sample_box_score_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "game_id": ["0022400001", "0022400001"],
            "team_id": [1610612747, 1610612747],
            "player_id": [2544, 203507],
            "start_position": ["F", "F"],
            "min": [36.0, 34.0],
            "fgm": [10, 12],
            "fga": [20, 22],
            "fg_pct": [0.5, 0.545],
            "fg3m": [3, 2],
            "fg3a": [8, 5],
            "fg3_pct": [0.375, 0.4],
            "ftm": [5, 8],
            "fta": [6, 9],
            "ft_pct": [0.833, 0.889],
            "oreb": [1, 3],
            "dreb": [6, 8],
            "reb": [7, 11],
            "ast": [8, 5],
            "stl": [2, 1],
            "blk": [1, 2],
            "tov": [3, 2],
            "pf": [2, 3],
            "pts": [28, 34],
            "plus_minus": [12.0, 8.0],
        }
    )


@pytest.fixture
def mock_duckdb_conn() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB connection for testing.

    Contract: Returns a bare in-memory DuckDB connection with no tables.
    Use specialized fixtures (duckdb_memory_with_pipeline_tables, etc.) for pre-configured tables.
    """
    return duckdb.connect(":memory:")


@pytest.fixture
def duckdb_memory_conn() -> duckdb.DuckDBPyConnection:
    """Canonical in-memory DuckDB connection for testing.

    Contract: Returns a bare in-memory DuckDB connection with no tables.
    Use specialized fixtures for pre-configured tables.
    """
    conn = duckdb.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def duckdb_memory_with_pipeline_tables() -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with standard pipeline tracking tables.

    Contract: Creates _pipeline_watermarks, _extraction_journal, _pipeline_metrics
    tables as defined in nbadb.orchestrate.journal.
    """
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE _pipeline_watermarks (
            table_name VARCHAR NOT NULL,
            watermark_type VARCHAR NOT NULL,
            watermark_value VARCHAR,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            row_count_at_watermark BIGINT,
            PRIMARY KEY (table_name, watermark_type)
        )
    """)
    conn.execute("""
        CREATE TABLE _extraction_journal (
            endpoint VARCHAR NOT NULL,
            params VARCHAR,
            status VARCHAR NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            rows_extracted BIGINT,
            error_message VARCHAR,
            retry_count INTEGER DEFAULT 0,
            PRIMARY KEY (endpoint, params)
        )
    """)
    conn.execute("""
        CREATE TABLE _pipeline_metrics (
            endpoint VARCHAR NOT NULL,
            run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_seconds FLOAT,
            rows_extracted BIGINT,
            error_count INT DEFAULT 0,
            PRIMARY KEY (endpoint, run_timestamp)
        )
    """)
    yield conn
    conn.close()


@pytest.fixture
def fixture_loader() -> callable:
    def _load(name: str) -> dict:
        with open(Path(__file__).parent / "fixtures" / name) as f:
            return json.load(f)

    return _load


@pytest.fixture
def sample_db(tmp_path: Path) -> Path:
    """Canonical sample DuckDB for chat tests.

    Consolidated fixture (Lane K) that provides:
    - dim_player: player_id, full_name, is_current
    - fact_player_game_log: player_id, pts, reb, ast
    - fact_game_log: game_id, pts (for backward compat with test_db.py)
    """
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        # Core player dimension with SCD Type 2 marker
        conn.execute(
            "CREATE TABLE dim_player (player_id INT, full_name VARCHAR, is_current BOOLEAN)"
        )
        conn.execute(
            "INSERT INTO dim_player VALUES (1, 'LeBron James', TRUE), (2, 'Stephen Curry', TRUE)"
        )
        # Player-level fact table
        conn.execute("CREATE TABLE fact_player_game_log (player_id INT, pts INT, reb INT, ast INT)")
        conn.execute("INSERT INTO fact_player_game_log VALUES (1, 30, 8, 10), (2, 35, 5, 7)")
        # Game-level fact table (for backward compat with test_db.py)
        conn.execute("CREATE TABLE fact_game_log (game_id INT, pts INT)")
        conn.execute("INSERT INTO fact_game_log VALUES (100, 30)")
    return db_path
