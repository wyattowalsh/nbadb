from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import (
    CommonPlayoffSeries,
    ISTStandings,
    LeagueStandingsV3,
    PlayoffPicture,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


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
        season_id: str = params["season_id"]
        logger.debug(f"Extracting playoff picture for {season_id}")
        return self._from_nba_api(PlayoffPicture, season_id=season_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        """Return all result sets: East/West conf playoff pictures."""
        season_id: str = params["season_id"]
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
        return self._from_nba_api(ISTStandings, season=season)
