from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import SynergyPlayTypes

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class SynergyPlayTypesExtractor(BaseExtractor):
    endpoint_name = "synergy_play_types"
    category = "synergy"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        play_type: str = params.get("play_type", "Isolation")
        player_or_team: str = params.get("player_or_team", "P")
        season_type: str = params.get("season_type", "Regular Season")
        type_grouping: str = params.get("type_grouping", "offensive")
        logger.debug(
            f"Extracting synergy {play_type} for {season}"
        )
        return self._from_nba_api(
            SynergyPlayTypes,
            season=season,
            play_type_nullable=play_type,
            player_or_team_abbreviation=player_or_team,
            season_type_all_star=season_type,
            type_grouping_nullable=type_grouping,
        )
