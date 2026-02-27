from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import polars as pl
from nba_api.stats.endpoints import BoxScoreSummaryV2

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@registry.register
class BoxScoreSummaryExtractor(BaseExtractor):
    endpoint_name = "box_score_summary"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        logger.debug(f"Extracting box score summary for {game_id}")
        return self._from_nba_api(BoxScoreSummaryV2, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        """Return all result sets: GameSummary, OtherStats, Officials, etc."""
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScoreSummaryV2, game_id=game_id)
