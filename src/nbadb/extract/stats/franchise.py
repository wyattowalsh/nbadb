from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    FranchiseLeaders,
    FranchisePlayers,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class FranchiseLeadersExtractor(BaseExtractor):
    endpoint_name = "franchise_leaders"
    category = "franchise"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        return self._from_nba_api(FranchiseLeaders, team_id=team_id)


@registry.register
class FranchisePlayersExtractor(BaseExtractor):
    endpoint_name = "franchise_players"
    category = "franchise"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        return self._from_nba_api(FranchisePlayers, team_id=team_id)
