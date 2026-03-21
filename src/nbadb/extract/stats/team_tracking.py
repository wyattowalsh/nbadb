from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    TeamDashPtPass,
    TeamDashPtReb,
    TeamDashPtShots,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class TeamDashPtShotsExtractor(BaseExtractor):
    endpoint_name = "team_dash_pt_shots"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamDashPtShots,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            TeamDashPtShots,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class TeamDashPtPassExtractor(BaseExtractor):
    endpoint_name = "team_dash_pt_pass"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamDashPtPass,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            TeamDashPtPass,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class TeamDashPtRebExtractor(BaseExtractor):
    endpoint_name = "team_dash_pt_reb"
    category = "team_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamDashPtReb,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            TeamDashPtReb,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
        )
