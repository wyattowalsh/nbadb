from __future__ import annotations

from unittest.mock import patch

import polars as pl
import pytest

from nbadb.extract.nba_api_adapter import NbaApiResultPacket
from nbadb.extract.static.players import StaticPlayersExtractor, StaticWnbaPlayersExtractor
from nbadb.extract.static.teams import StaticTeamsExtractor, StaticWnbaTeamsExtractor


class TestStaticPlayersExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_dataframe(self) -> None:
        packet = NbaApiResultPacket(
            name="players_shape_1",
            provider_index=0,
            canonical_index=0,
            headers=("id", "last_name", "first_name", "full_name", "is_active"),
            frame=pl.DataFrame(
                {
                    "id": [2544, 201566],
                    "last_name": ["James", "Westbrook"],
                    "first_name": ["LeBron", "Russell"],
                    "full_name": ["LeBron James", "Russell Westbrook"],
                    "is_active": [True, True],
                }
            ),
        )
        with patch(
            "nbadb.extract.static.players.fetch_static_packet", return_value=packet
        ) as fetch:
            ext = StaticPlayersExtractor()
            df = await ext.extract()
            assert isinstance(df, pl.DataFrame)
            assert df.shape[0] == 2
            assert df.columns == ["id", "full_name", "first_name", "last_name", "is_active"]
            fetch.assert_called_once_with("static_players", capture=None)

    def test_class_attributes(self) -> None:
        assert StaticPlayersExtractor.endpoint_name == "static_players"
        assert StaticPlayersExtractor.category == "static"


class TestStaticTeamsExtractor:
    @pytest.mark.asyncio
    async def test_extract_returns_dataframe(self) -> None:
        packet = NbaApiResultPacket(
            name="teams_shape_1",
            provider_index=0,
            canonical_index=0,
            headers=(
                "id",
                "abbreviation",
                "nickname",
                "year_founded",
                "city",
                "full_name",
                "state",
                "championship_year",
            ),
            frame=pl.DataFrame(
                {
                    "id": [1610612747, 1610612766],
                    "abbreviation": ["LAL", "CHA"],
                    "nickname": ["Lakers", "Hornets"],
                    "year_founded": [1947, 1988],
                    "city": ["Los Angeles", "Charlotte"],
                    "full_name": ["Los Angeles Lakers", "Charlotte Hornets"],
                    "state": ["California", "North Carolina"],
                    "championship_year": [[1949, 1950], []],
                }
            ),
        )
        with patch("nbadb.extract.static.teams.fetch_static_packet", return_value=packet) as fetch:
            ext = StaticTeamsExtractor()
            df = await ext.extract()
            assert isinstance(df, pl.DataFrame)
            assert df.shape == (2, 8)
            assert df["championship_years_json"].to_list() == ["[1949,1950]", "[]"]
            assert "championship_year" not in df.columns
            fetch.assert_called_once_with("static_teams", capture=None)

    def test_class_attributes(self) -> None:
        assert StaticTeamsExtractor.endpoint_name == "static_teams"
        assert StaticTeamsExtractor.category == "static"


class TestStaticWnbaPlayersExtractor:
    @pytest.mark.asyncio
    async def test_extract_preserves_raw_field_order_and_adds_league(self) -> None:
        packet = NbaApiResultPacket(
            name="wnba_players_shape_1",
            provider_index=0,
            canonical_index=0,
            headers=("id", "last_name", "first_name", "full_name", "is_active"),
            frame=pl.DataFrame(
                {
                    "id": [203025],
                    "last_name": ["Abdi"],
                    "first_name": ["Farhiya"],
                    "full_name": ["Farhiya Abdi"],
                    "is_active": [False],
                }
            ),
        )
        with patch(
            "nbadb.extract.static.players.fetch_static_packet", return_value=packet
        ) as fetch:
            df = await StaticWnbaPlayersExtractor().extract()

        assert df.columns == [
            "id",
            "last_name",
            "first_name",
            "full_name",
            "is_active",
            "league",
        ]
        assert df.row(0, named=True) == {
            "id": 203025,
            "last_name": "Abdi",
            "first_name": "Farhiya",
            "full_name": "Farhiya Abdi",
            "is_active": False,
            "league": "WNBA",
        }
        fetch.assert_called_once_with("static_wnba_players", capture=None)

    def test_class_attributes(self) -> None:
        assert StaticWnbaPlayersExtractor.endpoint_name == "static_wnba_players"
        assert StaticWnbaPlayersExtractor.category == "static"


class TestStaticWnbaTeamsExtractor:
    @pytest.mark.asyncio
    async def test_extract_preserves_raw_field_order_and_compact_championships(self) -> None:
        packet = NbaApiResultPacket(
            name="wnba_teams_shape_1",
            provider_index=0,
            canonical_index=0,
            headers=(
                "id",
                "abbreviation",
                "nickname",
                "year_founded",
                "city",
                "full_name",
                "state",
                "championship_year",
            ),
            frame=pl.DataFrame(
                {
                    "id": [1611661328],
                    "abbreviation": ["SEA"],
                    "nickname": ["Storm"],
                    "year_founded": [2000],
                    "city": ["Seattle"],
                    "full_name": ["Seattle Storm"],
                    "state": ["Washington"],
                    "championship_year": [[2004, 2010, 2018, 2020]],
                }
            ),
        )
        with patch("nbadb.extract.static.teams.fetch_static_packet", return_value=packet) as fetch:
            df = await StaticWnbaTeamsExtractor().extract()

        assert df.columns == [
            "id",
            "abbreviation",
            "nickname",
            "year_founded",
            "city",
            "full_name",
            "state",
            "championship_years_json",
            "league",
        ]
        assert df["championship_years_json"].to_list() == ["[2004,2010,2018,2020]"]
        assert df["league"].to_list() == ["WNBA"]
        fetch.assert_called_once_with("static_wnba_teams", capture=None)

    def test_class_attributes(self) -> None:
        assert StaticWnbaTeamsExtractor.endpoint_name == "static_wnba_teams"
        assert StaticWnbaTeamsExtractor.category == "static"
