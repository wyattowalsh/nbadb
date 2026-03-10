from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING

from loguru import logger

from nbadb.orchestrate.extractor_runner import _assign_proxy, _sync_extract

if TYPE_CHECKING:
    from collections.abc import Callable

    import polars as pl

    from nbadb.core.proxy import ProxyPool
    from nbadb.extract.registry import EndpointRegistry

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
        proxy_pool: ProxyPool | None = None,
    ) -> None:
        self._registry = registry
        self._proxy_pool = proxy_pool

    async def discover_game_ids(
        self,
        seasons: list[str],
        on_progress: object | None = None,
    ) -> tuple[list[str], pl.DataFrame]:
        """Extract league_game_log for given seasons.

        Returns (game_ids, raw_df). The raw_df is also usable as
        stg_league_game_log (dual purpose -- avoids re-extraction).

        Seasons are fetched concurrently (up to ``_DISCOVERY_CONCURRENCY``
        in-flight at once). Each season failure is isolated -- it does not
        cancel the remaining seasons.
        """
        import polars as pl

        extractor_cls = self._registry.get("league_game_log")

        if on_progress is not None:
            on_progress.start_pattern(f"game discovery ({len(seasons)} seasons)", len(seasons))

        semaphore = asyncio.Semaphore(_DISCOVERY_CONCURRENCY)

        async def _fetch_season(season: str) -> pl.DataFrame | None:
            async with semaphore:
                logger.info("discovering game IDs for season {}", season)
                extractor = extractor_cls()
                try:
                    _assign_proxy(extractor, self._proxy_pool)
                    df = await _extract_with_retry(
                        extractor,
                        f"league_game_log({season})",
                        season=season,
                    )
                    if on_progress is not None:
                        on_progress.advance_pattern(success=True)
                    if not df.is_empty():
                        return df
                    return None
                except Exception as exc:
                    logger.error(
                        "failed to extract game log for {}: {}",
                        season,
                        type(exc).__name__,
                    )
                    if on_progress is not None:
                        on_progress.advance_pattern(success=False)
                    return None

        results = await asyncio.gather(*[_fetch_season(s) for s in seasons])
        frames: list[pl.DataFrame] = [df for df in results if df is not None]

        if not frames:
            logger.warning("no game log data returned")
            return [], pl.DataFrame()

        combined = pl.concat(frames, how="diagonal_relaxed")
        game_ids = combined.get_column("game_id").unique().sort().to_list()
        logger.info(
            "discovered {} unique game IDs across {} seasons",
            len(game_ids),
            len(seasons),
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
