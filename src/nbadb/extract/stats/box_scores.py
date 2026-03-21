from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import polars as pl
from nba_api.stats.endpoints import (
    BoxScoreAdvancedV3,
    BoxScoreDefensiveV2,
    BoxScoreFourFactorsV3,
    BoxScoreHustleV2,
    BoxScoreMiscV3,
    BoxScorePlayerTrackV3,
    BoxScoreScoringV3,
    BoxScoreTraditionalV3,
    BoxScoreUsageV3,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@registry.register
class BoxScoreTraditionalExtractor(BaseExtractor):
    endpoint_name = "box_score_traditional"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        logger.debug(f"Extracting traditional box score for {game_id}")
        return self._from_nba_api(BoxScoreTraditionalV3, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScoreTraditionalV3, game_id=game_id)


@registry.register
class BoxScoreAdvancedExtractor(BaseExtractor):
    endpoint_name = "box_score_advanced"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(BoxScoreAdvancedV3, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScoreAdvancedV3, game_id=game_id)


@registry.register
class BoxScoreMiscExtractor(BaseExtractor):
    endpoint_name = "box_score_misc"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(BoxScoreMiscV3, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScoreMiscV3, game_id=game_id)


@registry.register
class BoxScoreScoringExtractor(BaseExtractor):
    endpoint_name = "box_score_scoring"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(BoxScoreScoringV3, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScoreScoringV3, game_id=game_id)


@registry.register
class BoxScoreUsageExtractor(BaseExtractor):
    endpoint_name = "box_score_usage"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(BoxScoreUsageV3, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScoreUsageV3, game_id=game_id)


@registry.register
class BoxScoreFourFactorsExtractor(BaseExtractor):
    endpoint_name = "box_score_four_factors"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(BoxScoreFourFactorsV3, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScoreFourFactorsV3, game_id=game_id)


@registry.register
class BoxScoreHustleExtractor(BaseExtractor):
    endpoint_name = "box_score_hustle"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(BoxScoreHustleV2, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScoreHustleV2, game_id=game_id)


@registry.register
class BoxScorePlayerTrackExtractor(BaseExtractor):
    endpoint_name = "box_score_player_track"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(BoxScorePlayerTrackV3, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScorePlayerTrackV3, game_id=game_id)


@registry.register
class BoxScoreDefensiveExtractor(BaseExtractor):
    endpoint_name = "box_score_defensive"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(BoxScoreDefensiveV2, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(BoxScoreDefensiveV2, game_id=game_id)
