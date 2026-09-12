from __future__ import annotations

from typing import Any

import polars as pl
from loguru import logger
from nba_api.stats.endpoints import (
    CommonAllPlayers,
    CommonPlayerInfo,
    PlayerAwards,
    PlayerCareerStats,
    PlayerIndex,
    PlayerNextNGames,
    PlayerProfileV2,
)

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
        frames = await self.extract_all(**params)
        return frames[0] if frames else pl.DataFrame()

    async def extract_all(self, **params: Any) -> list[pl.DataFrame]:
        """Return all result sets: regular, post, allstar, etc."""
        player_id: int = params["player_id"]
        timeout = params.get("timeout")
        request_kwargs: dict[str, Any] = {"player_id": player_id}
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        return self._from_nba_api_multi(PlayerCareerStats, **request_kwargs)


@registry.register
class PlayerAwardsExtractor(BaseExtractor):
    endpoint_name = "player_awards"
    category = "player_info"

    @staticmethod
    def _normalize_award_fields(df: pl.DataFrame) -> pl.DataFrame:
        if "all_nba_team_number" not in df.columns:
            return df

        cleaned = pl.col("all_nba_team_number").cast(pl.Utf8, strict=False).str.strip_chars()
        normalized = (
            pl.when(cleaned.is_null() | cleaned.str.to_lowercase().is_in(["", "nan", "none"]))
            .then(None)
            .otherwise(cleaned)
            .alias("_all_nba_team_number_clean")
        )
        return (
            df.with_columns(normalized)
            .with_columns(
                pl.col("_all_nba_team_number_clean")
                .cast(pl.Int64, strict=True)
                .alias("all_nba_team_number")
            )
            .drop("_all_nba_team_number_clean")
        )

    async def extract(self, **params: Any) -> pl.DataFrame:
        player_id: int = params["player_id"]
        converted = self._call_nba_api(PlayerAwards, player_id=player_id)
        if not converted:
            return pl.DataFrame()
        return self._validate(self._normalize_award_fields(converted[0]))


@registry.register
class PlayerIndexExtractor(BaseExtractor):
    endpoint_name = "player_index"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season = params.get("season") or None
        timeout = params.get("timeout")
        kwargs: dict[str, Any] = {}
        if season is not None:
            kwargs["season"] = season
        if timeout is not None:
            kwargs["timeout"] = timeout
        return self._from_nba_api(PlayerIndex, **kwargs)


@registry.register
class CommonAllPlayersExtractor(BaseExtractor):
    endpoint_name = "common_all_players"
    category = "player_info"

    async def extract(self, **params: Any) -> pl.DataFrame:
        season = params.get("season") or None
        is_only_current: int = params.get("is_only_current_season", 0)
        allow_static_fallback = bool(params.get("allow_static_fallback", False))
        kwargs: dict[str, Any] = {"is_only_current_season": is_only_current}
        if season is not None:
            kwargs["season"] = season
        timeout = params.get("timeout")
        if timeout is not None:
            kwargs["timeout"] = timeout

        if allow_static_fallback:
            raise ValueError(
                "allow_static_fallback is not valid for assured CommonAllPlayers extraction; "
                "use the static_players extractor explicitly"
            )
        return self._from_nba_api(CommonAllPlayers, **kwargs)


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
