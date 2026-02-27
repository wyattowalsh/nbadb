from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    PlayerDashboardByClutch,
    PlayerDashboardByGameSplits,
    PlayerDashboardByGeneralSplits,
    PlayerDashboardByLastNGames,
    PlayerDashboardByShootingSplits,
    PlayerDashboardByTeamPerformance,
    PlayerDashboardByYearOverYear,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class PlayerDashboardByYearOverYearExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_year_over_year"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashboardByYearOverYear,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashboardByLastNGamesExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_last_n_games"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashboardByLastNGames,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashboardByGameSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_game_splits"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashboardByGameSplits,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashboardByClutchExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_clutch"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashboardByClutch,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashboardByShootingSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_shooting_splits"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashboardByShootingSplits,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashboardByTeamPerformanceExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_team_performance"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashboardByTeamPerformance,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashboardGeneralSplitsExtractor(BaseExtractor):
    endpoint_name = "player_dashboard_general_splits"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashboardByGeneralSplits,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )
