from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import PlayerGameLogs, PlayerGameStreakFinder

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class PlayerGameLogsExtractor(BaseExtractor):
    endpoint_name = "player_game_logs"
    category = "game_log"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerGameLogs,
            season_nullable=season,
            season_type_nullable=season_type,
        )


@registry.register
class PlayerGameStreakFinderExtractor(BaseExtractor):
    endpoint_name = "player_game_streak_finder"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(PlayerGameStreakFinder, **params)
