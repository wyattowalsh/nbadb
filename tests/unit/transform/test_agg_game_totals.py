"""Tests for agg_game_totals aggregate transform."""

from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.derived.agg_game_totals import AggGameTotalsTransformer

# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------


def test_output_table():
    assert AggGameTotalsTransformer.output_table == "agg_game_totals"


def test_depends_on():
    deps = AggGameTotalsTransformer.depends_on
    assert "fact_team_game" in deps
    assert "bridge_game_team" in deps
    assert "dim_game" in deps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn() -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB with realistic source tables for one game."""
    conn = duckdb.connect()

    fact_team_game = pl.DataFrame(
        {
            "game_id": [1001, 1001],
            "team_id": [10, 20],
            "fgm": [40, 35],
            "fga": [85, 80],
            "fg_pct": [0.471, 0.438],
            "fg3m": [12, 10],
            "fg3a": [30, 28],
            "fg3_pct": [0.400, 0.357],
            "ftm": [18, 22],
            "fta": [22, 26],
            "ft_pct": [0.818, 0.846],
            "oreb": [10, 8],
            "dreb": [30, 32],
            "reb": [40, 40],
            "ast": [25, 22],
            "stl": [8, 6],
            "blk": [5, 4],
            "tov": [12, 14],
            "pf": [20, 18],
            "pts": [110, 102],
            "pts_qtr1": [28, 25],
            "pts_qtr2": [30, 27],
            "pts_qtr3": [26, 24],
            "pts_qtr4": [26, 26],
        }
    )

    bridge_game_team = pl.DataFrame(
        {
            "game_id": [1001, 1001],
            "team_id": [10, 20],
            "side": ["home", "away"],
            "wl": ["W", "L"],
            "season_year": [2024, 2024],
        }
    )

    dim_game = pl.DataFrame(
        {
            "game_id": [1001],
            "game_date": ["2024-01-15"],
            "season_year": [2024],
            "season_type": ["Regular Season"],
            "home_team_id": [10],
            "visitor_team_id": [20],
            "matchup": ["HME vs AWY"],
            "arena_name": ["Test Arena"],
            "arena_city": ["Test City"],
        }
    )

    conn.register("fact_team_game", fact_team_game)
    conn.register("bridge_game_team", bridge_game_team)
    conn.register("dim_game", dim_game)

    return conn


# ---------------------------------------------------------------------------
# Functional tests
# ---------------------------------------------------------------------------


class TestOneGameTwoTeams:
    """A single game with home/away stats should produce exactly 1 output row."""

    def test_single_row(self):
        conn = _make_conn()
        transformer = AggGameTotalsTransformer()
        transformer._conn = conn

        result = transformer.transform({})

        assert result.shape[0] == 1
        conn.close()

    def test_expected_columns(self):
        conn = _make_conn()
        transformer = AggGameTotalsTransformer()
        transformer._conn = conn

        result = transformer.transform({})

        expected_cols = {
            "game_id",
            "game_date",
            "season_year",
            "season_type",
            "home_team_id",
            "away_team_id",
            "home_pts",
            "away_pts",
            "total_pts",
            "home_reb",
            "away_reb",
            "home_ast",
            "away_ast",
            "home_fg_pct",
            "away_fg_pct",
        }
        assert set(result.columns) == expected_cols
        conn.close()

    def test_correct_team_ids(self):
        conn = _make_conn()
        transformer = AggGameTotalsTransformer()
        transformer._conn = conn

        result = transformer.transform({})
        row = result.row(0, named=True)

        assert row["home_team_id"] == 10
        assert row["away_team_id"] == 20
        conn.close()

    def test_correct_stats(self):
        conn = _make_conn()
        transformer = AggGameTotalsTransformer()
        transformer._conn = conn

        result = transformer.transform({})
        row = result.row(0, named=True)

        assert row["home_pts"] == 110
        assert row["away_pts"] == 102
        assert row["home_reb"] == 40
        assert row["away_reb"] == 40
        assert row["home_ast"] == 25
        assert row["away_ast"] == 22
        conn.close()


class TestTotalPtsComputed:
    """Verify total_pts = home_pts + away_pts."""

    def test_total_pts_equals_sum(self):
        conn = _make_conn()
        transformer = AggGameTotalsTransformer()
        transformer._conn = conn

        result = transformer.transform({})
        row = result.row(0, named=True)

        assert row["total_pts"] == row["home_pts"] + row["away_pts"]
        assert row["total_pts"] == 212
        conn.close()

    def test_fg_pct_values(self):
        conn = _make_conn()
        transformer = AggGameTotalsTransformer()
        transformer._conn = conn

        result = transformer.transform({})
        row = result.row(0, named=True)

        # home: 40/85 ≈ 0.4706, away: 35/80 = 0.4375
        assert abs(row["home_fg_pct"] - 40 / 85) < 1e-4
        assert abs(row["away_fg_pct"] - 35 / 80) < 1e-4
        conn.close()
