"""Tests that verify extract() calls with mocked nba_api endpoints using JSON fixtures.

Each test mocks the nba_api endpoint class, feeds it fixture data (converted
to a pandas DataFrame), and asserts the extractor returns a properly-shaped
Polars DataFrame with lowercased columns.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import polars as pl

from nbadb.extract.base import BaseExtractor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES_DIR = "tests/fixtures"


def _load_fixture(name: str) -> dict[str, Any]:
    with open(f"{FIXTURES_DIR}/{name}") as f:
        return json.load(f)


def _fixture_to_pandas(fixture: dict[str, Any], result_set_idx: int = 0) -> pd.DataFrame:
    """Convert a raw nba_api-style JSON fixture to a pandas DataFrame."""
    rs = fixture["resultSets"][result_set_idx]
    return pd.DataFrame(rs["rowSet"], columns=rs["headers"])


def _mock_endpoint(fixture: dict[str, Any]) -> MagicMock:
    """Create a MagicMock endpoint that returns fixture data as pandas DFs."""
    mock = MagicMock()
    dfs = [_fixture_to_pandas(fixture, i) for i in range(len(fixture["resultSets"]))]
    mock.return_value.get_data_frames.return_value = dfs
    return mock


# ---------------------------------------------------------------------------
# Box Score Traditional
# ---------------------------------------------------------------------------


class TestBoxScoreTraditionalExtract:
    async def test_extract_returns_lowercased_columns(self) -> None:
        from nbadb.extract.stats.box_scores import BoxScoreTraditionalExtractor

        fixture = _load_fixture("raw_box_score_traditional.json")
        mock_ep = _mock_endpoint(fixture)

        ext = BoxScoreTraditionalExtractor()
        ext._from_nba_api = lambda ep_cls, **kw: BaseExtractor._from_nba_api(ext, mock_ep, **kw)

        result = ext._from_nba_api(mock_ep, game_id="0022400001")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 2
        assert all(c == c.lower() for c in result.columns)
        assert "player_id" in result.columns
        assert "pts" in result.columns

    def test_fixture_has_two_result_sets(self) -> None:
        fixture = _load_fixture("raw_box_score_traditional.json")
        assert len(fixture["resultSets"]) == 2


# ---------------------------------------------------------------------------
# Play By Play
# ---------------------------------------------------------------------------


class TestPlayByPlayExtract:
    async def test_extract_returns_play_events(self) -> None:
        from nbadb.extract.stats.play_by_play import PlayByPlayExtractor

        fixture = _load_fixture("raw_play_by_play.json")
        mock_ep = _mock_endpoint(fixture)

        ext = PlayByPlayExtractor()
        result = ext._from_nba_api(mock_ep, game_id="0022400001")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 3
        assert "game_id" in result.columns
        assert "eventnum" in result.columns


# ---------------------------------------------------------------------------
# Game Log
# ---------------------------------------------------------------------------


class TestGameLogExtract:
    async def test_extract_returns_game_log(self) -> None:
        from nbadb.extract.stats.game_log import LeagueGameLogExtractor

        fixture = _load_fixture("raw_game_log.json")
        mock_ep = _mock_endpoint(fixture)

        ext = LeagueGameLogExtractor()
        result = ext._from_nba_api(mock_ep, season="2024-25")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 2
        assert "game_id" in result.columns
        assert "team_abbreviation" in result.columns


# ---------------------------------------------------------------------------
# Player Info
# ---------------------------------------------------------------------------


class TestPlayerInfoExtract:
    async def test_extract_returns_player_info(self) -> None:
        from nbadb.extract.stats.player_info import CommonPlayerInfoExtractor

        fixture = _load_fixture("raw_player_info.json")
        mock_ep = _mock_endpoint(fixture)

        ext = CommonPlayerInfoExtractor()
        result = ext._from_nba_api(mock_ep, player_id=2544)
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 1
        assert "person_id" in result.columns
        assert "first_name" in result.columns


# ---------------------------------------------------------------------------
# Draft
# ---------------------------------------------------------------------------


class TestDraftExtract:
    async def test_extract_returns_draft_history(self) -> None:
        from nbadb.extract.stats.draft import DraftHistoryExtractor

        fixture = _load_fixture("raw_draft.json")
        mock_ep = _mock_endpoint(fixture)

        ext = DraftHistoryExtractor()
        result = ext._from_nba_api(mock_ep, season="2024")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 2
        assert "person_id" in result.columns
        assert "player_name" in result.columns


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------


class TestStandingsExtract:
    async def test_extract_returns_standings(self) -> None:
        from nbadb.extract.stats.standings import LeagueStandingsExtractor

        fixture = _load_fixture("raw_standings.json")
        mock_ep = _mock_endpoint(fixture)

        ext = LeagueStandingsExtractor()
        result = ext._from_nba_api(mock_ep, season="2024-25")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 1
        assert "team_id" in result.columns
        assert "wins" in result.columns


# ---------------------------------------------------------------------------
# Shot Chart
# ---------------------------------------------------------------------------


class TestShotChartExtract:
    async def test_extract_returns_shots(self) -> None:
        from nbadb.extract.stats.shots import ShotChartDetailExtractor

        fixture = _load_fixture("raw_shot_chart.json")
        mock_ep = _mock_endpoint(fixture)

        ext = ShotChartDetailExtractor()
        result = ext._from_nba_api(mock_ep, player_id=0)
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 2
        assert "player_name" in result.columns
        assert "shot_made_flag" in result.columns


# ---------------------------------------------------------------------------
# Rotation (multi result sets)
# ---------------------------------------------------------------------------


class TestRotationExtract:
    async def test_extract_multi_returns_both_teams(self) -> None:
        from nbadb.extract.stats.rotation import GameRotationExtractor

        fixture = _load_fixture("raw_rotation.json")
        mock_ep = _mock_endpoint(fixture)

        ext = GameRotationExtractor()
        results = ext._from_nba_api_multi(mock_ep, game_id="0022400001")
        assert len(results) == 2
        home = results[0]
        away = results[1]
        assert "game_id" in home.columns
        assert "person_id" in home.columns
        assert home.shape[0] == 1
        assert away.shape[0] == 1

    async def test_extract_single_returns_first(self) -> None:
        from nbadb.extract.stats.rotation import GameRotationExtractor

        fixture = _load_fixture("raw_rotation.json")
        mock_ep = _mock_endpoint(fixture)

        ext = GameRotationExtractor()
        result = ext._from_nba_api(mock_ep, game_id="0022400001")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 1


# ---------------------------------------------------------------------------
# Synergy
# ---------------------------------------------------------------------------


class TestSynergyExtract:
    async def test_extract_returns_synergy(self) -> None:
        from nbadb.extract.stats.synergy import SynergyPlayTypesExtractor

        fixture = _load_fixture("raw_synergy.json")
        mock_ep = _mock_endpoint(fixture)

        ext = SynergyPlayTypesExtractor()
        result = ext._from_nba_api(mock_ep, season="2024-25")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 1
        assert "play_type" in result.columns


# ---------------------------------------------------------------------------
# Win Probability
# ---------------------------------------------------------------------------


class TestWinProbabilityExtract:
    async def test_extract_returns_win_prob(self) -> None:
        from nbadb.extract.stats.win_probability import WinProbabilityExtractor

        fixture = _load_fixture("raw_win_probability.json")
        mock_ep = _mock_endpoint(fixture)

        ext = WinProbabilityExtractor()
        result = ext._from_nba_api(mock_ep, game_id="0022400001")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 2
        assert "home_pct" in result.columns


# ---------------------------------------------------------------------------
# Schedule (using raw_schedule.json which is in LeagueGameFinder format)
# ---------------------------------------------------------------------------


class TestScheduleExtract:
    async def test_extract_returns_schedule(self) -> None:
        from nbadb.extract.stats.schedule import ScheduleExtractor

        fixture = _load_fixture("raw_schedule.json")
        mock_ep = _mock_endpoint(fixture)

        ext = ScheduleExtractor()
        result = ext._from_nba_api(mock_ep, season="2024-25")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] >= 1
        assert all(c == c.lower() for c in result.columns)


# ---------------------------------------------------------------------------
# Hustle Stats
# ---------------------------------------------------------------------------


class TestHustleStatsExtract:
    async def test_extract_returns_hustle(self) -> None:
        from nbadb.extract.stats.hustle import HustleStatsBoxScoreExtractor

        fixture = _load_fixture("raw_hustle_stats.json")
        mock_ep = _mock_endpoint(fixture)

        ext = HustleStatsBoxScoreExtractor()
        result = ext._from_nba_api(mock_ep, game_id="0022400001")
        assert isinstance(result, pl.DataFrame)
        assert all(c == c.lower() for c in result.columns)


# ---------------------------------------------------------------------------
# Tracking Defense
# ---------------------------------------------------------------------------


class TestTrackingDefenseExtract:
    async def test_extract_returns_defense(self) -> None:
        from nbadb.extract.stats.tracking_defense import LeagueDashPtDefendExtractor

        fixture = _load_fixture("raw_tracking_defense.json")
        mock_ep = _mock_endpoint(fixture)

        ext = LeagueDashPtDefendExtractor()
        result = ext._from_nba_api(mock_ep, season="2024-25")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 1
        assert "player_name" in result.columns
        assert "d_fg_pct" in result.columns


# ---------------------------------------------------------------------------
# League Dash Player Stats
# ---------------------------------------------------------------------------


class TestLeagueDashPlayerStatsExtract:
    async def test_extract_returns_player_stats(self) -> None:
        from nbadb.extract.stats.league_stats import LeagueDashPlayerStatsExtractor

        fixture = _load_fixture("raw_league_dash_player_stats.json")
        mock_ep = _mock_endpoint(fixture)

        ext = LeagueDashPlayerStatsExtractor()
        result = ext._from_nba_api(mock_ep, season="2024-25")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 1
        assert "player_id" in result.columns
        assert "pts" in result.columns


# ---------------------------------------------------------------------------
# Franchise Leaders
# ---------------------------------------------------------------------------


class TestFranchiseLeadersExtract:
    async def test_extract_returns_franchise_leaders(self) -> None:
        from nbadb.extract.stats.franchise import FranchiseLeadersExtractor

        fixture = _load_fixture("raw_franchise_leaders.json")
        mock_ep = _mock_endpoint(fixture)

        ext = FranchiseLeadersExtractor()
        result = ext._from_nba_api(mock_ep, team_id=1610612747)
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 1
        assert "team_id" in result.columns


# ---------------------------------------------------------------------------
# League Leaders
# ---------------------------------------------------------------------------


class TestLeagueLeadersExtract:
    async def test_extract_returns_leaders(self) -> None:
        from nbadb.extract.stats.leaders import LeagueLeadersExtractor

        fixture = _load_fixture("raw_league_leaders.json")
        mock_ep = _mock_endpoint(fixture)

        ext = LeagueLeadersExtractor()
        result = ext._from_nba_api(mock_ep, season="2024-25")
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 1
        assert "player_id" in result.columns
        assert "pts" in result.columns


# ---------------------------------------------------------------------------
# Edge case: _from_nba_api_multi with box_score_traditional (2 result sets)
# ---------------------------------------------------------------------------


class TestMultiResultSet:
    async def test_multi_returns_all_sets(self) -> None:
        from nbadb.extract.stats.box_summary import BoxScoreSummaryExtractor

        fixture = _load_fixture("raw_box_score_traditional.json")
        mock_ep = _mock_endpoint(fixture)

        ext = BoxScoreSummaryExtractor()
        results = ext._from_nba_api_multi(mock_ep, game_id="0022400001")
        assert len(results) == 2
        player_stats = results[0]
        team_stats = results[1]
        assert "player_id" in player_stats.columns
        assert "team_name" in team_stats.columns
