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
game_score = _mod.game_score
possessions_fn = _mod.possessions  # avoid shadowing builtins
per_minute = _mod.per_minute
assist_pct = _mod.assist_pct
steal_pct = _mod.steal_pct
block_pct = _mod.block_pct
turnover_pct = _mod.turnover_pct


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


# -- game_score ----------------------------------------------------------------


class TestGameScore:
    def test_typical_value(self):
        # 30pts, 10fgm, 20fga, 8ftm, 10fta, 3oreb, 7dreb, 2stl, 5ast, 1blk, 3pf, 2tov
        # = 30 + 0.4*10 - 0.7*20 - 0.4*(10-8) + 0.7*3 + 0.3*7 + 2 + 0.7*5 + 0.7*1 - 0.4*3 - 2
        # = 30 + 4 - 14 - 0.8 + 2.1 + 2.1 + 2 + 3.5 + 0.7 - 1.2 - 2
        # = 26.4
        result = game_score(30, 10, 20, 8, 10, 3, 7, 2, 5, 1, 3, 2)
        assert result == pytest.approx(26.4, abs=0.01)

    def test_all_zeros(self):
        assert game_score(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0) == 0.0

    def test_none_inputs(self):
        result = game_score(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        assert result == 0.0


# -- possessions ---------------------------------------------------------------


class TestPossessions:
    def test_typical_value(self):
        # 85 FGA, 22 FTA, 10 OREB, 14 TOV → 85 - 10 + 14 + 0.44*22 = 98.68
        result = possessions_fn(85, 22, 10, 14)
        assert result == pytest.approx(98.68, abs=0.01)

    def test_none_inputs(self):
        assert possessions_fn(None, None, None, None) == 0.0


# -- per_minute ----------------------------------------------------------------


class TestPerMinute:
    def test_per36(self):
        # 20 pts in 30 min → 20*36/30 = 24.0
        result = per_minute(20, 30)
        assert result == pytest.approx(24.0)

    def test_per48(self):
        # 20 pts in 30 min, base=48 → 20*48/30 = 32.0
        result = per_minute(20, 30, base=48)
        assert result == pytest.approx(32.0)

    def test_zero_minutes(self):
        assert per_minute(20, 0) == 0.0


# -- assist_pct ----------------------------------------------------------------


class TestAssistPct:
    def test_typical_value(self):
        # 8 ast, 32 min, 40 team_fgm, 6 fgm, 240 team_min
        # adj = (32 / 48) * 40 - 6 = 26.667 - 6 = 20.667
        # = 100 * 8 / 20.667 ≈ 38.71
        result = assist_pct(8, 32, 40, 6, 240)
        assert 0.0 < result < 50.0

    def test_zero_minutes(self):
        assert assist_pct(8, 0, 40, 6, 240) == 0.0


# -- steal_pct -----------------------------------------------------------------


class TestStealPct:
    def test_typical_value(self):
        # 2 stl, 30 min, 100 poss, 240 team min
        # = 100 * (2 * 48) / (30 * 100) = 100 * 96 / 3000 = 3.2
        result = steal_pct(2, 30, 100, 240)
        assert result == pytest.approx(3.2, abs=0.01)

    def test_zero_minutes(self):
        assert steal_pct(2, 0, 100, 240) == 0.0


# -- block_pct -----------------------------------------------------------------


class TestBlockPct:
    def test_typical_value(self):
        # 2 blk, 30 min, 80 opp_fga, 240 team min
        # = 100 * (2 * 48) / (30 * 80) = 100 * 96 / 2400 = 4.0
        result = block_pct(2, 30, 80, 240)
        assert result == pytest.approx(4.0, abs=0.01)

    def test_zero_minutes(self):
        assert block_pct(2, 0, 80, 240) == 0.0


# -- turnover_pct --------------------------------------------------------------


class TestTurnoverPct:
    def test_typical_value(self):
        # 3 TOV, 18 FGA, 5 FTA → denom = 18 + 0.44*5 + 3 = 23.2
        # = 100 * 3 / 23.2 ≈ 12.93
        result = turnover_pct(3, 18, 5)
        assert result == pytest.approx(12.93, abs=0.01)

    def test_zero_denominator(self):
        assert turnover_pct(0, 0, 0) == 0.0
