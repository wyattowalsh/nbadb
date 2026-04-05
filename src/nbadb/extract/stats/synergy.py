from __future__ import annotations

import time
from typing import Any

import pandas as pd
import polars as pl
from loguru import logger
from nba_api.stats.endpoints import SynergyPlayTypes
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.extract.base import BaseExtractor, _safe_from_pandas, _to_snake_case, is_retryable_error
from nbadb.extract.registry import registry

_SYNERGY_PLAY_TYPES = [
    "Isolation",
    "Transition",
    "PRBallHandler",
    "PRRollMan",
    "Postup",
    "Spotup",
    "Handoff",
    "Cut",
    "OffScreen",
    "Putbacks",
    "Misc",
]

_SYNERGY_ENTITY_TYPES = ["P", "T"]  # Player, Team
_SYNERGY_GROUPINGS = ["offensive", "defensive"]
_UNSUPPORTED_INVALID_PARAMETER_COMBOS = frozenset({("Putbacks", "P", "offensive")})
_RETRYABLE_SUBREQUEST_ATTEMPTS = 2
_RETRYABLE_SUBREQUEST_BACKOFF_SECONDS = 2.0


class SynergyInvalidParameterError(RuntimeError):
    """Raised when synergy returns an unexpected Invalid Parameter payload."""


def _reset_nba_stats_session() -> None:
    NBAStatsHTTP.set_session(None)


def _has_invalid_parameter_payload(payload: dict[str, Any]) -> bool:
    return len(payload) == 1 and next(iter(payload.values())) == ["Invalid Parameter"]


def _synergy_payload_to_frame(payload: dict[str, Any], *, season_type: str) -> pl.DataFrame:
    import polars as pl

    if "resultSets" in payload:
        results = payload["resultSets"]
    elif "resultSet" in payload:
        results = payload["resultSet"]
    else:
        raise KeyError("resultSet")

    if isinstance(results, list):
        if not results:
            return pl.DataFrame()
        dataset = results[0]
    elif isinstance(results, dict):
        dataset = results
    else:
        raise KeyError("resultSet")

    headers = dataset.get("headers")
    rows = dataset.get("rowSet")
    if not isinstance(headers, list) or not isinstance(rows, list):
        raise KeyError("resultSet")

    pdf = pd.DataFrame(rows, columns=headers)
    df = _safe_from_pandas(pdf)
    if df.columns:
        df = df.rename({c: _to_snake_case(c) for c in df.columns})
    if season_type and "season_type" not in df.columns:
        df = df.with_columns(pl.lit(season_type).alias("season_type"))
    return df


@registry.register
class SynergyPlayTypesExtractor(BaseExtractor):
    endpoint_name = "synergy_play_types"
    category = "synergy"

    def _fetch_synergy_frame(
        self,
        *,
        season: str,
        season_type: str,
        play_type: str,
        entity_type: str,
        grouping: str,
    ) -> pl.DataFrame:
        request_kwargs: dict[str, Any] = {
            "season": season,
            "play_type_nullable": play_type,
            "player_or_team_abbreviation": entity_type,
            "season_type_all_star": season_type,
            "type_grouping_nullable": grouping,
        }
        try:
            return self._from_nba_api(SynergyPlayTypes, **request_kwargs)
        except KeyError as exc:
            if exc.args != ("resultSet",):
                raise

        self._inject_timeout(request_kwargs)
        endpoint = SynergyPlayTypes(get_request=False, **request_kwargs)
        payload = (
            NBAStatsHTTP()
            .send_api_request(
                endpoint=endpoint.endpoint,
                parameters=endpoint.parameters,
                proxy=endpoint.proxy,
                headers=endpoint.headers,
                timeout=endpoint.timeout,
            )
            .get_dict()
        )
        if _has_invalid_parameter_payload(payload):
            combo = (play_type, entity_type, grouping)
            if combo in _UNSUPPORTED_INVALID_PARAMETER_COMBOS:
                logger.debug(
                    (
                        "synergy {}/{}/{} for {} ({}) returned Invalid Parameter; "
                        "skipping unsupported combo"
                    ),
                    play_type,
                    entity_type,
                    grouping,
                    season,
                    season_type,
                )
                return pl.DataFrame()
            raise SynergyInvalidParameterError(
                f"synergy {play_type}/{entity_type}/{grouping} "
                f"for {season} ({season_type}) returned Invalid Parameter"
            )
        return _synergy_payload_to_frame(payload, season_type=season_type)

    async def extract(self, **params: Any) -> pl.DataFrame:
        import polars as pl

        season: str = params["season"]
        season_type: str = params.get("season_type", "Regular Season")
        frames: list[pl.DataFrame] = []

        for play_type in _SYNERGY_PLAY_TYPES:
            for entity_type in _SYNERGY_ENTITY_TYPES:
                for grouping in _SYNERGY_GROUPINGS:
                    logger.debug(
                        "Extracting synergy {}/{}/{} for {} ({})",
                        play_type,
                        entity_type,
                        grouping,
                        season,
                        season_type,
                    )
                    for attempt in range(1, _RETRYABLE_SUBREQUEST_ATTEMPTS + 1):
                        try:
                            df = self._fetch_synergy_frame(
                                season=season,
                                season_type=season_type,
                                play_type=play_type,
                                entity_type=entity_type,
                                grouping=grouping,
                            )
                        except Exception as exc:
                            if isinstance(exc, SynergyInvalidParameterError):
                                raise
                            if is_retryable_error(exc):
                                if attempt < _RETRYABLE_SUBREQUEST_ATTEMPTS:
                                    logger.warning(
                                        (
                                            "synergy {}/{}/{} for {} ({}) attempt {}/{} "
                                            "failed: {}, retrying in {:.1f}s"
                                        ),
                                        play_type,
                                        entity_type,
                                        grouping,
                                        season,
                                        season_type,
                                        attempt,
                                        _RETRYABLE_SUBREQUEST_ATTEMPTS,
                                        type(exc).__name__,
                                        _RETRYABLE_SUBREQUEST_BACKOFF_SECONDS,
                                    )
                                    _reset_nba_stats_session()
                                    time.sleep(_RETRYABLE_SUBREQUEST_BACKOFF_SECONDS)
                                    continue
                                logger.error(
                                    (
                                        "synergy {}/{}/{} for {} ({}) exhausted {} "
                                        "retryable attempts: {}"
                                    ),
                                    play_type,
                                    entity_type,
                                    grouping,
                                    season,
                                    season_type,
                                    _RETRYABLE_SUBREQUEST_ATTEMPTS,
                                    type(exc).__name__,
                                )
                                raise
                            logger.warning(
                                "synergy {}/{}/{} for {} ({}) failed with non-retryable {}",
                                play_type,
                                entity_type,
                                grouping,
                                season,
                                season_type,
                                type(exc).__name__,
                            )
                            break
                        else:
                            if not df.is_empty():
                                if "play_type" not in df.columns:
                                    df = df.with_columns(pl.lit(play_type).alias("play_type"))
                                if "entity_type" not in df.columns:
                                    df = df.with_columns(pl.lit(entity_type).alias("entity_type"))
                                if "type_grouping" not in df.columns:
                                    df = df.with_columns(pl.lit(grouping).alias("type_grouping"))
                                frames.append(df)
                            break
                    # Throttle within the 44-call loop to respect rate limits
                    time.sleep(0.6)

        total = len(_SYNERGY_PLAY_TYPES) * len(_SYNERGY_ENTITY_TYPES) * len(_SYNERGY_GROUPINGS)
        if not frames:
            raise RuntimeError(f"all {total} synergy combinations failed for {season}")
        return pl.concat(frames, how="diagonal_relaxed")
