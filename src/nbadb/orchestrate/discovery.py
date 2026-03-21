from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from nbadb.orchestrate.extractor_runner import _assign_proxy, _sync_extract

if TYPE_CHECKING:
    from collections.abc import Callable

    import polars as pl

    from nbadb.core.proxy import ProxyUrlProvider
    from nbadb.extract.registry import EndpointRegistry


class _PatternProgress(Protocol):
    def start_pattern(self, pattern: str, total: int) -> None: ...

    def advance_pattern(self, *, success: bool = True) -> None: ...

_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 2.0  # seconds between retries
_DISCOVERY_CONCURRENCY = 10


async def _extract_with_retry(
    extractor: object,
    label: str,
    **kwargs: object,
) -> pl.DataFrame:
    """Extract with retries and inter-call delay for rate limiting.

    Uses ``asyncio.to_thread`` + ``_sync_extract`` so the synchronous
    nba_api call does not block the event loop.
    """
    import polars as pl

    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            df: pl.DataFrame = await asyncio.to_thread(_sync_extract, extractor, **kwargs)
            return df
        except Exception as exc:
            if attempt < _RETRY_ATTEMPTS:
                delay = _RETRY_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.warning(
                    "{}: attempt {}/{} failed ({}), retrying in {:.0f}s",
                    label,
                    attempt,
                    _RETRY_ATTEMPTS,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "{}: all {} attempts failed: {}",
                    label,
                    _RETRY_ATTEMPTS,
                    type(exc).__name__,
                )
                raise
    return pl.DataFrame()  # unreachable, satisfies type checker


class EntityDiscovery:
    """Discovers entity IDs needed for extraction loops."""

    def __init__(
        self,
        registry: EndpointRegistry,
        proxy_pool: ProxyUrlProvider | None = None,
    ) -> None:
        self._registry = registry
        self._proxy_pool = proxy_pool

    async def discover_game_ids(
        self,
        seasons: list[str],
        on_progress: _PatternProgress | None = None,
        season_types: list[str] | None = None,
    ) -> tuple[list[str], pl.DataFrame]:
        """Extract league_game_log for given seasons and season_types.

        Returns (game_ids, raw_df). The raw_df is also usable as
        stg_league_game_log (dual purpose -- avoids re-extraction).

        When *season_types* is provided, the game log is fetched once per
        (season, season_type) pair so that Playoff, All-Star, and Pre Season
        games are discovered alongside Regular Season games.

        Seasons are fetched concurrently (up to ``_DISCOVERY_CONCURRENCY``
        in-flight at once). Each season failure is isolated -- it does not
        cancel the remaining seasons.
        """
        import polars as pl

        if season_types is None:
            season_types = ["Regular Season"]

        extractor_cls = self._registry.get("league_game_log")

        combos = [(s, st) for s in seasons for st in season_types]
        if on_progress is not None:
            on_progress.start_pattern(f"game discovery ({len(combos)} combos)", len(combos))

        semaphore = asyncio.Semaphore(_DISCOVERY_CONCURRENCY)

        async def _fetch(season: str, season_type: str) -> pl.DataFrame | None:
            async with semaphore:
                label = f"league_game_log({season}, {season_type})"
                logger.info("discovering game IDs: {}", label)
                extractor = extractor_cls()
                try:
                    _assign_proxy(extractor, self._proxy_pool)
                    df = await _extract_with_retry(
                        extractor,
                        label,
                        season=season,
                        season_type=season_type,
                    )
                    if on_progress is not None:
                        on_progress.advance_pattern(success=True)
                    if not df.is_empty():
                        return df
                    return None
                except Exception as exc:
                    logger.error(
                        "failed to extract game log for {}: {}",
                        label,
                        type(exc).__name__,
                    )
                    if on_progress is not None:
                        on_progress.advance_pattern(success=False)
                    return None

        results = await asyncio.gather(*[_fetch(s, st) for s, st in combos])
        frames: list[pl.DataFrame] = [df for df in results if df is not None]

        if not frames:
            logger.warning("no game log data returned")
            return [], pl.DataFrame()

        combined = pl.concat(frames, how="diagonal_relaxed")
        game_ids = combined.get_column("game_id").unique().sort().to_list()
        logger.info(
            "discovered {} unique game IDs across {} season×type combos",
            len(game_ids),
            len(combos),
        )
        return game_ids, combined

    async def _discover_entity_ids(
        self,
        endpoint: str,
        staging_key: str,
        id_column: str,
        params: dict,
        *,
        filter_fn: Callable[[pl.DataFrame], pl.DataFrame] | None = None,
    ) -> list[int]:
        """Shared logic for discovering entity IDs from a registry endpoint.

        Args:
            endpoint: Registry key for the extractor class.
            staging_key: Label used in logging and retry messages.
            id_column: Column containing the entity IDs.
            params: Keyword arguments forwarded to the extractor.
            filter_fn: Optional post-extraction filter applied before
                extracting the ID column (e.g. active-player filtering).
        """
        extractor_cls = self._registry.get(endpoint)
        extractor = extractor_cls()

        try:
            _assign_proxy(extractor, self._proxy_pool)
            df = await _extract_with_retry(extractor, staging_key, **params)
        except Exception as exc:
            logger.error(
                "failed to discover {} IDs: {}",
                staging_key,
                type(exc).__name__,
            )
            return []

        if df.is_empty():
            logger.warning("no {} data returned", staging_key)
            return []

        if filter_fn is not None:
            df = filter_fn(df)

        entity_ids: list[int] = df.get_column(id_column).unique().sort().to_list()
        logger.info("discovered {} {} IDs", len(entity_ids), staging_key)
        return entity_ids

    async def discover_player_ids(self, season: str | None = None) -> list[int]:
        """Get active player IDs from common_all_players."""

        def _active_only(df: pl.DataFrame) -> pl.DataFrame:
            if "is_active" in df.columns:
                return df.filter(df["is_active"] == 1)
            return df

        params = {"season": season} if season else {}
        return await self._discover_entity_ids(
            endpoint="common_all_players",
            staging_key="common_all_players",
            id_column="person_id",
            params=params,
            filter_fn=_active_only,
        )

    async def discover_all_player_ids(self, season: str | None = None) -> list[int]:
        """Get ALL player IDs (active + historical) from common_all_players.

        Use this for ``run_init()`` to ensure historical players are included
        in player-level extraction.
        """
        params = {"season": season} if season else {}
        return await self._discover_entity_ids(
            endpoint="common_all_players",
            staging_key="common_all_players",
            id_column="person_id",
            params=params,
        )

    async def discover_player_team_season_params(
        self,
        seasons: list[str],
    ) -> list[dict[str, int | str]]:
        """Get season-scoped player/team tuples from common_all_players."""
        import polars as pl

        if not seasons:
            return []

        extractor_cls = self._registry.get("common_all_players")
        semaphore = asyncio.Semaphore(_DISCOVERY_CONCURRENCY)

        async def _fetch(season: str) -> pl.DataFrame | None:
            async with semaphore:
                label = f"common_all_players({season})"
                logger.info("discovering player/team pairs: {}", label)
                extractor = extractor_cls()
                try:
                    _assign_proxy(extractor, self._proxy_pool)
                    df = await _extract_with_retry(extractor, label, season=season)
                except Exception as exc:
                    logger.error(
                        "failed to discover player/team pairs for {}: {}",
                        label,
                        type(exc).__name__,
                    )
                    return None

                if df.is_empty():
                    logger.warning("no common_all_players data returned for {}", season)
                    return None

                required = {"person_id", "team_id"}
                missing = required - set(df.columns)
                if missing:
                    logger.warning(
                        "common_all_players missing columns {} for {}",
                        sorted(missing),
                        season,
                    )
                    return None

                return (
                    df.select(
                        pl.col("person_id").cast(pl.Int64, strict=False).alias("player_id"),
                        pl.col("team_id").cast(pl.Int64, strict=False).alias("team_id"),
                    )
                    .filter(
                        pl.col("player_id").is_not_null()
                        & pl.col("team_id").is_not_null()
                        & (pl.col("team_id") > 0)
                    )
                    .with_columns(pl.lit(season).alias("season"))
                    .unique()
                )

        results = await asyncio.gather(*[_fetch(season) for season in seasons])
        frames = [df for df in results if df is not None]
        if not frames:
            return []

        combined = (
            pl.concat(frames, how="vertical_relaxed")
            .unique(subset=["player_id", "team_id", "season"])
            .sort(["season", "player_id", "team_id"])
        )
        params = combined.to_dicts()
        logger.info("discovered {} player/team/season combos", len(params))
        return params

    async def discover_team_ids(self) -> list[int]:
        """Get all team IDs from common_team_years."""
        return await self._discover_entity_ids(
            endpoint="common_team_years",
            staging_key="common_team_years",
            id_column="team_id",
            params={},
        )

    async def discover_game_dates(self, game_log_df: pl.DataFrame) -> list[str]:
        """Extract unique game dates from an already-fetched game log."""
        import polars as pl

        if game_log_df.is_empty():
            return []

        dates: list[str] = (
            game_log_df.get_column("game_date").cast(pl.Utf8).unique().sort().to_list()
        )
        logger.info("discovered {} unique game dates", len(dates))
        return dates
