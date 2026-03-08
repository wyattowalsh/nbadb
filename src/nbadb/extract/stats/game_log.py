from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import polars as pl
from nba_api.stats.endpoints import (
    LeagueGameLog,
    PlayerGameLog,
    ScoreboardV2,
    ScoreboardV3,
    TeamGameLog,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry


@registry.register
class LeagueGameLogExtractor(BaseExtractor):
    endpoint_name = "league_game_log"
    category = "game_log"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        logger.debug(f"Extracting league game log for {season} ({season_type})")
        return self._from_nba_api(LeagueGameLog, season=season, season_type_all_star=season_type)


@registry.register
class PlayerGameLogExtractor(BaseExtractor):
    endpoint_name = "player_game_log"
    category = "game_log"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id = params.get("player_id")
        if player_id is None:
            import polars as pl

            return pl.DataFrame()
        season = params.get("season")
        season_type: str = params.get("season_type", "Regular Season")
        request_kwargs: dict[str, Any] = {
            "player_id": int(player_id),
            "season_type_all_star": season_type,
        }
        if season:
            request_kwargs["season"] = season
        return self._from_nba_api(PlayerGameLog, **request_kwargs)


@registry.register
class TeamGameLogExtractor(BaseExtractor):
    endpoint_name = "team_game_log"
    category = "game_log"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id = params.get("team_id")
        if team_id is None:
            import polars as pl

            return pl.DataFrame()
        season = params.get("season")
        season_type: str = params.get("season_type", "Regular Season")
        request_kwargs: dict[str, Any] = {
            "team_id": int(team_id),
            "season_type_all_star": season_type,
        }
        if season:
            request_kwargs["season"] = season
        return self._from_nba_api(TeamGameLog, **request_kwargs)


@registry.register
class ScoreboardV2Extractor(BaseExtractor):
    endpoint_name = "scoreboard_v2"
    category = "game_log"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_date: str = params["game_date"]
        return self._from_nba_api(ScoreboardV2, game_date=game_date)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        """Return all result sets for ScoreboardV2."""
        game_date: str = params["game_date"]
        return self._from_nba_api_multi(ScoreboardV2, game_date=game_date)


@registry.register
class ScoreboardV3Extractor(BaseExtractor):
    endpoint_name = "scoreboard_v3"
    category = "game_log"

    async def extract(self, **params: Any) -> pl.DataFrame:
        game_date: str = params["game_date"]
        return self._from_nba_api(ScoreboardV3, game_date=game_date)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        game_date: str = params["game_date"]
        return self._from_nba_api_multi(ScoreboardV3, game_date=game_date)
