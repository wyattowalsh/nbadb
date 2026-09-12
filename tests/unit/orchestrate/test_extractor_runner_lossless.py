"""Adversarial runner coverage for the universal ``nba_api`` fallback route."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import polars as pl
import pytest
from nba_api.stats.endpoints import LeagueGameLog

from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
from nbadb.extract.base import BaseExtractor
from nbadb.extract.bronze import ParserInputContext
from nbadb.extract.nba_api_adapter import (
    LOSSLESS_FALLBACK_SCHEMA,
    LOSSLESS_FALLBACK_STAGING_KEY,
    NbaApiCaptureContract,
    NbaApiLosslessFallback,
    NbaApiResultPacket,
    NbaApiResultPackets,
)
from nbadb.orchestrate.extractor_runner import (
    ExtractorRunner,
    _ExtractionTaskResult,
    _FailedExtraction,
)
from nbadb.orchestrate.staging_map import StagingEntry

if TYPE_CHECKING:
    from collections.abc import Callable


def _settings(**overrides: object) -> MagicMock:
    settings = MagicMock()
    settings.semaphore_tiers = {"default": 5}
    settings.endpoint_semaphore_limits = {}
    settings.pbp_chunk_size = 50
    settings.default_chunk_size = 50
    settings.thread_pool_size = 2
    settings.adaptive_rate_min = 1.0
    settings.adaptive_rate_recovery = 50
    settings.endpoint_rate_limits = {}
    settings.endpoint_request_timeouts = {}
    settings.endpoint_chunk_size_limits = {}
    settings.endpoint_retry_budgets = {}
    settings.zero_progress_abort_endpoints = set()
    settings.response_contract_circuit_thresholds = {}
    settings.extract_max_retries = 0
    settings.extract_retry_base_delay = 0.0
    settings.circuit_breaker_threshold = 5
    settings.circuit_breaker_max_wait = 600.0
    settings.latency_window_size = 10
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


def _journal() -> MagicMock:
    journal = MagicMock()
    journal.was_extracted.return_value = False
    journal.was_extracted_batch.return_value = set()
    journal.get_failed.return_value = []
    return journal


def _registry(extractor_cls: type[BaseExtractor]) -> MagicMock:
    registry = MagicMock()
    registry.get.return_value = extractor_cls
    return registry


def _fallback(*, expected_result_set_count: int) -> NbaApiLosslessFallback:
    frame = pl.DataFrame(
        [
            {
                "response_receipt_sha256": None,
                "endpoint_slug": "leaguegamelog",
                "record_kind": "missing_expected",
                "result_set_name": "Missing",
                "result_set_occurrence": 0,
                "provider_index": None,
                "canonical_index": 0,
                "header_name": None,
                "header_ordinal": None,
                "row_ordinal": None,
                "value_kind": None,
                "canonical_json": None,
                "anomaly_codes_json": '["missing_result_set"]',
            }
        ],
        schema=LOSSLESS_FALLBACK_SCHEMA,
        orient="row",
    )
    return NbaApiLosslessFallback(
        endpoint_slug="leaguegamelog",
        reason_codes=("missing_result_set",),
        provider_result_set_count=0,
        expected_result_set_count=expected_result_set_count,
        result_set_receipts=(),
        frame=frame,
    )


def _wide_packet(*, canonical_index: int = 0) -> NbaApiResultPacket:
    return NbaApiResultPacket(
        name=f"Result{canonical_index}",
        provider_index=canonical_index,
        canonical_index=canonical_index,
        headers=("VALUE",),
        frame=pl.DataFrame({"VALUE": [canonical_index + 1]}),
    )


class _SingleExtractor(BaseExtractor):
    endpoint_name = "ep1"
    category = "default"

    async def extract(self, **params: object) -> pl.DataFrame:
        return self._from_nba_api(LeagueGameLog, **params)


class _MultiExtractor(BaseExtractor):
    endpoint_name = "ep1"
    category = "default"

    async def extract(self, **params: object) -> pl.DataFrame:
        return self._from_nba_api(LeagueGameLog, **params)

    async def extract_all(self, **params: object) -> list[pl.DataFrame]:
        return self._from_nba_api_multi(LeagueGameLog, **params)


class _CaptureFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.sinks: list[MagicMock] = []

    def __call__(self, _endpoint: str, _params: dict[str, object]) -> NbaApiCaptureContract:
        sink = MagicMock()

        def _record_logical_call(**_kwargs: object) -> str:
            self.events.append("logical-receipt")
            return "f" * 64

        sink.record_logical_call.side_effect = _record_logical_call
        self.sinks.append(sink)
        return NbaApiCaptureContract(
            sink=sink,
            context=ParserInputContext(attempt_id=f"lossless-{len(self.sinks)}"),
            provider_authority_sha256=expected_nba_api_provider_authority()["authority_sha256"],
            endpoint_contract_sha256="0" * 64,
        )


def _capturing_fetch(
    packets_factory: Callable[[str | None], NbaApiResultPackets],
    events: list[str],
) -> Callable[..., NbaApiResultPackets]:
    def _fetch(
        _endpoint_cls: type,
        *,
        capture: NbaApiCaptureContract | None = None,
        **_kwargs: object,
    ) -> NbaApiResultPackets:
        events.append("provider")
        receipt: str | None = None
        if capture is not None:
            receipt = chr(ord("a") + capture.context.retry_ordinal) * 64
            request_context = capture.begin_request()
            capture.record_receipt(request_context, receipt, successful=True)
        return packets_factory(receipt)

    return _fetch


@pytest.mark.asyncio
async def test_wide_and_fallback_persist_under_one_exact_logical_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    fallback = _fallback(expected_result_set_count=1)
    monkeypatch.setattr(
        "nbadb.extract.base.fetch_stats_packets",
        _capturing_fetch(
            lambda receipt: NbaApiResultPackets(
                (_wide_packet(),),
                lossless_fallback=(
                    fallback.bind_response_receipt(receipt) if receipt is not None else fallback
                ),
            ),
            events,
        ),
    )
    factory = _CaptureFactory(events)
    journal = _journal()
    persisted: list[dict[str, object]] = []

    def _persist(
        frames: dict[str, pl.DataFrame],
        *,
        expected_staging_keys: list[str],
        source_results: list[dict[str, object]],
    ) -> None:
        events.append("persist")
        persisted.append(
            {
                "frames": frames,
                "expected": expected_staging_keys,
                "sources": source_results,
            }
        )

    runner = ExtractorRunner(
        _registry(_SingleExtractor),
        _settings(),
        journal,
        capture_contract_factory=factory,
        call_admission=lambda *_args: events.append("static-admission"),
        conditional_route_admission=lambda *_args: events.append("conditional-admission"),
    )
    entry = StagingEntry("ep1", "stg_ep1", "season")

    result = await runner.run_pattern_result(
        "season",
        [{"season": "2024-25"}],
        [entry],
        persist_chunk_results=_persist,
        required_route_ids=("ep1:stg_ep1:0",),
    )

    fallback_route = f"ep1:{LOSSLESS_FALLBACK_STAGING_KEY}:1"
    assert events == [
        "static-admission",
        "provider",
        "conditional-admission",
        "logical-receipt",
        "persist",
    ]
    assert result.is_complete
    assert result.frames["stg_ep1"].to_dicts() == [{"value": 1, "season_year": "2024-25"}]
    assert result.frames[LOSSLESS_FALLBACK_STAGING_KEY][
        "response_receipt_sha256"
    ].unique().to_list() == ["a" * 64]
    source = persisted[0]["sources"]
    assert isinstance(source, list)
    assert len(source) == 1
    assert source[0]["expected_staging_keys"] == (
        "stg_ep1",
        LOSSLESS_FALLBACK_STAGING_KEY,
    )
    assert source[0]["result_route_ids_by_staging_key"] == tuple(
        sorted(
            (
                ("stg_ep1", "ep1:stg_ep1:0"),
                (LOSSLESS_FALLBACK_STAGING_KEY, fallback_route),
            )
        )
    )
    logical_call = factory.sinks[0].record_logical_call.call_args.kwargs
    assert logical_call["response_receipt_sha256s"] == ("a" * 64,)
    assert logical_call["successful_response_ordinals"] == (0,)
    assert logical_call["result_route_ids"] == tuple(sorted(("ep1:stg_ep1:0", fallback_route)))
    journal.record_success.assert_called_once()
    assert journal.record_success.call_args.args[2] == 2


@pytest.mark.asyncio
async def test_fallback_only_multi_response_is_successful_and_keeps_all_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    fallback = _fallback(expected_result_set_count=2)
    monkeypatch.setattr(
        "nbadb.extract.base.fetch_stats_packets",
        _capturing_fetch(
            lambda receipt: NbaApiResultPackets(
                lossless_fallback=fallback.bind_response_receipt(receipt or "a" * 64),
            ),
            events,
        ),
    )
    factory = _CaptureFactory(events)
    runner = ExtractorRunner(
        _registry(_MultiExtractor),
        _settings(),
        _journal(),
        capture_contract_factory=factory,
        conditional_route_admission=lambda *_args: events.append("conditional-admission"),
    )
    entries = [
        StagingEntry("ep1", "stg_first", "season", result_set_index=0, use_multi=True),
        StagingEntry("ep1", "stg_second", "season", result_set_index=1, use_multi=True),
    ]

    result = await runner._extract_multi_result("ep1", entries, {"season": "2024-25"})

    assert isinstance(result, _ExtractionTaskResult)
    assert result.frames["stg_first"].is_empty()
    assert result.frames["stg_second"].is_empty()
    assert result.frames[LOSSLESS_FALLBACK_STAGING_KEY].height == 1
    assert result.expected_staging_keys == (
        "stg_first",
        "stg_second",
        LOSSLESS_FALLBACK_STAGING_KEY,
    )
    assert result.pending_success is not None
    assert result.pending_success.rows == 1
    assert result.pending_success.receipt_binding is not None
    assert result.pending_success.receipt_binding.result_route_ids == tuple(
        sorted(
            (
                "ep1:stg_first:0",
                "ep1:stg_second:1",
                f"ep1:{LOSSLESS_FALLBACK_STAGING_KEY}:2",
            )
        )
    )


@pytest.mark.asyncio
async def test_no_capture_returns_unbound_fallback_without_receipt_route_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = _fallback(expected_result_set_count=1)
    monkeypatch.setattr(
        "nbadb.extract.base.fetch_stats_packets",
        lambda *_args, **_kwargs: NbaApiResultPackets(lossless_fallback=fallback),
    )
    journal = _journal()
    runner = ExtractorRunner(_registry(_SingleExtractor), _settings(), journal)
    entry = StagingEntry("ep1", "stg_ep1", "season")

    result = await runner._extract_single_result(entry, {"season": "2024-25"})

    assert isinstance(result, _ExtractionTaskResult)
    assert result.frames["stg_ep1"].is_empty()
    assert result.frames[LOSSLESS_FALLBACK_STAGING_KEY]["response_receipt_sha256"].null_count() == 1
    assert result.result_route_ids_by_staging_key == ()
    assert result.pending_success is not None
    assert result.pending_success.recorded
    journal.record_success.assert_called_once()


@pytest.mark.asyncio
async def test_retry_does_not_leak_first_attempt_fallback_into_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = _fallback(expected_result_set_count=1)

    class _RetryExtractor(_SingleExtractor):
        async def extract(self, **params: object) -> pl.DataFrame:
            result = self._from_nba_api(LeagueGameLog, **params)
            assert self._capture_contract is not None
            if self._capture_contract.context.retry_ordinal == 0:
                raise ConnectionError("retry after parsed response")
            return result

    def _packets(receipt: str | None) -> NbaApiResultPackets:
        if receipt == "a" * 64:
            return NbaApiResultPackets(lossless_fallback=fallback.bind_response_receipt(receipt))
        return NbaApiResultPackets((_wide_packet(),))

    events: list[str] = []
    monkeypatch.setattr(
        "nbadb.extract.base.fetch_stats_packets",
        _capturing_fetch(_packets, events),
    )
    factory = _CaptureFactory(events)
    runner = ExtractorRunner(
        _registry(_RetryExtractor),
        _settings(extract_max_retries=1),
        _journal(),
        capture_contract_factory=factory,
    )
    entry = StagingEntry("ep1", "stg_ep1", "season")

    result = await runner._extract_single_result(entry, {"season": "2024-25"})

    assert isinstance(result, dict)
    assert result["stg_ep1"].to_dicts() == [{"value": 1, "season_year": "2024-25"}]
    assert LOSSLESS_FALLBACK_STAGING_KEY not in result
    logical_call = factory.sinks[0].record_logical_call.call_args.kwargs
    assert logical_call["response_receipt_sha256s"] == ("a" * 64, "b" * 64)
    assert logical_call["result_route_ids"] == ("ep1:stg_ep1:0",)


@pytest.mark.asyncio
async def test_capture_enabled_multi_cache_never_cross_binds_fallback_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fallback = _fallback(expected_result_set_count=1)
    provider_calls = 0

    def _fetch(
        _endpoint_cls: type,
        *,
        capture: NbaApiCaptureContract | None = None,
        **_kwargs: object,
    ) -> NbaApiResultPackets:
        nonlocal provider_calls
        provider_calls += 1
        assert capture is not None
        receipt = chr(ord("a") + provider_calls - 1) * 64
        request_context = capture.begin_request()
        capture.record_receipt(request_context, receipt, successful=True)
        return NbaApiResultPackets(lossless_fallback=fallback.bind_response_receipt(receipt))

    events: list[str] = []
    monkeypatch.setattr(
        "nbadb.extract.base.fetch_stats_packets",
        _fetch,
    )
    factory = _CaptureFactory(events)
    runner = ExtractorRunner(
        _registry(_MultiExtractor),
        _settings(),
        _journal(),
        capture_contract_factory=factory,
        conditional_route_admission=lambda *_args: None,
    )
    entries = [StagingEntry("ep1", "stg_first", "season", result_set_index=0, use_multi=True)]

    first = await runner._extract_multi_result("ep1", entries, {"season": "2024-25"})
    second = await runner._extract_multi_result("ep1", entries, {"season": "2024-25"})

    assert isinstance(first, _ExtractionTaskResult)
    assert isinstance(second, _ExtractionTaskResult)
    assert provider_calls == 2
    assert runner._multi_cache == {}
    assert first.frames[LOSSLESS_FALLBACK_STAGING_KEY][
        "response_receipt_sha256"
    ].unique().to_list() == ["a" * 64]
    assert second.frames[LOSSLESS_FALLBACK_STAGING_KEY][
        "response_receipt_sha256"
    ].unique().to_list() == ["b" * 64]
    assert len(factory.sinks) == 2


@pytest.mark.asyncio
async def test_successor_fallback_fails_closed_without_conditional_route_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    fallback = _fallback(expected_result_set_count=1)
    monkeypatch.setattr(
        "nbadb.extract.base.fetch_stats_packets",
        _capturing_fetch(
            lambda receipt: NbaApiResultPackets(
                lossless_fallback=fallback.bind_response_receipt(receipt or "a" * 64),
            ),
            events,
        ),
    )
    factory = _CaptureFactory(events)
    journal = _journal()
    runner = ExtractorRunner(
        _registry(_SingleExtractor),
        _settings(),
        journal,
        capture_contract_factory=factory,
        call_admission=lambda *_args: events.append("static-admission"),
    )
    entry = StagingEntry("ep1", "stg_ep1", "season")

    result = await runner._extract_single_result(entry, {"season": "2024-25"})

    assert isinstance(result, _FailedExtraction)
    assert result.error == "ParserInputCaptureIntegrityError"
    assert events == ["static-admission", "provider"]
    factory.sinks[0].record_logical_call.assert_not_called()
    journal.record_success.assert_not_called()
    journal.record_failure.assert_called_once()
