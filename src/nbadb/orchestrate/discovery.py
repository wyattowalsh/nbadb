from __future__ import annotations

import asyncio
import random
from typing import TYPE_CHECKING, Protocol

from aiolimiter import AsyncLimiter
from loguru import logger

from nbadb.core.config import get_settings
from nbadb.orchestrate.extractor_runner import _sync_extract

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import ThreadPoolExecutor

    import polars as pl

    from nbadb.core.config import NbaDbSettings
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
    *,
    thread_pool: ThreadPoolExecutor | None = None,
    attempts: int | None = None,
    base_delay: float | None = None,
    rate_limiter: AsyncLimiter | None = None,
    **kwargs: object,
) -> pl.DataFrame:
    """Extract with retries and inter-call delay for rate limiting.

    When *thread_pool* is provided the synchronous nba_api call is
    dispatched to that pool via ``loop.run_in_executor``, reusing the
    same ``ThreadPoolExecutor`` that :class:`ExtractorRunner` owns.
    Falls back to ``asyncio.to_thread`` when no pool is given.
    """
    import polars as pl

    attempts = _RETRY_ATTEMPTS if attempts is None else max(1, attempts)
    base_delay = _RETRY_DELAY if base_delay is None else base_delay

    for attempt in range(1, attempts + 1):
        try:
            loop = asyncio.get_running_loop()
            if rate_limiter is None:
                df: pl.DataFrame = await loop.run_in_executor(
                    thread_pool, lambda: _sync_extract(extractor, **kwargs)
                )
            else:
                async with rate_limiter:
                    df = await loop.run_in_executor(
                        thread_pool, lambda: _sync_extract(extractor, **kwargs)
                    )
            return df
        except Exception as exc:
            if attempt < attempts:
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.warning(
                    "{}: attempt {}/{} failed ({}), retrying in {:.0f}s",
                    label,
                    attempt,
                    attempts,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "{}: all {} attempts failed: {}",
                    label,
                    attempts,
                    type(exc).__name__,
                )
                raise
    return pl.DataFrame()  # unreachable, satisfies type checker


class EntityDiscovery:
    """Discovers entity IDs needed for extraction loops."""

    def __init__(
        self,
        registry: EndpointRegistry,
        thread_pool: ThreadPoolExecutor | None = None,
        settings: NbaDbSettings | None = None,
    ) -> None:
        self._registry = registry
        self._thread_pool = thread_pool
        self._settings = settings or get_settings()
        self._rate_limiter = AsyncLimiter(max_rate=self._settings.rate_limit, time_period=1.0)
        self._discovery_concurrency = max(1, int(self._settings.discovery_concurrency))
        self._retry_attempts = max(1, int(self._settings.extract_max_retries) + 1)
        self._retry_delay = float(self._settings.extract_retry_base_delay)

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

        semaphore = asyncio.Semaphore(self._discovery_concurrency)

        async def _fetch(
            season: str,
            season_type: str,
            *,
            progress: _PatternProgress | None,
            use_semaphore: bool,
            phase: str,
        ) -> tuple[tuple[str, str], pl.DataFrame | None, bool]:
            label = f"league_game_log({season}, {season_type})"

            async def _run() -> tuple[tuple[str, str], pl.DataFrame | None, bool]:
                logger.info("{} game IDs: {}", phase, label)
                extractor = extractor_cls()
                try:
                    df = await _extract_with_retry(
                        extractor,
                        label,
                        thread_pool=self._thread_pool,
                        attempts=self._retry_attempts,
                        base_delay=self._retry_delay,
                        rate_limiter=self._rate_limiter,
                        season=season,
                        season_type=season_type,
                    )
                except Exception as exc:
                    message = (
                        "failed to recover game log for {}: {}"
                        if phase == "recovering"
                        else "failed to extract game log for {}: {}"
                    )
                    logger.error(message, label, type(exc).__name__)
                    if progress is not None:
                        progress.advance_pattern(success=False)
                    return (season, season_type), None, False

                if progress is not None:
                    progress.advance_pattern(success=True)
                if phase == "recovering":
                    logger.info("recovered game log for {}", label)
                if df.is_empty():
                    return (season, season_type), None, True
                return (season, season_type), df, True

            if not use_semaphore:
                return await _run()

            async with semaphore:
                return await _run()

        initial_results = await asyncio.gather(
            *[
                _fetch(
                    season,
                    season_type,
                    progress=on_progress,
                    use_semaphore=True,
                    phase="discovering",
                )
                for season, season_type in combos
            ]
        )

        frames: list[pl.DataFrame] = [
            df for _combo, df, success in initial_results if success and df is not None
        ]
        failed_combos = [combo for combo, _df, success in initial_results if not success]

        if failed_combos:
            logger.warning(
                "retrying {} failed game discovery combos sequentially",
                len(failed_combos),
            )
            if on_progress is not None:
                on_progress.start_pattern(
                    f"game discovery recovery ({len(failed_combos)} combos)",
                    len(failed_combos),
                )

            recovered = 0
            for season, season_type in failed_combos:
                _combo, df, success = await _fetch(
                    season,
                    season_type,
                    progress=on_progress,
                    use_semaphore=False,
                    phase="recovering",
                )
                if success:
                    recovered += 1
                    if df is not None:
                        frames.append(df)

            if recovered == len(failed_combos):
                logger.info("recovered all {} failed game discovery combos", recovered)
            else:
                logger.warning(
                    "game discovery finished with {} unrecovered combo failures",
                    len(failed_combos) - recovered,
                )

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
            df = await _extract_with_retry(
                extractor,
                staging_key,
                thread_pool=self._thread_pool,
                attempts=self._retry_attempts,
                base_delay=self._retry_delay,
                rate_limiter=self._rate_limiter,
                **params,
            )
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
            if "roster_status" in df.columns:
                return df.filter(df["roster_status"] == 1)
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
        semaphore = asyncio.Semaphore(self._discovery_concurrency)

        async def _fetch(
            season: str,
            *,
            use_semaphore: bool,
            phase: str,
        ) -> tuple[str, pl.DataFrame | None, bool]:
            label = f"common_all_players({season})"

            async def _run() -> tuple[str, pl.DataFrame | None, bool]:
                logger.info("{} player/team pairs: {}", phase, label)
                extractor = extractor_cls()
                try:
                    df = await _extract_with_retry(
                        extractor,
                        label,
                        thread_pool=self._thread_pool,
                        attempts=self._retry_attempts,
                        base_delay=self._retry_delay,
                        rate_limiter=self._rate_limiter,
                        season=season,
                    )
                except Exception as exc:
                    message = (
                        "failed to recover player/team pairs for {}: {}"
                        if phase == "recovering"
                        else "failed to discover player/team pairs for {}: {}"
                    )
                    logger.error(message, label, type(exc).__name__)
                    return season, None, False

                if phase == "recovering":
                    logger.info("recovered player/team pairs for {}", label)
                if df.is_empty():
                    logger.warning("no common_all_players data returned for {}", season)
                    return season, None, False

                required = {"person_id", "team_id"}
                missing = required - set(df.columns)
                if missing:
                    logger.warning(
                        "common_all_players missing columns {} for {}",
                        sorted(missing),
                        season,
                    )
                    return season, None, False

                return (
                    season,
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
                    .unique(),
                    True,
                )

            if not use_semaphore:
                return await _run()

            async with semaphore:
                return await _run()

        initial_results = await asyncio.gather(
            *[
                _fetch(
                    season,
                    use_semaphore=True,
                    phase="discovering",
                )
                for season in seasons
            ]
        )

        frames = [df for _season, df, success in initial_results if success and df is not None]
        failed_seasons = [season for season, _df, success in initial_results if not success]

        if failed_seasons:
            logger.warning(
                "retrying {} failed player/team discovery seasons sequentially",
                len(failed_seasons),
            )
            recovered = 0
            for season in failed_seasons:
                _season, df, success = await _fetch(
                    season,
                    use_semaphore=False,
                    phase="recovering",
                )
                if success:
                    recovered += 1
                    if df is not None:
                        frames.append(df)

            if recovered == len(failed_seasons):
                logger.info(
                    "recovered all {} failed player/team discovery seasons",
                    recovered,
                )
            else:
                logger.warning(
                    "player/team discovery finished with {} unrecovered seasons",
                    len(failed_seasons) - recovered,
                )

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
