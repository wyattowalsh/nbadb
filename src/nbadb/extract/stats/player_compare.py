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
        def _normalize_id_list(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, (list, tuple, set)):
                return ",".join(str(v) for v in value)
            return str(value)

        player_id_list = _normalize_id_list(params.get("player_id_list"))
        if not player_id_list:
            player_id_list = _normalize_id_list(params.get("player_id"))

        vs_player_id_list = _normalize_id_list(params.get("vs_player_id_list"))
        if not vs_player_id_list:
            vs_player_id_list = _normalize_id_list(params.get("vs_player_id"))
        if not vs_player_id_list:
            vs_player_id_list = player_id_list

        if not player_id_list or not vs_player_id_list:
            import polars as pl

            return pl.DataFrame()

        season = params.get("season")
        season_type: str = params.get("season_type", "Regular Season")
        request_kwargs: dict[str, Any] = {
            "player_id_list": player_id_list,
            "vs_player_id_list": vs_player_id_list,
            "season_type_playoffs": season_type,
        }
        if season:
            request_kwargs["season"] = season
        return self._from_nba_api(PlayerCompare, **request_kwargs)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        def _normalize_id_list(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, (list, tuple, set)):
                return ",".join(str(v) for v in value)
            return str(value)

        player_id_list = _normalize_id_list(params.get("player_id_list"))
        if not player_id_list:
            player_id_list = _normalize_id_list(params.get("player_id"))

        vs_player_id_list = _normalize_id_list(params.get("vs_player_id_list"))
        if not vs_player_id_list:
            vs_player_id_list = _normalize_id_list(params.get("vs_player_id"))
        if not vs_player_id_list:
            vs_player_id_list = player_id_list

        if not player_id_list or not vs_player_id_list:
            return []

        season = params.get("season")
        season_type: str = params.get("season_type", "Regular Season")
        request_kwargs: dict[str, Any] = {
            "player_id_list": player_id_list,
            "vs_player_id_list": vs_player_id_list,
            "season_type_playoffs": season_type,
        }
        if season:
            request_kwargs["season"] = season
        return self._from_nba_api_multi(PlayerCompare, **request_kwargs)


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
            season_type_playoffs=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        vs_player_id: int = params["vs_player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            PlayerVsPlayer,
            player_id=player_id,
            vs_player_id=vs_player_id,
            season=season,
            season_type_playoffs=season_type,
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
            season_type_playoffs=season_type,
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        team_id: int = params["team_id"]
        vs_player_id: int = params["vs_player_id"]
        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api_multi(
            TeamVsPlayer,
            team_id=team_id,
            vs_player_id=vs_player_id,
            season=season,
            season_type_playoffs=season_type,
        )


@registry.register
class TeamAndPlayersVsPlayersExtractor(BaseExtractor):
    endpoint_name = "team_and_players_vs_players"
    category = "player_info"

    @staticmethod
    def _request_kwargs(params: dict[str, Any]) -> dict[str, Any]:
        """Build the complete upstream five-v-five request.

        ``TeamAndPlayersVsPlayers`` has no two-player request shape. Requiring
        both exact five-player lineups here keeps this extractor alias aligned
        with the provider class and prevents a superficially successful plan
        from failing only when the live constructor is reached.
        """

        team_id = int(params["team_id"])
        vs_team_id = int(params["vs_team_id"])
        player_ids = tuple(int(params[f"player_id{index}"]) for index in range(1, 6))
        vs_player_ids = tuple(int(params[f"vs_player_id{index}"]) for index in range(1, 6))
        if team_id <= 0 or vs_team_id <= 0 or team_id == vs_team_id:
            raise ValueError("five-v-five requests require two distinct positive team IDs")
        if (
            any(player_id <= 0 for player_id in (*player_ids, *vs_player_ids))
            or len(set(player_ids)) != 5
            or len(set(vs_player_ids)) != 5
            or set(player_ids) & set(vs_player_ids)
        ):
            raise ValueError(
                "five-v-five requests require two disjoint lineups of five positive player IDs"
            )
        return {
            "team_id": team_id,
            "vs_team_id": vs_team_id,
            **{
                f"player_id{index}": player_id
                for index, player_id in enumerate(player_ids, start=1)
            },
            **{
                f"vs_player_id{index}": player_id
                for index, player_id in enumerate(vs_player_ids, start=1)
            },
            "season": str(params["season"]),
            "season_type_playoffs": str(params.get("season_type", "Regular Season")),
        }

    async def extract(self, **params: Any) -> pl.DataFrame:
        return self._from_nba_api(
            TeamAndPlayersVsPlayers,
            **self._request_kwargs(params),
        )

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(
            TeamAndPlayersVsPlayers,
            **self._request_kwargs(params),
        )
