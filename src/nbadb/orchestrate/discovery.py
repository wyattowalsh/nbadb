from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import polars as pl
from aiolimiter import AsyncLimiter
from loguru import logger
from nba_api.stats.library.http import NBAStatsHTTP

from nbadb.core.config import get_settings
from nbadb.core.errors import ExtractionError, NbaDbError, TransientError
from nbadb.extract.base import is_retryable_error
from nbadb.orchestrate.extractor_runner import _sync_extract
from nbadb.orchestrate.seasons import season_range

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import ThreadPoolExecutor

    from nbadb.core.config import NbaDbSettings
    from nbadb.extract.registry import EndpointRegistry


class _PatternProgress(Protocol):
    def start_pattern(self, pattern: str, total: int) -> None: ...

    def advance_pattern(self, *, success: bool = True) -> None: ...


_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 2.0  # seconds between retries
_DISCOVERY_CONCURRENCY = 10
_CONCURRENT_DISCOVERY_ATTEMPTS_CAP = 1
_CONCURRENT_DISCOVERY_TIMEOUT = (3.05, 10.0)
_SERIAL_DISCOVERY_RECOVERY_WAVES = 2


@dataclass(frozen=True, slots=True)
class GameDiscoveryResult:
    game_ids: list[str]
    raw: pl.DataFrame
    requested_combos: frozenset[tuple[str, str]]
    covered_combos: frozenset[tuple[str, str]]
    frames_by_combo: dict[tuple[str, str], pl.DataFrame] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.requested_combos <= self.covered_combos


@dataclass(frozen=True, slots=True)
class PlayerTeamSeasonDiscoveryResult:
    params: list[dict[str, int | str]]
    requested_pairs: frozenset[tuple[str, str]]
    covered_pairs: frozenset[tuple[str, str]]

    @property
    def is_complete(self) -> bool:
        return self.requested_pairs <= self.covered_pairs


def _reset_nba_stats_session() -> None:
    """Drop the shared nba_api session so recovery starts from a fresh client."""
    NBAStatsHTTP.set_session(None)


def _season_start_year(season: str | None) -> int | None:
    if not season:
        return None
    try:
        return int(str(season)[:4])
    except (TypeError, ValueError):
        return None


def _filter_player_year_window(df: pl.DataFrame, season: str | None) -> tuple[pl.DataFrame, bool]:
    start_year = _season_start_year(season)
    if start_year is None:
        return df, True
    if {"from_year", "to_year"} - set(df.columns):
        return df, False

    from_year = pl.col("from_year").cast(pl.Int64, strict=False)
    to_year = pl.col("to_year").cast(pl.Int64, strict=False)
    valid_years = from_year.is_not_null() & to_year.is_not_null()
    valid_count = df.filter(valid_years).height
    if valid_count == 0:
        return df, False

    return df.filter(valid_years & (from_year <= start_year) & (to_year >= start_year)), True


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
            if isinstance(exc, TransientError):
                retryable = True
            elif isinstance(exc, NbaDbError):
                raise
            elif is_retryable_error(exc):
                retryable = True
            else:
                raise ExtractionError(f"{label}: extraction failed") from exc

            if not retryable:
                raise
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
                if isinstance(exc, TransientError):
                    raise
                raise TransientError(f"{label}: transient extraction failure") from exc
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
        self._concurrent_retry_attempts = min(
            self._retry_attempts,
            _CONCURRENT_DISCOVERY_ATTEMPTS_CAP,
        )
        self._retry_delay = float(self._settings.extract_retry_base_delay)

    async def discover_game_ids_result(
        self,
        seasons: list[str],
        on_progress: _PatternProgress | None = None,
        season_types: list[str] | None = None,
    ) -> GameDiscoveryResult:
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
            attempts: int | None = None,
        ) -> tuple[tuple[str, str], pl.DataFrame | None, bool]:
            label = f"league_game_log({season}, {season_type})"

            async def _run() -> tuple[tuple[str, str], pl.DataFrame | None, bool]:
                logger.info("{} game IDs: {}", phase, label)
                if phase == "recovering":
                    _reset_nba_stats_session()
                extractor = extractor_cls()
                request_params: dict[str, object] = {
                    "season": season,
                    "season_type": season_type,
                }
                if phase != "recovering":
                    request_params["timeout"] = _CONCURRENT_DISCOVERY_TIMEOUT
                try:
                    df = await _extract_with_retry(
                        extractor,
                        label,
                        thread_pool=self._thread_pool,
                        attempts=(
                            attempts
                            if attempts is not None
                            else (
                                self._retry_attempts
                                if phase == "recovering"
                                else self._concurrent_retry_attempts
                            )
                        ),
                        base_delay=self._retry_delay,
                        rate_limiter=self._rate_limiter,
                        **request_params,
                    )
                except NbaDbError as exc:
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
                    return (season, season_type), df, True
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

        combo_frames: dict[tuple[str, str], pl.DataFrame] = {
            combo: df for combo, df, success in initial_results if success and df is not None
        }
        failed_combos = [combo for combo, _df, success in initial_results if not success]

        if failed_combos:
            unresolved_combos = failed_combos
            total_recovered = 0
            remaining_recovery_attempts = self._retry_attempts

            for wave in range(1, _SERIAL_DISCOVERY_RECOVERY_WAVES + 1):
                if not unresolved_combos or remaining_recovery_attempts <= 0:
                    break

                wave_attempts = max(
                    1,
                    remaining_recovery_attempts - (_SERIAL_DISCOVERY_RECOVERY_WAVES - wave),
                )
                remaining_recovery_attempts -= wave_attempts

                if wave == 1:
                    logger.warning(
                        "retrying {} failed game discovery combos sequentially ({} attempts each)",
                        len(unresolved_combos),
                        wave_attempts,
                    )
                    progress_label = f"game discovery recovery ({len(unresolved_combos)} combos)"
                else:
                    logger.warning(
                        (
                            "retrying {} unrecovered game discovery combos sequentially "
                            "(wave {}/{}, {} attempts each)"
                        ),
                        len(unresolved_combos),
                        wave,
                        _SERIAL_DISCOVERY_RECOVERY_WAVES,
                        wave_attempts,
                    )
                    progress_label = (
                        f"game discovery recovery wave {wave} ({len(unresolved_combos)} combos)"
                    )

                if on_progress is not None:
                    on_progress.start_pattern(progress_label, len(unresolved_combos))

                next_unresolved: list[tuple[str, str]] = []
                for season, season_type in unresolved_combos:
                    _combo, df, success = await _fetch(
                        season,
                        season_type,
                        progress=on_progress,
                        use_semaphore=False,
                        phase="recovering",
                        attempts=wave_attempts,
                    )
                    if success:
                        total_recovered += 1
                        if df is not None:
                            combo_frames[(season, season_type)] = df
                    else:
                        next_unresolved.append((season, season_type))

                unresolved_combos = next_unresolved
                if not unresolved_combos:
                    logger.info(
                        "recovered all {} failed game discovery combos",
                        total_recovered,
                    )
                elif wave < _SERIAL_DISCOVERY_RECOVERY_WAVES:
                    logger.warning(
                        "game discovery recovery wave {} left {} unresolved combos",
                        wave,
                        len(unresolved_combos),
                    )

            if unresolved_combos:
                logger.warning(
                    "game discovery finished with {} unrecovered combo failures: {}",
                    len(unresolved_combos),
                    unresolved_combos,
                )

        if not combo_frames:
            logger.warning("no game discovery combos completed successfully")
            return GameDiscoveryResult(
                game_ids=[],
                raw=pl.DataFrame(),
                requested_combos=frozenset(combos),
                covered_combos=frozenset(),
            )

        non_empty_frames = [df for df in combo_frames.values() if not df.is_empty()]
        combined = (
            pl.concat(non_empty_frames, how="diagonal_relaxed")
            if non_empty_frames
            else pl.DataFrame()
        )
        game_ids = (
            combined.get_column("game_id").unique().sort().to_list()
            if not combined.is_empty() and "game_id" in combined.columns
            else []
        )
        logger.info(
            "discovered {} unique game IDs across {}/{} season×type combos",
            len(game_ids),
            len(combo_frames),
            len(combos),
        )
        covered_combos = {combo for combo in combos if combo not in failed_combos}
        if failed_combos:
            covered_combos = {combo for combo in combos if combo not in unresolved_combos}
        return GameDiscoveryResult(
            game_ids=game_ids,
            raw=combined,
            requested_combos=frozenset(combos),
            covered_combos=frozenset(covered_combos),
            frames_by_combo=combo_frames,
        )

    async def discover_game_ids(
        self,
        seasons: list[str],
        on_progress: _PatternProgress | None = None,
        season_types: list[str] | None = None,
    ) -> tuple[list[str], pl.DataFrame]:
        result = await self.discover_game_ids_result(
            seasons,
            on_progress=on_progress,
            season_types=season_types,
        )
        return result.game_ids, result.raw

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
        except NbaDbError as exc:
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

    async def _discover_season_player_ids_from_endpoint(
        self,
        endpoint: str,
        staging_key: str,
        season: str,
        params: dict[str, object],
    ) -> list[int] | None:
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
        except NbaDbError as exc:
            logger.error(
                "failed to discover {} IDs for {}: {}",
                staging_key,
                season,
                type(exc).__name__,
            )
            return None

        if df.is_empty():
            logger.warning("no {} data returned for {}", staging_key, season)
            return []

        if "person_id" not in df.columns:
            logger.warning("{} missing person_id column for {}", staging_key, season)
            return None

        filtered, usable = _filter_player_year_window(df, season)
        if not usable:
            logger.warning(
                "{} has no usable from_year/to_year metadata for {}; cannot season-scope IDs",
                staging_key,
                season,
            )
            return None

        entity_ids: list[int] = filtered.get_column("person_id").unique().sort().to_list()
        logger.info("discovered {} {} IDs for {}", len(entity_ids), staging_key, season)
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
        if season:
            common_ids = await self._discover_season_player_ids_from_endpoint(
                endpoint="common_all_players",
                staging_key="common_all_players",
                season=season,
                params={
                    "allow_static_fallback": False,
                    "timeout": _CONCURRENT_DISCOVERY_TIMEOUT,
                },
            )
            if common_ids is not None:
                return common_ids

            logger.warning(
                "falling back to player_index for season-scoped player discovery ({})",
                season,
            )
            player_index_ids = await self._discover_season_player_ids_from_endpoint(
                endpoint="player_index",
                staging_key="player_index",
                season=season,
                params={"season": season, "timeout": _CONCURRENT_DISCOVERY_TIMEOUT},
            )
            if player_index_ids is not None:
                return player_index_ids

            logger.error("failed to season-scope player discovery for {}", season)
            return []

        return await self._discover_entity_ids(
            endpoint="common_all_players",
            staging_key="common_all_players",
            id_column="person_id",
            params={},
        )

    async def discover_all_player_ids_by_season(self, seasons: list[str]) -> dict[str, list[int]]:
        """Get historical player IDs for many seasons from one player directory call.

        The unscoped ``CommonAllPlayers`` response includes ``from_year`` and
        ``to_year`` metadata.  Reusing that payload avoids one upstream request
        per season during GitHub full-extraction discovery seeding while keeping
        the same season-window filtering used by ``discover_all_player_ids``.
        Seasons that cannot be derived are omitted so callers can fall back to
        targeted per-season discovery.
        """

        unique_seasons = sorted({season for season in seasons if season})
        if not unique_seasons:
            return {}

        extractor_cls = self._registry.get("common_all_players")
        extractor = extractor_cls()

        try:
            df = await _extract_with_retry(
                extractor,
                "common_all_players",
                thread_pool=self._thread_pool,
                attempts=self._retry_attempts,
                base_delay=self._retry_delay,
                rate_limiter=self._rate_limiter,
                allow_static_fallback=False,
                timeout=_CONCURRENT_DISCOVERY_TIMEOUT,
            )
        except NbaDbError as exc:
            logger.error(
                "failed to bulk-discover historical player IDs by season: {}",
                type(exc).__name__,
            )
            return {}

        if df.is_empty():
            logger.warning("no common_all_players data returned for bulk season discovery")
            return {}
        if "person_id" not in df.columns:
            logger.warning("common_all_players missing person_id column for bulk season discovery")
            return {}

        ids_by_season: dict[str, list[int]] = {}
        for season in unique_seasons:
            filtered, usable = _filter_player_year_window(df, season)
            if not usable:
                logger.warning(
                    "common_all_players has no usable from_year/to_year metadata for {}; "
                    "cannot bulk season-scope IDs",
                    season,
                )
                continue
            entity_ids: list[int] = filtered.get_column("person_id").unique().sort().to_list()
            if entity_ids:
                ids_by_season[season] = entity_ids
                logger.info(
                    "bulk-discovered {} common_all_players IDs for {}",
                    len(entity_ids),
                    season,
                )
            else:
                logger.warning("bulk-discovered no common_all_players IDs for {}", season)
        return ids_by_season

    async def discover_player_team_season_params_result(
        self,
        seasons: list[str],
        season_types: list[str] | None = None,
    ) -> PlayerTeamSeasonDiscoveryResult:
        """Get season-scoped player/team tuples from common_all_players."""
        import polars as pl

        if not seasons:
            return PlayerTeamSeasonDiscoveryResult(
                params=[],
                requested_pairs=frozenset(),
                covered_pairs=frozenset(),
            )
        resolved_season_types = list(season_types or ["Regular Season"])

        extractor_cls = self._registry.get("common_all_players")
        semaphore = asyncio.Semaphore(self._discovery_concurrency)

        async def _fetch(
            season: str,
            *,
            use_semaphore: bool,
            phase: str,
            attempts: int | None = None,
        ) -> tuple[str, pl.DataFrame | None, bool]:
            label = f"common_all_players({season})"

            async def _run() -> tuple[str, pl.DataFrame | None, bool]:
                logger.info("{} player/team pairs: {}", phase, label)
                if phase == "recovering":
                    _reset_nba_stats_session()
                extractor = extractor_cls()
                request_params: dict[str, object] = {"season": season}
                if phase != "recovering":
                    request_params["timeout"] = _CONCURRENT_DISCOVERY_TIMEOUT
                try:
                    df = await _extract_with_retry(
                        extractor,
                        label,
                        thread_pool=self._thread_pool,
                        attempts=(
                            attempts
                            if attempts is not None
                            else (
                                self._retry_attempts
                                if phase == "recovering"
                                else self._concurrent_retry_attempts
                            )
                        ),
                        base_delay=self._retry_delay,
                        rate_limiter=self._rate_limiter,
                        **request_params,
                    )
                except NbaDbError as exc:
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

                normalized = (
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
                if normalized.is_empty():
                    logger.warning("no valid player/team pairs returned for {}", season)
                    return season, None, False

                return season, normalized, True

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

        season_frames: dict[str, pl.DataFrame] = {
            season: df for season, df, success in initial_results if success and df is not None
        }
        failed_seasons = [season for season, _df, success in initial_results if not success]

        if failed_seasons:
            unresolved_seasons = failed_seasons
            total_recovered = 0
            remaining_recovery_attempts = self._retry_attempts

            for wave in range(1, _SERIAL_DISCOVERY_RECOVERY_WAVES + 1):
                if not unresolved_seasons or remaining_recovery_attempts <= 0:
                    break

                wave_attempts = max(
                    1,
                    remaining_recovery_attempts - (_SERIAL_DISCOVERY_RECOVERY_WAVES - wave),
                )
                remaining_recovery_attempts -= wave_attempts

                if wave == 1:
                    logger.warning(
                        (
                            "retrying {} failed player/team discovery seasons "
                            "sequentially ({} attempts each)"
                        ),
                        len(unresolved_seasons),
                        wave_attempts,
                    )
                else:
                    logger.warning(
                        (
                            "retrying {} unrecovered player/team discovery seasons "
                            "sequentially (wave {}/{}, {} attempts each)"
                        ),
                        len(unresolved_seasons),
                        wave,
                        _SERIAL_DISCOVERY_RECOVERY_WAVES,
                        wave_attempts,
                    )

                next_unresolved: list[str] = []
                for season in unresolved_seasons:
                    _season, df, success = await _fetch(
                        season,
                        use_semaphore=False,
                        phase="recovering",
                        attempts=wave_attempts,
                    )
                    if success:
                        total_recovered += 1
                        if df is not None:
                            season_frames[season] = df
                    else:
                        next_unresolved.append(season)

                unresolved_seasons = next_unresolved
                if not unresolved_seasons:
                    logger.info(
                        "recovered all {} failed player/team discovery seasons",
                        total_recovered,
                    )
                elif wave < _SERIAL_DISCOVERY_RECOVERY_WAVES:
                    logger.warning(
                        "player/team discovery recovery wave {} left {} unresolved seasons",
                        wave,
                        len(unresolved_seasons),
                    )

            if unresolved_seasons:
                logger.warning(
                    "player/team discovery finished with {} unrecovered seasons: {}",
                    len(unresolved_seasons),
                    unresolved_seasons,
                )

        if not season_frames:
            return PlayerTeamSeasonDiscoveryResult(
                params=[],
                requested_pairs=frozenset(
                    (season, season_type)
                    for season in seasons
                    for season_type in resolved_season_types
                ),
                covered_pairs=frozenset(),
            )

        non_empty_frames = [df for df in season_frames.values() if not df.is_empty()]
        combined = (
            pl.concat(non_empty_frames, how="vertical_relaxed")
            .unique(subset=["player_id", "team_id", "season"])
            .sort(["season", "player_id", "team_id"])
            if non_empty_frames
            else pl.DataFrame(
                schema={"player_id": pl.Int64, "team_id": pl.Int64, "season": pl.Utf8}
            )
        )
        params: list[dict[str, int | str]] = []
        for row in combined.to_dicts():
            for season_type in resolved_season_types:
                params.append({**row, "season_type": season_type})
        logger.info("discovered {} player/team/season combos", len(params))
        successful_seasons = sorted(season_frames)
        return PlayerTeamSeasonDiscoveryResult(
            params=params,
            requested_pairs=frozenset(
                (season, season_type) for season in seasons for season_type in resolved_season_types
            ),
            covered_pairs=frozenset(
                (season, season_type)
                for season in successful_seasons
                for season_type in resolved_season_types
            ),
        )

    async def discover_player_team_season_params(
        self,
        seasons: list[str],
        season_types: list[str] | None = None,
    ) -> list[dict[str, int | str]]:
        result = await self.discover_player_team_season_params_result(
            seasons,
            season_types=season_types,
        )
        return result.params

    async def discover_team_ids(self) -> list[int]:
        """Get all team IDs from common_team_years."""
        return await self._discover_entity_ids(
            endpoint="common_team_years",
            staging_key="common_team_years",
            id_column="team_id",
            params={},
        )

    async def discover_current_team_ids(self) -> list[int]:
        """Get current NBA team IDs from common_team_years."""
        import polars as pl

        latest_start_year = season_range()[-1][:4]

        def _current_nba_only(df: pl.DataFrame) -> pl.DataFrame:
            filtered = df
            if "league_id" in filtered.columns:
                filtered = filtered.filter(pl.col("league_id").cast(pl.Utf8) == "00")
            if "max_year" not in filtered.columns or filtered.is_empty():
                return filtered

            max_year_values = filtered.get_column("max_year").cast(pl.Utf8)
            latest_year = max_year_values.max() or latest_start_year
            current_only = filtered.filter(pl.col("max_year").cast(pl.Utf8) == latest_year)
            return current_only if not current_only.is_empty() else filtered

        return await self._discover_entity_ids(
            endpoint="common_team_years",
            staging_key="common_team_years_current",
            id_column="team_id",
            params={},
            filter_fn=_current_nba_only,
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
