from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    PlayerDashPtPass,
    PlayerDashPtReb,
    PlayerDashPtShotDefend,
    PlayerDashPtShots,
    PlayerEstimatedMetrics,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class PlayerDashPtShotsExtractor(BaseExtractor):
    endpoint_name = "player_dash_pt_shots"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashPtShots,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            PlayerDashPtShots,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashPtPassExtractor(BaseExtractor):
    endpoint_name = "player_dash_pt_pass"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashPtPass,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            PlayerDashPtPass,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashPtRebExtractor(BaseExtractor):
    endpoint_name = "player_dash_pt_reb"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashPtReb,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            PlayerDashPtReb,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashPtDefendExtractor(BaseExtractor):
    endpoint_name = "player_dash_pt_defend"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashPtShotDefend,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerDashPtShotDefendExtractor(BaseExtractor):
    """Aliased extractor with canonical endpoint_name for staging map."""

    endpoint_name = "player_dash_pt_shot_defend"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerDashPtShotDefend,
            player_id=player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerEstimatedMetricsExtractor(BaseExtractor):
    endpoint_name = "player_estimated_metrics"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerEstimatedMetrics,
            season=season,
            season_type=season_type,
        )
