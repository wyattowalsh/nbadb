"""Tests for nbadb.orchestrate.extractor_runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import polars as pl
import pytest

from nbadb.core.config import NbaDbSettings
from nbadb.core.errors import (
    ExtractionError,
    TransientError,
)
from nbadb.core.errors import (
    ValidationError as NbaDbValidationError,
)
from nbadb.extract.base import BaseExtractor
from nbadb.orchestrate.execution_policy import build_execution_policy
from nbadb.orchestrate.extractor_runner import (
    ExtractorRunner,
    _AdaptiveThrottle,
    _DeferredExtraction,
    _ExtractionTaskResult,
    _FailedExtraction,
    _PendingJournalSuccess,
    _record_chunk_completion_heartbeat,
    _sync_extract,
)
from nbadb.orchestrate.resilience import _CircuitBreaker, _LatencyTracker
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
    j.was_extracted_batch.return_value = set()
    j.get_failed.return_value = failed or []
    return j


def _make_settings(**overrides):
    s = MagicMock()
    s.semaphore_tiers = {"default": 5}
    s.endpoint_semaphore_limits = {}
    s.pbp_chunk_size = 50
    s.default_chunk_size = 500
    s.thread_pool_size = 4
    s.adaptive_rate_min = 1.0
    s.adaptive_rate_recovery = 50
    s.endpoint_rate_limits = {}
    s.endpoint_request_timeouts = {}
    s.endpoint_chunk_size_limits = {}
    s.endpoint_retry_budgets = {}
    s.zero_progress_abort_endpoints = set()
    s.extract_max_retries = 0  # disable retries in unit tests by default
    s.extract_retry_base_delay = 0.0
    s.circuit_breaker_threshold = 5
    s.circuit_breaker_max_wait = 600.0
    s.latency_window_size = 10
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def test_record_chunk_completion_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    heartbeat_path = tmp_path / "chunk-heartbeat"
    monkeypatch.setenv("NBADB_EXTRACTION_HEARTBEAT_PATH", str(heartbeat_path))

    _record_chunk_completion_heartbeat()

    assert heartbeat_path.is_file()


def _make_registry(extractor_cls):
    r = MagicMock()
    r.get.return_value = extractor_cls
    return r


class TestSyncExtractBoundary:
    def test_wraps_retryable_errors_as_transient(self):
        class _Ext:
            endpoint_name = "ep1"

            async def extract(self, **kwargs):
                raise ConnectionError("boom")

        with pytest.raises(TransientError, match="ep1: transient extraction failure"):
            _sync_extract(_Ext())

    def test_wraps_non_retryable_errors_as_extraction(self):
        class _Ext:
            endpoint_name = "ep1"

            async def extract(self, **kwargs):
                raise RuntimeError("boom")

        with pytest.raises(ExtractionError, match="ep1: extraction failed"):
            _sync_extract(_Ext())

    def test_preserves_existing_taxonomy_errors(self):
        class _Ext:
            endpoint_name = "ep1"

            async def extract(self, **kwargs):
                raise NbaDbValidationError("already translated")

        with pytest.raises(NbaDbValidationError, match="already translated"):
            _sync_extract(_Ext())


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
        """HR-A-001: record_failure should use the translated error type, not str(exc)."""
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
        """HR-A-001: multi-path record_failure uses the translated type name."""
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
    async def test_required_out_of_range_index_fails(self):
        df0 = pl.DataFrame({"x": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(dfs=[df0]))
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
            StagingEntry("ep_multi", "stg_b", "season", result_set_index=5, use_multi=True),
        ]
        result = await runner._extract_multi_result("ep_multi", entries, {})
        assert result is not None
        assert isinstance(result, _FailedExtraction)
        assert result.status == "unexpected"
        assert result.error == "MissingRequiredResultSet:stg_b:5"
        journal.record_failure.assert_called_with(
            "ep_multi",
            "{}",
            "MissingRequiredResultSet:stg_b:5",
        )

    @pytest.mark.asyncio
    async def test_optional_out_of_range_index_returns_empty_df_without_warning(self):
        df0 = pl.DataFrame({"x": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(dfs=[df0]))
        runner = ExtractorRunner(registry, settings, journal)

        entries = [
            StagingEntry("ep_multi", "stg_a", "season", result_set_index=0, use_multi=True),
            StagingEntry(
                "ep_multi",
                "stg_optional",
                "season",
                result_set_index=5,
                use_multi=True,
                allow_missing_result_set=True,
            ),
        ]
        with patch("nbadb.orchestrate.extractor_runner.logger.warning") as warning:
            result = await runner._extract_multi("ep_multi", entries, {})

        assert result is not None
        assert result["stg_a"].shape[0] == 1
        assert result["stg_optional"].is_empty()
        warning.assert_not_called()


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

    @pytest.mark.asyncio
    async def test_run_pattern_explicit_skip_does_not_increment_journal_skip_counter(self):
        df = pl.DataFrame({"col": [10, 20]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            [entry],
            skip_items={("ep1", '{"season": "2024-25"}')},
        )

        assert result.get("stg_ep1", pl.DataFrame()).is_empty()
        assert runner.skipped == 1
        assert runner.skipped_due_to_journal == 0

    @pytest.mark.asyncio
    async def test_run_pattern_result_treats_explicit_retry_skip_as_complete(self):
        df = pl.DataFrame({"col": [10, 20]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern_result(
            "season",
            [{"season": "2024-25"}],
            [entry],
            skip_items={("ep1", '{"season": "2024-25"}')},
        )

        assert result.is_complete
        assert result.retry_skip_count == 1
        assert result.failure_count == 0

    @pytest.mark.asyncio
    async def test_run_pattern_persists_chunk_before_journal_success(self):
        class _SeasonEchoExtractor:
            category = "default"

            async def extract(self, **kwargs):
                return pl.DataFrame({"season": [kwargs["season"]]})

        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_SeasonEchoExtractor)
        runner = ExtractorRunner(registry, settings, journal)
        persist_events: list[str] = []

        def persist_chunk(frames: dict[str, pl.DataFrame]) -> None:
            assert journal.record_success.call_count == len(persist_events)
            persist_events.append(frames["stg_ep1"]["season"].item())

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern(
            "season",
            [{"season": "2024-25"}, {"season": "2025-26"}],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert persist_events == ["2024-25", "2025-26"]
        assert result["stg_ep1"].shape[0] == 2
        assert journal.record_success.call_count == 2

    @pytest.mark.asyncio
    async def test_run_pattern_passes_source_results_for_single_entries(self):
        df = pl.DataFrame({"season": ["2024-25"]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)
        captured_sources: list[list[dict[str, object]]] = []

        def persist_chunk(
            frames: dict[str, pl.DataFrame],
            *,
            expected_staging_keys: list[str],
            source_results: list[dict[str, object]],
        ) -> None:
            captured_sources.append(source_results)
            assert expected_staging_keys == ["stg_ep1"]
            source_frames = source_results[0]["frames"]
            assert isinstance(source_frames, dict)
            assert source_frames["stg_ep1"].equals(frames["stg_ep1"])

        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert len(captured_sources) == 1
        assert captured_sources[0][0]["source_endpoint_name"] == "ep1"
        assert captured_sources[0][0]["source_params_json"] == '{"season": "2024-25"}'
        assert captured_sources[0][0]["expected_staging_keys"] == ("stg_ep1",)
        source_frames = captured_sources[0][0]["frames"]
        assert isinstance(source_frames, dict)
        assert source_frames["stg_ep1"].equals(df)
        journal.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_pattern_passes_source_results_for_multi_endpoint(self):
        df0 = pl.DataFrame({"a": [1]})
        df1 = pl.DataFrame({"b": [2]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(dfs=[df0, df1]))
        runner = ExtractorRunner(registry, settings, journal)
        captured_sources: list[list[dict[str, object]]] = []

        def persist_chunk(
            _frames: dict[str, pl.DataFrame],
            *,
            source_results: list[dict[str, object]],
        ) -> None:
            captured_sources.append(source_results)

        entries = [
            StagingEntry("schedule", "stg_schedule", "season", result_set_index=0, use_multi=True),
            StagingEntry(
                "schedule",
                "stg_schedule_weeks",
                "season",
                result_set_index=1,
                use_multi=True,
            ),
        ]
        await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            entries,
            persist_chunk_results=persist_chunk,
        )

        assert len(captured_sources) == 1
        assert captured_sources[0][0]["source_endpoint_name"] == "schedule"
        assert captured_sources[0][0]["source_params_json"] == '{"season": "2024-25"}'
        assert captured_sources[0][0]["expected_staging_keys"] == (
            "stg_schedule",
            "stg_schedule_weeks",
        )
        source_frames = captured_sources[0][0]["frames"]
        assert isinstance(source_frames, dict)
        assert source_frames["stg_schedule"].equals(df0)
        assert source_frames["stg_schedule_weeks"].equals(df1)
        journal.record_success.assert_called_once()

    def test_source_results_for_persistence_requires_source_identity(self):
        result = _ExtractionTaskResult(
            frames={"stg_ep1": pl.DataFrame({"a": [1]})},
            pending_success=_PendingJournalSuccess("ep1", "{}", 1),
        )

        with pytest.raises(RuntimeError, match="missing source identity"):
            ExtractorRunner._source_results_for_persistence([result])

    @pytest.mark.asyncio
    async def test_run_pattern_does_not_mark_success_when_chunk_persist_fails(self):
        df = pl.DataFrame({"col": [10, 20]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        def fail_persist(_frames: dict[str, pl.DataFrame]) -> None:
            raise RuntimeError("staging unavailable")

        entry = StagingEntry("ep1", "stg_ep1", "season")
        with pytest.raises(RuntimeError, match="staging unavailable"):
            await runner.run_pattern(
                "season",
                [{"season": "2024-25"}],
                [entry],
                persist_chunk_results=fail_persist,
            )

        journal.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_pattern_persists_empty_chunk_before_journal_success(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(df=pl.DataFrame()))
        runner = ExtractorRunner(registry, settings, journal)
        persist_events: list[list[str]] = []

        def persist_chunk(
            frames: dict[str, pl.DataFrame],
            *,
            expected_staging_keys: list[str],
        ) -> None:
            assert frames == {}
            assert journal.record_success.call_count == 0
            persist_events.append(expected_staging_keys)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert persist_events == [["stg_ep1"]]
        assert result.get("stg_ep1", pl.DataFrame()).is_empty()
        journal.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_pattern_filters_chunk_metadata_for_callback_signature(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor(df=pl.DataFrame({"season": ["2024-25"]})))
        runner = ExtractorRunner(registry, settings, journal)
        chunk_indexes: list[int] = []

        def persist_chunk(
            frames: dict[str, pl.DataFrame],
            *,
            chunk_index: int,
        ) -> None:
            assert "stg_ep1" in frames
            chunk_indexes.append(chunk_index)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner.run_pattern(
            "season",
            [{"season": "2024-25"}],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert chunk_indexes == [0]

    @pytest.mark.asyncio
    async def test_deferred_multi_replay_preserves_eligible_entry_subset(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(default_chunk_size=1)
        registry = _make_registry(_make_extractor())
        runner = ExtractorRunner(registry, settings, journal)
        active = StagingEntry("ep_multi", "stg_active", "season", use_multi=True)
        filtered = StagingEntry("ep_multi", "stg_filtered", "season", use_multi=True)
        captured_entries: list[list[StagingEntry]] = []

        async def _capture_extract_multi_result(
            endpoint_name,
            entries,
            params,
            **kwargs,
        ):
            captured_entries.append(entries)
            return {}

        runner._extract_multi_result = _capture_extract_multi_result  # type: ignore[method-assign]

        await runner._replay_deferred_chunk(
            [
                _DeferredExtraction(
                    endpoint_name="ep_multi",
                    params={"season": "2024-25"},
                    wait_seconds=0,
                    eligible_staging_keys=("stg_active",),
                )
            ],
            single_by_key={},
            multi_by_ep={"ep_multi": [active, filtered]},
            on_progress=None,
            defer_journal_success=False,
        )

        assert captured_entries == [[active]]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("endpoint_name", "staging_key"),
        [
            ("scoreboard_v2", "stg_scoreboard"),
            ("scoreboard_v3", "stg_scoreboard_v3_metadata"),
        ],
    )
    async def test_run_pattern_replays_retryable_scoreboard_date_after_cooldown(
        self, endpoint_name: str, staging_key: str
    ):
        call_count = 0
        df = pl.DataFrame({"col": [10, 20]})

        class _ScoreboardExt:
            category = "game_log"

            async def extract_all(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise ConnectionError("transient")
                return [df]

        journal = _make_journal(already_done=False)
        settings = _make_settings(extract_max_retries=0, extract_retry_base_delay=0.0)
        registry = _make_registry(_ScoreboardExt)
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry(
            endpoint_name,
            staging_key,
            "date",
            result_set_index=0,
            use_multi=True,
        )
        with patch(
            "nbadb.orchestrate.extractor_runner.asyncio.sleep",
            new=AsyncMock(),
        ) as mock_sleep:
            result = await runner.run_pattern("date", [{"game_date": "02/11/1968"}], [entry])

        assert result[staging_key].shape[0] == 2
        assert call_count == 2
        assert runner.failed_current_run == 0
        journal.record_success.assert_called_once()
        journal.record_failure.assert_not_called()
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("endpoint_name", "staging_key"),
        [
            ("scoreboard_v2", "stg_scoreboard"),
            ("scoreboard_v3", "stg_scoreboard_v3_metadata"),
        ],
    )
    async def test_run_pattern_final_late_recovery_failure_records_once(
        self, endpoint_name: str, staging_key: str
    ):
        call_count = 0

        class _ScoreboardExt:
            category = "game_log"

            async def extract_all(self, **kwargs):
                nonlocal call_count
                call_count += 1
                raise ConnectionError("still transient")

        journal = _make_journal(already_done=False)
        settings = _make_settings(extract_max_retries=0, extract_retry_base_delay=0.0)
        registry = _make_registry(_ScoreboardExt)
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry(
            endpoint_name,
            staging_key,
            "date",
            result_set_index=0,
            use_multi=True,
        )
        with patch(
            "nbadb.orchestrate.extractor_runner.asyncio.sleep",
            new=AsyncMock(),
        ) as mock_sleep:
            result = await runner.run_pattern("date", [{"game_date": "02/11/1968"}], [entry])

        assert result == {}
        assert call_count == 2
        assert runner.failed_current_run == 1
        journal.record_success.assert_not_called()
        journal.record_failure.assert_called_once_with(
            endpoint_name,
            '{"game_date": "02/11/1968"}',
            "ConnectionError",
        )
        mock_sleep.assert_awaited_once_with(1.0)

    @pytest.mark.asyncio
    async def test_non_scoreboard_date_failure_does_not_defer(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(extract_max_retries=0, extract_retry_base_delay=0.0)
        registry = _make_registry(_make_extractor(exc=ConnectionError("boom")))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("video_status", "stg_video_status", "date")
        with patch(
            "nbadb.orchestrate.extractor_runner.asyncio.sleep",
            new=AsyncMock(),
        ) as mock_sleep:
            result = await runner.run_pattern("date", [{"game_date": "02/11/1968"}], [entry])

        assert result == {}
        assert runner.failed_current_run == 1
        journal.record_failure.assert_called_once_with(
            "video_status",
            '{"game_date": "02/11/1968"}',
            "ConnectionError",
        )
        mock_sleep.assert_not_awaited()


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
    async def test_prepare_extractor_sets_endpoint_timeout_override(self):
        class _Ext(BaseExtractor):
            endpoint_name = "ep1"
            category = "default"

            async def extract(self, **kwargs):
                return pl.DataFrame({"timeout": [self._request_timeout_override]})

        journal = _make_journal(already_done=False)
        settings = _make_settings(endpoint_request_timeouts={"ep1": 45})
        registry = MagicMock()
        registry.get.return_value = _Ext
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})

        assert result is not None
        assert result["stg_ep1"]["timeout"][0] == 45

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

    @pytest.mark.asyncio
    async def test_isolated_endpoint_failure_does_not_back_off_global_rate(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(endpoint_rate_limits={"ep1": 2.0})
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)
        original_limiter = runner._rate_limiter

        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner._extract_single(entry, {"season": "2024-25"})

        assert runner._rate_limiter is original_limiter
        assert runner._adaptive.current_rate == 10.0

    @pytest.mark.asyncio
    async def test_isolated_endpoint_uses_endpoint_limiter_instead_of_global_limiter(self):
        class _TrackedAsyncContext:
            def __init__(self):
                self.entered = 0

            async def __aenter__(self):
                self.entered += 1
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        df = pl.DataFrame({"a": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings(endpoint_rate_limits={"ep1": 2.0})
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)
        global_limiter = _TrackedAsyncContext()
        endpoint_limiter = _TrackedAsyncContext()
        runner._rate_limiter = global_limiter
        runner._endpoint_rate_limiters["ep1"] = endpoint_limiter

        entry = StagingEntry("ep1", "stg_ep1", "season")
        result = await runner._extract_single(entry, {"season": "2024-25"})

        assert result is not None
        assert global_limiter.entered == 0
        assert endpoint_limiter.entered == 1

    @pytest.mark.asyncio
    async def test_family_isolation_uses_family_limiter_without_backing_off_global_rate(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_family_overrides={"ep1": "player_history"},
            family_rate_limits={"player_history": 2.0},
        )
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal, rate_limit=10.0)
        original_limiter = runner._rate_limiter

        entry = StagingEntry("ep1", "stg_ep1", "season")
        await runner._extract_single(entry, {"season": "2024-25"})

        assert runner._rate_limiter is original_limiter
        assert runner._adaptive.current_rate == 10.0
        assert "player_history" in runner._family_rate_limiters

    def test_endpoint_semaphore_override_takes_precedence(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(endpoint_semaphore_limits={"ep1": 1})
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        semaphore = runner._get_semaphore("ep1", "default")
        assert semaphore._value == 1

    def test_family_semaphore_override_applies_when_endpoint_override_missing(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_family_overrides={"ep1": "player_history"},
            family_semaphore_limits={"player_history": 2},
        )
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        semaphore = runner._get_semaphore("ep1", "default")
        assert semaphore._value == 2

    def test_chunk_size_is_reduced_for_isolated_family(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_family_overrides={"ep1": "player_history"},
            family_chunk_multipliers={"player_history": 0.25},
            adaptive_chunk_min_size=10,
            adaptive_chunk_max_size=500,
            default_chunk_size=400,
        )
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        chunk_size = runner._chunk_size_for_entries(
            "player", [StagingEntry("ep1", "stg_ep1", "player")]
        )
        assert chunk_size == 100

    def test_direct_profile_player_history_chunk_size_fits_lane_timeout(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_family_overrides={"player_dash_game_splits": "player_history"},
            family_chunk_multipliers={
                "default": 1.0,
                "box_score": 1.0,
                "play_by_play": 0.5,
                "player_history": 0.001,
                "team_history": 0.5,
            },
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=100,
            default_chunk_size=1000,
        )
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        chunk_size = runner._chunk_size_for_entries(
            "player_season",
            [
                StagingEntry(
                    "player_dash_game_splits", "stg_player_dash_game_splits", "player_season"
                )
            ],
        )

        assert chunk_size == 1

    def test_endpoint_chunk_size_limit_can_be_smaller_than_adaptive_floor(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            endpoint_chunk_size_limits={"video_details_asset": 10},
            adaptive_chunk_min_size=25,
            adaptive_chunk_max_size=1000,
            default_chunk_size=1000,
        )
        runner = ExtractorRunner(_make_registry(_make_extractor()), settings, journal)

        chunk_size = runner._chunk_size_for_entries(
            "player_team_season",
            [
                StagingEntry(
                    "video_details_asset",
                    "stg_video_details_asset",
                    "player_team_season",
                )
            ],
        )

        assert chunk_size == 10

    def test_default_settings_isolate_slow_player_history_endpoints(self):
        settings = NbaDbSettings()

        assert settings.endpoint_semaphore_limits["player_awards"] == 1
        assert settings.endpoint_rate_limits["player_awards"] == 1.0
        assert settings.endpoint_request_timeouts["player_awards"] == 120
        assert settings.endpoint_semaphore_limits["player_career_stats"] == 1
        assert settings.endpoint_rate_limits["player_career_stats"] == 1.0
        assert settings.endpoint_request_timeouts["player_career_stats"] == 120
        assert settings.endpoint_semaphore_limits["video_details_asset"] == 2
        assert settings.endpoint_rate_limits["video_details_asset"] == 2.0
        assert settings.endpoint_request_timeouts["video_details_asset"] == 15
        assert settings.endpoint_chunk_size_limits["video_details_asset"] == 10
        assert settings.endpoint_retry_budgets["video_details_asset"] == 0
        assert settings.zero_progress_abort_endpoints == {"video_details_asset"}
        assert build_execution_policy("video_details_asset", settings=settings).retry_budget == 0

    @pytest.mark.asyncio
    async def test_endpoint_retry_budget_overrides_global_budget(self):
        class _CountingExtractor:
            category = "default"
            endpoint_name = "video_details_asset"
            calls = 0

            async def extract(self, **_kwargs):
                type(self).calls += 1
                raise TimeoutError("boom")

        journal = _make_journal(already_done=False)
        settings = _make_settings(
            extract_max_retries=6,
            endpoint_retry_budgets={"video_details_asset": 0},
        )
        registry = _make_registry(_CountingExtractor)
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )
        result = await runner._extract_single(entry, {"season": "2024-25"})

        assert result is None
        assert _CountingExtractor.calls == 1
        journal.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_progress_endpoint_aborts_after_first_fully_failed_chunk(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            default_chunk_size=100,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=100,
            endpoint_chunk_size_limits={"video_details_asset": 2},
            zero_progress_abort_endpoints={"video_details_asset"},
        )
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal)
        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )

        result = await runner.run_pattern_result(
            "player_team_season",
            [{"season": f"20{year:02d}-{year + 1:02d}"} for year in range(20, 25)],
            [entry],
        )

        assert result.eligible_calls == 2
        assert result.success_count == 0
        assert result.failure_count == 2
        assert any(error.startswith("zero_progress_chunk_abort:") for error in result.errors)
        assert journal.record_start.call_count == 2

    @pytest.mark.asyncio
    async def test_zero_progress_endpoint_continues_after_any_success(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            default_chunk_size=100,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=100,
            endpoint_chunk_size_limits={"video_details_asset": 2},
            zero_progress_abort_endpoints={"video_details_asset"},
        )
        registry = _make_registry(_make_extractor(df=pl.DataFrame()))
        runner = ExtractorRunner(registry, settings, journal)
        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )

        result = await runner.run_pattern_result(
            "player_team_season",
            [{"season": f"20{year:02d}-{year + 1:02d}"} for year in range(20, 25)],
            [entry],
        )

        assert result.eligible_calls == 5
        assert result.success_count == 5
        assert result.failure_count == 0
        assert not any(error.startswith("zero_progress_chunk_abort:") for error in result.errors)
        assert journal.record_start.call_count == 5

    @pytest.mark.asyncio
    async def test_zero_progress_abort_counts_only_newly_attempted_calls(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(
            default_chunk_size=2,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=2,
            endpoint_chunk_size_limits={"video_details_asset": 2},
            zero_progress_abort_endpoints={"video_details_asset"},
        )
        registry = _make_registry(_make_extractor(exc=TimeoutError("boom")))
        runner = ExtractorRunner(registry, settings, journal)
        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )
        params = [{"season": "2020-21"}, {"season": "2021-22"}]
        skipped = {
            (
                "video_details_asset",
                '{"season": "2020-21"}',
            )
        }

        result = await runner.run_pattern_result(
            "player_team_season",
            params,
            [entry],
            skip_items=skipped,
        )

        assert result.eligible_calls == 2
        assert result.retry_skip_count == 1
        assert result.failure_count == 1
        assert any("attempted=1:skipped=1" in error for error in result.errors)

    @pytest.mark.asyncio
    async def test_zero_progress_abort_preserves_prior_empty_chunk_durability(self):
        class _MixedExtractor:
            category = "default"
            endpoint_name = "video_details_asset"

            async def extract(self, **params):
                if params["season"] in {"2020-21", "2021-22"}:
                    return pl.DataFrame()
                raise TimeoutError("boom")

        journal = _make_journal(already_done=False)
        events: list[str] = []
        journal.record_success.side_effect = lambda *_args: events.append("journal-success")
        settings = _make_settings(
            default_chunk_size=2,
            adaptive_chunk_min_size=1,
            adaptive_chunk_max_size=2,
            endpoint_chunk_size_limits={"video_details_asset": 2},
            zero_progress_abort_endpoints={"video_details_asset"},
        )
        runner = ExtractorRunner(_make_registry(_MixedExtractor), settings, journal)
        entry = StagingEntry(
            "video_details_asset",
            "stg_video_details_asset",
            "player_team_season",
        )

        def persist_chunk(
            frames,
            *,
            expected_staging_keys,
            source_results,
            **_metadata,
        ):
            assert frames == {}
            assert expected_staging_keys == ["stg_video_details_asset"]
            assert len(source_results) == 2
            events.append("persist-empty-chunk")

        result = await runner.run_pattern_result(
            "player_team_season",
            [
                {"season": "2020-21"},
                {"season": "2021-22"},
                {"season": "2022-23"},
                {"season": "2023-24"},
                {"season": "2024-25"},
            ],
            [entry],
            persist_chunk_results=persist_chunk,
        )

        assert result.eligible_calls == 4
        assert result.success_count == 2
        assert result.failure_count == 2
        assert events == ["persist-empty-chunk", "journal-success", "journal-success"]
        assert any("chunk=1:attempted=2:skipped=0" in error for error in result.errors)
        assert journal.record_start.call_count == 4

    @pytest.mark.asyncio
    async def test_waits_for_open_circuit_breaker_instead_of_skipping(self):
        df = pl.DataFrame({"a": [1]})
        journal = _make_journal(already_done=False)
        settings = _make_settings()
        registry = _make_registry(_make_extractor(df=df))
        runner = ExtractorRunner(registry, settings, journal)

        entry = StagingEntry("ep1", "stg_ep1", "season")
        with (
            patch(
                "nbadb.orchestrate.resilience._CircuitBreaker.is_open",
                side_effect=[True, False],
            ),
            patch("nbadb.orchestrate.resilience._CircuitBreaker.retry_after", return_value=0.0),
            patch(
                "nbadb.orchestrate.extractor_runner.asyncio.sleep",
                new=AsyncMock(),
            ) as mock_sleep,
        ):
            result = await runner._extract_single(entry, {"season": "2024-25"})

        assert result is not None
        assert result["stg_ep1"].shape[0] == 1
        mock_sleep.assert_awaited_once_with(1.0)
        journal.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_open_circuit_breaker_timeout_records_failure(self):
        journal = _make_journal(already_done=False)
        settings = _make_settings(circuit_breaker_max_wait=5.0)
        registry = _make_registry(_make_extractor(df=pl.DataFrame({"a": [1]})))
        runner = ExtractorRunner(registry, settings, journal)
        runner._circuit_breaker = MagicMock()
        runner._circuit_breaker.is_open.side_effect = [True, True]
        runner._circuit_breaker.retry_after.return_value = 10.0

        entry = StagingEntry("ep1", "stg_ep1", "season")
        with (
            patch(
                "nbadb.orchestrate.extractor_runner.time.monotonic",
                side_effect=[0.0, 0.0, 5.1],
            ),
            patch(
                "nbadb.orchestrate.extractor_runner.asyncio.sleep",
                new=AsyncMock(),
            ) as mock_sleep,
        ):
            result = await runner._extract_single(entry, {"season": "2024-25"})

        assert result is None
        mock_sleep.assert_awaited_once_with(5.0)
        journal.record_failure.assert_called_once()
        assert journal.record_failure.call_args.args[2] == "_CircuitBreakerTimeoutError"


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
        [ConnectionError, ConnectionResetError],
    )
    def test_retryable_exceptions(self, exc_type):
        assert ExtractorRunner._is_retryable(exc_type("msg")) is True

    def test_ssl_error_is_retryable(self):
        class SSLError(Exception):
            pass

        assert ExtractorRunner._is_retryable(SSLError("msg")) is True

    @pytest.mark.parametrize(
        "exc_type",
        [ValueError, IndexError, TypeError],
    )
    def test_non_retryable_exceptions(self, exc_type):
        assert ExtractorRunner._is_retryable(exc_type("msg")) is False

    def test_json_decode_error(self):
        import json

        exc = json.JSONDecodeError("msg", "doc", 0)
        assert ExtractorRunner._is_retryable(exc) is False


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

    def test_progress_not_called_on_exception(self):
        accum = {"k": []}
        progress = MagicMock()
        ExtractorRunner._collect_results([RuntimeError("boom")], accum, progress)
        progress.advance_pattern.assert_not_called()

    def test_progress_called_on_success(self):
        df = pl.DataFrame({"a": [1]})
        accum = {"k": []}
        progress = MagicMock()
        ExtractorRunner._collect_results([{"k": df}], accum, progress)
        progress.advance_pattern.assert_called_once_with(success=True, rows=1)

    def test_progress_not_called_on_unexpected_type(self):
        accum = {"k": []}
        progress = MagicMock()
        ExtractorRunner._collect_results(["bad"], accum, progress)
        progress.advance_pattern.assert_not_called()


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


# ---------------------------------------------------------------------------
# _CircuitBreaker unit tests (HR-T-001)
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_trips_after_threshold(self):
        cb = _CircuitBreaker(threshold=3, recovery_seconds=60.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")
        assert cb.is_open("ep1") is False  # 2 < threshold
        cb.record_failure("ep1")
        assert cb.is_open("ep1") is True  # 3 >= threshold

    def test_recovery_allows_probe(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=1.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")
        assert cb.is_open("ep1") is True

        # Simulate recovery window elapsed
        with patch("nbadb.orchestrate.resilience.time") as mock_time:
            # First call to is_open reads monotonic for the trip
            # After recovery, monotonic should show elapsed time
            mock_time.monotonic.return_value = 999999.0
            assert cb.is_open("ep1") is False  # half-open: probe allowed

    def test_half_open_blocks_second_probe(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=1.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")

        with patch("nbadb.orchestrate.resilience.time") as mock_time:
            mock_time.monotonic.return_value = 999999.0
            # First probe allowed
            assert cb.is_open("ep1") is False
            # Second probe blocked (first still in flight)
            assert cb.is_open("ep1") is True

    def test_record_success_clears_probe(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=1.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")

        with patch("nbadb.orchestrate.resilience.time") as mock_time:
            mock_time.monotonic.return_value = 999999.0
            cb.is_open("ep1")  # transition to half-open, adds to probing set

        cb.record_success("ep1")
        assert "ep1" not in cb._half_open_probing
        assert cb.is_open("ep1") is False  # fully closed

    def test_record_failure_retrips(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=1.0)
        cb.record_failure("ep1")
        cb.record_failure("ep1")

        with patch("nbadb.orchestrate.resilience.time") as mock_time:
            mock_time.monotonic.return_value = 999999.0
            cb.is_open("ep1")  # half-open probe

        # Probe fails → re-trip
        cb.record_failure("ep1")
        assert "ep1" not in cb._half_open_probing
        assert cb.is_open("ep1") is True  # re-tripped

    def test_retry_after_returns_remaining_cooldown(self):
        cb = _CircuitBreaker(threshold=2, recovery_seconds=10.0)
        with patch("nbadb.orchestrate.resilience.time.monotonic", return_value=100.0):
            cb.record_failure("ep1")
            cb.record_failure("ep1")
        with patch("nbadb.orchestrate.resilience.time.monotonic", return_value=104.0):
            assert cb.retry_after("ep1") == pytest.approx(6.0)


# ---------------------------------------------------------------------------
# deprecated_after enforcement (HR-T-003)
# ---------------------------------------------------------------------------


class TestBuildChunkTasksDeprecated:
    def test_deprecated_entry_is_skipped(self):
        import asyncio

        settings = _make_settings()
        journal = _make_journal()
        registry = MagicMock()
        runner = ExtractorRunner(
            registry=registry,
            settings=settings,
            journal=journal,
            rate_limit=10.0,
        )

        deprecated_entry = StagingEntry(
            "old_ep", "stg_old", "season", deprecated_after="2020-01-01"
        )
        active_entry = StagingEntry("new_ep", "stg_new", "season")

        async def _run():
            return runner._build_chunk_tasks(
                single_entries=[deprecated_entry, active_entry],
                multi_by_ep={},
                chunk=[{"season": "2024-25"}],
                already_done=set(),
                on_progress=None,
            )

        batch = asyncio.run(_run())

        # Only the active entry should produce a task
        assert len(batch.tasks) == 1
        assert batch.eligible_calls == 1
        assert batch.support_skip_count == 1
        assert runner.skipped >= 1

    def test_non_deprecated_entry_proceeds(self):
        import asyncio

        settings = _make_settings()
        journal = _make_journal()
        registry = MagicMock()
        runner = ExtractorRunner(
            registry=registry,
            settings=settings,
            journal=journal,
            rate_limit=10.0,
        )

        entry = StagingEntry("ep1", "stg_ep1", "season")

        async def _run():
            return runner._build_chunk_tasks(
                single_entries=[entry],
                multi_by_ep={},
                chunk=[{"season": "2024-25"}],
                already_done=set(),
                on_progress=None,
            )

        batch = asyncio.run(_run())
        assert len(batch.tasks) == 1
        assert batch.eligible_calls == 1
        assert runner.skipped == 0


class TestSeasonYear:
    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"season": "2024-25"}, 2024),
            ({"season": "2024"}, 2024),
            ({"game_id": "0024800127"}, 1948),
            ({"game_id": "0020000730"}, 2000),
            ({"game_id": "0021500232"}, 2015),
            ({"game_id": "001"}, None),
        ],
    )
    def test_extracts_season_year_from_params(self, params, expected):
        assert ExtractorRunner._season_year(params) == expected


class TestBuildChunkTasksMinSeason:
    def test_game_entry_min_season_uses_game_id_year(self):
        import asyncio

        settings = _make_settings()
        journal = _make_journal()
        registry = MagicMock()
        runner = ExtractorRunner(
            registry=registry,
            settings=settings,
            journal=journal,
            rate_limit=10.0,
        )

        entry = StagingEntry(
            "box_score_misc",
            "stg_box_score_misc",
            "game",
            result_set_index=0,
            use_multi=True,
            min_season=1996,
        )

        async def _run():
            return runner._build_chunk_tasks(
                single_entries=[],
                multi_by_ep={"box_score_misc": [entry]},
                chunk=[{"game_id": "0024800127"}],
                already_done=set(),
                on_progress=None,
            )

        batch = asyncio.run(_run())

        assert batch.tasks == []
        assert batch.eligible_calls == 0
        assert batch.support_skip_count == 1
        assert runner.skipped == 1


# ---------------------------------------------------------------------------
# _LatencyTracker tests
# ---------------------------------------------------------------------------


class TestLatencyTracker:
    def test_record_and_percentile(self):
        lt = _LatencyTracker(window_size=10)
        for i in range(1, 11):
            lt.record("ep1", float(i))
        p50 = lt.percentile("ep1", 50)
        assert p50 is not None
        assert 4.0 <= p50 <= 6.0

    def test_percentile_empty_returns_none(self):
        lt = _LatencyTracker()
        assert lt.percentile("missing", 50) is None

    def test_summary(self):
        lt = _LatencyTracker(window_size=100)
        for i in range(1, 51):
            lt.record("ep1", float(i))
        s = lt.summary("ep1")
        assert s is not None
        assert "p50" in s
        assert "p95" in s
        assert "p99" in s
        assert s["count"] == 50.0

    def test_summary_missing_returns_none(self):
        lt = _LatencyTracker()
        assert lt.summary("missing") is None

    def test_all_summaries(self):
        lt = _LatencyTracker()
        lt.record("ep1", 1.0)
        lt.record("ep2", 2.0)
        sums = lt.all_summaries()
        assert "ep1" in sums
        assert "ep2" in sums

    def test_deque_window_eviction(self):
        lt = _LatencyTracker(window_size=3)
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            lt.record("ep1", v)
        # Window of 3 → only last 3 values (3.0, 4.0, 5.0)
        assert lt.summary("ep1")["count"] == 3.0
        p50 = lt.percentile("ep1", 50)
        assert p50 == 4.0
