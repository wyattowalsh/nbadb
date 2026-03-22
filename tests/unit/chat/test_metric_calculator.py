"""Tests for NBA metric calculator functions."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# Load metric_calculator dynamically since it's a skill script, not a package.
_CALC_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "chat"
    / "skills"
    / "nba-data-analytics"
    / "scripts"
    / "metric_calculator.py"
)
_spec = importlib.util.spec_from_file_location("metric_calculator", _CALC_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

true_shooting_pct = _mod.true_shooting_pct
effective_fg_pct = _mod.effective_fg_pct
usage_rate = _mod.usage_rate
pace = _mod.pace
offensive_rating = _mod.offensive_rating
defensive_rating = _mod.defensive_rating
net_rating = _mod.net_rating
assist_to_turnover = _mod.assist_to_turnover
rebound_pct = _mod.rebound_pct


# -- true_shooting_pct --------------------------------------------------------


class TestTrueShootingPct:
    def test_typical_value(self):
        # 30 pts on 20 FGA, 10 FTA → TS% = 30 / (2*(20+4.4)) = 30/48.8 ≈ 0.6148
        result = true_shooting_pct(30, 20, 10)
        assert abs(result - 0.6148) < 0.001

    def test_zero_attempts(self):
        assert true_shooting_pct(0, 0, 0) == 0.0

    def test_none_inputs(self):
        assert true_shooting_pct(None, 20, 10) == 0.0
        assert true_shooting_pct(30, None, None) == 0.0


# -- effective_fg_pct ----------------------------------------------------------


class TestEffectiveFgPct:
    def test_typical_value(self):
        # 8 FGM, 3 3PM, 18 FGA → eFG% = (8+1.5)/18 ≈ 0.5278
        result = effective_fg_pct(8, 3, 18)
        assert abs(result - (8 + 1.5) / 18) < 0.001

    def test_zero_attempts(self):
        assert effective_fg_pct(0, 0, 0) == 0.0

    def test_none_inputs(self):
        # fgm=None coerced to 0 → (0 + 0.5*3)/18 ≈ 0.0833
        assert effective_fg_pct(None, 3, 18) == pytest.approx(0.0833, abs=0.001)
        # All None → fga=0 → guard returns 0.0
        assert effective_fg_pct(None, None, None) == 0.0


# -- usage_rate ----------------------------------------------------------------


class TestUsageRate:
    def test_typical_value(self):
        # Realistic: 18 FGA, 5 FTA, 3 TOV, 36 min
        # Team: 85 FGA, 22 FTA, 14 TOV, 240 min
        result = usage_rate(18, 5, 3, 36, 85, 22, 14, 240)
        assert 15.0 < result < 35.0  # NBA usage rates typically 15-35%

    def test_zero_minutes(self):
        assert usage_rate(10, 5, 2, 0, 80, 20, 14, 240) == 0.0

    def test_zero_team_possessions(self):
        assert usage_rate(10, 0, 0, 30, 0, 0, 0, 240) == 0.0

    def test_none_inputs(self):
        assert usage_rate(None, None, None, None, None, None, None, None) == 0.0


# -- pace ----------------------------------------------------------------------


class TestPace:
    def test_typical_value(self):
        # 100 team poss, 98 opp poss, 240 team min
        result = pace(100, 98, 240)
        # pace = 48 * (198 / (2 * 48)) = 48 * (198/96) = 48 * 2.0625 = 99.0
        assert abs(result - 99.0) < 0.1

    def test_zero_minutes(self):
        assert pace(100, 98, 0) == 0.0

    def test_none_inputs(self):
        assert pace(None, None, None) == 0.0


# -- offensive_rating ----------------------------------------------------------


class TestOffensiveRating:
    def test_typical_value(self):
        # 110 pts on 100 possessions → 110.0
        result = offensive_rating(110, 100)
        assert abs(result - 110.0) < 0.01

    def test_zero_possessions(self):
        assert offensive_rating(110, 0) == 0.0

    def test_none_inputs(self):
        assert offensive_rating(None, 100) == 0.0


# -- defensive_rating ----------------------------------------------------------


class TestDefensiveRating:
    def test_typical_value(self):
        result = defensive_rating(105, 100)
        assert abs(result - 105.0) < 0.01

    def test_zero_possessions(self):
        assert defensive_rating(105, 0) == 0.0

    def test_none_inputs(self):
        assert defensive_rating(None, None) == 0.0


# -- net_rating ----------------------------------------------------------------


class TestNetRating:
    def test_typical_value(self):
        assert net_rating(112.5, 108.3) == pytest.approx(4.2, abs=0.01)

    def test_negative(self):
        assert net_rating(100.0, 110.0) == pytest.approx(-10.0, abs=0.01)

    def test_none_inputs(self):
        assert net_rating(None, None) == 0.0


# -- assist_to_turnover --------------------------------------------------------


class TestAssistToTurnover:
    def test_typical_value(self):
        assert assist_to_turnover(10, 4) == pytest.approx(2.5)

    def test_zero_turnovers_returns_none(self):
        result = assist_to_turnover(10, 0)
        assert result is None

    def test_none_inputs(self):
        result = assist_to_turnover(None, None)
        assert result is None  # tov=0 → None

    def test_json_serializable(self):
        """All return values must be JSON-serializable (no float('inf'))."""
        result = assist_to_turnover(10, 0)
        # None serializes to null in JSON — no ValueError
        serialized = json.dumps({"ratio": result})
        assert '"ratio": null' in serialized

    def test_json_serializable_normal(self):
        result = assist_to_turnover(10, 4)
        serialized = json.dumps({"ratio": result})
        assert "2.5" in serialized


# -- rebound_pct ---------------------------------------------------------------


class TestReboundPct:
    def test_typical_value(self):
        # 10 reb, 30 min, 45 team reb, 40 opp reb, 240 team min
        result = rebound_pct(10, 30, 45, 40, 240)
        # = 100 * (10 * 48) / (30 * 85) = 100 * 480 / 2550 ≈ 18.82
        assert 15.0 < result < 25.0

    def test_zero_minutes(self):
        assert rebound_pct(10, 0, 45, 40, 240) == 0.0

    def test_zero_rebounds(self):
        assert rebound_pct(10, 30, 0, 0, 240) == 0.0

    def test_none_inputs(self):
        assert rebound_pct(None, None, None, None, None) == 0.0
