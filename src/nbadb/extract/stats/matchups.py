from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger
from nba_api.stats.endpoints import (
    BoxScoreMatchupsV3,
    LeagueDashLineups,
    LeagueSeasonMatchups,
    MatchupsRollup,
    TeamDashLineups,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class BoxScoreMatchupsExtractor(BaseExtractor):
    endpoint_name = "box_score_matchups"
    category = "box_score"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_id: str = params["game_id"]
        logger.debug(f"Extracting matchups for {game_id}")
        return self._from_nba_api(BoxScoreMatchupsV3, game_id=game_id)


@registry.register
class LeagueSeasonMatchupsExtractor(BaseExtractor):
    endpoint_name = "league_season_matchups"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            LeagueSeasonMatchups,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class MatchupsRollupExtractor(BaseExtractor):
    endpoint_name = "matchups_rollup"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            MatchupsRollup,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class LeagueDashLineupsExtractor(BaseExtractor):
    endpoint_name = "league_dash_lineups"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        group_quantity: int = params.get("group_quantity", 5)
        return self._from_nba_api(
            LeagueDashLineups,
            season=season,
            season_type_all_star=season_type,
            group_quantity=group_quantity,
        )


@registry.register
class TeamDashLineupsExtractor(BaseExtractor):
    endpoint_name = "team_dash_lineups"
    category = "league"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        group_quantity: int = params.get("group_quantity", 5)
        return self._from_nba_api(
            TeamDashLineups,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
            group_quantity=group_quantity,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        team_id: int = params["team_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        group_quantity: int = params.get("group_quantity", 5)
        return self._from_nba_api_multi(
            TeamDashLineups,
            team_id=team_id,
            season=season,
            season_type_all_star=season_type,
            group_quantity=group_quantity,
        )
