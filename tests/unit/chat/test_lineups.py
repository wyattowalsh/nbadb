"""Tests for lineup analysis helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "chat"
    / "skills"
    / "nba-data-analytics"
    / "scripts"
    / "lineups.py"
)
_spec = importlib.util.spec_from_file_location("lineups", _PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

on_off_impact = _mod.on_off_impact
two_man_combos = _mod.two_man_combos
lineup_chart = _mod.lineup_chart


# ---------------------------------------------------------------------------
# on_off_impact
# ---------------------------------------------------------------------------


class TestOnOffImpact:
    def test_computes_delta(self):
        df = pd.DataFrame(
            {
                "entity_id": [1, 1],
                "on_off": ["On", "Off"],
                "off_rating": [110.0, 105.0],
                "def_rating": [100.0, 108.0],
            }
        )
        result = on_off_impact(df)
        assert len(result) == 1
        assert result["off_rating_delta"].iloc[0] == pytest.approx(5.0)
        assert result["def_rating_delta"].iloc[0] == pytest.approx(-8.0)

    def test_handles_multiple_players(self):
        rows = []
        for pid in [1, 2, 3]:
            rows.append({"entity_id": pid, "on_off": "On", "net_rating": 5.0 * pid})
            rows.append({"entity_id": pid, "on_off": "Off", "net_rating": 2.0 * pid})
        df = pd.DataFrame(rows)
        result = on_off_impact(df)
        assert len(result) == 3
        # deltas should be 3, 6, 9
        deltas = sorted(result["net_rating_delta"].tolist())
        assert deltas == pytest.approx([3.0, 6.0, 9.0])

    def test_empty_when_no_match(self):
        df = pd.DataFrame(
            {
                "entity_id": [1, 2],
                "on_off": ["On", "Off"],
                "net_rating": [110.0, 105.0],
            }
        )
        result = on_off_impact(df)
        assert result.empty

    def test_name_col_included(self):
        df = pd.DataFrame(
            {
                "entity_id": [10, 10],
                "on_off": ["On", "Off"],
                "net_rating": [8.0, 3.0],
                "player_name": ["LeBron James", "LeBron James"],
            }
        )
        result = on_off_impact(df, name_col="player_name")
        assert "player_name" in result.columns
        assert result["player_name"].iloc[0] == "LeBron James"


# ---------------------------------------------------------------------------
# two_man_combos
# ---------------------------------------------------------------------------


class TestTwoManCombos:
    def test_generates_pairs(self):
        df = pd.DataFrame(
            {
                "player1": ["A", "A"],
                "player2": ["B", "B"],
                "player3": ["C", "D"],
                "avg_net_rating": [5.0, -2.0],
                "min": [24.0, 18.0],
            }
        )
        result = two_man_combos(df)
        # 3 players in row 1 → 3 pairs; row 2 has A,B,D → 3 pairs
        # unique pairs: A-B, A-C, B-C, A-D, B-D  = 5
        assert len(result) == 5

    def test_sorted_by_rating(self):
        df = pd.DataFrame(
            {
                "player1": ["A", "X"],
                "player2": ["B", "Y"],
                "avg_net_rating": [-10.0, 15.0],
                "min": [20.0, 20.0],
            }
        )
        result = two_man_combos(df)
        assert result.iloc[0]["weighted_net_rating"] >= result.iloc[-1]["weighted_net_rating"]

    def test_no_player_cols(self):
        df = pd.DataFrame({"rating": [1.0], "minutes": [10.0]})
        result = two_man_combos(df)
        assert "error" in result.columns


# ---------------------------------------------------------------------------
# lineup_chart
# ---------------------------------------------------------------------------


@pytest.mark.skipif(importlib.util.find_spec("plotly") is None, reason="plotly not installed")
class TestLineupChart:
    @pytest.fixture()
    def sample_df(self):
        return pd.DataFrame(
            {
                "group_id": [f"lineup_{i}" for i in range(20)],
                "avg_net_rating": [float(i - 10) for i in range(20)],
            }
        )

    def test_returns_plotly_figure(self, sample_df):
        fig = lineup_chart(sample_df, n=5)
        assert hasattr(fig, "data")
        assert hasattr(fig, "layout")

    def test_top_and_bottom(self, sample_df):
        fig = lineup_chart(sample_df, n=5)
        # The chart should include both positive and negative values
        bar_data = fig.data[0]
        values = list(bar_data.x)
        assert any(v > 0 for v in values)
        assert any(v < 0 for v in values)
