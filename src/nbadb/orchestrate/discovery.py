from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, cast

import polars as pl
from aiolimiter import AsyncLimiter
from loguru import logger

from nbadb.core.config import get_settings
from nbadb.core.errors import (
    ExtractionError,
    NbaDbError,
    TransientError,
    ValidationError,
)
from nbadb.core.extraction_failures import classify_exception
from nbadb.core.types import season_type_upstream_unavailable_reason
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


class _TimeoutAwareExtractor(Protocol):
    _request_timeout_override: int | None


_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 2.0  # seconds between retries
_DISCOVERY_CONCURRENCY = 10
_CONCURRENT_DISCOVERY_ATTEMPTS_CAP = 1
_CONCURRENT_DISCOVERY_TIMEOUT = (3.05, 10.0)
_RECOVERY_DISCOVERY_TIMEOUT = (3.05, 30.0)
_BROAD_OUTAGE_CANARY_ATTEMPTS_CAP = 3

type _DiscoveryFailureKind = Literal["transport", "response", "permanent", "no_data"]


class _DiscoveryResponseError(Exception):
    """Retryable failure proving that a discovery response cannot cover its scope."""


def _is_positive_request_timeout(value: object) -> bool:
    if isinstance(value, (int, float)):
        return value > 0
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and all(isinstance(part, (int, float)) and part > 0 for part in value)
    )


@dataclass(frozen=True, slots=True)
class GameDiscoveryResult:
    game_ids: list[str]
    raw: pl.DataFrame
    requested_combos: frozenset[tuple[str, str]]
    covered_combos: frozenset[tuple[str, str]]
    frames_by_combo: dict[tuple[str, str], pl.DataFrame] = field(default_factory=dict)
    failures_by_combo: dict[tuple[str, str], _DiscoveryFailureKind] = field(default_factory=dict)
    upstream_unavailable_combos: dict[tuple[str, str], str] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.requested_combos <= self.covered_combos


@dataclass(frozen=True, slots=True)
class PlayerTeamSeasonDiscoveryResult:
    params: list[dict[str, int | str]]
    requested_pairs: frozenset[tuple[str, str]]
    covered_pairs: frozenset[tuple[str, str]]
    failures_by_pair: dict[tuple[str, str], _DiscoveryFailureKind] = field(default_factory=dict)
    upstream_unavailable_pairs: dict[tuple[str, str], str] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.requested_pairs <= self.covered_pairs


@dataclass(frozen=True, slots=True)
class PlayerIdDiscoveryResult:
    ids: list[int]
    requested_season: str | None
    source: str | None = None
    failure_kind: _DiscoveryFailureKind | None = None
    failures_by_source: dict[str, _DiscoveryFailureKind] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.failure_kind is None


def _dominant_failure_kind(
    failures: dict[str, _DiscoveryFailureKind],
) -> _DiscoveryFailureKind:
    for failure_kind in ("permanent", "transport", "response", "no_data"):
        if failure_kind in failures.values():
            return failure_kind
    return "no_data"


def _season_start_year(season: str | None) -> int | None:
    if not season:
        return None
    try:
        return int(str(season)[:4])
    except (TypeError, ValueError):
        return None


def _season_type_unavailable_reason(season: str, season_type: str) -> str | None:
    season_start_year = _season_start_year(season)
    if season_start_year is None:
        return None
    try:
        return season_type_upstream_unavailable_reason(season_start_year, season_type)
    except ValueError:
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
    validate: Callable[[pl.DataFrame], pl.DataFrame] | None = None,
    attempt_offset: int = 0,
    attempt_total: int | None = None,
    /,
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

    The optional validator runs inside the retry loop, so malformed responses
    consume real attempts. The offset and total keep attempt logs truthful when
    one configured budget spans the concurrent fast pass and serial recovery.
    """
    import polars as pl

    attempts = _RETRY_ATTEMPTS if attempts is None else max(1, attempts)
    base_delay = _RETRY_DELAY if base_delay is None else base_delay
    attempt_offset = max(0, attempt_offset)
    attempt_total = max(attempt_offset + attempts, attempt_total or attempts)
    request_kwargs = dict(kwargs)
    request_timeout = request_kwargs.get("timeout")
    if not _is_positive_request_timeout(request_timeout):
        request_timeout = _RECOVERY_DISCOVERY_TIMEOUT
        request_kwargs["timeout"] = request_timeout
    if hasattr(extractor, "_request_timeout_override"):
        read_timeout = (
            request_timeout[-1] if isinstance(request_timeout, tuple) else request_timeout
        )
        if isinstance(read_timeout, (int, float)) and read_timeout > 0:
            cast("_TimeoutAwareExtractor", extractor)._request_timeout_override = max(
                1, int(read_timeout)
            )

    for attempt in range(1, attempts + 1):
        try:
            loop = asyncio.get_running_loop()
            if rate_limiter is None:
                df: pl.DataFrame = await loop.run_in_executor(
                    thread_pool, lambda: _sync_extract(extractor, **request_kwargs)
                )
            else:
                async with rate_limiter:
                    df = await loop.run_in_executor(
                        thread_pool, lambda: _sync_extract(extractor, **request_kwargs)
                    )
            return validate(df) if validate is not None else df
        except Exception as exc:
            failure_class = classify_exception(exc)
            response_failure = (
                isinstance(
                    exc,
                    (_DiscoveryResponseError, ValidationError),
                )
                or failure_class == "response_contract"
            )
            retryable = (
                response_failure
                or isinstance(exc, TransientError)
                or failure_class == "transport_transient"
            )
            if not retryable:
                if isinstance(exc, NbaDbError):
                    raise
                raise ExtractionError(f"{label}: extraction failed") from exc

            overall_attempt = attempt_offset + attempt
            failure = (
                f"response shape: {type(exc).__name__}" if response_failure else type(exc).__name__
            )
            if attempt < attempts:
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 1)
                logger.warning(
                    "{}: attempt {}/{} failed ({}), retrying in {:.0f}s",
                    label,
                    overall_attempt,
                    attempt_total,
                    failure,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "{}: attempt {}/{} failed ({})",
                    label,
                    overall_attempt,
                    attempt_total,
                    failure,
                )
                if response_failure:
                    if isinstance(exc, _DiscoveryResponseError):
                        raise
                    raise _DiscoveryResponseError(f"{label}: response validation failed") from exc
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
        *,
        on_combo_covered: Callable[[tuple[str, str], pl.DataFrame], None] | None = None,
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

        combos = list(
            dict.fromkeys(
                (season, season_type) for season in seasons for season_type in season_types
            )
        )
        requested_combos = frozenset(combos)
        upstream_unavailable_combos = {
            combo: reason
            for combo in combos
            if (reason := _season_type_unavailable_reason(*combo)) is not None
        }
        executable_combos = [combo for combo in combos if combo not in upstream_unavailable_combos]
        if on_progress is not None:
            on_progress.start_pattern(f"game discovery ({len(combos)} combos)", len(combos))

        extractor_cls = self._registry.get("league_game_log")
        semaphore = asyncio.Semaphore(self._discovery_concurrency)

        async def _fetch(
            season: str,
            season_type: str,
            *,
            progress: _PatternProgress | None,
            use_semaphore: bool,
            phase: str,
            attempts: int,
            attempt_offset: int,
        ) -> tuple[tuple[str, str], pl.DataFrame | None, _DiscoveryFailureKind | None]:
            label = f"league_game_log({season}, {season_type})"

            def _validate_response(df: pl.DataFrame) -> pl.DataFrame:
                required_columns = {"game_id", "game_date"}
                missing_columns = required_columns - set(df.columns)
                if missing_columns:
                    raise _DiscoveryResponseError(
                        f"missing required columns {sorted(missing_columns)}"
                    )
                if df.schema["game_id"] != pl.String:
                    raise _DiscoveryResponseError("game_id must be String")
                if df.schema["game_date"].base_type() not in {
                    pl.String,
                    pl.Date,
                    pl.Datetime,
                }:
                    raise _DiscoveryResponseError("game_date must be String, Date, or Datetime")
                if df.get_column("game_id").null_count() or (
                    not df.is_empty()
                    and df.select(pl.col("game_id").str.strip_chars().eq("").any()).item()
                ):
                    raise _DiscoveryResponseError("game_id must contain non-empty values")
                if df.get_column("game_date").null_count():
                    raise _DiscoveryResponseError("game_date must not contain nulls")
                if (
                    df.schema["game_date"] == pl.String
                    and not df.is_empty()
                    and df.select(pl.col("game_date").str.strip_chars().eq("").any()).item()
                ):
                    raise _DiscoveryResponseError("game_date must contain non-empty values")
                return df

            async def _run() -> tuple[
                tuple[str, str], pl.DataFrame | None, _DiscoveryFailureKind | None
            ]:
                logger.info("{} game IDs: {}", phase, label)
                extractor = extractor_cls()
                request_params: dict[str, object] = {
                    "season": season,
                    "season_type": season_type,
                    "timeout": (
                        _RECOVERY_DISCOVERY_TIMEOUT
                        if phase == "recovering"
                        else _CONCURRENT_DISCOVERY_TIMEOUT
                    ),
                }
                try:
                    df = await _extract_with_retry(
                        extractor,
                        label,
                        _validate_response,
                        attempt_offset,
                        self._retry_attempts,
                        thread_pool=self._thread_pool,
                        attempts=attempts,
                        base_delay=self._retry_delay,
                        rate_limiter=self._rate_limiter,
                        **request_params,
                    )
                except _DiscoveryResponseError:
                    failure: _DiscoveryFailureKind = "response"
                except TransientError:
                    failure = "transport"
                except NbaDbError:
                    failure = "permanent"
                else:
                    if progress is not None:
                        progress.advance_pattern(success=True)
                    if phase == "recovering":
                        logger.info("recovered game log for {}", label)
                    combo = (season, season_type)
                    if on_combo_covered is not None:
                        on_combo_covered(combo, df)
                    return combo, df, None

                if progress is not None:
                    progress.advance_pattern(success=False)
                logger.error(
                    "{} game log failed for {} ({})",
                    phase,
                    label,
                    failure,
                )
                return (season, season_type), None, failure

            if not use_semaphore:
                return await _run()

            async with semaphore:
                return await _run()

        combo_frames: dict[tuple[str, str], pl.DataFrame] = {}
        for combo, reason in upstream_unavailable_combos.items():
            empty_frame = pl.DataFrame(schema={"game_id": pl.String, "game_date": pl.String})
            combo_frames[combo] = empty_frame
            if on_combo_covered is not None:
                on_combo_covered(combo, empty_frame)
            if on_progress is not None:
                on_progress.advance_pattern(success=True)
            logger.info(
                "classified game discovery scope {} as upstream unavailable ({})",
                combo,
                reason,
            )

        initial_results = await asyncio.gather(
            *[
                _fetch(
                    season,
                    season_type,
                    progress=on_progress,
                    use_semaphore=True,
                    phase="discovering",
                    attempts=self._concurrent_retry_attempts,
                    attempt_offset=0,
                )
                for season, season_type in executable_combos
            ]
        )

        def _record_combo(combo: tuple[str, str], df: pl.DataFrame) -> None:
            combo_frames[combo] = df

        for combo, df, failure in initial_results:
            if failure is None and df is not None:
                _record_combo(combo, df)
        failures: dict[tuple[str, str], _DiscoveryFailureKind] = {}
        for combo, _df, failure in initial_results:
            if failure is not None:
                failures[combo] = failure

        retryable_combos = [
            combo for combo in executable_combos if failures.get(combo) in {"transport", "response"}
        ]
        remaining_attempts = {
            combo: self._retry_attempts - self._concurrent_retry_attempts
            for combo in retryable_combos
        }

        broad_failure_kinds = set(failures.values())
        broad_systemic_failure = (
            len(executable_combos) > 1
            and len(failures) == len(executable_combos)
            and broad_failure_kinds <= {"transport", "response"}
        )
        if broad_systemic_failure:
            for systemic_failure_kind in ("transport", "response"):
                affected_combos = [
                    combo
                    for combo in retryable_combos
                    if failures.get(combo) == systemic_failure_kind
                ]
                if not affected_combos:
                    continue
                canary = affected_combos[0]
                canary_attempts = min(
                    _BROAD_OUTAGE_CANARY_ATTEMPTS_CAP,
                    remaining_attempts[canary],
                )
                if canary_attempts <= 0:
                    continue
                logger.warning(
                    (
                        "checking broad game discovery {} failure with {} "
                        "bounded canary attempts: {}"
                    ),
                    systemic_failure_kind,
                    canary_attempts,
                    canary,
                )
                _combo, df, failure = await _fetch(
                    *canary,
                    progress=None,
                    use_semaphore=False,
                    phase="canary",
                    attempts=canary_attempts,
                    attempt_offset=self._concurrent_retry_attempts,
                )
                remaining_attempts[canary] -= canary_attempts
                if failure is None and df is not None:
                    _record_combo(canary, df)
                    failures.pop(canary, None)
                    retryable_combos.remove(canary)
                elif failure == "permanent":
                    failures[canary] = failure
                    retryable_combos.remove(canary)
                elif failure in {"transport", "response"}:
                    failures[canary] = failure
                    logger.error(
                        (
                            "game discovery {} canary failed; skipping recovery for {} "
                            "systemically affected {} scopes"
                        ),
                        failure,
                        len(affected_combos),
                        systemic_failure_kind,
                    )
                    affected_set = set(affected_combos)
                    retryable_combos = [
                        combo for combo in retryable_combos if combo not in affected_set
                    ]
                elif failure is not None:
                    failures[canary] = failure

        recovery_combos = [
            combo for combo in retryable_combos if remaining_attempts.get(combo, 0) > 0
        ]
        if recovery_combos:
            logger.warning(
                "retrying {} failed game discovery combos sequentially within remaining budgets",
                len(recovery_combos),
            )
            if on_progress is not None:
                on_progress.start_pattern(
                    f"game discovery recovery ({len(recovery_combos)} combos)",
                    len(recovery_combos),
                )

            for season, season_type in recovery_combos:
                combo = (season, season_type)
                attempts = remaining_attempts[combo]
                _combo, df, failure = await _fetch(
                    season,
                    season_type,
                    progress=on_progress,
                    use_semaphore=False,
                    phase="recovering",
                    attempts=attempts,
                    attempt_offset=self._retry_attempts - attempts,
                )
                if failure is None and df is not None:
                    _record_combo(combo, df)
                    failures.pop(combo, None)
                elif failure is not None:
                    failures[combo] = failure

        unresolved_combos = [combo for combo in combos if combo not in combo_frames]
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
                requested_combos=requested_combos,
                covered_combos=frozenset(),
                failures_by_combo=dict(failures),
                upstream_unavailable_combos=upstream_unavailable_combos,
            )

        non_empty_frames = [df for df in combo_frames.values() if not df.is_empty()]
        combined = (
            pl.concat(non_empty_frames, how="diagonal_relaxed")
            if non_empty_frames
            else next(iter(combo_frames.values())).clone()
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
        return GameDiscoveryResult(
            game_ids=game_ids,
            raw=combined,
            requested_combos=requested_combos,
            covered_combos=frozenset(combo_frames),
            frames_by_combo=combo_frames,
            failures_by_combo=dict(failures),
            upstream_unavailable_combos=upstream_unavailable_combos,
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
        season: str | None,
        params: dict[str, object],
    ) -> PlayerIdDiscoveryResult:
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
        except _DiscoveryResponseError:
            failure_kind: _DiscoveryFailureKind = "response"
        except TransientError:
            failure_kind = "transport"
        except NbaDbError as exc:
            failure_kind = "permanent"
            logger.error(
                "failed to discover {} IDs for {}: {}",
                staging_key,
                season or "all seasons",
                type(exc).__name__,
            )
        else:
            failure_kind = "no_data"
            if df.is_empty():
                logger.warning("no {} data returned for {}", staging_key, season or "all seasons")
            elif "person_id" not in df.columns:
                failure_kind = "response"
                logger.warning(
                    "{} missing person_id column for {}",
                    staging_key,
                    season or "all seasons",
                )
            else:
                filtered, usable = _filter_player_year_window(df, season)
                if not usable:
                    failure_kind = "response"
                    logger.warning(
                        "{} has no usable from_year/to_year metadata for {}; "
                        "cannot season-scope IDs",
                        staging_key,
                        season,
                    )
                else:
                    entity_ids: list[int] = (
                        filtered.get_column("person_id").unique().sort().to_list()
                    )
                    if entity_ids:
                        logger.info(
                            "discovered {} {} IDs for {}",
                            len(entity_ids),
                            staging_key,
                            season or "all seasons",
                        )
                        return PlayerIdDiscoveryResult(
                            ids=entity_ids,
                            requested_season=season,
                            source=staging_key,
                        )
                    logger.warning(
                        "no season-scoped {} IDs returned for {}",
                        staging_key,
                        season or "all seasons",
                    )

        return PlayerIdDiscoveryResult(
            ids=[],
            requested_season=season,
            source=staging_key,
            failure_kind=failure_kind,
            failures_by_source={staging_key: failure_kind},
        )

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

    async def discover_all_player_ids_result(
        self,
        season: str | None = None,
    ) -> PlayerIdDiscoveryResult:
        """Get structured ALL-player discovery evidence for one season or all history.

        Use this for ``run_init()`` to ensure historical players are included
        in player-level extraction. The legacy list-returning method delegates
        here so existing callers retain their interface.
        """
        common_result = await self._discover_season_player_ids_from_endpoint(
            endpoint="common_all_players",
            staging_key="common_all_players",
            season=season,
            params={
                **({"allow_static_fallback": False} if season else {}),
                "timeout": _CONCURRENT_DISCOVERY_TIMEOUT,
            },
        )
        if common_result.is_complete or common_result.failure_kind == "no_data" or not season:
            return common_result

        logger.warning(
            "falling back to player_index for season-scoped player discovery ({})",
            season,
        )
        player_index_result = await self._discover_season_player_ids_from_endpoint(
            endpoint="player_index",
            staging_key="player_index",
            season=season,
            params={"season": season, "timeout": _CONCURRENT_DISCOVERY_TIMEOUT},
        )
        if player_index_result.is_complete:
            return player_index_result

        failures_by_source = {
            **common_result.failures_by_source,
            **player_index_result.failures_by_source,
        }
        failure_kind = _dominant_failure_kind(failures_by_source)
        logger.error(
            "failed to season-scope player discovery for {} ({})",
            season,
            failure_kind,
        )
        return PlayerIdDiscoveryResult(
            ids=[],
            requested_season=season,
            failure_kind=failure_kind,
            failures_by_source=failures_by_source,
        )

    async def discover_all_player_ids(self, season: str | None = None) -> list[int]:
        """Get ALL player IDs while preserving the historical list-returning API."""
        result = await self.discover_all_player_ids_result(season=season)
        return result.ids

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
        """Get exact player/team affiliations from season-type game logs.

        ``common_all_players`` exposes one team per player and loses traded or
        otherwise multi-team affiliations. ``player_game_logs`` returns every
        player game with both identifiers, so one request per season/type can be
        deduplicated into the complete set of affiliations that can produce video.
        """
        import polars as pl

        if not seasons:
            return PlayerTeamSeasonDiscoveryResult(
                params=[],
                requested_pairs=frozenset(),
                covered_pairs=frozenset(),
            )
        unique_seasons = list(dict.fromkeys(seasons))
        resolved_season_types = list(dict.fromkeys(season_types or ["Regular Season"]))
        ordered_pairs = list(
            dict.fromkeys(
                (season, season_type)
                for season in unique_seasons
                for season_type in resolved_season_types
            )
        )
        requested_pairs = frozenset(ordered_pairs)
        upstream_unavailable_pairs = {
            pair: reason
            for pair in requested_pairs
            if (reason := _season_type_unavailable_reason(*pair)) is not None
        }
        executable_pairs = [
            pair for pair in ordered_pairs if pair not in upstream_unavailable_pairs
        ]

        extractor_cls = self._registry.get("player_game_logs")
        semaphore = asyncio.Semaphore(self._discovery_concurrency)

        async def _fetch(
            season: str,
            season_type: str,
            *,
            use_semaphore: bool,
            phase: str,
            attempts: int,
            attempt_offset: int,
        ) -> tuple[tuple[str, str], pl.DataFrame | None, _DiscoveryFailureKind | None]:
            pair = (season, season_type)
            label = f"player_game_logs({season}, {season_type})"

            def _validate_response(df: pl.DataFrame) -> pl.DataFrame:
                required = {"player_id", "team_id"}
                missing = required - set(df.columns)
                if missing:
                    raise _DiscoveryResponseError(f"missing columns {sorted(missing)}")

                normalized = (
                    df.select(
                        pl.col("player_id").cast(pl.Int64, strict=False),
                        pl.col("team_id").cast(pl.Int64, strict=False).alias("team_id"),
                    )
                    .filter(
                        pl.col("player_id").is_not_null()
                        & (pl.col("player_id") > 0)
                        & pl.col("team_id").is_not_null()
                        & (pl.col("team_id") > 0)
                    )
                    .with_columns(
                        pl.lit(season).alias("season"),
                        pl.lit(season_type).alias("season_type"),
                    )
                    .unique()
                )
                if not df.is_empty() and normalized.is_empty():
                    raise _DiscoveryResponseError("no valid player/team pairs")
                return normalized

            async def _run() -> tuple[
                tuple[str, str], pl.DataFrame | None, _DiscoveryFailureKind | None
            ]:
                logger.info("{} player/team pairs: {}", phase, label)
                extractor = extractor_cls()
                request_params: dict[str, object] = {
                    "season": season,
                    "season_type": season_type,
                    "timeout": (
                        _RECOVERY_DISCOVERY_TIMEOUT
                        if phase == "recovering"
                        else _CONCURRENT_DISCOVERY_TIMEOUT
                    ),
                }
                try:
                    df = await _extract_with_retry(
                        extractor,
                        label,
                        _validate_response,
                        attempt_offset,
                        self._retry_attempts,
                        thread_pool=self._thread_pool,
                        attempts=attempts,
                        base_delay=self._retry_delay,
                        rate_limiter=self._rate_limiter,
                        **request_params,
                    )
                except _DiscoveryResponseError:
                    failure: _DiscoveryFailureKind = "response"
                except TransientError:
                    failure = "transport"
                except NbaDbError:
                    failure = "permanent"
                else:
                    if phase == "recovering":
                        logger.info("recovered player/team pairs for {}", label)
                    return pair, df, None

                logger.error(
                    "{} player/team discovery failed for {} ({})",
                    phase,
                    label,
                    failure,
                )
                return pair, None, failure

            if not use_semaphore:
                return await _run()

            async with semaphore:
                return await _run()

        pair_frames: dict[tuple[str, str], pl.DataFrame] = {
            pair: pl.DataFrame(
                schema={
                    "player_id": pl.Int64,
                    "team_id": pl.Int64,
                    "season": pl.String,
                    "season_type": pl.String,
                }
            )
            for pair in upstream_unavailable_pairs
        }
        for pair, reason in upstream_unavailable_pairs.items():
            logger.info(
                "classified player/team discovery scope {} as upstream unavailable ({})",
                pair,
                reason,
            )

        initial_results = await asyncio.gather(
            *[
                _fetch(
                    season,
                    season_type,
                    use_semaphore=True,
                    phase="discovering",
                    attempts=self._concurrent_retry_attempts,
                    attempt_offset=0,
                )
                for season, season_type in executable_pairs
            ]
        )

        pair_frames.update(
            {
                pair: df
                for pair, df, failure in initial_results
                if failure is None and df is not None
            }
        )
        failures: dict[tuple[str, str], _DiscoveryFailureKind] = {}
        for pair, _df, failure in initial_results:
            if failure is not None:
                failures[pair] = failure

        retryable_pairs = [
            pair for pair in executable_pairs if pair in failures and failures[pair] != "permanent"
        ]
        remaining_attempts = {
            pair: self._retry_attempts - self._concurrent_retry_attempts for pair in retryable_pairs
        }

        broad_failure_kinds = set(failures.values())
        broad_systemic_failure = (
            len(executable_pairs) > 1
            and len(failures) == len(executable_pairs)
            and broad_failure_kinds <= {"transport", "response"}
        )
        if broad_systemic_failure:
            for systemic_failure_kind in ("transport", "response"):
                affected_pairs = [
                    pair for pair in retryable_pairs if failures.get(pair) == systemic_failure_kind
                ]
                if not affected_pairs:
                    continue
                canary = affected_pairs[0]
                canary_attempts = min(
                    _BROAD_OUTAGE_CANARY_ATTEMPTS_CAP,
                    remaining_attempts[canary],
                )
                if canary_attempts <= 0:
                    continue
                logger.warning(
                    (
                        "checking broad player/team discovery {} failure with "
                        "{} bounded canary attempts: {}"
                    ),
                    systemic_failure_kind,
                    canary_attempts,
                    canary,
                )
                _pair, df, failure = await _fetch(
                    *canary,
                    use_semaphore=False,
                    phase="canary",
                    attempts=canary_attempts,
                    attempt_offset=self._concurrent_retry_attempts,
                )
                remaining_attempts[canary] -= canary_attempts
                if failure is None and df is not None:
                    pair_frames[canary] = df
                    failures.pop(canary, None)
                    retryable_pairs.remove(canary)
                elif failure == "permanent":
                    failures[canary] = failure
                    retryable_pairs.remove(canary)
                elif failure in {"transport", "response"}:
                    failures[canary] = failure
                    logger.error(
                        (
                            "player/team discovery {} canary failed; skipping "
                            "recovery for {} systemically affected {} scopes"
                        ),
                        failure,
                        len(affected_pairs),
                        systemic_failure_kind,
                    )
                    affected_set = set(affected_pairs)
                    retryable_pairs = [pair for pair in retryable_pairs if pair not in affected_set]
                elif failure is not None:
                    failures[canary] = failure

        recovery_pairs = [pair for pair in retryable_pairs if remaining_attempts.get(pair, 0) > 0]
        if recovery_pairs:
            logger.warning(
                (
                    "retrying {} failed player/team discovery scopes sequentially "
                    "within remaining budgets"
                ),
                len(recovery_pairs),
            )
            for pair in recovery_pairs:
                attempts = remaining_attempts[pair]
                _pair, df, failure = await _fetch(
                    *pair,
                    use_semaphore=False,
                    phase="recovering",
                    attempts=attempts,
                    attempt_offset=self._retry_attempts - attempts,
                )
                if failure is None and df is not None:
                    pair_frames[pair] = df
                    failures.pop(pair, None)
                elif failure is not None:
                    failures[pair] = failure

        unresolved_pairs = [pair for pair in executable_pairs if pair not in pair_frames]
        if unresolved_pairs:
            logger.warning(
                "player/team discovery finished with {} unrecovered scopes: {}",
                len(unresolved_pairs),
                unresolved_pairs,
            )

        if not pair_frames:
            return PlayerTeamSeasonDiscoveryResult(
                params=[],
                requested_pairs=requested_pairs,
                covered_pairs=frozenset(),
                failures_by_pair=dict(failures),
                upstream_unavailable_pairs=upstream_unavailable_pairs,
            )

        non_empty_frames = [df for df in pair_frames.values() if not df.is_empty()]
        combined = (
            pl.concat(non_empty_frames, how="vertical_relaxed")
            .unique(subset=["player_id", "team_id", "season", "season_type"])
            .sort(["season", "season_type", "player_id", "team_id"])
            if non_empty_frames
            else pl.DataFrame(
                schema={
                    "player_id": pl.Int64,
                    "team_id": pl.Int64,
                    "season": pl.String,
                    "season_type": pl.String,
                }
            )
        )
        params: list[dict[str, int | str]] = [
            {
                "player_id": int(row["player_id"]),
                "team_id": int(row["team_id"]),
                "season": str(row["season"]),
                "season_type": str(row["season_type"]),
            }
            for row in combined.to_dicts()
        ]
        pair_order = {pair: index for index, pair in enumerate(ordered_pairs)}
        params.sort(
            key=lambda row: (
                pair_order[(str(row["season"]), str(row["season_type"]))],
                int(row["player_id"]),
                int(row["team_id"]),
            )
        )
        logger.info("discovered {} player/team/season/type combos", len(params))
        return PlayerTeamSeasonDiscoveryResult(
            params=params,
            requested_pairs=requested_pairs,
            covered_pairs=frozenset(pair_frames),
            failures_by_pair=dict(failures),
            upstream_unavailable_pairs=upstream_unavailable_pairs,
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
