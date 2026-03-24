"""Tests for trend and streak detection helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "chat"
    / "skills"
    / "nba-data-analytics"
    / "scripts"
    / "trends.py"
)
_spec = importlib.util.spec_from_file_location("trends", _PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

rolling_stats = _mod.rolling_stats
detect_streaks = _mod.detect_streaks
find_breakouts = _mod.find_breakouts
season_projection = _mod.season_projection


# ---------------------------------------------------------------------------
# rolling_stats
# ---------------------------------------------------------------------------


class TestRollingStats:
    @pytest.fixture()
    def game_log(self):
        dates = pd.date_range("2025-10-01", periods=20, freq="2D")
        return pd.DataFrame(
            {
                "game_date": dates,
                "pts": list(range(20, 40)),
                "reb": [10.0] * 20,
            }
        )

    def test_rolling_average(self, game_log):
        result = rolling_stats(game_log, stat_cols=["pts"], window=10)
        col = "pts_rolling_10"
        assert col in result.columns
        # First value is just itself (min_periods=1)
        assert result[col].iloc[0] == pytest.approx(20.0)
        # 10th value should be mean of first 10: mean(20..29) = 24.5
        assert result[col].iloc[9] == pytest.approx(24.5)

    def test_adds_columns(self, game_log):
        result = rolling_stats(game_log, stat_cols=["pts", "reb"], window=5)
        assert "pts_rolling_5" in result.columns
        assert "reb_rolling_5" in result.columns

    def test_respects_window_param(self, game_log):
        r5 = rolling_stats(game_log, stat_cols=["pts"], window=5)
        r10 = rolling_stats(game_log, stat_cols=["pts"], window=10)
        # At row 9, window=5 uses last 5 values, window=10 uses all 10
        # They should differ because the underlying data is non-constant
        assert r5["pts_rolling_5"].iloc[9] != r10["pts_rolling_10"].iloc[9]


# ---------------------------------------------------------------------------
# detect_streaks
# ---------------------------------------------------------------------------


class TestDetectStreaks:
    def test_planted_streak(self):
        # 5 games below + 7 games at/above + 5 games below threshold
        values = [20] * 5 + [30] * 7 + [20] * 5
        dates = pd.date_range("2025-11-01", periods=17, freq="D")
        df = pd.DataFrame({"game_date": dates, "pts": values})

        result = detect_streaks(df, stat_col="pts", threshold=25, direction="above")
        assert result["length"].max() == 7

    def test_no_qualifying_games(self):
        dates = pd.date_range("2025-11-01", periods=10, freq="D")
        df = pd.DataFrame({"game_date": dates, "pts": [10] * 10})
        result = detect_streaks(df, stat_col="pts", threshold=25, direction="above")
        assert result.empty

    def test_multiple_streaks(self):
        # Two distinct streaks of 3 and 4 games above threshold
        values = [30, 30, 30, 10, 10, 30, 30, 30, 30, 10]
        dates = pd.date_range("2025-11-01", periods=10, freq="D")
        df = pd.DataFrame({"game_date": dates, "pts": values})

        result = detect_streaks(df, stat_col="pts", threshold=25, direction="above")
        assert len(result) == 2
        lengths = sorted(result["length"].tolist())
        assert lengths == [3, 4]

    def test_below_direction(self):
        values = [5, 5, 5, 50, 50]
        dates = pd.date_range("2025-11-01", periods=5, freq="D")
        df = pd.DataFrame({"game_date": dates, "pts": values})
        result = detect_streaks(df, stat_col="pts", threshold=10, direction="below")
        assert result["length"].max() == 3


# ---------------------------------------------------------------------------
# find_breakouts
# ---------------------------------------------------------------------------


class TestFindBreakouts:
    def test_planted_outlier(self):
        np.random.seed(42)
        pts = [20.0] * 40 + [50.0]
        dates = pd.date_range("2025-10-01", periods=41, freq="D")
        df = pd.DataFrame({"game_date": dates, "pts": pts})

        result = find_breakouts(df, stat_col="pts", sigma=2.0)
        assert len(result) >= 1
        assert result["pts"].iloc[0] == 50.0
        assert "_sigma_above" in result.columns

    def test_no_breakouts(self):
        # Use slightly varying data so std > 0, but no value exceeds mean + 2*std
        np.random.seed(99)
        pts = np.random.normal(20.0, 1.0, size=30).round(1).tolist()
        # Clip to ensure nothing is more than 2 sigma above mean
        mean, std = np.mean(pts), np.std(pts)
        pts = [min(p, mean + 1.5 * std) for p in pts]
        dates = pd.date_range("2025-10-01", periods=30, freq="D")
        df = pd.DataFrame({"game_date": dates, "pts": pts})
        result = find_breakouts(df, stat_col="pts", sigma=2.0)
        assert len(result) == 0

    def test_too_few_games(self):
        dates = pd.date_range("2025-10-01", periods=5, freq="D")
        df = pd.DataFrame({"game_date": dates, "pts": [20.0] * 5})
        result = find_breakouts(df, stat_col="pts", sigma=2.0, min_games=20)
        assert "error" in result.columns


# ---------------------------------------------------------------------------
# season_projection
# ---------------------------------------------------------------------------


class TestSeasonProjection:
    def test_basic_projection(self):
        result = season_projection({"pts": 1000}, games_played=41, total_games=82)
        proj = result["projections"]["pts"]
        assert proj["projected_total"] == pytest.approx(2000.0, abs=0.5)
        assert proj["per_game"] == pytest.approx(24.39, abs=0.01)

    def test_confidence_interval(self):
        result = season_projection({"pts": 500}, games_played=20, total_games=82)
        proj = result["projections"]["pts"]
        assert proj["projected_low"] < proj["projected_total"]
        assert proj["projected_total"] < proj["projected_high"]

    def test_zero_games(self):
        result = season_projection({"pts": 0}, games_played=0)
        assert "error" in result

    def test_series_input(self):
        stats = pd.Series({"pts": 800.0, "reb": 400.0})
        result = season_projection(stats, games_played=40, total_games=82)
        assert "pts" in result["projections"]
        assert "reb" in result["projections"]

    def test_full_season_no_remaining(self):
        result = season_projection({"pts": 2000}, games_played=82, total_games=82)
        proj = result["projections"]["pts"]
        # With 0 remaining games, projected == current
        assert proj["projected_total"] == pytest.approx(2000.0, abs=0.5)
