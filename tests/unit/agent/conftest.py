"""Shared fixtures for agent / chat-with-data unit tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest

from nbadb.agent.query import QueryAgent
from nbadb.orchestrate.seasons import current_season

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def season_year() -> str:
    return current_season()


@pytest.fixture
def tmp_db(tmp_path: Path, season_year: str) -> Path:
    """Minimal DuckDB warehouse with season-grain columns for catalog routes."""
    db_path = tmp_path / "test.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute(
            "CREATE TABLE dim_player ("
            "  player_id INTEGER, full_name VARCHAR, first_name VARCHAR,"
            "  last_name VARCHAR, is_current BOOLEAN)"
        )
        conn.execute(
            "CREATE TABLE dim_team ("
            "  team_id INTEGER, full_name VARCHAR, abbreviation VARCHAR, city VARCHAR)"
        )
        conn.execute(
            "CREATE TABLE dim_game ("
            "  game_id VARCHAR, game_date VARCHAR, season_year VARCHAR, season_type VARCHAR)"
        )
        conn.execute(
            "CREATE TABLE agg_player_season ("
            "  player_id INTEGER, season_year VARCHAR, season_type VARCHAR,"
            "  total_pts INTEGER, total_ast INTEGER, total_reb INTEGER)"
        )
        conn.execute(
            "CREATE TABLE fact_standings ("
            "  team_id INTEGER, season_year VARCHAR, season_type VARCHAR,"
            "  wins INTEGER, losses INTEGER, win_pct DOUBLE)"
        )
        conn.execute("CREATE TABLE _pipeline_metadata (table_name VARCHAR, row_count INTEGER)")
        conn.execute(
            "INSERT INTO dim_player VALUES "
            "(1, 'Test Player', 'Test', 'Player', TRUE),"
            "(2544, 'LeBron James', 'LeBron', 'James', TRUE),"
            "(201939, 'Stephen Curry', 'Stephen', 'Curry', TRUE),"
            "(203552, 'Seth Curry', 'Seth', 'Curry', TRUE)"
        )
        conn.execute(
            "INSERT INTO dim_team VALUES "
            "(1, 'Test Team', 'TST', 'Test'),"
            "(1610612738, 'Boston Celtics', 'BOS', 'Boston'),"
            "(1610612748, 'Miami Heat', 'MIA', 'Miami')"
        )
        conn.execute(
            "INSERT INTO dim_game VALUES "
            "('g1', '2024-10-01', ?, 'Regular Season'),"
            "('g2', '2024-01-10', '2023-24', 'Regular Season')",
            [season_year],
        )
        conn.execute(
            "INSERT INTO agg_player_season VALUES (1, ?, 'Regular Season', 2500, 800, 900)",
            [season_year],
        )
        conn.execute(
            "INSERT INTO fact_standings VALUES (1, ?, 'Regular Season', 50, 32, 0.61)",
            [season_year],
        )
        conn.execute(
            "INSERT INTO _pipeline_metadata VALUES ('dim_game', 2), ('agg_player_season', 1)"
        )
        conn.execute(
            "CREATE TABLE fact_box_score_team ("
            "  game_id VARCHAR, team_id INTEGER, pts INTEGER, reb INTEGER, ast INTEGER)"
        )
        conn.execute(
            "CREATE TABLE fact_player_game_traditional ("
            "  game_id VARCHAR, player_id INTEGER, season_year VARCHAR,"
            "  pts INTEGER, reb INTEGER, ast INTEGER)"
        )
        conn.execute(
            "CREATE TABLE analytics_team_game_complete ("
            "  game_id VARCHAR, game_date VARCHAR, team_id INTEGER, team_name VARCHAR,"
            "  season_year VARCHAR,"
            "  pts INTEGER, reb INTEGER, ast INTEGER)"
        )
        conn.execute(
            "CREATE TABLE analytics_player_game_complete ("
            "  game_id VARCHAR, player_id INTEGER, team_id INTEGER, season_year VARCHAR,"
            "  player_name VARCHAR, pts INTEGER, reb INTEGER, ast INTEGER)"
        )
        conn.execute(
            "CREATE TABLE bridge_player_team_season ("
            "  player_id INTEGER, team_id INTEGER, season_year VARCHAR)"
        )
        conn.execute("INSERT INTO fact_box_score_team VALUES ('g1', 1, 110, 40, 25)")
        conn.execute(
            "INSERT INTO fact_player_game_traditional VALUES ('g1', 1, ?, 30, 8, 7)",
            [season_year],
        )
        conn.execute(
            "INSERT INTO analytics_team_game_complete VALUES "
            "('g1', '2024-10-01', 1, 'Test Team', ?, 110, 40, 25)",
            [season_year],
        )
        conn.execute(
            "INSERT INTO analytics_player_game_complete VALUES "
            "('g1', 2544, 1610612748, ?, 'LeBron James', 31, 8, 9),"
            "('g2', 201939, 1, '2023-24', 'Stephen Curry', 42, 5, 6)",
            [season_year],
        )
        conn.execute(
            "INSERT INTO bridge_player_team_season VALUES "
            "(1, 1610612738, ?), (2544, 1610612748, ?)",
            [season_year, season_year],
        )
    return db_path


@pytest.fixture
def agent(tmp_db: Path) -> QueryAgent:
    return QueryAgent(tmp_db)


@pytest.fixture
def agent_empty(tmp_path: Path) -> QueryAgent:
    db_path = tmp_path / "empty.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("SELECT 1")
    return QueryAgent(db_path)
