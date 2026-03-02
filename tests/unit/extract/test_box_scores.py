from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from nbadb.extract.stats.box_scores import BoxScoreTraditionalExtractor

FIXTURE_PATH = "tests/fixtures/raw_box_score_traditional.json"


@pytest.fixture
def box_score_fixture() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _mock_nba_api_response(fixture: dict) -> MagicMock:
    import pandas as pd

    rs = fixture["resultSets"][0]
    pdf = pd.DataFrame(rs["rowSet"], columns=rs["headers"])
    mock_cls = MagicMock()
    mock_cls.return_value.get_data_frames.return_value = [pdf]
    return mock_cls


class TestBoxScoreTraditionalExtractor:
    def test_class_attributes(self) -> None:
        assert BoxScoreTraditionalExtractor.endpoint_name == "box_score_traditional"
        assert BoxScoreTraditionalExtractor.category == "box_score"

    @pytest.mark.asyncio
    async def test_extract_returns_lowercased_columns(self, box_score_fixture: dict) -> None:
        mock_cls = _mock_nba_api_response(box_score_fixture)
        ext = BoxScoreTraditionalExtractor()
        with patch.object(
            ext,
            "_from_nba_api",
            wraps=ext._from_nba_api,
        ):
            ext._from_nba_api = MagicMock(
                return_value=pl.from_pandas(
                    mock_cls.return_value.get_data_frames.return_value[0]
                ).rename(
                    {
                        c: c.lower()
                        for c in mock_cls.return_value.get_data_frames.return_value[0].columns
                    }
                )
            )
            result = await ext.extract(game_id="0022400001")
            assert isinstance(result, pl.DataFrame)
            assert result.shape[0] == 2
            assert all(c == c.lower() for c in result.columns)
            assert "player_id" in result.columns
            assert "pts" in result.columns

    @pytest.mark.asyncio
    async def test_extract_with_mock_nba_api(self, box_score_fixture: dict) -> None:
        mock_cls = _mock_nba_api_response(box_score_fixture)
        ext = BoxScoreTraditionalExtractor()
        with patch(
            "nbadb.extract.stats.box_scores.BoxScoreTraditionalV3",
            mock_cls,
        ):
            result = ext._from_nba_api(mock_cls, game_id="0022400001")
            assert isinstance(result, pl.DataFrame)
            assert result.shape[0] == 2

    def test_registered_in_registry(self) -> None:
        from nbadb.extract.registry import registry

        cls = registry.get("box_score_traditional")
        assert cls is BoxScoreTraditionalExtractor
