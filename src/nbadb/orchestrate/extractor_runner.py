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

if TYPE_CHECKING:
    from collections.abc import Callable

    import polars as pl

    from nbadb.core.config import NbaDbSettings
    from nbadb.core.proxy import ProxyPool
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
        coro.close()  # type: ignore[union-attr]


def _sync_extract(extractor: object, **kwargs: object) -> pl.DataFrame:
    """Call extractor.extract() synchronously (for asyncio.to_thread)."""
    return _drive_coroutine(extractor.extract(**kwargs))  # type: ignore[union-attr,return-value]


def _sync_extract_all(extractor: object, **kwargs: object) -> list[pl.DataFrame]:
    """Call extractor.extract_all() synchronously."""
    return _drive_coroutine(extractor.extract_all(**kwargs))  # type: ignore[union-attr,return-value]


def _assign_proxy(extractor: object, proxy_pool: object) -> None:
    """Assign a proxy URL to an extractor if a pool is available."""
    if proxy_pool is not None:
        url = proxy_pool.get_proxy_url()  # type: ignore[union-attr]
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
        proxy_pool: ProxyPool | None = None,
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
        # Cache for multi-endpoint results: (endpoint, params_json) -> DFs
        self._multi_cache: dict[tuple[str, str], list[pl.DataFrame]] = {}
        # Count of extractions skipped because already done in journal
        self.skipped: int = 0

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
                tasks.append(
                    asyncio.create_task(
                        self._extract_multi(
                            ep_name,
                            ep_entries,
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
                    on_progress.advance_pattern(success=False)  # type: ignore[union-attr]
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

    async def _run_with_journal(
        self,
        endpoint_name: str,
        params_json: str,
        *,
        fn: Callable,
    ) -> pl.DataFrame | list[pl.DataFrame] | None:
        """Execute an extraction call with full journal tracking.

        *fn* is a one-arg async-compatible callable ``fn(extractor)``
        that performs the actual extraction (params captured via
        closure).  Returns ``None`` on failure.
        """
        try:
            extractor_cls = self._registry.get(endpoint_name)
        except KeyError:
            logger.warning("no extractor for endpoint: {}", endpoint_name)
            return None

        extractor = extractor_cls()
        self._prepare_extractor(extractor)
        sem = self._get_semaphore(extractor.category)

        self._journal.record_start(endpoint_name, params_json)
        t0 = time.perf_counter()

        try:
            async with self._rate_limiter, sem:
                result = await fn(extractor)
        except Exception as exc:
            duration = time.perf_counter() - t0
            self._journal.record_failure(endpoint_name, params_json, type(exc).__name__)
            self._journal.record_metric(endpoint_name, duration, 0, errors=1)
            # Adaptive backoff on failure
            new_rate = self._adaptive.record_failure()
            if new_rate is not None:
                self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
                logger.warning("adaptive rate: backing off to {:.1f} req/s", new_rate)
            logger.error(
                "extract failed: {} [{}] -> {}",
                endpoint_name,
                params_json,
                type(exc).__name__,
            )
            return None

        duration = time.perf_counter() - t0
        if isinstance(result, list):
            rows = sum(df.shape[0] for df in result if not df.is_empty())
        else:
            rows = result.shape[0] if not result.is_empty() else 0
        self._journal.record_success(endpoint_name, params_json, rows)
        self._journal.record_metric(endpoint_name, duration, rows)
        # Adaptive recovery on success
        new_rate = self._adaptive.record_success()
        if new_rate is not None:
            self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
            logger.info("adaptive rate: recovering to {:.1f} req/s", new_rate)
        return result

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
