from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    LeagueDashPtDefend,
    LeagueDashPtTeamDefend,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class LeagueDashPtDefendExtractor(BaseExtractor):
    endpoint_name = "league_dash_pt_defend"
    category = "tracking"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        defense_category: str = params.get("defense_category", "Overall")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashPtDefend,
            season=season,
            defense_category=defense_category,
            season_type_all_star=season_type,
        )


@registry.register
class LeagueDashPtTeamDefendExtractor(BaseExtractor):
    endpoint_name = "league_dash_pt_team_defend"
    category = "tracking"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        defense_category: str = params.get("defense_category", "Overall")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueDashPtTeamDefend,
            season=season,
            defense_category=defense_category,
            season_type_all_star=season_type,
        )
