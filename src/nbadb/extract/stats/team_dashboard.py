from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    TeamDashboardByGeneralSplits,
    TeamDashboardByShootingSplits,
    TeamEstimatedMetrics,
    TeamPlayerDashboard,
    TeamPlayerOnOffDetails,
    TeamPlayerOnOffSummary,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class TeamDashboardByShootingSplitsExtractor(BaseExtractor):
    endpoint_name = "team_dashboard_shooting_splits"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamDashboardByShootingSplits,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class TeamDashboardByGeneralSplitsExtractor(BaseExtractor):
    endpoint_name = "team_dashboard_general_splits"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamDashboardByGeneralSplits,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class TeamPlayerOnOffDetailsExtractor(BaseExtractor):
    endpoint_name = "team_player_on_off_details"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamPlayerOnOffDetails,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class TeamPlayerOnOffSummaryExtractor(BaseExtractor):
    endpoint_name = "team_player_on_off_summary"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamPlayerOnOffSummary,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class TeamPlayerDashboardExtractor(BaseExtractor):
    endpoint_name = "team_player_dashboard"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamPlayerDashboard,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class TeamEstimatedMetricsExtractor(BaseExtractor):
    endpoint_name = "team_estimated_metrics"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamEstimatedMetrics,
            season=season,
            season_type=season_type,
        )
