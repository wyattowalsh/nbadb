from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING

from loguru import logger

from nbadb.orchestrate.staging_map import StagingEntry, get_multi_entries

if TYPE_CHECKING:
    import polars as pl

    from nbadb.core.config import NbaDbSettings
    from nbadb.core.proxy import ProxyPool
    from nbadb.extract.registry import EndpointRegistry
    from nbadb.orchestrate.journal import PipelineJournal


def _sync_extract(extractor: object, **kwargs: object) -> pl.DataFrame:
    """Call extractor.extract() synchronously (for asyncio.to_thread)."""
    import asyncio as _asyncio

    return _asyncio.run(extractor.extract(**kwargs))  # type: ignore[union-attr]


def _sync_extract_all(
    extractor: object, **kwargs: object
) -> list[pl.DataFrame]:
    """Call extractor.extract_all() synchronously."""
    import asyncio as _asyncio

    return _asyncio.run(extractor.extract_all(**kwargs))  # type: ignore[union-attr]


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
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._journal = journal
        self._proxy_pool = proxy_pool
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        # Cache for multi-endpoint results: (endpoint, params_json) -> DFs
        self._multi_cache: dict[
            tuple[str, str], list[pl.DataFrame]
        ] = {}

    # ── public API ─────────────────────────────────────────────

    async def run_pattern(
        self,
        pattern: str,
        param_sets: list[dict],
        entries: list[StagingEntry],
    ) -> dict[str, pl.DataFrame]:
        """Extract all *entries* across every *param_set*.

        Returns ``{staging_key: concatenated_df}`` for all entries
        that produced data.
        """
        import polars as pl

        multi_groups = get_multi_entries()
        # Separate entries into multi vs single
        multi_entries: list[StagingEntry] = []
        single_entries: list[StagingEntry] = []
        for entry in entries:
            if (
                entry.use_multi
                and entry.endpoint_name in multi_groups
            ):
                multi_entries.append(entry)
            else:
                single_entries.append(entry)

        # Accumulate results per staging_key
        accum: dict[str, list[pl.DataFrame]] = {
            e.staging_key: [] for e in entries
        }

        # Chunk param_sets for game-level to limit memory
        chunk_size = (
            self._settings.pbp_chunk_size
            if pattern == "game"
            else len(param_sets) or 1
        )
        for chunk_start in range(0, max(len(param_sets), 1), chunk_size):
            chunk = param_sets[chunk_start:chunk_start + chunk_size]
            if not chunk:
                break

            tasks: list[asyncio.Task] = []

            # -- single-endpoint entries --------------------------
            for entry in single_entries:
                for params in chunk:
                    tasks.append(
                        asyncio.create_task(
                            self._extract_single(entry, params)
                        )
                    )

            # -- multi-endpoint entries (deduplicated) ------------
            # Group multi entries by endpoint_name
            multi_by_ep: dict[str, list[StagingEntry]] = {}
            for entry in multi_entries:
                multi_by_ep.setdefault(
                    entry.endpoint_name, []
                ).append(entry)

            for ep_name, ep_entries in multi_by_ep.items():
                for params in chunk:
                    tasks.append(
                        asyncio.create_task(
                            self._extract_multi(
                                ep_name, ep_entries, params
                            )
                        )
                    )

            # Await all tasks for this chunk
            results = await asyncio.gather(
                *tasks, return_exceptions=True
            )

            # Collect results
            for result in results:
                if isinstance(result, Exception):
                    logger.error(
                        "extraction task failed: {}",
                        type(result).__name__,
                    )
                    continue
                if result is None:
                    continue
                # result is dict[str, pl.DataFrame]
                for key, df in result.items():
                    if not df.is_empty():
                        accum[key].append(df)

        # Concatenate per staging_key
        output: dict[str, pl.DataFrame] = {}
        for key, frames in accum.items():
            if frames:
                output[key] = pl.concat(frames)
                logger.info(
                    "{}: {} rows total",
                    key,
                    output[key].shape[0],
                )
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
                    int(
                        base_limit
                        * self._settings.proxy_semaphore_multiplier
                    ),
                )
            else:
                limit = base_limit
            self._semaphores[category] = asyncio.Semaphore(limit)
        return self._semaphores[category]

    def _prepare_extractor(self, extractor: object) -> None:
        """Set proxy URL on an extractor instance before extraction."""
        if self._proxy_pool is not None:
            extractor._proxy_url = self._proxy_pool.get_proxy_url()

    async def _extract_single(
        self,
        entry: StagingEntry,
        params: dict,
    ) -> dict[str, pl.DataFrame] | None:
        """Extract a single (non-multi) entry for one param set."""
        params_json = json.dumps(params, sort_keys=True)

        # Resume: skip if already extracted
        if self._journal.was_extracted(
            entry.endpoint_name, params_json
        ):
            logger.debug(
                "skip (already done): {} [{}]",
                entry.endpoint_name,
                params_json,
            )
            return None

        try:
            extractor_cls = self._registry.get(entry.endpoint_name)
        except KeyError:
            logger.warning(
                "no extractor for endpoint: {}",
                entry.endpoint_name,
            )
            return None

        extractor = extractor_cls()
        self._prepare_extractor(extractor)
        sem = self._get_semaphore(extractor.category)

        self._journal.record_start(entry.endpoint_name, params_json)
        t0 = time.perf_counter()

        try:
            async with sem:
                df: pl.DataFrame = await asyncio.to_thread(
                    _sync_extract, extractor, **params
                )
        except Exception as exc:
            duration = time.perf_counter() - t0
            self._journal.record_failure(
                entry.endpoint_name,
                params_json,
                str(exc),
            )
            self._journal.record_metric(
                entry.endpoint_name, duration, 0, errors=1
            )
            logger.error(
                "extract failed: {} [{}] -> {}",
                entry.endpoint_name,
                params_json,
                type(exc).__name__,
            )
            return None

        duration = time.perf_counter() - t0
        rows = df.shape[0] if not df.is_empty() else 0
        self._journal.record_success(
            entry.endpoint_name, params_json, rows
        )
        self._journal.record_metric(
            entry.endpoint_name, duration, rows
        )
        return {entry.staging_key: df}

    async def _extract_multi(
        self,
        endpoint_name: str,
        entries: list[StagingEntry],
        params: dict,
    ) -> dict[str, pl.DataFrame] | None:
        """Extract a multi-result endpoint once and fan out by
        ``result_set_index``.

        Uses a cache so the same (endpoint, params) is only called
        once even if multiple staging entries reference it.
        """
        import polars as pl

        params_json = json.dumps(params, sort_keys=True)
        cache_key = (endpoint_name, params_json)

        # Check if ALL entries for this endpoint+params are done
        all_done = all(
            self._journal.was_extracted(endpoint_name, params_json)
            for _ in entries
        )
        if all_done and self._journal.was_extracted(
            endpoint_name, params_json
        ):
            logger.debug(
                "skip (already done): {} [{}]",
                endpoint_name,
                params_json,
            )
            return None

        # Check cache first
        if cache_key not in self._multi_cache:
            try:
                extractor_cls = self._registry.get(endpoint_name)
            except KeyError:
                logger.warning(
                    "no extractor for endpoint: {}",
                    endpoint_name,
                )
                return None

            extractor = extractor_cls()
            self._prepare_extractor(extractor)
            sem = self._get_semaphore(extractor.category)

            self._journal.record_start(endpoint_name, params_json)
            t0 = time.perf_counter()

            try:
                async with sem:
                    all_dfs: list[pl.DataFrame] = (
                        await asyncio.to_thread(
                            _sync_extract_all, extractor, **params
                        )
                    )
            except Exception as exc:
                duration = time.perf_counter() - t0
                self._journal.record_failure(
                    endpoint_name, params_json, str(exc)
                )
                self._journal.record_metric(
                    endpoint_name, duration, 0, errors=1
                )
                logger.error(
                    "multi-extract failed: {} [{}] -> {}",
                    endpoint_name,
                    params_json,
                    type(exc).__name__,
                )
                return None

            duration = time.perf_counter() - t0
            total_rows = sum(
                df.shape[0] for df in all_dfs if not df.is_empty()
            )
            self._journal.record_success(
                endpoint_name, params_json, total_rows
            )
            self._journal.record_metric(
                endpoint_name, duration, total_rows
            )
            self._multi_cache[cache_key] = all_dfs

        # Fan out results by result_set_index
        all_dfs = self._multi_cache[cache_key]
        output: dict[str, pl.DataFrame] = {}
        for entry in entries:
            idx = entry.result_set_index
            if idx < len(all_dfs):
                output[entry.staging_key] = all_dfs[idx]
            else:
                logger.warning(
                    "{}: result_set_index {} out of range "
                    "(got {} sets)",
                    entry.staging_key,
                    idx,
                    len(all_dfs),
                )
                output[entry.staging_key] = pl.DataFrame()

        return output
