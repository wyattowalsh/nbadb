from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    AssistLeaders,
    AssistTracker,
    DefenseHub,
    HomePageLeaders,
    HomePageV2,
    LeadersTiles,
    LeagueLeaders,
    TeamHistoricalLeaders,
    TeamYearByYearStats,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class AssistLeadersExtractor(BaseExtractor):
    endpoint_name = "assist_leaders"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            AssistLeaders,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class AssistTrackerExtractor(BaseExtractor):
    endpoint_name = "assist_tracker"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            AssistTracker,
            season_nullable=season,
            season_type_all_star_nullable=season_type,
        )


@registry.register
class HomePageLeadersExtractor(BaseExtractor):
    endpoint_name = "home_page_leaders"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            HomePageLeaders,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class HomePageV2Extractor(BaseExtractor):
    endpoint_name = "home_page_v2"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            HomePageV2,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class LeadersTilesExtractor(BaseExtractor):
    endpoint_name = "leaders_tiles"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeadersTiles,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class LeagueLeadersExtractor(BaseExtractor):
    endpoint_name = "league_leaders"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        stat_category: str = params.get("stat_category", "PTS")
        return self._from_nba_api(
            LeagueLeaders,
            season=season,
            season_type_all_star=season_type,
            stat_category_abbreviation=stat_category,
        )


@registry.register
class HomePageLeadersAltExtractor(BaseExtractor):
    endpoint_name = "homepage_leaders"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            HomePageLeaders,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class HomePageV2AltExtractor(BaseExtractor):
    endpoint_name = "homepage_v2"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            HomePageV2,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class DefenseHubExtractor(BaseExtractor):
    endpoint_name = "defense_hub"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            DefenseHub,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class TeamHistoricalLeadersExtractor(BaseExtractor):
    endpoint_name = "team_historical_leaders"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        return self._from_nba_api(TeamHistoricalLeaders, team_id=team_id)


@registry.register
class TeamYearByYearStatsExtractor(BaseExtractor):
    endpoint_name = "team_year_by_year_stats"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamYearByYearStats,
            team_id=team_id,
            season_type_all_star=season_type,
        )
