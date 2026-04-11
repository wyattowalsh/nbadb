from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from aiolimiter import AsyncLimiter
from loguru import logger

from nbadb.extract.base import BaseExtractor, is_retryable_error
from nbadb.orchestrate.resilience import _AdaptiveThrottle, _CircuitBreaker, _LatencyTracker
from nbadb.orchestrate.staging_map import StagingEntry, get_multi_entries

if TYPE_CHECKING:
    from collections.abc import Callable

    import polars as pl

    from nbadb.core.config import NbaDbSettings
    from nbadb.extract.registry import EndpointRegistry
    from nbadb.orchestrate.journal import PipelineJournal


# ── sync helpers ──────────────────────────────────────────────


def _drive_coroutine(coro: object) -> object:
    """Drive a coroutine that does no real async I/O to completion.

    All nba_api extractors are ``async def`` but perform only synchronous
    HTTP work internally.  This avoids the overhead of creating a fresh
    event loop per call (the old ``asyncio.run()`` pattern).

    Raises ``RuntimeError`` if the coroutine actually yields (i.e. does
    real async I/O), so any future extractor that adds a genuine
    ``await`` will fail loudly rather than silently misbehave.

    IMPORTANT: All BaseExtractor subclasses must perform only synchronous
    I/O inside ``extract()`` / ``extract_all()``.  They are ``async def``
    for interface uniformity but must NOT contain real ``await`` expressions.
    If genuine async I/O is needed in the future, use
    ``asyncio.to_thread`` in the caller instead.
    """
    try:
        coro.send(None)  # type: ignore[union-attr]
    except StopIteration as exc:
        return exc.value
    else:
        raise RuntimeError("coroutine yielded unexpectedly; it may perform real async I/O")
    finally:
        coro.close()


def _sync_extract(extractor: object, **kwargs: object) -> pl.DataFrame:
    """Call extractor.extract() synchronously (for asyncio.to_thread)."""
    return _drive_coroutine(extractor.extract(**kwargs))  # type: ignore[union-attr,return-value]


def _sync_extract_all(extractor: object, **kwargs: object) -> list[pl.DataFrame]:
    """Call extractor.extract_all() synchronously."""
    return _drive_coroutine(extractor.extract_all(**kwargs))  # type: ignore[union-attr,return-value]


@dataclass(frozen=True, slots=True)
class _DeferredExtraction:
    endpoint_name: str
    params: dict[str, object]
    wait_seconds: float
    staging_key: str | None = None


class _CircuitBreakerTimeoutError(RuntimeError):
    """Raised when an endpoint remains breaker-open past the configured budget."""


class ExtractorRunner:
    """Runs extractors concurrently with semaphore gating and journal
    tracking.

    Supports resume (skips already-extracted via journal), endpoint
    deduplication for ``use_multi`` entries, and chunked processing
    for game-level extractions.
    """

    _LATE_RECOVERY_ENDPOINTS = frozenset({"scoreboard_v2", "scoreboard_v3"})

    def __init__(
        self,
        registry: EndpointRegistry,
        settings: NbaDbSettings,
        journal: PipelineJournal,
        rate_limit: float = 10.0,
        progress: object | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._journal = journal
        self._progress = progress
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._rate_limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
        self._endpoint_rate_limiters: dict[str, AsyncLimiter] = {}
        self._adaptive = _AdaptiveThrottle(
            base_rate=rate_limit,
            min_rate=getattr(settings, "adaptive_rate_min", 1.0),
            recovery_threshold=getattr(settings, "adaptive_rate_recovery", 50),
        )
        try:
            self._thread_pool = ThreadPoolExecutor(max_workers=settings.thread_pool_size)
        except (AttributeError, ValueError, TypeError) as exc:
            logger.warning("thread_pool_size misconfigured, falling back to 4: {}", exc)
            self._thread_pool = ThreadPoolExecutor(max_workers=4)
        self._circuit_breaker = _CircuitBreaker(
            threshold=getattr(settings, "circuit_breaker_threshold", 10),
            recovery_seconds=getattr(settings, "circuit_breaker_recovery", 120.0),
        )
        self._latency = _LatencyTracker(
            window_size=getattr(settings, "latency_window_size", 200),
        )
        # Cache for multi-endpoint results: (endpoint, params_json) -> DFs
        self._multi_cache: dict[tuple[str, str], list[pl.DataFrame]] = {}
        # Count of extractions skipped because already done in journal
        self.skipped: int = 0
        # Count only journal-driven skips for the current run.
        self.skipped_due_to_journal: int = 0
        # Count of extraction calls scheduled after runtime eligibility checks.
        self.planned_calls: int = 0
        # Count of extraction calls that failed in the current run after retries.
        self.failed_current_run: int = 0

    def shutdown(self) -> None:
        """Shut down the thread pool to release worker threads."""
        self._thread_pool.shutdown(wait=False)

    def log_latency_summary(self) -> None:
        """Log the top 5 slowest endpoints by p95 latency."""
        sums = self._latency.all_summaries()
        if not sums:
            return
        sorted_eps = sorted(sums.items(), key=lambda kv: kv[1]["p95"], reverse=True)
        logger.info("Latency Summary (Top 5 slowest endpoints by p95):")
        for ep, s in sorted_eps[:5]:
            logger.info(
                "  {:<25} | p50: {:5.2f}s | p95: {:5.2f}s | p99: {:5.2f}s | count: {}",
                ep,
                s["p50"],
                s["p95"],
                s["p99"],
                int(s["count"]),
            )

    async def __aenter__(self) -> ExtractorRunner:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.shutdown()

    def __del__(self) -> None:
        self._thread_pool.shutdown(wait=False)

    # ── public API ─────────────────────────────────────────────

    async def run_pattern(
        self,
        pattern: str,
        param_sets: list[dict],
        entries: list[StagingEntry],
        on_progress: object | None = None,
        *,
        skip_items: set[tuple[str, str]] | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Extract all *entries* across every *param_set*.

        Returns ``{staging_key: concatenated_df}`` for all entries
        that produced data.  Also increments ``self.skipped`` for
        each param set that was already recorded in the journal.
        """

        multi_entries, single_entries, multi_by_ep = self._classify_entries(entries)
        accum: dict[str, list[pl.DataFrame]] = {e.staging_key: [] for e in entries}
        single_by_key = {
            (entry.endpoint_name, entry.staging_key): entry for entry in single_entries
        }

        if pattern == "game":
            chunk_size = self._settings.pbp_chunk_size
        else:
            chunk_size = self._settings.default_chunk_size
        for chunk_start in range(0, max(len(param_sets), 1), chunk_size):
            chunk = param_sets[chunk_start : chunk_start + chunk_size]
            if not chunk:
                break

            already_done = self._prefetch_done(single_entries, multi_by_ep, chunk)
            tasks = self._build_chunk_tasks(
                single_entries,
                multi_by_ep,
                chunk,
                already_done,
                on_progress=on_progress,
                skip_items=skip_items,
            )

            results = await asyncio.gather(*tasks, return_exceptions=True)
            delayed = [r for r in results if isinstance(r, _DeferredExtraction)]
            immediate = [r for r in results if not isinstance(r, _DeferredExtraction)]
            self._collect_results(immediate, accum, on_progress)
            if delayed:
                replay_results = await self._replay_deferred_chunk(
                    delayed,
                    single_by_key=single_by_key,
                    multi_by_ep=multi_by_ep,
                    on_progress=on_progress,
                )
                replay_deferred = [r for r in replay_results if isinstance(r, _DeferredExtraction)]
                if replay_deferred:
                    logger.error(
                        "late recovery replay returned deferred extractions unexpectedly: {}",
                        len(replay_deferred),
                    )
                self._collect_results(
                    [r for r in replay_results if not isinstance(r, _DeferredExtraction)],
                    accum,
                    on_progress,
                )

            # HR-A-007: free multi-endpoint cache between chunks to
            # prevent unbounded memory growth on large historical runs.
            self._multi_cache.clear()

        return self._concat_accum(accum)

    # ── run_pattern decomposition ──────────────────────────────

    @staticmethod
    def _classify_entries(
        entries: list[StagingEntry],
    ) -> tuple[list[StagingEntry], list[StagingEntry], dict[str, list[StagingEntry]]]:
        """Split entries into multi vs single and group multi by endpoint."""
        multi_groups = get_multi_entries()
        multi_entries: list[StagingEntry] = []
        single_entries: list[StagingEntry] = []
        for entry in entries:
            if entry.use_multi and entry.endpoint_name in multi_groups:
                multi_entries.append(entry)
            else:
                single_entries.append(entry)

        multi_by_ep: dict[str, list[StagingEntry]] = {}
        for entry in multi_entries:
            multi_by_ep.setdefault(entry.endpoint_name, []).append(entry)

        return multi_entries, single_entries, multi_by_ep

    def _prefetch_done(
        self,
        single_entries: list[StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        chunk: list[dict],
    ) -> set[tuple[str, str]]:
        """Batch-prefetch already-done items for this chunk (HR-B-008)."""
        batch_items: list[tuple[str, str]] = []
        for entry in single_entries:
            for params in chunk:
                batch_items.append((entry.endpoint_name, json.dumps(params, sort_keys=True)))
        for ep_name in multi_by_ep:
            for params in chunk:
                batch_items.append((ep_name, json.dumps(params, sort_keys=True)))
        return self._journal.was_extracted_batch(batch_items) if batch_items else set()

    @staticmethod
    def _season_year(params: dict) -> int | None:
        """Extract the integer season year from param sets.

        Handles formats:
        - ``"2024-25"`` → 2024
        - ``"2024"`` → 2024
        - ``"0024800127"`` → 1948
        - ``"0020000730"`` → 2000

        Returns ``None`` when no season hint can be derived.
        """
        season = params.get("season")
        if season is not None:
            try:
                return int(str(season)[:4])
            except (ValueError, TypeError):
                return None
        game_id = params.get("game_id")
        game_id_str = str(game_id) if game_id is not None else ""
        if len(game_id_str) < 5 or not game_id_str[3:5].isdigit():
            return None
        season_suffix = int(game_id_str[3:5])
        if season_suffix <= 30:
            return 2000 + season_suffix
        return 1900 + season_suffix

    def _build_chunk_tasks(
        self,
        single_entries: list[StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        chunk: list[dict],
        already_done: set[tuple[str, str]],
        on_progress: object | None = None,
        skip_items: set[tuple[str, str]] | None = None,
    ) -> list[asyncio.Task[dict[str, pl.DataFrame] | _DeferredExtraction | None]]:
        """Create asyncio tasks for all entries in a chunk."""
        tasks: list[asyncio.Task[dict[str, pl.DataFrame] | _DeferredExtraction | None]] = []
        today = date.today()

        for entry in single_entries:
            for params in chunk:
                # Skip entries deprecated before today
                if entry.deprecated_after is not None and today > date.fromisoformat(
                    entry.deprecated_after
                ):
                    self.skipped += 1
                    if on_progress is not None:
                        on_progress.advance_pattern(success=True)  # type: ignore[union-attr]
                    continue
                # HR-A-014: skip entries whose min_season exceeds
                # the requested season — avoids fruitless API calls
                # for pre-tracking-era historical runs.
                sy = self._season_year(params)
                if entry.min_season is not None and sy is not None and sy < entry.min_season:
                    self.skipped += 1
                    if on_progress is not None:
                        on_progress.advance_pattern(success=True)  # type: ignore[union-attr]
                    continue
                self.planned_calls += 1
                tasks.append(
                    asyncio.create_task(
                        self._extract_single(
                            entry,
                            params,
                            already_done=already_done,
                            skip_items=skip_items,
                            on_progress=on_progress,
                            allow_late_recovery=True,
                        )
                    )
                )

        for ep_name, ep_entries in multi_by_ep.items():
            for params in chunk:
                # For multi-endpoint groups, filter entries down to those
                # eligible for this season and not deprecated.
                today = date.today()
                sy = self._season_year(params)
                eligible = [
                    e
                    for e in ep_entries
                    if (e.min_season is None or sy is None or sy >= e.min_season)
                    and (
                        e.deprecated_after is None
                        or today <= date.fromisoformat(e.deprecated_after)
                    )
                ]
                if not eligible:
                    self.skipped += len(ep_entries)
                    if on_progress is not None:
                        for _ in ep_entries:
                            on_progress.advance_pattern(success=True)  # type: ignore[union-attr]
                    continue
                self.planned_calls += 1
                tasks.append(
                    asyncio.create_task(
                        self._extract_multi(
                            ep_name,
                            eligible,
                            params,
                            already_done=already_done,
                            skip_items=skip_items,
                            on_progress=on_progress,
                            allow_late_recovery=True,
                        )
                    )
                )

        return tasks

    async def _replay_deferred_chunk(
        self,
        deferred: list[_DeferredExtraction],
        *,
        single_by_key: dict[tuple[str, str], StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        on_progress: object | None,
    ) -> list[dict[str, pl.DataFrame] | BaseException | _DeferredExtraction | None]:
        deduped: dict[tuple[str, str, str | None], _DeferredExtraction] = {}
        for item in deferred:
            params_json = json.dumps(item.params, sort_keys=True)
            key = (item.endpoint_name, params_json, item.staging_key)
            existing = deduped.get(key)
            if existing is None or item.wait_seconds > existing.wait_seconds:
                deduped[key] = item

        replay_items = list(deduped.values())
        wait_seconds = max(item.wait_seconds for item in replay_items)
        logger.warning(
            "replaying {} deferred date extractions after {:.1f}s cooldown",
            len(replay_items),
            wait_seconds,
        )
        await asyncio.sleep(wait_seconds)

        tasks: list[asyncio.Task[dict[str, pl.DataFrame] | _DeferredExtraction | None]] = []
        for item in replay_items:
            if item.staging_key is None:
                entries = multi_by_ep.get(item.endpoint_name)
                if not entries:
                    logger.error(
                        "late recovery missing multi entries for endpoint: {}",
                        item.endpoint_name,
                    )
                    continue
                tasks.append(
                    asyncio.create_task(
                        self._extract_multi(
                            item.endpoint_name,
                            entries,
                            item.params,
                            on_progress=on_progress,
                            allow_late_recovery=False,
                            late_recovery_replay=True,
                        )
                    )
                )
                continue

            entry = single_by_key.get((item.endpoint_name, item.staging_key))
            if entry is None:
                logger.error(
                    "late recovery missing single entry for endpoint {} staging {}",
                    item.endpoint_name,
                    item.staging_key,
                )
                continue
            tasks.append(
                asyncio.create_task(
                    self._extract_single(
                        entry,
                        item.params,
                        on_progress=on_progress,
                        allow_late_recovery=False,
                        late_recovery_replay=True,
                    )
                )
            )

        if not tasks:
            return []
        return await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _collect_results(
        results: list[dict[str, pl.DataFrame] | BaseException | None],
        accum: dict[str, list[pl.DataFrame]],
        on_progress: object | None,
    ) -> None:
        """Merge task results into the accumulator."""
        for result in results:
            if isinstance(result, BaseException):
                # Don't advance progress here — the task either already
                # advanced before raising or was never started.
                logger.error(
                    "extraction task failed: {}",
                    type(result).__name__,
                )
                continue
            if result is None:
                continue
            if not isinstance(result, dict):
                # Don't advance progress — unexpected type indicates a
                # programming error, not a countable extraction attempt.
                logger.error(
                    "unexpected extraction task result type: {}",
                    type(result).__name__,
                )
                continue
            # Compute rows for progress reporting
            rows = sum(df.shape[0] for key, df in result.items() if not df.is_empty())
            if on_progress is not None:
                on_progress.advance_pattern(success=True, rows=rows)  # type: ignore[union-attr]
            for key, df in result.items():
                if not df.is_empty():
                    accum[key].append(df)

    @staticmethod
    def _concat_accum(accum: dict[str, list[pl.DataFrame]]) -> dict[str, pl.DataFrame]:
        """Concatenate per-staging_key frames into final output."""
        import polars as pl

        output: dict[str, pl.DataFrame] = {}
        for key, frames in accum.items():
            if frames:
                if len(frames) > 1:
                    col_sets = [frozenset(f.columns) for f in frames]
                    if len(set(col_sets)) > 1:
                        all_cols = frozenset().union(*col_sets)
                        common = frozenset.intersection(*col_sets)
                        drift = all_cols - common
                        logger.warning(
                            "{}: schema drift detected across {} frames — divergent columns: {}",
                            key,
                            len(frames),
                            ", ".join(sorted(drift)),
                        )
                output[key] = pl.concat(frames, how="diagonal_relaxed")
                logger.info("{}: {} rows total", key, output[key].shape[0])
            else:
                logger.debug("{}: no data extracted", key)
        return output

    # ── private helpers ────────────────────────────────────────

    def _get_endpoint_rate_limiter(self, endpoint_name: str) -> AsyncLimiter | None:
        endpoint_limits = getattr(self._settings, "endpoint_rate_limits", {})
        if endpoint_name not in endpoint_limits:
            return None
        if endpoint_name not in self._endpoint_rate_limiters:
            self._endpoint_rate_limiters[endpoint_name] = AsyncLimiter(
                max_rate=endpoint_limits[endpoint_name],
                time_period=1.0,
            )
        return self._endpoint_rate_limiters[endpoint_name]

    def _get_semaphore(self, endpoint_name: str, category: str) -> asyncio.Semaphore:
        """Lazily create a semaphore for the given endpoint/category lane."""
        endpoint_limits = getattr(self._settings, "endpoint_semaphore_limits", {})
        key = endpoint_name if endpoint_name in endpoint_limits else category
        if key not in self._semaphores:
            limit = endpoint_limits.get(
                endpoint_name,
                self._settings.semaphore_tiers.get(
                    category,
                    self._settings.semaphore_tiers.get("default", 10),
                ),
            )
            self._semaphores[key] = asyncio.Semaphore(limit)
        return self._semaphores[key]

    def _prepare_extractor(self, extractor: object) -> None:
        """Prepare an extractor instance before extraction."""
        if not isinstance(extractor, BaseExtractor):
            return
        endpoint_timeouts = getattr(self._settings, "endpoint_request_timeouts", {})
        timeout = endpoint_timeouts.get(extractor.endpoint_name)
        if timeout is not None:
            extractor._request_timeout_override = timeout

    async def _wait_for_circuit_breaker(self, endpoint_name: str, params_json: str) -> None:
        max_wait = max(float(getattr(self._settings, "circuit_breaker_max_wait", 600.0)), 0.0)
        deadline = time.monotonic() + max_wait
        while self._circuit_breaker.is_open(endpoint_name):
            wait_seconds = max(self._circuit_breaker.retry_after(endpoint_name), 1.0)
            if max_wait > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.error(
                        "circuit breaker wait budget exhausted: {} [{}] ({:.1f}s)",
                        endpoint_name,
                        params_json,
                        max_wait,
                    )
                    raise _CircuitBreakerTimeoutError(endpoint_name)
                wait_seconds = min(wait_seconds, remaining)
            logger.debug(
                "circuit breaker OPEN, delaying: {} [{}] ({:.1f}s)",
                endpoint_name,
                params_json,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

    # Exception types that warrant a retry (transient network / rate-limit errors)
    _RETRYABLE_ERRORS: tuple[type[Exception], ...] = ()

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Return True if the exception is transient and worth retrying."""
        return is_retryable_error(exc)

    def _should_delay_replay(
        self,
        endpoint_name: str,
        params: dict[str, object] | None,
        exc: Exception | None,
        *,
        allow_late_recovery: bool,
    ) -> bool:
        if not allow_late_recovery or exc is None or not self._is_retryable(exc):
            return False
        if endpoint_name not in self._LATE_RECOVERY_ENDPOINTS:
            return False
        if params is None:
            return False
        return "game_date" in params

    def _late_recovery_wait_seconds(self, endpoint_name: str) -> float:
        backoff_wait = 0.0
        if self._settings.extract_retry_base_delay > 0:
            backoff_wait = self._settings.extract_retry_base_delay * (
                2 ** max(self._settings.extract_max_retries, 0)
            )
        return max(self._circuit_breaker.retry_after(endpoint_name), backoff_wait, 1.0)

    def _record_runtime_failure(
        self,
        endpoint_name: str,
        duration: float,
        *,
        isolated_rate: bool,
    ) -> None:
        self._journal.record_metric(endpoint_name, duration, 0, errors=1)
        self._circuit_breaker.record_failure(endpoint_name)
        tripped = self._circuit_breaker.tripped_endpoints()
        if tripped and self._progress is not None:
            self._progress.update_circuit_breakers(tripped)  # type: ignore[union-attr]
        self._latency.record(endpoint_name, duration)
        if not isolated_rate:
            new_rate = self._adaptive.record_failure()
            if new_rate is not None:
                self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
                logger.warning("adaptive rate: backing off to {:.1f} req/s", new_rate)
                if self._progress is not None:
                    self._progress.update_rate_info(  # type: ignore[union-attr]
                        self._adaptive.current_rate,
                        self._adaptive._base_rate,
                    )

    async def _run_with_journal(
        self,
        endpoint_name: str,
        params_json: str,
        *,
        params: dict[str, object] | None,
        fn: Callable,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
    ) -> pl.DataFrame | list[pl.DataFrame] | _DeferredExtraction | None:
        """Execute an extraction call with full journal tracking and retries.

        *fn* is a one-arg async-compatible callable ``fn(extractor)``
        that performs the actual extraction (params captured via
        closure). Returns ``None`` on terminal failure and a deferred
        replay sentinel when a retryable date extraction should cool
        down before one final in-run replay.
        """
        try:
            extractor_cls = self._registry.get(endpoint_name)
        except KeyError:
            logger.warning("no extractor for endpoint: {}", endpoint_name)
            return None

        max_retries = self._settings.extract_max_retries
        base_delay = self._settings.extract_retry_base_delay
        last_exc: Exception | None = None

        self._journal.record_start(endpoint_name, params_json)
        t0 = time.perf_counter()
        endpoint_limiter = self._get_endpoint_rate_limiter(endpoint_name)
        isolated_rate = endpoint_limiter is not None

        for attempt in range(max_retries + 1):
            extractor = extractor_cls()
            self._prepare_extractor(extractor)
            sem = self._get_semaphore(endpoint_name, extractor.category)
            rate_limiter = endpoint_limiter or self._rate_limiter

            try:
                await self._wait_for_circuit_breaker(endpoint_name, params_json)
                async with sem, rate_limiter:
                    result = await fn(extractor)
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries and self._is_retryable(exc):
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "extract retry {}/{}: {} [{}] -> {} (backoff {:.1f}s)",
                        attempt + 1,
                        max_retries,
                        endpoint_name,
                        params_json,
                        type(exc).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                # Non-retryable or retries exhausted
                break
            else:
                # Success
                duration = time.perf_counter() - t0
                if isinstance(result, list):
                    rows = sum(df.shape[0] for df in result if not df.is_empty())
                else:
                    rows = result.shape[0] if not result.is_empty() else 0
                self._journal.record_success(endpoint_name, params_json, rows)
                self._journal.record_metric(endpoint_name, duration, rows)
                self._circuit_breaker.record_success(endpoint_name)
                self._latency.record(endpoint_name, duration)
                if not isolated_rate:
                    new_rate = self._adaptive.record_success()
                    if new_rate is not None:
                        self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
                        logger.info("adaptive rate: recovering to {:.1f} req/s", new_rate)
                        if self._progress is not None:
                            self._progress.update_rate_info(  # type: ignore[union-attr]
                                self._adaptive.current_rate,
                                self._adaptive._base_rate,
                            )
                if attempt > 0:
                    logger.info(
                        "extract succeeded on retry {}: {} [{}]",
                        attempt,
                        endpoint_name,
                        params_json,
                    )
                return result

        # All retries exhausted
        duration = time.perf_counter() - t0
        exc_name = type(last_exc).__name__ if last_exc else "Unknown"
        if self._should_delay_replay(
            endpoint_name,
            params,
            last_exc,
            allow_late_recovery=allow_late_recovery,
        ):
            self._record_runtime_failure(
                endpoint_name,
                duration,
                isolated_rate=isolated_rate,
            )
            wait_seconds = self._late_recovery_wait_seconds(endpoint_name)
            logger.warning(
                "deferring retryable date extraction for late replay: {} [{}] -> {} ({:.1f}s)",
                endpoint_name,
                params_json,
                exc_name,
                wait_seconds,
            )
            return _DeferredExtraction(
                endpoint_name=endpoint_name,
                params=dict(params or {}),
                wait_seconds=wait_seconds,
            )

        self.failed_current_run += 1
        self._journal.record_failure(endpoint_name, params_json, exc_name)
        if not late_recovery_replay:
            self._record_runtime_failure(
                endpoint_name,
                duration,
                isolated_rate=isolated_rate,
            )
        logger.error(
            "extract failed after {} attempts: {} [{}] -> {}",
            max_retries + 1,
            endpoint_name,
            params_json,
            exc_name,
        )
        return None

    async def _extract_single(
        self,
        entry: StagingEntry,
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: object | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
    ) -> dict[str, pl.DataFrame] | _DeferredExtraction | None:
        """Extract a single (non-multi) entry for one param set."""
        params_json = json.dumps(params, sort_keys=True)

        # Resume: skip if already extracted (use pre-fetched set when available)
        journal_done = (
            (entry.endpoint_name, params_json) in already_done
            if already_done is not None
            else self._journal.was_extracted(entry.endpoint_name, params_json)
        )
        retry_skip = (
            (entry.endpoint_name, params_json) in skip_items if skip_items is not None else False
        )
        if journal_done or retry_skip:
            self.skipped += 1
            if journal_done:
                self.skipped_due_to_journal += 1
            if on_progress is not None:
                on_progress.record_skip()  # type: ignore[union-attr]
            logger.debug(
                "skip ({}): {} [{}]",
                "already done" if journal_done else "already attempted this run",
                entry.endpoint_name,
                params_json,
            )
            return None

        pool = self._thread_pool

        async def _do(ext: object) -> pl.DataFrame:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(pool, lambda: _sync_extract(ext, **params))

        df = await self._run_with_journal(
            entry.endpoint_name,
            params_json,
            params=params,
            fn=_do,
            allow_late_recovery=allow_late_recovery,
            late_recovery_replay=late_recovery_replay,
        )
        if df is None:
            return None
        if isinstance(df, _DeferredExtraction):
            return _DeferredExtraction(
                endpoint_name=df.endpoint_name,
                params=df.params,
                wait_seconds=df.wait_seconds,
                staging_key=entry.staging_key,
            )
        if isinstance(df, list):
            logger.error("unexpected list result for single extraction: {}", entry.endpoint_name)
            return None
        return {entry.staging_key: df}

    async def _extract_multi(
        self,
        endpoint_name: str,
        entries: list[StagingEntry],
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: object | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
    ) -> dict[str, pl.DataFrame] | _DeferredExtraction | None:
        """Extract a multi-result endpoint once and fan out by
        ``result_set_index``.

        Uses a cache so the same (endpoint, params) is only called
        once even if multiple staging entries reference it.
        """
        import polars as pl

        params_json = json.dumps(params, sort_keys=True)
        cache_key = (endpoint_name, params_json)

        # Single check: all entries share the same endpoint call
        # (use pre-fetched set when available)
        journal_done = (
            (endpoint_name, params_json) in already_done
            if already_done is not None
            else self._journal.was_extracted(endpoint_name, params_json)
        )
        retry_skip = (endpoint_name, params_json) in skip_items if skip_items is not None else False
        if journal_done or retry_skip:
            self.skipped += 1
            if journal_done:
                self.skipped_due_to_journal += 1
            if on_progress is not None:
                on_progress.record_skip()  # type: ignore[union-attr]
            logger.debug(
                "skip ({}): {} [{}]",
                "already done" if journal_done else "already attempted this run",
                endpoint_name,
                params_json,
            )
            return None

        # Check cache first
        if cache_key not in self._multi_cache:
            pool = self._thread_pool

            async def _do(ext: object) -> list[pl.DataFrame]:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(pool, lambda: _sync_extract_all(ext, **params))

            all_dfs = await self._run_with_journal(
                endpoint_name,
                params_json,
                params=params,
                fn=_do,
                allow_late_recovery=allow_late_recovery,
                late_recovery_replay=late_recovery_replay,
            )
            if all_dfs is None:
                return None
            if isinstance(all_dfs, _DeferredExtraction):
                return all_dfs
            if not isinstance(all_dfs, list):
                logger.error("unexpected non-list result for multi extraction: {}", endpoint_name)
                return None
            validated_dfs: list[pl.DataFrame] = []
            for df in all_dfs:
                if not isinstance(df, pl.DataFrame):
                    logger.error(
                        "unexpected element type for multi extraction {}: {}",
                        endpoint_name,
                        type(df).__name__,
                    )
                    return None
                validated_dfs.append(df)
            self._multi_cache[cache_key] = validated_dfs

        # Fan out results by result_set_index
        all_dfs = self._multi_cache[cache_key]
        output: dict[str, pl.DataFrame] = {}
        for entry in entries:
            idx = entry.result_set_index
            if idx < len(all_dfs):
                output[entry.staging_key] = all_dfs[idx]
            else:
                logger.warning(
                    "{}: result_set_index {} out of range (got {} sets)",
                    entry.staging_key,
                    idx,
                    len(all_dfs),
                )
                output[entry.staging_key] = pl.DataFrame()

        return output
