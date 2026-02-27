from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import ScheduleLeagueV2

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
        return self._from_nba_api(
            ScheduleLeagueV2, season=season, league_id=league_id
        )
