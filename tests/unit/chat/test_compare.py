"""Tests for player comparison framework."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

# Load compare module dynamically since it's a skill script, not a package.
_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "chat"
    / "skills"
    / "nba-data-analytics"
    / "scripts"
    / "compare.py"
)
_spec = importlib.util.spec_from_file_location("compare", _PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

compare_players = _mod.compare_players
percentile_rank = _mod.percentile_rank
radar_chart = _mod.radar_chart
per36 = _mod.per36
per100 = _mod.per100


@pytest.fixture(autouse=True)
def _close_plots():
    """Close all matplotlib figures after each test."""
    yield
    plt.close("all")


def _make_players_df() -> pd.DataFrame:
    """Build a synthetic 3-player DataFrame with known values."""
    return pd.DataFrame(
        {
            "full_name": ["Alice", "Bob", "Carol"],
            "player_id": [1, 2, 3],
            "pts": [25.0, 18.0, 30.0],
            "reb": [8.0, 10.0, 6.0],
            "ast": [7.0, 3.0, 9.0],
            "tov": [3.0, 2.0, 4.0],
        }
    )


# -- compare_players -----------------------------------------------------------


class TestComparePlayers:
    def test_three_players(self):
        df = _make_players_df()
        result = compare_players(df)
        # 3 players + League Avg row
        assert len(result) == 4
        assert "League Avg" in result.index

    def test_auto_detects_metrics(self):
        df = _make_players_df()
        result = compare_players(df)
        # player_id is excluded; pts, reb, ast, tov remain
        assert "pts" in result.columns
        assert "reb" in result.columns
        assert "player_id" not in result.columns

    def test_explicit_metrics(self):
        df = _make_players_df()
        result = compare_players(df, metrics=["pts", "ast"])
        assert list(result.columns) == ["pts", "ast"]
        assert len(result) == 4

    def test_single_player(self):
        df = _make_players_df().iloc[:1]
        result = compare_players(df)
        assert len(result) == 2  # 1 player + League Avg
        # League Avg equals the single player's values
        assert result.loc["League Avg", "pts"] == 25.0


# -- percentile_rank -----------------------------------------------------------


class TestPercentileRank:
    def test_percentiles_range(self):
        df = _make_players_df()
        result = percentile_rank(df)
        pctile_cols = [c for c in result.columns if c.endswith("_pctile")]
        assert len(pctile_cols) > 0
        for col in pctile_cols:
            assert result[col].min() > 0
            assert result[col].max() <= 100

    def test_best_player_top(self):
        df = _make_players_df()
        result = percentile_rank(df, metrics=["pts"])
        # Carol has 30 pts (highest) → highest percentile
        carol_pctile = result.loc[result["full_name"] == "Carol", "pts_pctile"].iloc[0]
        bob_pctile = result.loc[result["full_name"] == "Bob", "pts_pctile"].iloc[0]
        assert carol_pctile > bob_pctile

    def test_ascending_cols(self):
        df = _make_players_df()
        result = percentile_rank(df, metrics=["tov"], ascending_cols=["tov"])
        pctiles = result.set_index("full_name")["tov_pctile"]
        # Lower-is-better metrics should invert the raw ordering: 2 TOV beats 3 beats 4.
        assert pctiles["Bob"] > pctiles["Alice"] > pctiles["Carol"]


# -- radar_chart ---------------------------------------------------------------


class TestRadarChart:
    def test_basic_chart(self):
        stats = {
            "Alice": {"pts": 25, "reb": 8, "ast": 7},
            "Bob": {"pts": 18, "reb": 10, "ast": 3},
        }
        fig = radar_chart(stats)
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_dataframe_input(self):
        df = pd.DataFrame(
            {"pts": [25, 18], "reb": [8, 10], "ast": [7, 3]},
            index=["Alice", "Bob"],
        )
        fig = radar_chart(df)
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_empty_data(self):
        fig = radar_chart({})
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_two_categories(self):
        stats = {"Alice": {"pts": 25, "reb": 8}}
        fig = radar_chart(stats)
        assert isinstance(fig, matplotlib.figure.Figure)

    def test_multiple_players(self):
        stats = {
            "Alice": {"pts": 25, "reb": 8, "ast": 7, "stl": 2},
            "Bob": {"pts": 18, "reb": 10, "ast": 3, "stl": 1},
            "Carol": {"pts": 30, "reb": 6, "ast": 9, "stl": 3},
        }
        fig = radar_chart(stats, title="Trio Compare")
        assert isinstance(fig, matplotlib.figure.Figure)
        # Check the title was set
        axes = fig.get_axes()
        assert len(axes) == 1
        assert axes[0].get_title() == "Trio Compare"


# -- per36 ---------------------------------------------------------------------


class TestPer36:
    def test_normalization_math(self):
        df = pd.DataFrame({"full_name": ["Alice"], "avg_min": [30.0], "pts": [20.0]})
        result = per36(df)
        # 20 * 36 / 30 = 24.0
        assert result["pts_per36"].iloc[0] == pytest.approx(24.0)

    def test_zero_minutes(self):
        df = pd.DataFrame({"full_name": ["Alice"], "avg_min": [0.0], "pts": [20.0]})
        result = per36(df)
        assert result["pts_per36"].iloc[0] == pytest.approx(0.0)

    def test_adds_columns(self):
        df = pd.DataFrame(
            {
                "full_name": ["Alice"],
                "avg_min": [30.0],
                "pts": [20.0],
                "reb": [8.0],
            }
        )
        result = per36(df)
        assert "pts_per36" in result.columns
        assert "reb_per36" in result.columns
        # Original columns still present
        assert "pts" in result.columns
        assert "reb" in result.columns


# -- per100 --------------------------------------------------------------------


class TestPer100:
    def test_normalization_math(self):
        df = pd.DataFrame({"full_name": ["Alice"], "pace": [95.0], "pts": [25.0]})
        result = per100(df)
        # 25 * 100 / 95 ≈ 26.32
        assert result["pts_per100"].iloc[0] == pytest.approx(26.32, abs=0.01)

    def test_zero_pace(self):
        df = pd.DataFrame({"full_name": ["Alice"], "pace": [0.0], "pts": [25.0]})
        result = per100(df)
        assert result["pts_per100"].iloc[0] == pytest.approx(0.0)

    def test_adds_columns(self):
        df = pd.DataFrame(
            {
                "full_name": ["Alice"],
                "pace": [95.0],
                "pts": [25.0],
                "ast": [7.0],
            }
        )
        result = per100(df)
        assert "pts_per100" in result.columns
        assert "ast_per100" in result.columns
        assert "pts" in result.columns
        assert "ast" in result.columns
