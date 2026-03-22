"""Tests for nbadb.orchestrate.extractor_runner."""

from __future__ import annotations

from unittest.mock import MagicMock

import polars as pl
import pytest

from nbadb.orchestrate.extractor_runner import ExtractorRunner, _AdaptiveThrottle, _assign_proxy
from nbadb.orchestrate.staging_map import StagingEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_extractor(
    df: pl.DataFrame | None = None,
    dfs: list[pl.DataFrame] | None = None,
    exc: Exception | None = None,
):
    """Build a mock extractor class + instance."""

    class _Ext:
        category = "default"
        _proxy_url = None

        async def extract(self, **kwargs):
            if exc:
                raise exc
            return df if df is not None else pl.DataFrame()

        async def extract_all(self, **kwargs):
            if exc:
                raise exc
            return dfs if dfs is not None else []

    return _Ext


def _make_journal(*, already_done: bool = False, failed: list | None = None):
    j = MagicMock()
    j.was_extracted.return_value = already_done
    j.get_failed.return_value = failed or []
    return j


def _make_settings(**overrides):
    s = MagicMock()
    s.semaphore_tiers = {"default": 5}
    s.proxy_semaphore_multiplier = 2.0
    s.pbp_chunk_size = 50
    s.default_chunk_size = 500
    s.thread_pool_size = 4
    s.adaptive_rate_min = 1.0
    s.adaptive_rate_recovery = 50
    s.extract_max_retries = 0  # disable retries in unit tests by default
    s.extract_retry_base_delay = 0.0
    s.circuit_breaker_threshold = 5
    s.latency_window_size = 10
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_registry(extractor_cls):
    r = MagicMock()
    r.get.return_value = extractor_cls
    return r


# ---------------------------------------------------------------------------
# _assign_proxy tests
# ---------------------------------------------------------------------------


class TestAssignProxy:
    def test_assigns_url_when_pool_provided(self):
        ext = MagicMock()
        pool = MagicMock()
        pool.get_proxy_url.return_value = "http://proxy:8080"
        _assign_proxy(ext, pool)
        assert ext._proxy_url == "http://proxy:8080"

    def test_noop_when_pool_is_none(self):
        ext = MagicMock()
        _assign_proxy(ext, None)
        pool_calls = [c for c in ext.method_calls if "proxy" in str(c)]
        assert pool_calls == []


# ---------------------------------------------------------------------------
# _extract_single tests
# ---------------------------------------------------------------------------


class TestExtractSingle:
    @pytest.mark.asyncio
    async def test_skip_when_already_extracted(self):
        journal = _make_journal(already_done=True)
        settings = _make_settings()
        registry = _make_registry(_make_extractor())
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})
        assert result is None
        journal.was_extracted.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_data_on_success(self):
        df = pl.DataFrame({"a": [1, 2, 3]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})
        assert result is not None
        assert "stg_ep1" in result
        assert result["stg_ep1"].shape[0] == 3
        journal.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_records_failure_with_type_name(self):
        """HR-A-001: record_failure should use type(exc).__name__, not str(exc)."""
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(exc=ConnectionError("proxy://secret:1234")))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})
        assert result is None
        call_args = journal.record_failure.call_args
        error_msg = call_args[0][2]
        assert error_msg == "ConnectionError"
        assert "secret" not in error_msg

    @pytest.mark.asyncio
    async def test_retries_on_transient_error(self):
        """Retry transient errors up to extract_max_retries times."""
        call_count = 0
        df = pl.DataFrame({"a": [1]})

        class _FlakyExt:
            endpoint_name = "ep1"
            category = "default"
            _proxy_url = None

            async def extract(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ConnectionError("transient")
                return df

        journal = _make_journal(already_done=False)
        settings = _make_settings(extract_max_retries=3, extract_retry_base_delay=0.0)
        registry = MagicMock()
        registry.get.return_value = _FlakyExt
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})
        assert result is not None
        assert call_count == 3  # 2 failures + 1 success
        journal.record_success.assert_called_once()
        journal.record_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_endpoint_returns_none(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = MagicMock()
        registry.get.side_effect = KeyError("no such endpoint")
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("missing_ep", "stg_missing", "season")
        result = await runner._extract_single(entry, {})
        assert result is None


# ---------------------------------------------------------------------------
# _extract_multi tests
# ---------------------------------------------------------------------------


class TestExtractMulti:
    @pytest.mark.asyncio
    async def test_skip_when_already_extracted(self):
        """HR-A-010: Single was_extracted check for the endpoint+params."""
        journal = _make_journal(already_done=True)
        settings = _make_settings()
        registry = _make_registry(_make_extractor())
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
            StagingEntry("ep_multi", "stg_b", "season", result_set_index=1, use_multi=True),
        ]
        result = await runner._extract_multi("ep_multi", entries, {"season": "2024-25"})
        assert result is None
        assert journal.was_extracted.call_count == 1

    @pytest.mark.asyncio
    async def test_fans_out_result_sets(self):
        df0 = pl.DataFrame({"x": [1]})
        df1 = pl.DataFrame({"y": [2, 3]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(dfs=[df0, df1]))
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
            StagingEntry("ep_multi", "stg_b", "season", result_set_index=1, use_multi=True),
        ]
        result = await runner._extract_multi("ep_multi", entries, {"season": "2024-25"})
        assert result is not None
        assert result["stg_a"].shape[0] == 1
        assert result["stg_b"].shape[0] == 2

    @pytest.mark.asyncio
    async def test_records_failure_with_type_name(self):
        """HR-A-001: record_failure in multi path uses type(exc).__name__."""
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(exc=TimeoutError("proxy://secret:9999")))
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
        ]
        result = await runner._extract_multi("ep_multi", entries, {"season": "2024-25"})
        assert result is None
        error_msg = journal.record_failure.call_args[0][2]
        assert error_msg == "TimeoutError"
        assert "secret" not in error_msg

    @pytest.mark.asyncio
    async def test_out_of_range_index_returns_empty_df(self):
        df0 = pl.DataFrame({"x": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(dfs=[df0]))
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
            StagingEntry("ep_multi", "stg_b", "season", result_set_index=5, use_multi=True),
        ]
        result = await runner._extract_multi("ep_multi", entries, {})
        assert result is not None
        assert result["stg_a"].shape[0] == 1
        assert result["stg_b"].is_empty()


# ---------------------------------------------------------------------------
# run_pattern tests
# ---------------------------------------------------------------------------


class TestRunPattern:
    @pytest.mark.asyncio
    async def test_run_pattern_single_entries(self):
        df = pl.DataFrame({"col": [10, 20]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern("season", [{"season": "2024-25"}], [entry])
        assert "stg_ep1" in result
        assert result["stg_ep1"].shape[0] == 2

    @pytest.mark.asyncio
    async def test_run_pattern_empty_params_returns_empty(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor())
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern("season", [], [entry])
        assert "stg_ep1" not in result or result.get("stg_ep1", pl.DataFrame()).is_empty()

    @pytest.mark.asyncio
    async def test_run_pattern_tolerates_schema_drift_across_param_sets(self):
        class _SchemaDriftExtractor:
            category = "default"
            _proxy_url = None

            async def extract(self, **kwargs):
                season = kwargs.get("season")
                if season == "2024-25":
                    return pl.DataFrame({"a": [1], "b": [2]})
                return pl.DataFrame({"a": [3], "c": [4]})

        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_SchemaDriftExtractor)
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern(
            "season",
            [{"season": "2024-25"}, {"season": "2025-26"}],
            [entry],
        )

        assert "stg_ep1" in result
        assert result["stg_ep1"].shape[0] == 2
        assert set(result["stg_ep1"].columns) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# Proxy integration in runner
# ---------------------------------------------------------------------------


class TestRunnerProxy:
    @pytest.mark.asyncio
    async def test_proxy_assigned_to_extractor(self):
        df = pl.DataFrame({"a": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        ext_cls = _make_extractor(df=df)
        registry = _make_registry(ext_cls)
        pool = MagicMock()
        pool.get_proxy_url.return_value = "http://proxy:8080"
        runner = ExtractorRunner(registry, settings, journal, proxy_pool=pool)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner._extract_single(entry, {})
        pool.get_proxy_url.assert_called_once()

    def test_semaphore_multiplied_with_proxy(self):
        journal = _make_journal()
        settings = _make_settings()
        settings.semaphore_tiers = {"default": 5}
        settings.proxy_semaphore_multiplier = 3.0
        pool = MagicMock()
        runner = ExtractorRunner(MagicMock(), settings, journal, proxy_pool=pool)

        sem = runner._get_semaphore("default")
        assert sem._value == 15


# ---------------------------------------------------------------------------
# _AdaptiveThrottle tests
# ---------------------------------------------------------------------------


class TestAdaptiveThrottle:
    def test_initial_rate_equals_base(self):
        t = _AdaptiveThrottle(base_rate=10.0)
        assert t.current_rate == 10.0

    def test_failure_reduces_rate(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0)
        new_rate = t.record_failure()
        assert new_rate is not None
        assert new_rate < 10.0
        assert t.current_rate == pytest.approx(7.0, abs=0.01)

    def test_multiple_failures_converge_to_min(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0)
        for _ in range(50):
            t.record_failure()
        assert t.current_rate == pytest.approx(1.0, abs=0.01)

    def test_recovery_after_sustained_success(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0, recovery_threshold=5)
        # Drive rate down
        for _ in range(5):
            t.record_failure()
        low_rate = t.current_rate
        assert low_rate < 10.0
        # Recover
        for _ in range(5):
            t.record_success()
        assert t.current_rate > low_rate

    def test_recovery_does_not_exceed_base_rate(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0, recovery_threshold=3)
        # Small dip then lots of recovery
        t.record_failure()
        for _ in range(100):
            t.record_success()
        assert t.current_rate <= 10.0

    def test_failure_resets_consecutive_success(self):
        t = _AdaptiveThrottle(base_rate=10.0, min_rate=1.0, recovery_threshold=5)
        t.record_failure()  # drop rate
        for _ in range(4):
            t.record_success()
        rate_before = t.current_rate
        t.record_failure()  # resets consecutive counter
        for _ in range(4):
            t.record_success()
        # Should NOT have recovered since we never hit 5 consecutive
        assert t.current_rate <= rate_before

    def test_no_rate_change_returns_none_on_success(self):
        t = _AdaptiveThrottle(base_rate=10.0, recovery_threshold=50)
        # At base rate, no change expected
        result = t.record_success()
        assert result is None


class TestAdaptiveThrottleIntegration:
    @pytest.mark.asyncio
    async def test_runner_backs_off_on_failure(self):
        """Verify the runner replaces its rate limiter after extraction failure."""
        journal = _make_journal(already_done=False)
        settings = _make_settings(adaptive_rate_recovery=5)
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)

        original_limiter = runner._rate_limiter
        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner._extract_single(entry, {"season": "2024-25"})

        # Rate limiter should have been replaced with a slower one
        assert runner._rate_limiter is not original_limiter
        assert runner._adaptive.current_rate < 10.0

    @pytest.mark.asyncio
    async def test_runner_recovers_after_sustained_success(self):
        """Verify the runner increases rate after consecutive successes."""
        df = pl.DataFrame({"a": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(adaptive_rate_recovery=3)
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)

        # First: drive rate down
        runner._adaptive.record_failure()
        runner._adaptive.record_failure()
        low_rate = runner._adaptive.current_rate

        # Now: run 3 successful extractions to trigger recovery
        for i in range(3):
            entry = StagingEntry(f"ep{i}", f"stg_ep{i}", "season")
            await runner._extract_single(entry, {"season": "2024-25"})

        assert runner._adaptive.current_rate > low_rate


# ---------------------------------------------------------------------------
# _drive_coroutine tests
# ---------------------------------------------------------------------------


class TestDriveCoroutine:
    def test_sync_coroutine_returns_value(self):
        from nbadb.orchestrate.extractor_runner import _drive_coroutine

        async def _coro():
            return 42

        assert _drive_coroutine(_coro()) == 42

    def test_raises_on_real_async(self):
        import asyncio

        from nbadb.orchestrate.extractor_runner import _drive_coroutine

        async def _coro():
            await asyncio.sleep(0)
            return 42

        with pytest.raises(RuntimeError, match="yielded unexpectedly"):
            _drive_coroutine(_coro())


# ---------------------------------------------------------------------------
# _sync_extract / _sync_extract_all tests
# ---------------------------------------------------------------------------


class TestSyncExtract:
    def test_basic_call(self):
        from nbadb.orchestrate.extractor_runner import _sync_extract

        class _Ext:
            async def extract(self, **kw):
                return pl.DataFrame({"x": [1]})

        result = _sync_extract(_Ext())
        assert result.shape == (1, 1)

    def test_passes_kwargs(self):
        from nbadb.orchestrate.extractor_runner import _sync_extract

        class _Ext:
            async def extract(self, **kw):
                return pl.DataFrame({"season": [kw["season"]]})

        result = _sync_extract(_Ext(), season="2024-25")
        assert result["season"][0] == "2024-25"


class TestSyncExtractAll:
    def test_basic_call(self):
        from nbadb.orchestrate.extractor_runner import _sync_extract_all

        class _Ext:
            async def extract_all(self, **kw):
                return [pl.DataFrame({"x": [1]}), pl.DataFrame({"y": [2]})]

        result = _sync_extract_all(_Ext())
        assert len(result) == 2
        assert result[0].shape == (1, 1)


# ---------------------------------------------------------------------------
# _is_retryable tests
# ---------------------------------------------------------------------------


class TestIsRetryable:
    @pytest.mark.parametrize(
        "exc_type",
        [ConnectionError, ConnectionResetError, TypeError],
    )
    def test_retryable_exceptions(self, exc_type):
        assert ExtractorRunner._is_retryable(exc_type("msg")) is True

    @pytest.mark.parametrize(
        "exc_type",
        [ValueError, KeyError, IndexError],
    )
    def test_non_retryable_exceptions(self, exc_type):
        assert ExtractorRunner._is_retryable(exc_type("msg")) is False

    def test_json_decode_error(self):
        import json

        exc = json.JSONDecodeError("msg", "doc", 0)
        assert ExtractorRunner._is_retryable(exc) is True


# ---------------------------------------------------------------------------
# _collect_results tests
# ---------------------------------------------------------------------------


class TestCollectResults:
    def test_base_exception_logged(self):
        accum = {"k": []}
        ExtractorRunner._collect_results([RuntimeError("boom")], accum, None)
        assert accum["k"] == []

    def test_none_skipped(self):
        accum = {"k": []}
        ExtractorRunner._collect_results([None], accum, None)
        assert accum["k"] == []

    def test_dict_result_merged(self):
        df = pl.DataFrame({"a": [1]})
        accum = {"k": []}
        ExtractorRunner._collect_results([{"k": df}], accum, None)
        assert len(accum["k"]) == 1

    def test_unexpected_type_logged(self):
        accum = {"k": []}
        ExtractorRunner._collect_results(["unexpected_string"], accum, None)
        assert accum["k"] == []

    def test_empty_df_not_added(self):
        accum = {"k": []}
        ExtractorRunner._collect_results([{"k": pl.DataFrame()}], accum, None)
        assert accum["k"] == []

    def test_progress_called_on_exception(self):
        accum = {"k": []}
        progress = MagicMock()
        ExtractorRunner._collect_results([RuntimeError("boom")], accum, progress)
        progress.advance_pattern.assert_called_once_with(success=False)

    def test_progress_called_on_success(self):
        df = pl.DataFrame({"a": [1]})
        accum = {"k": []}
        progress = MagicMock()
        ExtractorRunner._collect_results([{"k": df}], accum, progress)
        progress.advance_pattern.assert_called_once_with(success=True)

    def test_progress_called_on_unexpected_type(self):
        accum = {"k": []}
        progress = MagicMock()
        ExtractorRunner._collect_results(["bad"], accum, progress)
        progress.advance_pattern.assert_called_once_with(success=False)


# ---------------------------------------------------------------------------
# _concat_accum tests
# ---------------------------------------------------------------------------


class TestConcatAccum:
    def test_empty_list_excluded(self):
        result = ExtractorRunner._concat_accum({"k": []})
        assert "k" not in result

    def test_single_frame(self):
        df = pl.DataFrame({"a": [1, 2]})
        result = ExtractorRunner._concat_accum({"k": [df]})
        assert result["k"].shape[0] == 2

    def test_multiple_frames(self):
        df1 = pl.DataFrame({"a": [1]})
        df2 = pl.DataFrame({"a": [2]})
        result = ExtractorRunner._concat_accum({"k": [df1, df2]})
        assert result["k"].shape[0] == 2

    def test_schema_drift_diagonal(self):
        df1 = pl.DataFrame({"a": [1], "b": [2]})
        df2 = pl.DataFrame({"a": [3], "c": [4]})
        result = ExtractorRunner._concat_accum({"k": [df1, df2]})
        assert set(result["k"].columns) == {"a", "b", "c"}
