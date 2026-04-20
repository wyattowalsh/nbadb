from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger
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
    _EMPTY_RESULT_KEYS = {"AvailableVideo", "PlayByPlay", "resultSet", "resultSets"}

    @classmethod
    def _empty_result_sets(cls, game_id: str) -> list[pl.DataFrame]:
        logger.warning(
            "{} returned deprecated empty payload for {}; treating as empty result sets",
            cls.endpoint_name,
            game_id,
        )
        return [pl.DataFrame(), pl.DataFrame()]

    async def extract(self, **params: Any) -> pl.DataFrame:
        frames = await self.extract_all(**params)
        if not frames:
            return pl.DataFrame()
        return frames[0]

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        try:
            return self._from_nba_api_multi(PlayByPlayV2, game_id=game_id)
        except KeyError as exc:
            missing_key = exc.args[0] if exc.args else None
            if missing_key not in self._EMPTY_RESULT_KEYS:
                raise
            return self._empty_result_sets(game_id)
