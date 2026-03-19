from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import (
    ShotChartDetail,
    ShotChartLeagueWide,
    ShotChartLineupDetail,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry
from nbadb.orchestrate.seasons import current_season

if TYPE_CHECKING:
    import polars as pl


@registry.register
class ShotChartDetailExtractor(BaseExtractor):
    endpoint_name = "shot_chart_detail"
    category = "shots"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params.get("player_id", 0)
        team_id: int = params.get("team_id", 0)
        game_id: str = params.get("game_id", "")
        season: str = params.get("season", "")
        season_type: str = params.get("season_type", "Regular Season")
        context_measure: str = params.get("context_measure", "FGA")
        logger.debug(f"Extracting shot chart: player={player_id}, game={game_id}")
        return self._from_nba_api(
            ShotChartDetail,
            player_id=player_id,
            team_id=team_id,
            game_id_nullable=game_id,
            season_nullable=season,
            season_type_all_star=season_type,
            context_measure_simple=context_measure,
        )


@registry.register
class ShotChartLineupDetailExtractor(BaseExtractor):
    endpoint_name = "shot_chart_lineup_detail"
    category = "shots"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            ShotChartLineupDetail,
            season=season,
            season_type_all_star=season_type,
            **{k: v for k, v in params.items() if k not in ("season", "season_type")},
        )


@registry.register
class ShotChartLeagueWideExtractor(BaseExtractor):
    endpoint_name = "shot_chart_league_wide"
    category = "shots"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        return self._from_nba_api(ShotChartLeagueWide, season=season)


@registry.register
class ShotChartLineupExtractor(BaseExtractor):
    """ShotChartLineupDetail alias with canonical short endpoint_name for staging map."""

    endpoint_name = "shot_chart_lineup"
    category = "shots"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        group_id: str = params.get("group_id", "")
        context_measure: str = params.get("context_measure", "FGA")
        return self._from_nba_api(
            ShotChartLineupDetail,
            season=season,
            season_type_all_star=season_type,
            group_id=group_id,
            context_measure_detailed=context_measure,
        )
