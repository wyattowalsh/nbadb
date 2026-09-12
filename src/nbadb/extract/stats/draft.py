from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger
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


def _first_result_with_season(
    extractor: BaseExtractor,
    endpoint_cls: type,
    *,
    season: str,
    season_year: int,
) -> pl.DataFrame:
    converted = extractor._call_nba_api(endpoint_cls, season_year=season_year)
    if not converted:
        logger.warning(f"{extractor.endpoint_name}: no data frames returned")
        return pl.DataFrame()

    df = converted[0]
    if "season" not in df.columns:
        df = df.with_columns(pl.lit(season).alias("season"))
    return extractor._validate(df)


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
        season_type: str = params.get("season_type", "Regular Season")
        season_year = int(season[:4])
        df = self._from_nba_api(DraftBoard, season_year=season_year)
        if "season" not in df.columns:
            df = df.with_columns(pl.lit(season).alias("season"))
        if "season_type" not in df.columns:
            df = df.with_columns(pl.lit(season_type).alias("season_type"))
        return df


@registry.register
class DraftCombineDrillResultsExtractor(BaseExtractor):
    endpoint_name = "draft_combine_drill_results"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season = str(params["season"])
        return _first_result_with_season(
            self,
            DraftCombineDrillResults,
            season=season,
            season_year=int(season[:4]),
        )


@registry.register
class DraftCombineNonStationaryShootingExtractor(BaseExtractor):
    endpoint_name = "draft_combine_non_stationary_shooting"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season = str(params["season"])
        return _first_result_with_season(
            self,
            DraftCombineNonStationaryShooting,
            season=season,
            season_year=int(season[:4]),
        )


@registry.register
class DraftCombinePlayerAnthroExtractor(BaseExtractor):
    endpoint_name = "draft_combine_player_anthro"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season = str(params["season"])
        return _first_result_with_season(
            self,
            DraftCombinePlayerAnthro,
            season=season,
            season_year=int(season[:4]),
        )


@registry.register
class DraftCombineSpotShootingExtractor(BaseExtractor):
    endpoint_name = "draft_combine_spot_shooting"
    category = "draft"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season = str(params["season"])
        return _first_result_with_season(
            self,
            DraftCombineSpotShooting,
            season=season,
            season_year=int(season[:4]),
        )
