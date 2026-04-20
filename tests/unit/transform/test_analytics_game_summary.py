"""Tests for analytics_game_summary view transformer."""

from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.views.analytics_game_summary import (
    AnalyticsGameSummaryTransformer,
)


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _make_staging() -> dict[str, pl.LazyFrame]:
    """Build minimal staging tables for one game."""
    dim_game = pl.DataFrame(
        {
            "game_id": ["0022400100"],
            "game_date": ["2024-11-01"],
            "season_year": [2024],
            "season_type": ["Regular Season"],
            "home_team_id": [1610612738],
            "visitor_team_id": [1610612747],
            "matchup": ["BOS vs. LAL"],
            "arena_name": ["TD Garden"],
        }
    ).lazy()

    fact_game_result = pl.DataFrame(
        {
            "game_id": ["0022400100"],
            "game_date": ["2024-11-01"],
            "season_year": [2024],
            "season_type": ["Regular Season"],
            "home_team_id": [1610612738],
            "visitor_team_id": [1610612747],
            "wl_home": ["W"],
            "pts_home": [112],
            "pts_away": [104],
            "plus_minus_home": [8],
            "plus_minus_away": [-8],
            "pts_qtr1_home": [30],
            "pts_qtr2_home": [28],
            "pts_qtr3_home": [26],
            "pts_qtr4_home": [28],
            "pts_ot1_home": [None],
            "pts_ot2_home": [None],
            "pts_qtr1_away": [25],
            "pts_qtr2_away": [27],
            "pts_qtr3_away": [24],
            "pts_qtr4_away": [28],
            "pts_ot1_away": [None],
            "pts_ot2_away": [None],
        }
    ).lazy()

    bridge_game_team = pl.DataFrame(
        {
            "game_id": ["0022400100", "0022400100"],
            "team_id": [1610612738, 1610612747],
            "side": ["home", "away"],
            "wl": ["W", "L"],
            "season_year": [2024, 2024],
        }
    ).lazy()

    dim_team = pl.DataFrame(
        {
            "team_id": [1610612738, 1610612747],
            "abbreviation": ["BOS", "LAL"],
            "full_name": ["Boston Celtics", "Los Angeles Lakers"],
            "city": ["Boston", "Los Angeles"],
            "state": ["Massachusetts", "California"],
            "arena": ["TD Garden", "Crypto.com Arena"],
            "year_founded": [1946, 1947],
            "conference": ["East", "West"],
            "division": ["Atlantic", "Pacific"],
        }
    ).lazy()

    return {
        "dim_game": dim_game,
        "fact_game_result": fact_game_result,
        "bridge_game_team": bridge_game_team,
        "dim_team": dim_team,
    }


class TestAnalyticsGameSummary:
    def test_output_table(self) -> None:
        t = AnalyticsGameSummaryTransformer()
        assert t.output_table == "analytics_game_summary"

    def test_depends_on(self) -> None:
        t = AnalyticsGameSummaryTransformer()
        assert set(t.depends_on) == {
            "fact_game_result",
            "dim_game",
            "bridge_game_team",
            "dim_team",
        }

    def test_sql_is_non_empty(self) -> None:
        assert AnalyticsGameSummaryTransformer._SQL.strip()

    def test_basic_game_summary(self) -> None:
        """One game with home/away teams produces correct wide row."""
        staging = _make_staging()
        result = _run(AnalyticsGameSummaryTransformer(), staging)

        assert result.shape[0] == 1
        row = result.row(0, named=True)

        assert row["game_id"] == "0022400100"
        assert row["game_date"] == "2024-11-01"
        assert row["season_year"] == 2024
        assert row["season_type"] == "Regular Season"

        # Home team
        assert row["home_team_id"] == 1610612738
        assert row["home_team_name"] == "Boston Celtics"
        assert row["home_team_abbreviation"] == "BOS"

        # Away team
        assert row["away_team_id"] == 1610612747
        assert row["away_team_name"] == "Los Angeles Lakers"
        assert row["away_team_abbreviation"] == "LAL"

        # Scores
        assert row["pts_home"] == 112
        assert row["pts_away"] == 104
        assert row["plus_minus_home"] == 8
        assert row["wl_home"] == "W"

        # Quarter scores
        assert row["pts_qtr1_home"] == 30
        assert row["pts_qtr2_home"] == 28
        assert row["pts_qtr3_home"] == 26
        assert row["pts_qtr4_home"] == 28
        assert row["pts_qtr1_away"] == 25

    def test_arena_and_matchup_included(self) -> None:
        """Verify arena_name and matchup come through from dim_game."""
        staging = _make_staging()
        result = _run(AnalyticsGameSummaryTransformer(), staging)

        row = result.row(0, named=True)
        assert row["arena_name"] == "TD Garden"
        assert row["matchup"] == "BOS vs. LAL"

    def test_no_connection_before_injection(self) -> None:
        t = AnalyticsGameSummaryTransformer()
        import pytest

        with pytest.raises(RuntimeError, match="No DuckDB connection"):
            t.conn  # noqa: B018
