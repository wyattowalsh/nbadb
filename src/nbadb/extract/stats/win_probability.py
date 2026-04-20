from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import WinProbabilityPBP

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class WinProbabilityExtractor(BaseExtractor):
    endpoint_name = "win_probability"
    category = "play_by_play"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        logger.debug(f"Extracting win probability for {game_id}")
        return self._from_nba_api(WinProbabilityPBP, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(WinProbabilityPBP, game_id=game_id)
