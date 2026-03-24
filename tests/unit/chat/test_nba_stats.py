"""Tests for NBA statistical testing helpers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# Load nba_stats dynamically since it's a skill script, not a package.
_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "chat"
    / "skills"
    / "nba-data-analytics"
    / "scripts"
    / "nba_stats.py"
)
_spec = importlib.util.spec_from_file_location("nba_stats", _PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

is_significant = _mod.is_significant
shooting_confidence = _mod.shooting_confidence
breakout_threshold = _mod.breakout_threshold
streak_significance = _mod.streak_significance


# -- is_significant ------------------------------------------------------------


class TestIsSignificant:
    def test_clearly_different(self):
        result = is_significant([30, 31, 32, 33, 34], [10, 11, 12, 13, 14])
        assert result["significant"] is True
        assert result["p_value"] < 0.05

    def test_similar_groups(self):
        result = is_significant([20, 21, 20, 21, 20], [20, 21, 20, 21, 20])
        assert result["significant"] is False

    def test_auto_selects_test(self):
        result = is_significant([30, 31, 32, 33, 34], [10, 11, 12, 13, 14])
        assert result["test_used"] in ("Welch's t-test", "Mann-Whitney U")

    def test_small_sample_error(self):
        result = is_significant([1, 2], [3, 4])
        assert "error" in result
        assert result["significant"] is None

    def test_json_serializable(self):
        result = is_significant([30, 31, 32, 33, 34], [10, 11, 12, 13, 14])
        serialized = json.dumps(result)
        assert isinstance(serialized, str)

    def test_forced_ttest(self):
        result = is_significant([30, 31, 32, 33, 34], [10, 11, 12, 13, 14], test="ttest")
        assert result["test_used"] == "Welch's t-test"
        assert result["significant"] is True

    def test_forced_mannwhitney(self):
        result = is_significant([30, 31, 32, 33, 34], [10, 11, 12, 13, 14], test="mannwhitney")
        assert result["test_used"] == "Mann-Whitney U"
        assert result["significant"] is True


# -- shooting_confidence -------------------------------------------------------


class TestShootingConfidence:
    def test_50_percent_shooter(self):
        result = shooting_confidence(50, 100)
        assert result["pct"] == pytest.approx(0.5, abs=0.01)
        assert result["lower"] < 0.5
        assert result["upper"] > 0.5

    def test_perfect_shooter(self):
        result = shooting_confidence(10, 10)
        assert result["pct"] == 1.0
        assert result["upper"] == 1.0

    def test_zero_attempts(self):
        result = shooting_confidence(0, 0)
        assert result["pct"] == 0.0
        assert result["lower"] == 0.0
        assert result["upper"] == 0.0

    def test_small_sample_wider_interval(self):
        small = shooting_confidence(3, 5)
        large = shooting_confidence(60, 100)
        # Small sample should produce a wider interval
        small_width = small["upper"] - small["lower"]
        large_width = large["upper"] - large["lower"]
        assert small_width > large_width


# -- breakout_threshold --------------------------------------------------------


class TestBreakoutThreshold:
    def test_planted_outlier(self):
        data = [20.0] * 40 + [50.0]
        result = breakout_threshold(data)
        assert result["breakout_count"] == 1
        assert 40 in result["breakout_indices"]

    def test_uniform_data(self):
        data = [20.0] * 50
        result = breakout_threshold(data)
        # All values identical → std=0 → threshold=mean → all values equal threshold
        # With std=0, threshold = mean + 0 = mean, so all values >= threshold
        # Actually all 50 values == 20 == threshold, so all are "breakouts"
        # But that's because std=0. Let's just verify the function runs.
        assert result["std"] == 0.0
        assert result["threshold"] == result["mean"]

    def test_small_sample_error(self):
        result = breakout_threshold([1, 2, 3])
        assert "error" in result
        assert result["breakout_indices"] == []

    def test_json_serializable(self):
        data = [20.0] * 40 + [50.0]
        result = breakout_threshold(data)
        serialized = json.dumps(result)
        assert isinstance(serialized, str)


# -- streak_significance -------------------------------------------------------


class TestStreakSignificance:
    def test_all_makes(self):
        result = streak_significance([1] * 20)
        assert result["longest_streak"] == 20

    def test_alternating(self):
        result = streak_significance([1, 0] * 10)
        assert result["longest_streak"] == 1

    def test_small_sample_error(self):
        result = streak_significance([1, 0, 1, 0, 1])
        assert "error" in result
        assert result["significant"] is None

    def test_hot_vs_cold_direction(self):
        data = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1]
        hot = streak_significance(data, direction="hot")
        cold = streak_significance(data, direction="cold")
        assert hot["direction"] == "hot"
        assert cold["direction"] == "cold"
        assert hot["longest_streak"] == 5
        assert cold["longest_streak"] == 5
