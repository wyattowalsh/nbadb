from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import ScheduleLeagueV2
from nba_api.stats.endpoints.scheduleleaguev2int import ScheduleLeagueV2Int

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class ScheduleExtractor(BaseExtractor):
    endpoint_name = "schedule"
    category = "schedule"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        league_id: str = params.get("league_id", "00")
        logger.debug(f"Extracting schedule for {season}")
        return self._from_nba_api(ScheduleLeagueV2, season=season, league_id=league_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        season: str = params["season"]
        league_id: str = params.get("league_id", "00")
        return self._from_nba_api_multi(ScheduleLeagueV2, season=season, league_id=league_id)


@registry.register
class ScheduleIntExtractor(BaseExtractor):
    endpoint_name = "schedule_int"
    category = "schedule"

    async def extract(self, **params: Any) -> pl.DataFrame:
        # Single-result fallback (returns SeasonGames only).
        # All staging entries use use_multi=True, so the orchestrator calls extract_all().
        season: str = params["season"]
        league_id: str = params.get("league_id", "00")
        logger.debug(f"Extracting international schedule for {season}")
        return self._from_nba_api(ScheduleLeagueV2Int, season=season, league_id=league_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        season: str = params["season"]
        league_id: str = params.get("league_id", "00")
        return self._from_nba_api_multi(ScheduleLeagueV2Int, season=season, league_id=league_id)
