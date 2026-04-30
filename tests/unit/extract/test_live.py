from __future__ import annotations

import json
from datetime import UTC, datetime
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
        snapshot_at = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)

        with patch("nbadb.extract.live.endpoints.ScoreBoard", _FakeScoreBoard):
            extractor = LiveScoreBoardExtractor()
            df = await extractor.extract(snapshot_at=snapshot_at)
        assert isinstance(df, pl.DataFrame)
        assert df.shape == (2, 6)
        assert "game_id" in df.columns
        assert "snapshot_at" in df.columns
        assert df["source_endpoint"].to_list() == ["live_score_board", "live_score_board"]
        assert df["snapshot_date"].to_list() == [snapshot_at.date(), snapshot_at.date()]
        assert json.loads(df["payload_json"][0])["gameId"] == "001"


class TestLiveOddsExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_games_dataframe(self) -> None:
        snapshot_at = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)

        with patch("nbadb.extract.live.endpoints.Odds", _FakeOdds):
            extractor = LiveOddsExtractor()
            df = await extractor.extract(snapshot_at=snapshot_at)
        assert isinstance(df, pl.DataFrame)
        assert df.shape[0] == 1
        assert "game_id" in df.columns
        # Note: Pandera schema validation strips timezone info during validation,
        # so we compare without timezone
        assert df["snapshot_at"][0] == snapshot_at.replace(tzinfo=None)
        assert df["source_endpoint"][0] == "live_odds"
        assert json.loads(df["payload_json"][0])["gameId"] == "001"


class TestLivePlayByPlayExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_actions_dataframe(self) -> None:
        snapshot_at = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)

        with patch("nbadb.extract.live.endpoints.PlayByPlay", _FakePlayByPlay):
            extractor = LivePlayByPlayExtractor()
            df = await extractor.extract(game_id="001", snapshot_at=snapshot_at)
        assert isinstance(df, pl.DataFrame)
        assert df.shape[0] == 1
        assert "action_number" in df.columns
        assert df["game_id"][0] == "001"
        assert df["source_endpoint"][0] == "live_play_by_play"
        assert json.loads(df["payload_json"][0])["actionNumber"] == 1


class TestLiveBoxScoreExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_primary_game_details(self) -> None:
        snapshot_at = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)

        with patch("nbadb.extract.live.endpoints.BoxScore", _FakeBoxScore):
            extractor = LiveBoxScoreExtractor()
            df = await extractor.extract(game_id="001", snapshot_at=snapshot_at)
        assert isinstance(df, pl.DataFrame)
        assert df.shape[0] == 1
        assert "game_id" in df.columns
        assert df["source_endpoint"][0] == "live_box_score.game_details"
        assert df["snapshot_at"][0] == snapshot_at.replace(tzinfo=None)
        assert json.loads(df["payload_json"][0])["gameId"] == "001"

    @pytest.mark.asyncio
    async def test_extract_all_returns_all_live_datasets(self) -> None:
        snapshot_at = datetime(2026, 4, 17, 12, 0, tzinfo=UTC)

        with patch("nbadb.extract.live.endpoints.BoxScore", _FakeBoxScore):
            extractor = LiveBoxScoreExtractor()
            frames = await extractor.extract_all(game_id="001", snapshot_at=snapshot_at)
        assert len(frames) == 7
        assert all(isinstance(frame, pl.DataFrame) for frame in frames)
        assert frames[0]["game_id"][0] == "001"
        assert [frame["source_endpoint"][0] for frame in frames] == [
            "live_box_score.game_details",
            "live_box_score.arena",
            "live_box_score.officials",
            "live_box_score.home_team_stats",
            "live_box_score.away_team_stats",
            "live_box_score.home_team_player_stats",
            "live_box_score.away_team_player_stats",
        ]
        assert frames[1]["game_id"][0] == "001"
        assert frames[2]["person_id"][0] == 1
        assert frames[3]["team_id"][0] == 1610612738
        assert frames[5]["person_id"][0] == 1
