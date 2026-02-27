from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    LeagueDashOppPtShot,
    LeagueDashPlayerPtShot,
    LeagueDashPlayerShotLocations,
    LeagueDashPtStats,
    LeagueDashTeamPtShot,
    LeagueDashTeamShotLocations,
    LeaguePlayerOnDetails,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class LeagueDashPlayerShotLocationsExtractor(BaseExtractor):
    endpoint_name = "league_dash_player_shot_locations"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashPlayerShotLocations,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashTeamShotLocationsExtractor(BaseExtractor):
    endpoint_name = "league_dash_team_shot_locations"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashTeamShotLocations,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashPlayerPtShotExtractor(BaseExtractor):
    endpoint_name = "league_dash_player_pt_shot"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashPlayerPtShot,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashTeamPtShotExtractor(BaseExtractor):
    endpoint_name = "league_dash_team_pt_shot"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashTeamPtShot,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashOppPtShotExtractor(BaseExtractor):
    endpoint_name = "league_dash_opp_pt_shot"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashOppPtShot,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashPtStatsExtractor(BaseExtractor):
    endpoint_name = "league_dash_pt_stats"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        player_or_team: str = params.get("player_or_team", "Player")
        return self._from_nba_api(
            LeagueDashPtStats,
            season=season,
            season_type_all_star=season_type,
            player_or_team=player_or_team,
        )


@registry.register
class LeaguePlayerOnDetailsExtractor(BaseExtractor):
    endpoint_name = "league_player_on_details"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeaguePlayerOnDetails,
            season=season,
            season_type_all_star=season_type,
        )
