from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import AllTimeLeadersGrids

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class AllTimeLeadersGridsExtractor(BaseExtractor):
    endpoint_name = "all_time_leaders_grids"
    category = "leaders"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(AllTimeLeadersGrids, season_type=season_type)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(AllTimeLeadersGrids, season_type=season_type)
