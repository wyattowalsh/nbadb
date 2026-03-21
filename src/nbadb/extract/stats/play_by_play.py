from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import polars as pl
from nba_api.stats.endpoints import PlayByPlayV2, PlayByPlayV3

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@registry.register
class PlayByPlayExtractor(BaseExtractor):
    endpoint_name = "play_by_play"
    category = "play_by_play"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        logger.debug(f"Extracting play-by-play for {game_id}")
        return self._from_nba_api(PlayByPlayV3, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(PlayByPlayV3, game_id=game_id)


@registry.register
class PlayByPlayV2Extractor(BaseExtractor):
    endpoint_name = "play_by_play_v2"
    category = "play_by_play"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(PlayByPlayV2, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(PlayByPlayV2, game_id=game_id)
