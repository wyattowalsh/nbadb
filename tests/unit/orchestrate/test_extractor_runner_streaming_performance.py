from __future__ import annotations

import asyncio
import inspect
import json
from functools import partial
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from nbadb.extract.nba_api_adapter import LOSSLESS_FALLBACK_STAGING_KEY
from nbadb.orchestrate.extractor_runner import (
    ExtractorRunner,
    _ExtractionTaskResult,
    _PendingJournalSuccess,
)
from nbadb.orchestrate.staging_map import StagingEntry


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "semaphore_tiers": {"default": 4},
        "endpoint_semaphore_limits": {},
        "family_semaphore_limits": {},
        "endpoint_rate_limits": {},
        "family_rate_limits": {},
        "endpoint_family_overrides": {},
        "endpoint_request_timeouts": {},
        "endpoint_chunk_size_limits": {},
        "endpoint_retry_budgets": {},
        "family_chunk_multipliers": {},
        "zero_progress_abort_endpoints": set(),
        "response_contract_circuit_thresholds": {},
        "pbp_chunk_size": 500,
        "default_chunk_size": 500,
        "adaptive_chunk_min_size": 1,
        "adaptive_chunk_max_size": 500,
        "thread_pool_size": 4,
        "adaptive_rate_min": 1.0,
        "adaptive_rate_recovery": 50,
        "extract_max_retries": 0,
        "extract_retry_base_delay": 0.0,
        "circuit_breaker_threshold": 5,
        "circuit_breaker_recovery": 120.0,
        "circuit_breaker_max_wait": 600.0,
        "latency_window_size": 10,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _journal() -> MagicMock:
    journal = MagicMock()
    journal.was_extracted.return_value = False
    journal.was_extracted_batch.return_value = set()
    journal.get_failed.return_value = []
    return journal


def _registry(extractor: type[object]) -> MagicMock:
    registry = MagicMock()
    registry.get.return_value = extractor
    return registry


@pytest.mark.asyncio
async def test_bounded_scheduler_caps_live_tasks_and_preserves_order() -> None:
    runner = ExtractorRunner(
        _registry(object),
        _settings(thread_pool_size=3),
        _journal(),
        rate_limit=10_000,
    )
    active = 0
    peak_active = 0
    started: list[int] = []

    async def work(index: int) -> dict[str, pl.DataFrame]:
        nonlocal active, peak_active
        started.append(index)
        active += 1
        peak_active = max(peak_active, active)
        try:
            await asyncio.sleep(0)
            return {"stg_ep": pl.DataFrame({"request_index": [index]})}
        finally:
            active -= 1

    try:
        execution = await runner._run_bounded_tasks([partial(work, index) for index in range(257)])
    finally:
        runner.shutdown()

    assert execution.peak_in_flight == 3
    assert peak_active == 3
    assert started == list(range(257))
    assert [result["stg_ep"]["request_index"].item() for result in execution.results] == list(
        range(257)
    )


@pytest.mark.asyncio
async def test_bounded_pattern_preserves_exact_requests_routes_and_accounting() -> None:
    calls: list[str] = []

    class _SeasonExtractor:
        category = "default"
        endpoint_name = "season_endpoint"

        async def extract(self, **params: object) -> pl.DataFrame:
            season = str(params["season"])
            calls.append(season)
            return pl.DataFrame({"season": [season]})

    params = [{"season": f"20{year:02d}-{year + 1:02d}"} for year in range(17)]
    journal = _journal()
    runner = ExtractorRunner(
        _registry(_SeasonExtractor),
        _settings(
            thread_pool_size=2,
            endpoint_semaphore_limits={"season_endpoint": 1},
        ),
        journal,
        rate_limit=10_000,
    )
    entry = StagingEntry("season_endpoint", "stg_season", "season")

    try:
        result = await runner.run_pattern_result("season", params, [entry])
    finally:
        runner.shutdown()

    expected_seasons = [str(item["season"]) for item in params]
    assert calls == expected_seasons
    assert result.frames["stg_season"]["season"].to_list() == expected_seasons
    assert result.eligible_calls == len(params)
    assert result.scheduled_calls == len(params)
    assert result.success_count == len(params)
    assert result.row_count == len(params)
    assert result.failure_count == 0
    assert result.deferred_failure_count == 0
    assert result.unattempted_eligible_calls == 0
    assert result.is_complete
    assert [call.args[:2] for call in journal.record_start.call_args_list] == [
        ("season_endpoint", json.dumps(item, sort_keys=True)) for item in params
    ]
    assert [call.args[:2] for call in journal.record_success.call_args_list] == [
        ("season_endpoint", json.dumps(item, sort_keys=True)) for item in params
    ]


@pytest.mark.asyncio
async def test_streaming_sink_persists_before_journal_and_avoids_final_concat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _SeasonExtractor:
        category = "default"
        endpoint_name = "season_endpoint"

        async def extract(self, **params: object) -> pl.DataFrame:
            season = str(params["season"])
            events.append(f"extract:{season}")
            return pl.DataFrame({"season": [season]})

    journal = _journal()
    journal.record_success.side_effect = lambda _endpoint, params_json, _rows: events.append(
        f"journal:{json.loads(params_json)['season']}"
    )
    runner = ExtractorRunner(
        _registry(_SeasonExtractor),
        _settings(default_chunk_size=1, adaptive_chunk_max_size=1),
        journal,
        rate_limit=10_000,
    )
    concat_frame_counts: list[int] = []
    original_concat = runner._concat_accum

    def tracked_concat(accum: dict[str, list[pl.DataFrame]]) -> dict[str, pl.DataFrame]:
        concat_frame_counts.append(sum(len(frames) for frames in accum.values()))
        return original_concat(accum)

    monkeypatch.setattr(runner, "_concat_accum", tracked_concat)

    def persist(
        frames: dict[str, pl.DataFrame],
        *,
        chunk_index: int,
        expected_staging_keys: list[str],
    ) -> None:
        season = frames["stg_season"]["season"].item()
        assert journal.record_success.call_count == chunk_index
        assert expected_staging_keys == ["stg_season"]
        events.append(f"persist:{season}")

    params = [{"season": "2022-23"}, {"season": "2023-24"}, {"season": "2024-25"}]
    entry = StagingEntry("season_endpoint", "stg_season", "season")
    try:
        with patch(
            "nbadb.orchestrate.extractor_runner.inspect.signature",
            wraps=inspect.signature,
        ) as signature:
            result = await runner.run_pattern_result(
                "season",
                params,
                [entry],
                persist_chunk_results=persist,
                retain_frames=False,
            )
    finally:
        runner.shutdown()

    assert events == [
        "extract:2022-23",
        "persist:2022-23",
        "journal:2022-23",
        "extract:2023-24",
        "persist:2023-24",
        "journal:2023-24",
        "extract:2024-25",
        "persist:2024-25",
        "journal:2024-25",
    ]
    assert signature.call_count == 1
    assert concat_frame_counts == [1, 1, 1]
    assert result.frames == {}
    assert result.row_count == 3
    assert result.success_count == 3
    assert result.is_complete


@pytest.mark.asyncio
async def test_streaming_sink_keeps_lossless_fallback_in_atomic_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = _journal()
    runner = ExtractorRunner(
        _registry(object),
        _settings(default_chunk_size=1, adaptive_chunk_max_size=1),
        journal,
        rate_limit=10_000,
    )
    wide = pl.DataFrame({"value": [1]})
    fallback = pl.DataFrame(
        {
            "logical_endpoint_id": ["ep1"],
            "result_set_ordinal": [1],
            "value_json": ['{"kind":"string","value":"unmodeled"}'],
        }
    )

    async def fake_extract(
        entry: StagingEntry,
        params: dict[str, object],
        **_kwargs: object,
    ) -> _ExtractionTaskResult:
        params_json = json.dumps(params, sort_keys=True)
        return _ExtractionTaskResult(
            frames={
                entry.staging_key: wide,
                LOSSLESS_FALLBACK_STAGING_KEY: fallback,
            },
            pending_success=_PendingJournalSuccess(entry.endpoint_name, params_json, 2),
            source_endpoint_name=entry.endpoint_name,
            source_params_json=params_json,
            expected_staging_keys=(entry.staging_key, LOSSLESS_FALLBACK_STAGING_KEY),
        )

    monkeypatch.setattr(runner, "_extract_single_result", fake_extract)
    persisted: list[dict[str, object]] = []

    def persist(
        frames: dict[str, pl.DataFrame],
        *,
        expected_staging_keys: list[str],
        source_results: list[dict[str, object]],
    ) -> None:
        persisted.append(
            {
                "frames": frames,
                "expected": expected_staging_keys,
                "sources": source_results,
            }
        )

    entry = StagingEntry("ep1", "stg_ep1", "season")
    try:
        result = await runner.run_pattern_result(
            "season",
            [{"season": "2024-25"}],
            [entry],
            persist_chunk_results=persist,
            retain_frames=False,
        )
    finally:
        runner.shutdown()

    assert result.frames == {}
    assert result.row_count == 2
    assert result.is_complete
    assert len(persisted) == 1
    assert set(persisted[0]["frames"]) == {"stg_ep1", LOSSLESS_FALLBACK_STAGING_KEY}
    assert persisted[0]["expected"] == sorted(("stg_ep1", LOSSLESS_FALLBACK_STAGING_KEY))
    source_results = persisted[0]["sources"]
    assert isinstance(source_results, list)
    assert source_results[0]["expected_staging_keys"] == (
        "stg_ep1",
        LOSSLESS_FALLBACK_STAGING_KEY,
    )
    journal.record_success.assert_called_once_with("ep1", '{"season": "2024-25"}', 2)


@pytest.mark.asyncio
async def test_default_persisted_mode_still_returns_frames() -> None:
    class _Extractor:
        category = "default"
        endpoint_name = "ep1"

        async def extract(self, **params: object) -> pl.DataFrame:
            return pl.DataFrame({"season": [str(params["season"])]})

    runner = ExtractorRunner(
        _registry(_Extractor),
        _settings(default_chunk_size=1, adaptive_chunk_max_size=1),
        _journal(),
        rate_limit=10_000,
    )
    persisted: list[str] = []
    entry = StagingEntry("ep1", "stg_ep1", "season")
    try:
        result = await runner.run_pattern_result(
            "season",
            [{"season": "2023-24"}, {"season": "2024-25"}],
            [entry],
            persist_chunk_results=lambda frames: persisted.append(
                frames["stg_ep1"]["season"].item()
            ),
        )
    finally:
        runner.shutdown()

    assert persisted == ["2023-24", "2024-25"]
    assert result.frames["stg_ep1"]["season"].to_list() == persisted


@pytest.mark.asyncio
async def test_streaming_sink_failure_does_not_record_success_or_continue() -> None:
    calls: list[str] = []

    class _Extractor:
        category = "default"
        endpoint_name = "ep1"

        async def extract(self, **params: object) -> pl.DataFrame:
            season = str(params["season"])
            calls.append(season)
            return pl.DataFrame({"season": [season]})

    journal = _journal()
    runner = ExtractorRunner(
        _registry(_Extractor),
        _settings(default_chunk_size=1, adaptive_chunk_max_size=1),
        journal,
        rate_limit=10_000,
    )

    def fail_persist(_frames: dict[str, pl.DataFrame]) -> None:
        raise RuntimeError("durable sink unavailable")

    try:
        with pytest.raises(RuntimeError, match="durable sink unavailable"):
            await runner.run_pattern_result(
                "season",
                [{"season": "2023-24"}, {"season": "2024-25"}],
                [StagingEntry("ep1", "stg_ep1", "season")],
                persist_chunk_results=fail_persist,
                retain_frames=False,
            )
    finally:
        runner.shutdown()

    assert calls == ["2023-24"]
    journal.record_success.assert_not_called()


@pytest.mark.asyncio
async def test_discard_mode_requires_a_durable_sink_before_any_side_effect() -> None:
    journal = _journal()
    registry = _registry(object)
    runner = ExtractorRunner(registry, _settings(), journal)
    try:
        with pytest.raises(ValueError, match="requires persist_chunk_results"):
            await runner.run_pattern_result(
                "season",
                [{"season": "2024-25"}],
                [StagingEntry("ep1", "stg_ep1", "season")],
                retain_frames=False,
            )
    finally:
        runner.shutdown()

    registry.get.assert_not_called()
    journal.was_extracted_batch.assert_not_called()
    journal.record_start.assert_not_called()


@pytest.mark.asyncio
async def test_bounded_scheduler_cancels_live_children_and_never_starts_tail() -> None:
    runner = ExtractorRunner(
        _registry(object),
        _settings(thread_pool_size=2),
        _journal(),
    )
    started: list[int] = []
    active = 0
    window_full = asyncio.Event()
    never = asyncio.Event()

    async def blocked(index: int) -> dict[str, pl.DataFrame]:
        nonlocal active
        started.append(index)
        active += 1
        if active == 2:
            window_full.set()
        try:
            await never.wait()
            return {}
        finally:
            active -= 1

    parent = asyncio.create_task(
        runner._run_bounded_tasks([partial(blocked, index) for index in range(20)])
    )
    try:
        await asyncio.wait_for(window_full.wait(), timeout=1)
        parent.cancel()
        with pytest.raises(asyncio.CancelledError):
            await parent
        await asyncio.sleep(0)
    finally:
        runner.shutdown()

    assert started == [0, 1]
    assert active == 0


@pytest.mark.asyncio
async def test_bounded_scheduler_returns_failures_in_original_position() -> None:
    runner = ExtractorRunner(
        _registry(object),
        _settings(thread_pool_size=2),
        _journal(),
    )

    async def work(index: int) -> dict[str, pl.DataFrame]:
        if index == 1:
            raise RuntimeError("synthetic failure")
        await asyncio.sleep(0)
        return {"stg_ep": pl.DataFrame({"request_index": [index]})}

    try:
        execution = await runner._run_bounded_tasks([partial(work, index) for index in range(4)])
    finally:
        runner.shutdown()

    assert execution.results[0]["stg_ep"]["request_index"].item() == 0
    assert isinstance(execution.results[1], RuntimeError)
    assert str(execution.results[1]) == "synthetic failure"
    assert execution.results[2]["stg_ep"]["request_index"].item() == 2
    assert execution.results[3]["stg_ep"]["request_index"].item() == 3
