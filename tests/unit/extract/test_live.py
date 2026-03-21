from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest

from nbadb.extract.live.endpoints import (
    LiveBoxScoreExtractor,
    LiveOddsExtractor,
    LivePlayByPlayExtractor,
    LiveScoreBoardExtractor,
)


class _FakeDataSet:
    def __init__(self, data):
        self._data = data

    def get_dict(self):
        return self._data


class _FakeScoreBoard:
    def __init__(self, **kwargs):
        self.games = _FakeDataSet(
            [
                {"gameId": "001", "gameStatusText": "Final"},
                {"gameId": "002", "gameStatusText": "Scheduled"},
            ]
        )


class _FakeOdds:
    def __init__(self, **kwargs):
        self.games = _FakeDataSet([{"gameId": "001", "markets": []}])


class _FakePlayByPlay:
    def __init__(self, **kwargs):
        self.actions = _FakeDataSet([{"actionNumber": 1, "teamId": 1610612738}])


class _FakeBoxScore:
    def __init__(self, **kwargs):
        self.game_details = _FakeDataSet({"gameId": kwargs["game_id"], "gameStatusText": "Final"})
        self.arena = _FakeDataSet({"arenaName": "Garden"})
        self.officials = _FakeDataSet([{"personId": 1}])
        self.home_team_stats = _FakeDataSet({"teamId": 1610612738, "score": 110})
        self.away_team_stats = _FakeDataSet({"teamId": 1610612737, "score": 108})
        self.home_team_player_stats = _FakeDataSet([{"personId": 1, "points": 20}])
        self.away_team_player_stats = _FakeDataSet([{"personId": 2, "points": 18}])


class TestLiveScoreBoardExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_games_dataframe(self) -> None:
        with patch("nbadb.extract.live.endpoints.ScoreBoard", _FakeScoreBoard):
            extractor = LiveScoreBoardExtractor()
            df = await extractor.extract()
        assert isinstance(df, pl.DataFrame)
        assert df.shape == (2, 2)
        assert "game_id" in df.columns


class TestLiveOddsExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_games_dataframe(self) -> None:
        with patch("nbadb.extract.live.endpoints.Odds", _FakeOdds):
            extractor = LiveOddsExtractor()
            df = await extractor.extract()
        assert isinstance(df, pl.DataFrame)
        assert df.shape[0] == 1
        assert "game_id" in df.columns


class TestLivePlayByPlayExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_actions_dataframe(self) -> None:
        with patch("nbadb.extract.live.endpoints.PlayByPlay", _FakePlayByPlay):
            extractor = LivePlayByPlayExtractor()
            df = await extractor.extract(game_id="001")
        assert isinstance(df, pl.DataFrame)
        assert df.shape[0] == 1
        assert "action_number" in df.columns


class TestLiveBoxScoreExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_primary_game_details(self) -> None:
        with patch("nbadb.extract.live.endpoints.BoxScore", _FakeBoxScore):
            extractor = LiveBoxScoreExtractor()
            df = await extractor.extract(game_id="001")
        assert isinstance(df, pl.DataFrame)
        assert df.shape[0] == 1
        assert "game_id" in df.columns

    @pytest.mark.asyncio
    async def test_extract_all_returns_all_live_datasets(self) -> None:
        with patch("nbadb.extract.live.endpoints.BoxScore", _FakeBoxScore):
            extractor = LiveBoxScoreExtractor()
            frames = await extractor.extract_all(game_id="001")
        assert len(frames) == 7
        assert all(isinstance(frame, pl.DataFrame) for frame in frames)
        assert frames[0]["game_id"][0] == "001"
