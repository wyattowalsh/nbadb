from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    LeagueDashPlayerBioStats,
    LeagueDashPlayerClutch,
    LeagueDashPlayerStats,
    LeagueDashTeamClutch,
    LeagueDashTeamStats,
    LeagueLineupViz,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class LeagueDashPlayerStatsExtractor(BaseExtractor):
    endpoint_name = "league_dash_player_stats"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashPlayerStats,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashTeamStatsExtractor(BaseExtractor):
    endpoint_name = "league_dash_team_stats"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashTeamStats,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashPlayerClutchExtractor(BaseExtractor):
    endpoint_name = "league_dash_player_clutch"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashPlayerClutch,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashTeamClutchExtractor(BaseExtractor):
    endpoint_name = "league_dash_team_clutch"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashTeamClutch,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashPlayerBioStatsExtractor(BaseExtractor):
    endpoint_name = "league_dash_player_bio_stats"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashPlayerBioStats,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashPlayerBioExtractor(BaseExtractor):
    endpoint_name = "league_dash_player_bio"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashPlayerBioStats,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueLineupVizExtractor(BaseExtractor):
    endpoint_name = "league_lineup_viz"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        minutes_min: int = params.get("minutes_min", 10)
        return self._from_nba_api(
            LeagueLineupViz,
            season=season,
            season_type_all_star=season_type,
            minutes_min=minutes_min,
        )
