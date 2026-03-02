from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import polars as pl
from nba_api.stats.endpoints import (
    CommonAllPlayers,
    CommonPlayerInfo,
    PlayerAwards,
    PlayerCareerStats,
    PlayerIndex,
    PlayerNextNGames,
    PlayerProfileV2,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@registry.register
class CommonPlayerInfoExtractor(BaseExtractor):
    endpoint_name = "common_player_info"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        logger.debug(f"Extracting common player info for {player_id}")
        return self._from_nba_api(CommonPlayerInfo, player_id=player_id)


@registry.register
class PlayerCareerStatsExtractor(BaseExtractor):
    endpoint_name = "player_career_stats"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        return self._from_nba_api(PlayerCareerStats, player_id=player_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        """Return all result sets: regular, post, allstar, etc."""
        player_id: int = params["player_id"]
        return self._from_nba_api_multi(PlayerCareerStats, player_id=player_id)


@registry.register
class PlayerAwardsExtractor(BaseExtractor):
    endpoint_name = "player_awards"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        return self._from_nba_api(PlayerAwards, player_id=player_id)


@registry.register
class PlayerIndexExtractor(BaseExtractor):
    endpoint_name = "player_index"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params.get("season", "")
        return self._from_nba_api(PlayerIndex, season=season)


@registry.register
class CommonAllPlayersExtractor(BaseExtractor):
    endpoint_name = "common_all_players"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params.get("season", "")
        is_only_current: int = params.get("is_only_current_season", 0)
        return self._from_nba_api(
            CommonAllPlayers,
            season=season,
            is_only_current_season=is_only_current,
        )


@registry.register
class PlayerProfileV2Extractor(BaseExtractor):
    endpoint_name = "player_profile_v2"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        return self._from_nba_api(PlayerProfileV2, player_id=player_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        return self._from_nba_api_multi(PlayerProfileV2, player_id=player_id)


@registry.register
class PlayerNextNGamesExtractor(BaseExtractor):
    endpoint_name = "player_next_games"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        number_of_games: int = params.get("number_of_games", 5)
        season: str = params.get("season", "2024-25")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerNextNGames,
            player_id=player_id,
            number_of_games=number_of_games,
            season_all=season,
            season_type_all_star=season_type,
        )
