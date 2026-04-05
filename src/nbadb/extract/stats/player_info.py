from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    import polars as pl
from nba_api.stats.endpoints import (
    CommonAllPlayers,
    CommonPlayerInfo,
    PlayerAwards,
    PlayerCareerStats,
    PlayerIndex,
    PlayerNextNGames,
    PlayerProfileV2,
)
from nba_api.stats.static import players as static_players

from nbadb.extract.base import BaseExtractor
from nbadb.extract.registry import registry
from nbadb.orchestrate.seasons import current_season


@registry.register
class CommonPlayerInfoExtractor(BaseExtractor):
    endpoint_name = "common_player_info"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        logger.debug(f"Extracting common player info for {player_id}")
        return self._from_nba_api(CommonPlayerInfo, player_id=player_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        return self._from_nba_api_multi(CommonPlayerInfo, player_id=player_id)


@registry.register
class PlayerCareerStatsExtractor(BaseExtractor):
    endpoint_name = "player_career_stats"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        return self._from_nba_api(PlayerCareerStats, player_id=player_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        """Return all result sets: regular, post, allstar, etc."""
        player_id: int = params["player_id"]
        return self._from_nba_api_multi(PlayerCareerStats, player_id=player_id)


@registry.register
class PlayerAwardsExtractor(BaseExtractor):
    endpoint_name = "player_awards"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        return self._from_nba_api(PlayerAwards, player_id=player_id)


@registry.register
class PlayerIndexExtractor(BaseExtractor):
    endpoint_name = "player_index"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season = params.get("season") or None
        kwargs: dict[str, Any] = {}
        if season is not None:
            kwargs["season"] = season
        return self._from_nba_api(PlayerIndex, **kwargs)


@registry.register
class CommonAllPlayersExtractor(BaseExtractor):
    endpoint_name = "common_all_players"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season = params.get("season") or None
        is_only_current: int = params.get("is_only_current_season", 0)
        kwargs: dict[str, Any] = {"is_only_current_season": is_only_current}
        if season is not None:
            kwargs["season"] = season

        try:
            return self._from_nba_api(CommonAllPlayers, **kwargs)
        except json.JSONDecodeError:
            if season is not None:
                raise
            logger.warning(
                "common_all_players: falling back to nba_api static players after JSONDecodeError"
            )
            return self._fallback_from_static_players(is_only_current=is_only_current)

    @staticmethod
    def _fallback_from_static_players(*, is_only_current: int) -> pl.DataFrame:
        import polars as pl

        df = pl.from_records(static_players.get_players())
        if df.is_empty():
            return df

        if is_only_current:
            df = df.filter(pl.col("is_active"))

        return df.with_columns(
            pl.col("id").cast(pl.Int64, strict=False).alias("person_id"),
            pl.when(pl.col("last_name").is_not_null() & pl.col("first_name").is_not_null())
            .then(pl.format("{}, {}", pl.col("last_name"), pl.col("first_name")))
            .otherwise(pl.col("full_name"))
            .cast(pl.Utf8, strict=False)
            .alias("display_last_comma_first"),
            pl.col("full_name").cast(pl.Utf8, strict=False).alias("display_first_last"),
            pl.col("is_active").cast(pl.Int64, strict=False).alias("roster_status"),
            pl.lit(None, dtype=pl.Utf8).alias("from_year"),
            pl.lit(None, dtype=pl.Utf8).alias("to_year"),
            pl.lit(None, dtype=pl.Utf8).alias("playercode"),
            pl.lit(None, dtype=pl.Int64).alias("team_id"),
            pl.lit(None, dtype=pl.Utf8).alias("team_city"),
            pl.lit(None, dtype=pl.Utf8).alias("team_name"),
            pl.lit(None, dtype=pl.Utf8).alias("team_abbreviation"),
            pl.lit(None, dtype=pl.Utf8).alias("team_code"),
            pl.lit(None, dtype=pl.Utf8).alias("games_played_flag"),
        ).select(
            "person_id",
            "display_last_comma_first",
            "display_first_last",
            "roster_status",
            "from_year",
            "to_year",
            "playercode",
            "team_id",
            "team_city",
            "team_name",
            "team_abbreviation",
            "team_code",
            "games_played_flag",
        )


@registry.register
class PlayerProfileV2Extractor(BaseExtractor):
    endpoint_name = "player_profile_v2"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        return self._from_nba_api(PlayerProfileV2, player_id=player_id)

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        player_id: int = params["player_id"]
        return self._from_nba_api_multi(PlayerProfileV2, player_id=player_id)


@registry.register
class PlayerNextNGamesExtractor(BaseExtractor):
    endpoint_name = "player_next_games"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        number_of_games: int = params.get("number_of_games", 5)
        season: str = params.get("season", current_season())
        season_type: str = params.get("season_type", "Regular Season")
        return self._from_nba_api(
            PlayerNextNGames,
            player_id=player_id,
            number_of_games=number_of_games,
            season_all=season,
            season_type_all_star=season_type,
        )
