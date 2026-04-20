from __future__ import annotations

import json
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
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.extract.base import BaseExtractor, _safe_from_pandas, _to_snake_case
from nbadb.extract.registry import registry


def _response_text(response: Any) -> str:
    raw = response.get_response()
    if isinstance(raw, str):
        return raw
    return getattr(raw, "text", str(raw))


def _is_unavailable_response(text: str) -> bool:
    normalized = text.strip()
    return (
        not normalized
        or "(403) Forbidden" in normalized
        or "System.Net.WebException" in normalized
        or "Sap.Data.Hana.HanaException" in normalized
        or "Socket closed by peer" in normalized
    )


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
        request_kwargs: dict[str, Any] = {"season_year": season_year}
        self._inject_timeout(request_kwargs)
        endpoint = DraftBoard(get_request=False, **request_kwargs)
        response = NBAStatsHTTP().send_api_request(
            endpoint=endpoint.endpoint,
            parameters=endpoint.parameters,
            proxy=endpoint.proxy,
            headers=endpoint.headers,
            timeout=endpoint.timeout,
        )
        try:
            endpoint.nba_response = response
            endpoint.load_response()
        except json.JSONDecodeError:
            if _is_unavailable_response(_response_text(response)):
                logger.info(
                    "draft_board unavailable for {} ({}); returning empty frame",
                    season,
                    season_type,
                )
                return pl.DataFrame()
            raise

        df = _safe_from_pandas(endpoint.draft_board.get_data_frame())
        if df.columns:
            df = df.rename({c: _to_snake_case(c) for c in df.columns})
        return df


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
