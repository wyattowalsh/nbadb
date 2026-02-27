from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger
from nba_api.stats.endpoints import (
    CommonTeamRoster,
    CommonTeamYears,
    FranchiseHistory,
    TeamDetails,
    TeamGameLogs,
    TeamInfoCommon,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@registry.register
class CommonTeamRosterExtractor(BaseExtractor):
    endpoint_name = "common_team_roster"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        logger.debug(f"Extracting team roster for {team_id} ({season})")
        return self._from_nba_api(
            CommonTeamRoster, team_id=team_id, season=season
        )

    async def extract_coaches(self, **params: Any) -> pl.DataFrame:
        """Return the Coaches result set."""
        team_id: int = params["team_id"]
        season: str = params["season"]
        dfs = self._from_nba_api_multi(
            CommonTeamRoster, team_id=team_id, season=season
        )
        if len(dfs) > 1:
            return dfs[1]
        return pl.DataFrame()


@registry.register
class FranchiseHistoryExtractor(BaseExtractor):
    endpoint_name = "franchise_history"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        logger.debug("Extracting franchise history")
        return self._from_nba_api(FranchiseHistory)


@registry.register
class TeamDetailsExtractor(BaseExtractor):
    endpoint_name = "team_details"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        return self._from_nba_api(TeamDetails, team_id=team_id)


@registry.register
class TeamInfoCommonExtractor(BaseExtractor):
    endpoint_name = "team_info_common"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamInfoCommon,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class CommonTeamYearsExtractor(BaseExtractor):
    endpoint_name = "common_team_years"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(CommonTeamYears)


@registry.register
class TeamGameLogsExtractor(BaseExtractor):
    endpoint_name = "team_game_logs"
    category = "game_log"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamGameLogs,
            season_nullable=season,
            season_type_nullable=season_type,
        )
