from __future__ import annotations

import json
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
from nba_api.stats.library.http import NBAStatsHTTP
from nba_api.stats.static import players as static_players

from nbadb.extract.base import BaseExtractor, _to_snake_case
from nbadb.extract.registry import registry
from nbadb.orchestrate.seasons import current_season

_UNSCOPED_COMMON_ALL_PLAYERS_FALLBACK_ERRORS = frozenset(
    {
        "JSONDecodeError",
        "ReadTimeout",
        "ConnectTimeout",
        "ConnectionError",
        "ConnectionResetError",
        "ChunkedEncodingError",
        "RemoteDisconnected",
    }
)


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

    @staticmethod
    def _coerce_result_set_payload(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
        name = payload.get("name")
        headers = list(payload.get("headers") or [])
        rows = list(payload.get("rowSet") or payload.get("data") or [])
        return name, {"headers": headers, "data": rows}

    @classmethod
    def _data_sets_from_raw_response(
        cls,
        raw_response: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        container = raw_response.get("resultSets")
        if container is None:
            container = raw_response.get("resultSet")
        if container is None:
            return {}

        if isinstance(container, list):
            data_sets: dict[str, dict[str, Any]] = {}
            for payload in container:
                if not isinstance(payload, dict):
                    continue
                name, normalized_payload = cls._coerce_result_set_payload(payload)
                if name:
                    data_sets[name] = normalized_payload
            return data_sets

        if isinstance(container, dict):
            if "name" in container:
                name, normalized_payload = cls._coerce_result_set_payload(container)
                return {name: normalized_payload} if name else {}
            return {
                name: {
                    "headers": list(payload.get("headers") or []),
                    "data": list(payload.get("data") or payload.get("rowSet") or []),
                }
                for name, payload in container.items()
                if isinstance(payload, dict)
            }

        return {}

    @staticmethod
    def _empty_result_set_frame(headers: list[str]) -> pl.DataFrame:
        return pl.DataFrame({_to_snake_case(header): [] for header in headers})

    @classmethod
    def _frames_from_sparse_result_sets(
        cls,
        data_sets: dict[str, dict[str, Any]],
    ) -> tuple[list[pl.DataFrame], list[str]]:
        frames: list[pl.DataFrame] = []
        missing_sets: list[str] = []

        for result_set_name, expected_headers in PlayerCareerStats.expected_data.items():
            payload = data_sets.get(result_set_name)
            headers = (
                list(payload.get("headers") or expected_headers)
                if payload
                else list(expected_headers)
            )
            rows = list(payload.get("data") or []) if payload else []
            if payload is None:
                missing_sets.append(result_set_name)
            if not rows:
                frames.append(cls._empty_result_set_frame(headers))
                continue
            df = pl.DataFrame(rows, schema=headers, orient="row")
            frames.append(df.rename({column: _to_snake_case(column) for column in df.columns}))

        return frames, missing_sets

    def _empty_sparse_result_frames(self, *, player_id: int, reason: str) -> list[pl.DataFrame]:
        logger.warning(
            "player_career_stats: player {} returned no usable JSON payload after {}; "
            "using empty fallbacks",
            player_id,
            reason,
        )
        frames, _ = self._frames_from_sparse_result_sets({})
        return frames

    def _extract_sparse_result_sets(
        self,
        *,
        player_id: int,
        timeout: int | None = None,
    ) -> list[pl.DataFrame]:
        request_kwargs: dict[str, Any] = {"player_id": player_id}
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        self._inject_timeout(request_kwargs)

        endpoint = PlayerCareerStats(get_request=False, **request_kwargs)
        response = NBAStatsHTTP().send_api_request(
            endpoint=endpoint.endpoint,
            parameters=endpoint.parameters,
            proxy=endpoint.proxy,
            headers=endpoint.headers,
            timeout=endpoint.timeout,
        )
        try:
            raw_response = response.get_dict()
        except json.JSONDecodeError:
            return self._empty_sparse_result_frames(
                player_id=player_id,
                reason="JSONDecodeError during sparse fallback loading",
            )

        data_sets = self._data_sets_from_raw_response(raw_response)
        frames, missing_sets = self._frames_from_sparse_result_sets(data_sets)
        if missing_sets:
            logger.warning(
                "player_career_stats: player {} missing result sets {}; using empty fallbacks",
                player_id,
                ", ".join(missing_sets),
            )
        elif not data_sets:
            logger.warning(
                "player_career_stats: player {} returned no result-set container; "
                "using empty fallbacks",
                player_id,
            )
        return frames

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
        try:
            return self._from_nba_api_multi(PlayerCareerStats, **request_kwargs)
        except (KeyError, json.JSONDecodeError) as exc:
            logger.warning(
                "player_career_stats: player {} raised {} during result-set loading; falling back",
                player_id,
                type(exc).__name__,
            )
            return self._extract_sparse_result_sets(player_id=player_id, timeout=timeout)


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
        timeout = params.get("timeout")
        if timeout is not None:
            kwargs["timeout"] = timeout

        try:
            return self._from_nba_api(CommonAllPlayers, **kwargs)
        except Exception as exc:
            if season is not None:
                raise
            if isinstance(exc, json.JSONDecodeError):
                logger.warning(
                    "common_all_players: falling back to nba_api static players "
                    "after JSONDecodeError"
                )
                return self._fallback_from_static_players(is_only_current=is_only_current)
            if type(exc).__name__ in _UNSCOPED_COMMON_ALL_PLAYERS_FALLBACK_ERRORS:
                logger.warning(
                    "common_all_players: falling back to nba_api static players after {}",
                    type(exc).__name__,
                )
                return self._fallback_from_static_players(is_only_current=is_only_current)
            raise

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
