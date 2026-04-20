"""Tests for NBA skill scripts: team_colors and season_utils."""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "chat"
    / "skills"
    / "nba-data-analytics"
    / "scripts"
)


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- team_colors ---------------------------------------------------------------

tc = _load_module("team_colors")


class TestTeamColors:
    def test_all_30_teams_present(self):
        assert len(tc.TEAM_COLORS) == 30

    def test_get_team_color_primary(self):
        assert tc.get_team_color("LAL") == "#552583"

    def test_get_team_color_secondary(self):
        assert tc.get_team_color("LAL", secondary=True) == "#FDB927"

    def test_get_team_color_case_insensitive(self):
        assert tc.get_team_color("lal") == "#552583"

    def test_get_team_color_unknown(self):
        assert tc.get_team_color("XXX") == "#888888"

    def test_get_color_map(self):
        cmap = tc.get_color_map(["LAL", "BOS", "GSW"])
        assert len(cmap) == 3
        assert cmap["LAL"] == "#552583"
        assert cmap["BOS"] == "#007A33"
        assert cmap["GSW"] == "#1D428A"

    def test_get_color_map_empty(self):
        assert tc.get_color_map([]) == {}

    def test_colors_are_valid_hex(self):
        for abbr, (primary, secondary) in tc.TEAM_COLORS.items():
            assert primary.startswith("#"), f"{abbr} primary missing #"
            assert len(primary) == 7, f"{abbr} primary wrong length"
            assert secondary.startswith("#"), f"{abbr} secondary missing #"
            assert len(secondary) == 7, f"{abbr} secondary wrong length"


# -- season_utils --------------------------------------------------------------

su = _load_module("season_utils")


class TestSeasonUtils:
    def test_current_season_november(self):
        # November 2025 → 2025-26 season
        result = su.current_season(date(2025, 11, 15))
        assert result == "2025-26"

    def test_current_season_march(self):
        # March 2026 → still 2025-26 season
        result = su.current_season(date(2026, 3, 15))
        assert result == "2025-26"

    def test_current_season_september(self):
        # September 2025 → still 2024-25 (offseason)
        result = su.current_season(date(2025, 9, 1))
        assert result == "2024-25"

    def test_current_season_october(self):
        # October = new season starts
        result = su.current_season(date(2025, 10, 1))
        assert result == "2025-26"

    def test_season_year_to_id(self):
        assert su.season_year_to_id("2024-25") == "22024"

    def test_season_id_to_year(self):
        assert su.season_id_to_year("22024") == "2024-25"

    def test_roundtrip(self):
        original = "2023-24"
        sid = su.season_year_to_id(original)
        back = su.season_id_to_year(sid)
        assert back == original
