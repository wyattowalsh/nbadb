from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nba_api.stats.endpoints import (
    PlayerCompare,
    PlayerVsPlayer,
    TeamAndPlayersVsPlayers,
    TeamVsPlayer,
)

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    import polars as pl


@registry.register
class PlayerCompareExtractor(BaseExtractor):
    endpoint_name = "player_compare"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id_list: str = params["player_id_list"]
        vs_player_id_list: str = params["vs_player_id_list"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerCompare,
            player_id_list=player_id_list,
            vs_player_id_list=vs_player_id_list,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class PlayerVsPlayerExtractor(BaseExtractor):
    endpoint_name = "player_vs_player"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        vs_player_id: int = params["vs_player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerVsPlayer,
            player_id=player_id,
            vs_player_id=vs_player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class TeamVsPlayerExtractor(BaseExtractor):
    endpoint_name = "team_vs_player"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        vs_player_id: int = params["vs_player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamVsPlayer,
            team_id=team_id,
            vs_player_id=vs_player_id,
            season=season,
            season_type_all_star=season_type,
        )


@registry.register
class TeamAndPlayersVsPlayersExtractor(BaseExtractor):
    endpoint_name = "team_and_players_vs_players"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        team_id: int = params["team_id"]
        player_id1: int = params["player_id1"]
        player_id2: int = params["player_id2"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            TeamAndPlayersVsPlayers,
            team_id=team_id,
            player_id1=player_id1,
            player_id2=player_id2,
            season=season,
            season_type_all_star=season_type,
        )
