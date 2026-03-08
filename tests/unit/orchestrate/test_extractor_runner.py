"""Tests for nbadb.orchestrate.extractor_runner."""

from __future__ import annotations

from unittest.mock import MagicMock

import polars as pl
import pytest

from nbadb.orchestrate.extractor_runner import ExtractorRunner, _assign_proxy
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
