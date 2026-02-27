from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import GameRotation

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class GameRotationExtractor(BaseExtractor):
    endpoint_name = "game_rotation"
    category = "rotation"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        logger.debug(f"Extracting rotation for {game_id}")
        return self._from_nba_api(GameRotation, game_id=game_id)

    async def extract_both(self, **params: Any) -> list[pl.DataFrame]:
        """Return HomeTeam and AwayTeam rotation result sets."""
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(GameRotation, game_id=game_id)
