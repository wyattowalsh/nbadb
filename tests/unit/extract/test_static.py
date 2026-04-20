from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest

from nbadb.extract.static.players import StaticPlayersExtractor
from nbadb.extract.static.teams import StaticTeamsExtractor


class TestStaticPlayersExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_dataframe(self) -> None:
        mock_data = [
            {
                "id": 2544,
                "full_name": "LeBron James",
                "first_name": "LeBron",
                "last_name": "James",
                "is_active": True,
            },
            {
                "id": 201566,
                "full_name": "Russell Westbrook",
                "first_name": "Russell",
                "last_name": "Westbrook",
                "is_active": True,
            },
        ]
        with patch(
            "nbadb.extract.static.players.static_players.get_players",
            return_value=mock_data,
        ):
            ext = StaticPlayersExtractor()
            df = await ext.extract()
            assert isinstance(df, pl.DataFrame)
            assert df.shape[0] == 2
            assert "id" in df.columns

    def test_class_attributes(self) -> None:
        assert StaticPlayersExtractor.endpoint_name == "static_players"
        assert StaticPlayersExtractor.category == "static"


class TestStaticTeamsExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_dataframe(self) -> None:
        mock_data = [
            {
                "id": 1610612747,
                "full_name": "Los Angeles Lakers",
                "abbreviation": "LAL",
                "nickname": "Lakers",
                "city": "Los Angeles",
                "state": "California",
                "year_founded": 1947,
            },
        ]
        with patch(
            "nbadb.extract.static.teams.static_teams.get_teams",
            return_value=mock_data,
        ):
            ext = StaticTeamsExtractor()
            df = await ext.extract()
            assert isinstance(df, pl.DataFrame)
            assert df.shape[0] == 1

    def test_class_attributes(self) -> None:
        assert StaticTeamsExtractor.endpoint_name == "static_teams"
        assert StaticTeamsExtractor.category == "static"
