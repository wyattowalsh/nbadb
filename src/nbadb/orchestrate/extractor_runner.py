from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from aiolimiter import AsyncLimiter
from loguru import logger

from nbadb.orchestrate.staging_map import StagingEntry, get_multi_entries

# ── adaptive rate control ────────────────────────────────────


class _AdaptiveThrottle:
    """Track success/failure streaks and compute adaptive request rate.

    Backs off by 30% on each failure (down to *min_rate*).  After
    *recovery_threshold* consecutive successes, recovers by 10%
    (up to *base_rate*).
    """

    __slots__ = (
        "_base_rate",
        "_min_rate",
        "_current_rate",
        "_consecutive_success",
        "_recovery_threshold",
    )

    def __init__(
        self,
        base_rate: float,
        min_rate: float = 1.0,
        recovery_threshold: int = 50,
    ) -> None:
        self._base_rate = base_rate
        self._min_rate = min_rate
        self._current_rate = base_rate
        self._consecutive_success = 0
        self._recovery_threshold = recovery_threshold

    def record_success(self) -> float | None:
        """Record success.  Returns new rate if it changed, else ``None``."""
        self._consecutive_success += 1
        if (
            self._consecutive_success >= self._recovery_threshold
            and self._current_rate < self._base_rate
        ):
            old = self._current_rate
            self._current_rate = min(self._base_rate, self._current_rate * 1.1)
            self._consecutive_success = 0
            if abs(self._current_rate - old) > 0.05:
                return self._current_rate
        return None

    def record_failure(self) -> float | None:
        """Record failure.  Returns new rate if it changed, else ``None``."""
        self._consecutive_success = 0
        old = self._current_rate
        self._current_rate = max(self._min_rate, self._current_rate * 0.7)
        if abs(self._current_rate - old) > 0.05:
            return self._current_rate
        return None

    @property
    def current_rate(self) -> float:
        return self._current_rate


class _CircuitBreaker:
    """Per-endpoint circuit breaker — trips after *threshold* consecutive
    failures, preventing further API calls until *recovery_seconds* elapse.

    States:
    - CLOSED: normal operation, calls proceed
    - OPEN:   tripped, calls are rejected immediately
    - HALF-OPEN: after recovery window, one probe call is allowed
    """

    __slots__ = ("_threshold", "_recovery_seconds", "_state")

    def __init__(
        self,
        threshold: int = 10,
        recovery_seconds: float = 120.0,
    ) -> None:
        self._threshold = threshold
        self._recovery_seconds = recovery_seconds
        # state per endpoint: (consecutive_failures, tripped_at_monotonic | None)
        self._state: dict[str, tuple[int, float | None]] = {}

    def is_open(self, endpoint: str) -> bool:
        """Return True if the breaker is tripped and recovery hasn't elapsed."""
        failures, tripped_at = self._state.get(endpoint, (0, None))
        if tripped_at is None:
            return False
        if time.monotonic() - tripped_at >= self._recovery_seconds:
            # Half-open: allow one probe — reset failures to threshold-1
            self._state[endpoint] = (self._threshold - 1, None)
            return False
        return True

    def record_success(self, endpoint: str) -> None:
        """Reset the failure counter on success."""
        if endpoint in self._state:
            self._state[endpoint] = (0, None)

    def record_failure(self, endpoint: str) -> None:
        """Increment failure counter; trip if threshold reached."""
        failures, _ = self._state.get(endpoint, (0, None))
        failures += 1
        if failures >= self._threshold:
            self._state[endpoint] = (failures, time.monotonic())
            logger.warning(
                "circuit breaker OPEN for '{}' after {} consecutive failures "
                "(recovery in {:.0f}s)",
                endpoint,
                failures,
                self._recovery_seconds,
            )
        else:
            self._state[endpoint] = (failures, None)

    def tripped_endpoints(self) -> list[str]:
        """Return list of currently tripped endpoint names."""
        return [
            ep
            for ep, (_, tripped_at) in self._state.items()
            if tripped_at is not None and time.monotonic() - tripped_at < self._recovery_seconds
        ]


class _LatencyTracker:
    """Lightweight per-endpoint latency histogram.

    Stores the last *window_size* latencies and provides percentile queries.
    """

    __slots__ = ("_window_size", "_data")

    def __init__(self, window_size: int = 200) -> None:
        self._window_size = window_size
        self._data: dict[str, list[float]] = {}

    def record(self, endpoint: str, duration: float) -> None:
        """Record a latency sample."""
        buf = self._data.setdefault(endpoint, [])
        buf.append(duration)
        if len(buf) > self._window_size:
            buf.pop(0)

    def percentile(self, endpoint: str, p: float) -> float | None:
        """Return the *p*-th percentile (0–100) latency, or None if no data."""
        buf = self._data.get(endpoint)
        if not buf:
            return None
        s = sorted(buf)
        idx = int(len(s) * p / 100)
        return s[min(idx, len(s) - 1)]

    def summary(self, endpoint: str) -> dict[str, float] | None:
        """Return p50/p95/p99 for an endpoint, or None."""
        if endpoint not in self._data:
            return None
        return {
            "p50": self.percentile(endpoint, 50) or 0.0,
            "p95": self.percentile(endpoint, 95) or 0.0,
            "p99": self.percentile(endpoint, 99) or 0.0,
            "count": float(len(self._data[endpoint])),
        }

    def all_summaries(self) -> dict[str, dict[str, float]]:
        """Return latency summaries for all tracked endpoints."""
        return {
            ep: s for ep in self._data if (s := self.summary(ep)) is not None
        }


if TYPE_CHECKING:
    from collections.abc import Callable

    import polars as pl

    from nbadb.core.config import NbaDbSettings
    from nbadb.core.proxy import ProxyUrlProvider
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


def _assign_proxy(extractor: object, proxy_pool: ProxyUrlProvider | None) -> None:
    """Assign a proxy URL to an extractor if a pool is available."""
    if proxy_pool is not None:
        url = proxy_pool.get_proxy_url()
        extractor._proxy_url = url  # type: ignore[attr-defined]


class ExtractorRunner:
    """Runs extractors concurrently with semaphore gating and journal
    tracking.

    Supports resume (skips already-extracted via journal), endpoint
    deduplication for ``use_multi`` entries, and chunked processing
    for game-level extractions.
    """

    def __init__(
        self,
        registry: EndpointRegistry,
        settings: NbaDbSettings,
        journal: PipelineJournal,
        proxy_pool: ProxyUrlProvider | None = None,
        rate_limit: float = 10.0,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._journal = journal
        self._proxy_pool = proxy_pool
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._rate_limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
        self._adaptive = _AdaptiveThrottle(
            base_rate=rate_limit,
            min_rate=getattr(settings, "adaptive_rate_min", 1.0),
            recovery_threshold=getattr(settings, "adaptive_rate_recovery", 50),
        )
        self._thread_pool = ThreadPoolExecutor(max_workers=settings.thread_pool_size)
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
                ep, s['p50'], s['p95'], s['p99'], int(s['count'])
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
    ) -> dict[str, pl.DataFrame]:
        """Extract all *entries* across every *param_set*.

        Returns ``{staging_key: concatenated_df}`` for all entries
        that produced data.  Also increments ``self.skipped`` for
        each param set that was already recorded in the journal.
        """

        multi_entries, single_entries, multi_by_ep = self._classify_entries(entries)
        accum: dict[str, list[pl.DataFrame]] = {e.staging_key: [] for e in entries}

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
                on_progress,
            )

            results = await asyncio.gather(*tasks, return_exceptions=True)
            self._collect_results(results, accum, on_progress)

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

        Handles formats: ``"2024-25"`` → 2024, ``"2024"`` → 2024.
        Returns ``None`` when no season key is present (e.g. game-level).
        """
        season = params.get("season")
        if season is None:
            return None
        try:
            return int(str(season)[:4])
        except (ValueError, TypeError):
            return None

    def _build_chunk_tasks(
        self,
        single_entries: list[StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        chunk: list[dict],
        already_done: set[tuple[str, str]],
        on_progress: object | None,
    ) -> list[asyncio.Task[dict[str, pl.DataFrame] | None]]:
        """Create asyncio tasks for all entries in a chunk."""
        tasks: list[asyncio.Task[dict[str, pl.DataFrame] | None]] = []

        for entry in single_entries:
            for params in chunk:
                # HR-A-014: skip entries whose min_season exceeds
                # the requested season — avoids fruitless API calls
                # for pre-tracking-era historical runs.
                sy = self._season_year(params)
                if entry.min_season is not None and sy is not None and sy < entry.min_season:
                    self.skipped += 1
                    if on_progress is not None:
                        on_progress.advance_pattern(success=True)  # type: ignore[union-attr]
                    continue
                tasks.append(
                    asyncio.create_task(
                        self._extract_single(
                            entry,
                            params,
                            already_done=already_done,
                            on_progress=on_progress,
                        )
                    )
                )

        for ep_name, ep_entries in multi_by_ep.items():
            for params in chunk:
                # For multi-endpoint groups, filter entries down to those
                # eligible for this season.  If none remain, skip entirely.
                sy = self._season_year(params)
                eligible = [
                    e
                    for e in ep_entries
                    if e.min_season is None or sy is None or sy >= e.min_season
                ]
                if not eligible:
                    self.skipped += len(ep_entries)
                    if on_progress is not None:
                        for _ in ep_entries:
                            on_progress.advance_pattern(success=True)  # type: ignore[union-attr]
                    continue
                tasks.append(
                    asyncio.create_task(
                        self._extract_multi(
                            ep_name,
                            eligible,
                            params,
                            already_done=already_done,
                            on_progress=on_progress,
                        )
                    )
                )

        return tasks

    @staticmethod
    def _collect_results(
        results: list[dict[str, pl.DataFrame] | BaseException | None],
        accum: dict[str, list[pl.DataFrame]],
        on_progress: object | None,
    ) -> None:
        """Merge task results into the accumulator."""
        for result in results:
            if isinstance(result, BaseException):
                logger.error(
                    "extraction task failed: {}",
                    type(result).__name__,
                )
                if on_progress is not None:
                    on_progress.advance_pattern(success=False)  # type: ignore[union-attr]
                continue
            if result is None:
                continue
            if not isinstance(result, dict):
                logger.error(
                    "unexpected extraction task result type: {}",
                    type(result).__name__,
                )
                if on_progress is not None:
                    on_progress.advance_pattern(success=False)
                continue
            if on_progress is not None:
                on_progress.advance_pattern(success=True)  # type: ignore[union-attr]
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
                output[key] = pl.concat(frames, how="diagonal_relaxed")
                logger.info("{}: {} rows total", key, output[key].shape[0])
            else:
                logger.debug("{}: no data extracted", key)
        return output

    # ── private helpers ────────────────────────────────────────

    def _get_semaphore(self, category: str) -> asyncio.Semaphore:
        """Lazily create a semaphore for the given category."""
        if category not in self._semaphores:
            base_limit = self._settings.semaphore_tiers.get(
                category,
                self._settings.semaphore_tiers.get("default", 10),
            )
            if self._proxy_pool is not None:
                limit = max(
                    1,
                    int(base_limit * self._settings.proxy_semaphore_multiplier),
                )
            else:
                limit = base_limit
            self._semaphores[category] = asyncio.Semaphore(limit)
        return self._semaphores[category]

    def _prepare_extractor(self, extractor: object) -> None:
        """Set proxy URL on an extractor instance before extraction."""
        _assign_proxy(extractor, self._proxy_pool)

    # Exception types that warrant a retry (transient network / rate-limit errors)
    _RETRYABLE_ERRORS: tuple[type[Exception], ...] = ()

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Return True if the exception is transient and worth retrying."""
        # Import-safe: check by name so we don't require requests at import time
        name = type(exc).__name__
        if name in (
            "ReadTimeout",
            "ConnectTimeout",
            "ConnectionError",
            "ConnectionResetError",
            "JSONDecodeError",
            "ChunkedEncodingError",
            "RemoteDisconnected",
            "ProxyError",
            "TypeError",
        ):
            return True
        # KeyError / IndexError from nba_api when the API returns an error page
        # instead of JSON — transient when caused by rate limiting
        return name in ("KeyError", "IndexError")

    async def _run_with_journal(
        self,
        endpoint_name: str,
        params_json: str,
        *,
        fn: Callable,
    ) -> pl.DataFrame | list[pl.DataFrame] | None:
        """Execute an extraction call with full journal tracking and retries.

        *fn* is a one-arg async-compatible callable ``fn(extractor)``
        that performs the actual extraction (params captured via
        closure).  Returns ``None`` on failure after all retries exhausted.
        """
        # Circuit breaker: skip endpoint if it's been failing too much
        if self._circuit_breaker.is_open(endpoint_name):
            logger.debug(
                "circuit breaker OPEN, skipping: {} [{}]",
                endpoint_name,
                params_json,
            )
            return None

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

        for attempt in range(max_retries + 1):
            extractor = extractor_cls()
            self._prepare_extractor(extractor)
            sem = self._get_semaphore(extractor.category)

            try:
                async with self._rate_limiter, sem:
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
                new_rate = self._adaptive.record_success()
                if new_rate is not None:
                    self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
                    logger.info("adaptive rate: recovering to {:.1f} req/s", new_rate)
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
        self._journal.record_failure(endpoint_name, params_json, exc_name)
        self._journal.record_metric(endpoint_name, duration, 0, errors=1)
        self._circuit_breaker.record_failure(endpoint_name)
        self._latency.record(endpoint_name, duration)
        new_rate = self._adaptive.record_failure()
        if new_rate is not None:
            self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
            logger.warning("adaptive rate: backing off to {:.1f} req/s", new_rate)
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
        on_progress: object | None = None,
    ) -> dict[str, pl.DataFrame] | None:
        """Extract a single (non-multi) entry for one param set."""
        params_json = json.dumps(params, sort_keys=True)

        # Resume: skip if already extracted (use pre-fetched set when available)
        is_done = (
            (entry.endpoint_name, params_json) in already_done
            if already_done is not None
            else self._journal.was_extracted(entry.endpoint_name, params_json)
        )
        if is_done:
            self.skipped += 1
            if on_progress is not None:
                on_progress.record_skip()  # type: ignore[union-attr]
            logger.debug(
                "skip (already done): {} [{}]",
                entry.endpoint_name,
                params_json,
            )
            return None

        pool = self._thread_pool

        async def _do(ext: object) -> pl.DataFrame:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(pool, lambda: _sync_extract(ext, **params))

        df = await self._run_with_journal(entry.endpoint_name, params_json, fn=_do)
        if df is None:
            return None
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
        on_progress: object | None = None,
    ) -> dict[str, pl.DataFrame] | None:
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
        is_done = (
            (endpoint_name, params_json) in already_done
            if already_done is not None
            else self._journal.was_extracted(endpoint_name, params_json)
        )
        if is_done:
            self.skipped += 1
            if on_progress is not None:
                on_progress.record_skip()  # type: ignore[union-attr]
            logger.debug(
                "skip (already done): {} [{}]",
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

            all_dfs = await self._run_with_journal(endpoint_name, params_json, fn=_do)
            if all_dfs is None:
                return None
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
