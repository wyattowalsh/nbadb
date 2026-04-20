from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    PlayerCareerByCollege,
    PlayerCareerByCollegeRollup,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class PlayerCareerByCollegeExtractor(BaseExtractor):
    endpoint_name = "player_career_by_college"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        college: str = params.get("college", "")
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerCareerByCollege,
            college=college,
            season_nullable=season,
            season_type_nullable=season_type,
        )


@registry.register
class PlayerCareerByCollegeRollupExtractor(BaseExtractor):
    endpoint_name = "player_career_by_college_rollup"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(PlayerCareerByCollegeRollup, **params)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(PlayerCareerByCollegeRollup, **params)


@registry.register
class PlayerCollegeRollupExtractor(BaseExtractor):
    """Alias with canonical short endpoint_name for staging map."""

    endpoint_name = "player_college_rollup"
    category = "player_info"
    param_pattern = "static"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerCareerByCollegeRollup,
            season_type_all_star=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            PlayerCareerByCollegeRollup,
            season_type_all_star=season_type,
        )
