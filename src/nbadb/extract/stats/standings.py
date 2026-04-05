from __future__ import annotations

import json
from typing import Any

import polars as pl
from loguru import logger
from nba_api.stats.endpoints import (
    CommonPlayoffSeries,
    ISTStandings,
    LeagueStandingsV3,
    PlayoffPicture,
)
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@registry.register
class LeagueStandingsExtractor(BaseExtractor):
    endpoint_name = "league_standings"
    category = "standings"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        logger.debug(f"Extracting standings for {season} ({season_type})")
        return self._from_nba_api(LeagueStandingsV3, season=season, season_type=season_type)


@registry.register
class PlayoffPictureExtractor(BaseExtractor):
    endpoint_name = "playoff_picture"
    category = "standings"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_id = f"2{season[:4]}"
        logger.debug(f"Extracting playoff picture for {season_id}")
        return self._from_nba_api(PlayoffPicture, season_id=season_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        """Return all result sets: East/West conf playoff pictures."""
        season: str = params["season"]
        season_id = f"2{season[:4]}"
        return self._from_nba_api_multi(PlayoffPicture, season_id=season_id)


@registry.register
class CommonPlayoffSeriesExtractor(BaseExtractor):
    endpoint_name = "common_playoff_series"
    category = "standings"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        return self._from_nba_api(CommonPlayoffSeries, season=season)


@registry.register
class ISTStandingsExtractor(BaseExtractor):
    endpoint_name = "ist_standings"
    category = "standings"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        try:
            return self._from_nba_api(ISTStandings, season=season)
        except json.JSONDecodeError:
            if season != "2021-22":
                raise

        request_kwargs = {"season": season}
        self._inject_timeout(request_kwargs)
        endpoint = ISTStandings(get_request=False, **request_kwargs)
        response = NBAStatsHTTP().send_api_request(
            endpoint=endpoint.endpoint,
            parameters=endpoint.parameters,
            proxy=endpoint.proxy,
            headers=endpoint.headers,
            timeout=endpoint.timeout,
        )
        raw_response = response.get_response()
        text = (
            raw_response
            if isinstance(raw_response, str)
            else getattr(raw_response, "text", str(raw_response))
        )
        normalized = text.strip()
        if normalized and (
            "(403) Forbidden" not in normalized or "System.Net.WebException" not in normalized
        ):
            raise json.JSONDecodeError("Expecting value", text, 0)

        logger.info("ist_standings unavailable for {}; returning empty frame", season)
        return pl.DataFrame()
