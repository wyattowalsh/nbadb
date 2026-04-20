from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    HustleStatsBoxScore,
    LeagueHustleStatsPlayer,
    LeagueHustleStatsTeam,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class LeagueHustlePlayerExtractor(BaseExtractor):
    endpoint_name = "league_hustle_player"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueHustleStatsPlayer,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueHustleTeamExtractor(BaseExtractor):
    endpoint_name = "league_hustle_team"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueHustleStatsTeam,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class HustleStatsBoxScoreExtractor(BaseExtractor):
    endpoint_name = "hustle_stats_box_score"
    category = "hustle"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        return self._from_nba_api(HustleStatsBoxScore, game_id=game_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_id: str = params["game_id"]
        return self._from_nba_api_multi(HustleStatsBoxScore, game_id=game_id)
