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
        api_params = dict(params)
        college: str = api_params.pop("college", "")

        if "season" in api_params:
            api_params.setdefault("season_nullable", api_params.pop("season"))
        if "season_type" in api_params:
            api_params.setdefault("season_type_all_star", api_params.pop("season_type"))

        return self._from_nba_api(
            PlayerCareerByCollege,
            college=college,
            **api_params,
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
