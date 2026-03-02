from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import polars as pl
from nba_api.stats.endpoints import (
    DraftBoard,
    DraftCombineDrillResults,
    DraftCombineNonStationaryShooting,
    DraftCombinePlayerAnthro,
    DraftCombineSpotShooting,
    DraftCombineStats,
    DraftHistory,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@registry.register
class DraftHistoryExtractor(BaseExtractor):
    endpoint_name = "draft_history"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str | None = params.get("season")
        logger.debug(f"Extracting draft history (season={season})")
        kwargs: dict[str, Any] = {}
        if season is not None:
            kwargs["season_year_nullable"] = season
        return self._from_nba_api(DraftHistory, **kwargs)


@registry.register
class DraftCombineStatsExtractor(BaseExtractor):
    endpoint_name = "draft_combine_stats"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        logger.debug(f"Extracting draft combine stats for {season}")
        return self._from_nba_api(DraftCombineStats, season_all_time=season)


@registry.register
class DraftBoardExtractor(BaseExtractor):
    endpoint_name = "draft_board"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        return self._from_nba_api(DraftBoard, season=season)


@registry.register
class DraftCombineDrillResultsExtractor(BaseExtractor):
    endpoint_name = "draft_combine_drill_results"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(
            DraftCombineDrillResults,
            season_year=int(str(params["season"])[:4]),
        )


@registry.register
class DraftCombineNonStationaryShootingExtractor(BaseExtractor):
    endpoint_name = "draft_combine_non_stationary_shooting"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(
            DraftCombineNonStationaryShooting,
            season_year=int(str(params["season"])[:4]),
        )


@registry.register
class DraftCombinePlayerAnthroExtractor(BaseExtractor):
    endpoint_name = "draft_combine_player_anthro"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(
            DraftCombinePlayerAnthro,
            season_year=int(str(params["season"])[:4]),
        )


@registry.register
class DraftCombineSpotShootingExtractor(BaseExtractor):
    endpoint_name = "draft_combine_spot_shooting"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(
            DraftCombineSpotShooting,
            season_year=int(str(params["season"])[:4]),
        )
