from __future__ import annotations

import asyncio
import inspect
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Literal, NoReturn, Protocol, cast

from aiolimiter import AsyncLimiter
from loguru import logger

from nbadb.core.errors import ExtractionError, NbaDbError, TransientError
from nbadb.extract.base import BaseExtractor, is_retryable_error
from nbadb.orchestrate.execution_policy import endpoint_family
from nbadb.orchestrate.resilience import _AdaptiveThrottle, _CircuitBreaker, _LatencyTracker
from nbadb.orchestrate.staging_map import StagingEntry, get_multi_entries

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    import polars as pl

    from nbadb.core.config import NbaDbSettings
    from nbadb.extract.registry import EndpointRegistry
    from nbadb.orchestrate.journal import PipelineJournal


class _ExtractorLike(Protocol):
    def extract(self, **kwargs: object) -> Coroutine[Any, Any, pl.DataFrame]: ...


class _MultiExtractorLike(Protocol):
    def extract_all(self, **kwargs: object) -> Coroutine[Any, Any, list[pl.DataFrame]]: ...


class _ProgressReporter(Protocol):
    def advance_pattern(self, *, success: bool = True, rows: int = 0) -> None: ...

    def update_circuit_breakers(self, tripped: list[str]) -> None: ...

    def update_rate_info(self, current_rate: float, base_rate: float) -> None: ...

    def record_skip(self) -> None: ...


# ── sync helpers ──────────────────────────────────────────────


def _drive_coroutine[T](coro: Coroutine[Any, Any, T]) -> T:
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
        coro.send(None)
    except StopIteration as exc:
        return exc.value
    else:
        raise RuntimeError("coroutine yielded unexpectedly; it may perform real async I/O")
    finally:
        coro.close()


def _sync_extract(extractor: object, **kwargs: object) -> pl.DataFrame:
    """Call extractor.extract() synchronously (for asyncio.to_thread)."""
    try:
        return _drive_coroutine(cast("_ExtractorLike", extractor).extract(**kwargs))
    except Exception as exc:
        _raise_extraction_boundary_error(extractor, exc)
        raise AssertionError("unreachable") from exc


def _sync_extract_all(extractor: object, **kwargs: object) -> list[pl.DataFrame]:
    """Call extractor.extract_all() synchronously."""
    try:
        return _drive_coroutine(cast("_MultiExtractorLike", extractor).extract_all(**kwargs))
    except Exception as exc:
        _raise_extraction_boundary_error(extractor, exc)
        raise AssertionError("unreachable") from exc


def _raise_extraction_boundary_error(extractor: object, exc: Exception) -> NoReturn:
    if isinstance(exc, NbaDbError):
        raise exc

    endpoint_name = getattr(extractor, "endpoint_name", type(extractor).__name__)
    if is_retryable_error(exc):
        raise TransientError(
            f"{endpoint_name}: transient extraction failure ({type(exc).__name__})"
        ) from exc

    raise ExtractionError(f"{endpoint_name}: extraction failed ({type(exc).__name__})") from exc


@dataclass(frozen=True, slots=True)
class _DeferredExtraction:
    endpoint_name: str
    params: dict[str, object]
    wait_seconds: float
    staging_key: str | None = None
    eligible_staging_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PendingJournalSuccess:
    endpoint_name: str
    params_json: str
    rows: int


@dataclass(frozen=True, slots=True)
class _JournaledExtraction:
    data: pl.DataFrame | list[pl.DataFrame]
    success: _PendingJournalSuccess


@dataclass(frozen=True, slots=True)
class _ExtractionTaskResult:
    frames: dict[str, pl.DataFrame]
    pending_success: _PendingJournalSuccess | None = None
    source_endpoint_name: str | None = None
    source_params_json: str | None = None
    expected_staging_keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _SkippedTaskResult:
    status: Literal["journal_skip", "retry_skip"]
    endpoint_name: str
    params_json: str


@dataclass(frozen=True, slots=True)
class _FailedExtraction:
    endpoint_name: str
    params_json: str
    error: str
    status: Literal["failure", "deferred_failure", "unexpected"] = "failure"


@dataclass(frozen=True, slots=True)
class _ChunkTaskBatch:
    tasks: list[
        asyncio.Task[
            dict[str, pl.DataFrame]
            | _ExtractionTaskResult
            | _DeferredExtraction
            | _SkippedTaskResult
            | _FailedExtraction
            | None
        ]
    ]
    eligible_calls: int = 0
    support_skip_count: int = 0


@dataclass(slots=True)
class PatternExtractionResult:
    frames: dict[str, pl.DataFrame]
    eligible_calls: int = 0
    support_skip_count: int = 0
    journal_skip_count: int = 0
    retry_skip_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    deferred_failure_count: int = 0
    row_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        if self.failure_count or self.deferred_failure_count:
            return False
        completed = self.success_count + self.journal_skip_count + self.retry_skip_count
        return completed == self.eligible_calls


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
        progress: _ProgressReporter | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._journal = journal
        self._progress = progress
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._rate_limiter = AsyncLimiter(max_rate=rate_limit, time_period=1.0)
        self._endpoint_rate_limiters: dict[str, AsyncLimiter] = {}
        self._family_rate_limiters: dict[str, AsyncLimiter] = {}
        self._adaptive = _AdaptiveThrottle(
            base_rate=rate_limit,
            min_rate=getattr(settings, "adaptive_rate_min", 1.0),
            recovery_threshold=getattr(settings, "adaptive_rate_recovery", 50),
        )
        self._family_adaptive: dict[str, _AdaptiveThrottle] = {}
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
        on_progress: _ProgressReporter | None = None,
        *,
        skip_items: set[tuple[str, str]] | None = None,
        persist_chunk_results: Callable[..., None] | None = None,
    ) -> dict[str, pl.DataFrame]:
        """Extract all *entries* across every *param_set*.

        Returns ``{staging_key: concatenated_df}`` for all entries
        that produced data.  Also increments ``self.skipped`` for
        each param set that was already recorded in the journal.
        """
        result = await self.run_pattern_result(
            pattern,
            param_sets,
            entries,
            on_progress=on_progress,
            skip_items=skip_items,
            persist_chunk_results=persist_chunk_results,
        )
        return result.frames

    async def run_pattern_result(
        self,
        pattern: str,
        param_sets: list[dict],
        entries: list[StagingEntry],
        on_progress: _ProgressReporter | None = None,
        *,
        skip_items: set[tuple[str, str]] | None = None,
        persist_chunk_results: Callable[..., None] | None = None,
    ) -> PatternExtractionResult:
        """Extract a pattern and return frames plus call-local accounting."""

        multi_entries, single_entries, multi_by_ep = self._classify_entries(entries)
        accum: dict[str, list[pl.DataFrame]] = {e.staging_key: [] for e in entries}
        single_by_key = {
            (entry.endpoint_name, entry.staging_key): entry for entry in single_entries
        }
        pattern_result = PatternExtractionResult(frames={})

        chunk_size = self._chunk_size_for_entries(pattern, entries)
        for chunk_index, chunk_start in enumerate(range(0, max(len(param_sets), 1), chunk_size)):
            chunk = param_sets[chunk_start : chunk_start + chunk_size]
            if not chunk:
                break
            chunk_accum: dict[str, list[pl.DataFrame]] = {e.staging_key: [] for e in entries}
            pending_successes: list[_PendingJournalSuccess] = []
            source_results: list[dict[str, object]] = []
            defer_journal_success = persist_chunk_results is not None

            already_done = self._prefetch_done(single_entries, multi_by_ep, chunk)
            chunk_batch = self._build_chunk_tasks(
                single_entries,
                multi_by_ep,
                chunk,
                already_done,
                on_progress=on_progress,
                skip_items=skip_items,
                defer_journal_success=defer_journal_success,
            )
            pattern_result.eligible_calls += chunk_batch.eligible_calls
            pattern_result.support_skip_count += chunk_batch.support_skip_count

            results = (
                await asyncio.gather(*chunk_batch.tasks, return_exceptions=True)
                if chunk_batch.tasks
                else []
            )
            delayed = [r for r in results if isinstance(r, _DeferredExtraction)]
            immediate = [r for r in results if not isinstance(r, _DeferredExtraction)]
            chunk_expected_staging_keys = set(self._successful_staging_keys(immediate))
            pending_successes.extend(
                self._collect_results(immediate, chunk_accum, on_progress, pattern_result)
            )
            if persist_chunk_results is not None:
                source_results.extend(self._source_results_for_persistence(immediate))
            if delayed:
                replay_results = await self._replay_deferred_chunk(
                    delayed,
                    single_by_key=single_by_key,
                    multi_by_ep=multi_by_ep,
                    on_progress=on_progress,
                    defer_journal_success=defer_journal_success,
                )
                replay_deferred = [r for r in replay_results if isinstance(r, _DeferredExtraction)]
                if replay_deferred:
                    logger.error(
                        "late recovery replay returned deferred extractions unexpectedly: {}",
                        len(replay_deferred),
                    )
                    pattern_result.deferred_failure_count += len(replay_deferred)
                    for item in replay_deferred:
                        pattern_result.errors.append(
                            f"{item.endpoint_name}[{json.dumps(item.params, sort_keys=True)}]: "
                            "deferred recovery did not complete"
                        )
                pending_successes.extend(
                    self._collect_results(
                        [r for r in replay_results if not isinstance(r, _DeferredExtraction)],
                        chunk_accum,
                        on_progress,
                        pattern_result,
                    )
                )
                chunk_expected_staging_keys.update(
                    self._successful_staging_keys(
                        [r for r in replay_results if not isinstance(r, _DeferredExtraction)]
                    )
                )
                if persist_chunk_results is not None:
                    source_results.extend(
                        self._source_results_for_persistence(
                            [r for r in replay_results if not isinstance(r, _DeferredExtraction)]
                        )
                    )

            chunk_output = self._concat_accum(chunk_accum)
            if persist_chunk_results is not None and (chunk_output or chunk_expected_staging_keys):
                self._persist_chunk_results(
                    persist_chunk_results,
                    chunk_output,
                    pattern=pattern,
                    chunk_index=chunk_index,
                    chunk_params=chunk,
                    entries=entries,
                    expected_staging_keys=sorted(chunk_expected_staging_keys),
                    source_results=source_results,
                )
            for success in pending_successes:
                self._journal.record_success(
                    success.endpoint_name,
                    success.params_json,
                    success.rows,
                )
            for key, df in chunk_output.items():
                if not df.is_empty():
                    accum[key].append(df)

            # HR-A-007: free multi-endpoint cache between chunks to
            # prevent unbounded memory growth on large historical runs.
            self._multi_cache.clear()

        pattern_result.frames = self._concat_accum(accum)
        return pattern_result

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
        on_progress: _ProgressReporter | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        defer_journal_success: bool = False,
    ) -> _ChunkTaskBatch:
        """Create asyncio tasks for all entries in a chunk."""
        tasks: list[
            asyncio.Task[
                dict[str, pl.DataFrame]
                | _ExtractionTaskResult
                | _DeferredExtraction
                | _SkippedTaskResult
                | _FailedExtraction
                | None
            ]
        ] = []
        support_skip_count = 0
        eligible_calls = 0
        today = date.today()

        for entry in single_entries:
            for params in chunk:
                # Skip entries deprecated before today
                if entry.deprecated_after is not None and today > date.fromisoformat(
                    entry.deprecated_after
                ):
                    self.skipped += 1
                    support_skip_count += 1
                    if on_progress is not None:
                        on_progress.advance_pattern(success=True)
                    continue
                # Honor only explicit upstream support floors. Production
                # entries default to no floor so historical runs begin at 1946.
                sy = self._season_year(params)
                if entry.min_season is not None and sy is not None and sy < entry.min_season:
                    self.skipped += 1
                    support_skip_count += 1
                    if on_progress is not None:
                        on_progress.advance_pattern(success=True)
                    continue
                self.planned_calls += 1
                eligible_calls += 1
                tasks.append(
                    asyncio.create_task(
                        self._extract_single_result(
                            entry,
                            params,
                            already_done=already_done,
                            skip_items=skip_items,
                            on_progress=on_progress,
                            allow_late_recovery=True,
                            defer_journal_success=defer_journal_success,
                        )
                    )
                )

        for ep_name, ep_entries in multi_by_ep.items():
            for params in chunk:
                # For multi-endpoint groups, keep only entries still eligible
                # under documented upstream support/deprecation windows.
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
                    support_skip_count += 1
                    if on_progress is not None:
                        for _ in ep_entries:
                            on_progress.advance_pattern(success=True)
                    continue
                self.planned_calls += 1
                eligible_calls += 1
                tasks.append(
                    asyncio.create_task(
                        self._extract_multi_result(
                            ep_name,
                            eligible,
                            params,
                            already_done=already_done,
                            skip_items=skip_items,
                            on_progress=on_progress,
                            allow_late_recovery=True,
                            defer_journal_success=defer_journal_success,
                        )
                    )
                )

        return _ChunkTaskBatch(
            tasks=tasks,
            eligible_calls=eligible_calls,
            support_skip_count=support_skip_count,
        )

    async def _replay_deferred_chunk(
        self,
        deferred: list[_DeferredExtraction],
        *,
        single_by_key: dict[tuple[str, str], StagingEntry],
        multi_by_ep: dict[str, list[StagingEntry]],
        on_progress: _ProgressReporter | None,
        defer_journal_success: bool = False,
    ) -> list[
        dict[str, pl.DataFrame]
        | _ExtractionTaskResult
        | _SkippedTaskResult
        | _FailedExtraction
        | BaseException
        | _DeferredExtraction
        | None
    ]:
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

        tasks: list[
            asyncio.Task[
                dict[str, pl.DataFrame]
                | _ExtractionTaskResult
                | _SkippedTaskResult
                | _FailedExtraction
                | _DeferredExtraction
                | None
            ]
        ] = []
        for item in replay_items:
            if item.staging_key is None:
                entries = multi_by_ep.get(item.endpoint_name)
                if not entries:
                    logger.error(
                        "late recovery missing multi entries for endpoint: {}",
                        item.endpoint_name,
                    )
                    continue
                if item.eligible_staging_keys:
                    eligible_keys = set(item.eligible_staging_keys)
                    entries = [entry for entry in entries if entry.staging_key in eligible_keys]
                tasks.append(
                    asyncio.create_task(
                        self._extract_multi_result(
                            item.endpoint_name,
                            entries,
                            item.params,
                            on_progress=on_progress,
                            allow_late_recovery=False,
                            late_recovery_replay=True,
                            defer_journal_success=defer_journal_success,
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
                    self._extract_single_result(
                        entry,
                        item.params,
                        on_progress=on_progress,
                        allow_late_recovery=False,
                        late_recovery_replay=True,
                        defer_journal_success=defer_journal_success,
                    )
                )
            )

        if not tasks:
            return []
        return await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _persist_chunk_results(
        callback: Callable[..., None],
        frames: dict[str, pl.DataFrame],
        *,
        pattern: str,
        chunk_index: int,
        chunk_params: list[dict],
        entries: list[StagingEntry],
        expected_staging_keys: list[str],
        source_results: list[dict[str, object]],
    ) -> None:
        """Call a chunk persistence callback with metadata when it accepts it."""
        signature = inspect.signature(callback)
        params = signature.parameters
        accepts_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()
        )
        metadata = {
            "pattern": pattern,
            "chunk_index": chunk_index,
            "chunk_params": chunk_params,
            "entries": entries,
            "expected_staging_keys": expected_staging_keys,
            "source_results": source_results,
        }
        if accepts_kwargs:
            callback(frames, **metadata)
            return
        accepted_metadata = {
            key: value
            for key, value in metadata.items()
            if key in params
            and params[key].kind
            in {
                inspect.Parameter.KEYWORD_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
        }
        if accepted_metadata:
            callback(frames, **accepted_metadata)
            return
        callback(frames)

    @staticmethod
    def _successful_staging_keys(
        results: list[
            dict[str, pl.DataFrame]
            | _ExtractionTaskResult
            | _SkippedTaskResult
            | _FailedExtraction
            | BaseException
            | None
        ],
    ) -> set[str]:
        keys: set[str] = set()
        for result in results:
            frames: dict[str, pl.DataFrame] | None = None
            if isinstance(result, _ExtractionTaskResult):
                frames = result.frames
            elif isinstance(result, dict):
                frames = result
            if frames is not None:
                keys.update(frames)
        return keys

    @staticmethod
    def _source_results_for_persistence(
        results: list[
            dict[str, pl.DataFrame]
            | _ExtractionTaskResult
            | _SkippedTaskResult
            | _FailedExtraction
            | BaseException
            | None
        ],
    ) -> list[dict[str, object]]:
        source_results: list[dict[str, object]] = []
        for result in results:
            if not isinstance(result, _ExtractionTaskResult):
                continue
            if result.pending_success is None:
                continue
            if result.source_endpoint_name is None or result.source_params_json is None:
                msg = (
                    "journal-backed extraction result missing source identity for "
                    f"{result.pending_success.endpoint_name}"
                )
                raise RuntimeError(msg)
            source_results.append(
                {
                    "frames": result.frames,
                    "source_endpoint_name": result.source_endpoint_name,
                    "source_params_json": result.source_params_json,
                    "expected_staging_keys": result.expected_staging_keys,
                }
            )
        return source_results

    @staticmethod
    def _collect_results(
        results: list[
            dict[str, pl.DataFrame]
            | _ExtractionTaskResult
            | _SkippedTaskResult
            | _FailedExtraction
            | BaseException
            | None
        ],
        accum: dict[str, list[pl.DataFrame]],
        on_progress: _ProgressReporter | None,
        pattern_result: PatternExtractionResult | None = None,
    ) -> list[_PendingJournalSuccess]:
        """Merge task results into the accumulator."""
        if pattern_result is None:
            pattern_result = PatternExtractionResult(frames={})
        pending_successes: list[_PendingJournalSuccess] = []
        for result in results:
            if isinstance(result, BaseException):
                # Don't advance progress here — the task either already
                # advanced before raising or was never started.
                logger.error(
                    "extraction task failed: {}",
                    type(result).__name__,
                )
                pattern_result.failure_count += 1
                pattern_result.errors.append(f"task_exception:{type(result).__name__}")
                continue
            if result is None:
                pattern_result.failure_count += 1
                pattern_result.errors.append("task_returned_none")
                continue
            if isinstance(result, _SkippedTaskResult):
                if result.status == "journal_skip":
                    pattern_result.journal_skip_count += 1
                else:
                    pattern_result.retry_skip_count += 1
                continue
            if isinstance(result, _FailedExtraction):
                if result.status == "deferred_failure":
                    pattern_result.deferred_failure_count += 1
                else:
                    pattern_result.failure_count += 1
                pattern_result.errors.append(
                    f"{result.endpoint_name}[{result.params_json}]: {result.error}"
                )
                continue
            if isinstance(result, _ExtractionTaskResult):
                frames = result.frames
                if result.pending_success is not None:
                    pending_successes.append(result.pending_success)
            else:
                frames = result
            if not isinstance(frames, dict):
                # Don't advance progress — unexpected type indicates a
                # programming error, not a countable extraction attempt.
                logger.error(
                    "unexpected extraction task result type: {}",
                    type(frames).__name__,
                )
                pattern_result.failure_count += 1
                pattern_result.errors.append(f"unexpected_result_type:{type(frames).__name__}")
                continue
            # Compute rows for progress reporting
            rows = sum(df.shape[0] for key, df in frames.items() if not df.is_empty())
            pattern_result.success_count += 1
            pattern_result.row_count += rows
            if on_progress is not None:
                on_progress.advance_pattern(success=True, rows=rows)
            for key, df in frames.items():
                if not df.is_empty():
                    accum[key].append(df)
        return pending_successes

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

    def _endpoint_family(self, endpoint_name: str, category: str) -> str:
        family_overrides = getattr(self._settings, "endpoint_family_overrides", {})
        if endpoint_name in family_overrides:
            return str(family_overrides[endpoint_name])
        return endpoint_family(endpoint_name, category)

    def _get_family_rate_limiter(self, family: str) -> AsyncLimiter | None:
        family_limits = getattr(self._settings, "family_rate_limits", {})
        if family not in family_limits:
            return None
        if family not in self._family_rate_limiters:
            self._family_rate_limiters[family] = AsyncLimiter(
                max_rate=family_limits[family],
                time_period=1.0,
            )
        return self._family_rate_limiters[family]

    def _get_family_adaptive(self, family: str) -> _AdaptiveThrottle | None:
        family_limits = getattr(self._settings, "family_rate_limits", {})
        if family not in family_limits:
            return None
        if family not in self._family_adaptive:
            self._family_adaptive[family] = _AdaptiveThrottle(
                base_rate=float(family_limits[family]),
                min_rate=getattr(self._settings, "adaptive_rate_min", 1.0),
                recovery_threshold=getattr(self._settings, "adaptive_rate_recovery", 50),
            )
        return self._family_adaptive[family]

    def _get_semaphore(self, endpoint_name: str, category: str) -> asyncio.Semaphore:
        """Lazily create a semaphore for the given endpoint/category lane."""
        endpoint_limits = getattr(self._settings, "endpoint_semaphore_limits", {})
        family_limits = getattr(self._settings, "family_semaphore_limits", {})
        family = self._endpoint_family(endpoint_name, category)
        if endpoint_name in endpoint_limits:
            key = endpoint_name
        elif family in family_limits:
            key = f"family:{family}"
        else:
            key = category
        if key not in self._semaphores:
            if endpoint_name in endpoint_limits:
                limit = endpoint_limits[endpoint_name]
            elif family in family_limits:
                limit = family_limits[family]
            else:
                limit = self._settings.semaphore_tiers.get(
                    category,
                    self._settings.semaphore_tiers.get("default", 10),
                )
            self._semaphores[key] = asyncio.Semaphore(limit)
        return self._semaphores[key]

    def _chunk_size_for_entries(self, pattern: str, entries: list[StagingEntry]) -> int:
        base_chunk_size = (
            self._settings.pbp_chunk_size
            if pattern == "game"
            else self._settings.default_chunk_size
        )
        multipliers = getattr(self._settings, "family_chunk_multipliers", {})
        min_chunk_size = max(1, int(getattr(self._settings, "adaptive_chunk_min_size", 25)))
        max_chunk_size = max(
            min_chunk_size, int(getattr(self._settings, "adaptive_chunk_max_size", base_chunk_size))
        )
        multiplier = 1.0
        for entry in entries:
            family = self._endpoint_family(entry.endpoint_name, entry.param_pattern)
            multiplier = min(multiplier, float(multipliers.get(family, 1.0)))
        return max(min_chunk_size, min(max_chunk_size, max(1, int(base_chunk_size * multiplier))))

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
        return isinstance(exc, TransientError) or is_retryable_error(exc)

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
        family: str,
        duration: float,
        *,
        isolated_scope: str,
    ) -> None:
        self._journal.record_metric(endpoint_name, duration, 0, errors=1)
        self._circuit_breaker.record_failure(endpoint_name)
        tripped = self._circuit_breaker.tripped_endpoints()
        if tripped and self._progress is not None:
            self._progress.update_circuit_breakers(tripped)
        self._latency.record(endpoint_name, duration)
        if isolated_scope == "global":
            new_rate = self._adaptive.record_failure()
            if new_rate is not None:
                self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
                logger.warning("adaptive rate: backing off to {:.1f} req/s", new_rate)
                if self._progress is not None:
                    self._progress.update_rate_info(
                        self._adaptive.current_rate,
                        self._adaptive._base_rate,
                    )
        elif isolated_scope == "family":
            adaptive = self._get_family_adaptive(family)
            if adaptive is not None:
                new_rate = adaptive.record_failure()
                if new_rate is not None:
                    self._family_rate_limiters[family] = AsyncLimiter(
                        max_rate=new_rate, time_period=1.0
                    )
                    logger.warning(
                        "family adaptive rate [{}]: backing off to {:.1f} req/s", family, new_rate
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
        defer_journal_success: bool = False,
        return_failures: bool = False,
    ) -> (
        pl.DataFrame
        | list[pl.DataFrame]
        | _JournaledExtraction
        | _DeferredExtraction
        | _FailedExtraction
        | None
    ):
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
            if return_failures:
                return _FailedExtraction(endpoint_name, params_json, "MissingExtractor")
            return None

        max_retries = self._settings.extract_max_retries
        base_delay = self._settings.extract_retry_base_delay
        last_exc: Exception | None = None
        family = self._endpoint_family(endpoint_name, getattr(extractor_cls, "category", "default"))

        self._journal.record_start(endpoint_name, params_json)
        t0 = time.perf_counter()
        isolated_scope = "global"

        for attempt in range(max_retries + 1):
            extractor = extractor_cls()
            self._prepare_extractor(extractor)
            family = self._endpoint_family(endpoint_name, extractor.category)
            sem = self._get_semaphore(endpoint_name, extractor.category)
            endpoint_limiter = self._get_endpoint_rate_limiter(endpoint_name)
            family_limiter = self._get_family_rate_limiter(family)
            if endpoint_limiter is not None:
                rate_limiter = endpoint_limiter
                isolated_scope = "endpoint"
            elif family_limiter is not None:
                rate_limiter = family_limiter
                isolated_scope = "family"
            else:
                rate_limiter = self._rate_limiter
                isolated_scope = "global"

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
                pending_success = _PendingJournalSuccess(endpoint_name, params_json, rows)
                if not defer_journal_success:
                    self._journal.record_success(endpoint_name, params_json, rows)
                self._journal.record_metric(endpoint_name, duration, rows)
                self._circuit_breaker.record_success(endpoint_name)
                self._latency.record(endpoint_name, duration)
                if isolated_scope == "global":
                    new_rate = self._adaptive.record_success()
                    if new_rate is not None:
                        self._rate_limiter = AsyncLimiter(max_rate=new_rate, time_period=1.0)
                        logger.info("adaptive rate: recovering to {:.1f} req/s", new_rate)
                        if self._progress is not None:
                            self._progress.update_rate_info(
                                self._adaptive.current_rate,
                                self._adaptive._base_rate,
                            )
                elif isolated_scope == "family":
                    adaptive = self._get_family_adaptive(family)
                    if adaptive is not None:
                        new_rate = adaptive.record_success()
                        if new_rate is not None:
                            self._family_rate_limiters[family] = AsyncLimiter(
                                max_rate=new_rate,
                                time_period=1.0,
                            )
                            logger.info(
                                "family adaptive rate [{}]: recovering to {:.1f} req/s",
                                family,
                                new_rate,
                            )
                if attempt > 0:
                    logger.info(
                        "extract succeeded on retry {}: {} [{}]",
                        attempt,
                        endpoint_name,
                        params_json,
                    )
                if defer_journal_success:
                    return _JournaledExtraction(data=result, success=pending_success)
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
                family,
                duration,
                isolated_scope=isolated_scope,
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
                family,
                duration,
                isolated_scope=isolated_scope,
            )
        logger.error(
            "extract failed after {} attempts: {} [{}] -> {}",
            max_retries + 1,
            endpoint_name,
            params_json,
            exc_name,
        )
        if return_failures:
            return _FailedExtraction(
                endpoint_name,
                params_json,
                exc_name,
                status="deferred_failure" if late_recovery_replay else "failure",
            )
        return None

    async def _extract_single(
        self,
        entry: StagingEntry,
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: _ProgressReporter | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
        defer_journal_success: bool = False,
    ) -> dict[str, pl.DataFrame] | _ExtractionTaskResult | _DeferredExtraction | None:
        result = await self._extract_single_result(
            entry,
            params,
            already_done=already_done,
            skip_items=skip_items,
            on_progress=on_progress,
            allow_late_recovery=allow_late_recovery,
            late_recovery_replay=late_recovery_replay,
            defer_journal_success=defer_journal_success,
        )
        if isinstance(result, (_ExtractionTaskResult, _DeferredExtraction)):
            return result
        if isinstance(result, dict):
            return result
        return None

    async def _extract_single_result(
        self,
        entry: StagingEntry,
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: _ProgressReporter | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
        defer_journal_success: bool = False,
    ) -> (
        dict[str, pl.DataFrame]
        | _ExtractionTaskResult
        | _DeferredExtraction
        | _SkippedTaskResult
        | _FailedExtraction
        | None
    ):
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
                on_progress.record_skip()
            logger.debug(
                "skip ({}): {} [{}]",
                "already done" if journal_done else "already attempted this run",
                entry.endpoint_name,
                params_json,
            )
            return _SkippedTaskResult(
                "journal_skip" if journal_done else "retry_skip",
                entry.endpoint_name,
                params_json,
            )

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
            defer_journal_success=defer_journal_success,
            return_failures=True,
        )
        if df is None:
            return _FailedExtraction(entry.endpoint_name, params_json, "UnknownFailure")
        if isinstance(df, _FailedExtraction):
            return df
        if isinstance(df, _DeferredExtraction):
            return _DeferredExtraction(
                endpoint_name=df.endpoint_name,
                params=df.params,
                wait_seconds=df.wait_seconds,
                staging_key=entry.staging_key,
                eligible_staging_keys=(entry.staging_key,),
            )
        pending_success: _PendingJournalSuccess | None = None
        if isinstance(df, _JournaledExtraction):
            pending_success = df.success
            df = df.data
        if isinstance(df, list):
            logger.error("unexpected list result for single extraction: {}", entry.endpoint_name)
            return _FailedExtraction(
                entry.endpoint_name,
                params_json,
                "UnexpectedListResult",
                status="unexpected",
            )
        frames = {entry.staging_key: df}
        if pending_success is not None:
            return _ExtractionTaskResult(
                frames=frames,
                pending_success=pending_success,
                source_endpoint_name=entry.endpoint_name,
                source_params_json=params_json,
                expected_staging_keys=(entry.staging_key,),
            )
        return frames

    async def _extract_multi(
        self,
        endpoint_name: str,
        entries: list[StagingEntry],
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: _ProgressReporter | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
        defer_journal_success: bool = False,
    ) -> dict[str, pl.DataFrame] | _ExtractionTaskResult | _DeferredExtraction | None:
        result = await self._extract_multi_result(
            endpoint_name,
            entries,
            params,
            already_done=already_done,
            skip_items=skip_items,
            on_progress=on_progress,
            allow_late_recovery=allow_late_recovery,
            late_recovery_replay=late_recovery_replay,
            defer_journal_success=defer_journal_success,
        )
        if isinstance(result, (_ExtractionTaskResult, _DeferredExtraction)):
            return result
        if isinstance(result, dict):
            return result
        return None

    async def _extract_multi_result(
        self,
        endpoint_name: str,
        entries: list[StagingEntry],
        params: dict,
        *,
        already_done: set[tuple[str, str]] | None = None,
        skip_items: set[tuple[str, str]] | None = None,
        on_progress: _ProgressReporter | None = None,
        allow_late_recovery: bool = True,
        late_recovery_replay: bool = False,
        defer_journal_success: bool = False,
    ) -> (
        dict[str, pl.DataFrame]
        | _ExtractionTaskResult
        | _DeferredExtraction
        | _SkippedTaskResult
        | _FailedExtraction
        | None
    ):
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
                on_progress.record_skip()
            logger.debug(
                "skip ({}): {} [{}]",
                "already done" if journal_done else "already attempted this run",
                endpoint_name,
                params_json,
            )
            return _SkippedTaskResult(
                "journal_skip" if journal_done else "retry_skip",
                endpoint_name,
                params_json,
            )

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
                defer_journal_success=defer_journal_success,
                return_failures=True,
            )
            if all_dfs is None:
                return _FailedExtraction(endpoint_name, params_json, "UnknownFailure")
            if isinstance(all_dfs, _FailedExtraction):
                return all_dfs
            if isinstance(all_dfs, _DeferredExtraction):
                return _DeferredExtraction(
                    endpoint_name=all_dfs.endpoint_name,
                    params=all_dfs.params,
                    wait_seconds=all_dfs.wait_seconds,
                    eligible_staging_keys=tuple(entry.staging_key for entry in entries),
                )
            pending_success: _PendingJournalSuccess | None = None
            if isinstance(all_dfs, _JournaledExtraction):
                pending_success = all_dfs.success
                all_dfs = all_dfs.data
            if not isinstance(all_dfs, list):
                logger.error("unexpected non-list result for multi extraction: {}", endpoint_name)
                return _FailedExtraction(
                    endpoint_name,
                    params_json,
                    "UnexpectedNonListResult",
                    status="unexpected",
                )
            validated_dfs: list[pl.DataFrame] = []
            for df in all_dfs:
                if not isinstance(df, pl.DataFrame):
                    logger.error(
                        "unexpected element type for multi extraction {}: {}",
                        endpoint_name,
                        type(df).__name__,
                    )
                    return _FailedExtraction(
                        endpoint_name,
                        params_json,
                        f"UnexpectedElementType:{type(df).__name__}",
                        status="unexpected",
                    )
                validated_dfs.append(df)
            self._multi_cache[cache_key] = validated_dfs
        else:
            pending_success = None

        # Fan out results by result_set_index
        all_dfs = self._multi_cache[cache_key]
        output: dict[str, pl.DataFrame] = {}
        for entry in entries:
            idx = entry.result_set_index
            if idx < len(all_dfs):
                output[entry.staging_key] = all_dfs[idx]
            elif entry.allow_missing_result_set:
                logger.debug(
                    "{}: optional result_set_index {} not returned (got {} sets)",
                    entry.staging_key,
                    idx,
                    len(all_dfs),
                )
                output[entry.staging_key] = pl.DataFrame()
            else:
                logger.warning(
                    "{}: result_set_index {} out of range (got {} sets)",
                    entry.staging_key,
                    idx,
                    len(all_dfs),
                )
                output[entry.staging_key] = pl.DataFrame()

        if pending_success is not None:
            return _ExtractionTaskResult(
                frames=output,
                pending_success=pending_success,
                source_endpoint_name=endpoint_name,
                source_params_json=params_json,
                expected_staging_keys=tuple(output),
            )
        return output
