"""Unit tests for enhanced progress tracking features.

Covers ETAEstimator, fmt_eta, fmt_rows, PatternState.rows_extracted,
CIProgress, PipelineProgress throttling, NoopProgress, RunSummary,
and journal resume_summary / error_breakdown.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from unittest.mock import patch

import duckdb

from nbadb.cli._progress_common import (
    ETAEstimator,
    PatternState,
    RunSummary,
    fmt_eta,
    fmt_rows,
)
from nbadb.cli.progress import CIProgress, NoopProgress, PipelineProgress
from nbadb.orchestrate.journal import PipelineJournal

if TYPE_CHECKING:
    import pytest


# ---------------------------------------------------------------------------
# ETAEstimator
# ---------------------------------------------------------------------------


class TestETAEstimator:
    def test_warmup_returns_none(self) -> None:
        """First few updates should return None (insufficient data)."""
        est = ETAEstimator(min_samples=5, min_warmup_s=10.0)
        # First update always returns None
        assert est.update(1, 100) is None
        # Second update still in warmup
        assert est.update(2, 100) is None

    def test_basic_estimation(self) -> None:
        """After warmup, should return a reasonable positive estimate."""
        est = ETAEstimator(min_samples=3, min_warmup_s=0.0)

        # Patch time.monotonic to control timestamps precisely
        t = 100.0
        with patch("nbadb.cli._progress_common.time") as mock_time:
            for i in range(6):
                mock_time.monotonic.return_value = t + i * 5.0
                result = est.update(i * 10, 100)

            # After 6 samples across 25 seconds with warmup=0, should give estimate
            assert result is not None
            assert result > 0

    def test_zero_remaining_returns_zero(self) -> None:
        """When completed == total, should return 0."""
        est = ETAEstimator(min_samples=2, min_warmup_s=0.0)

        t = 0.0
        with patch("nbadb.cli._progress_common.time") as mock_time:
            for i in range(5):
                mock_time.monotonic.return_value = t + i * 2.0
                est.update(i * 25, 100)

            # Now completed == total
            mock_time.monotonic.return_value = t + 10.0
            result = est.update(100, 100)

        assert result == 0.0

    def test_backwards_movement_resets(self) -> None:
        """Backwards completed count should reset the estimator."""
        est = ETAEstimator(min_samples=3, min_warmup_s=0.0)

        t = 0.0
        with patch("nbadb.cli._progress_common.time") as mock_time:
            # Build up some state
            for i in range(5):
                mock_time.monotonic.return_value = t + i * 2.0
                est.update(i * 20, 100)

            # Backwards movement: completed drops from 80 back to 5
            mock_time.monotonic.return_value = t + 12.0
            result = est.update(5, 200)

        # Reset means warmup again -> None
        assert result is None
        # Internal state should be reset
        assert est._samples == 1

    def test_reset(self) -> None:
        """reset() should clear all internal state."""
        est = ETAEstimator()

        t = 0.0
        with patch("nbadb.cli._progress_common.time") as mock_time:
            mock_time.monotonic.return_value = t
            est.update(10, 100)
            mock_time.monotonic.return_value = t + 5.0
            est.update(20, 100)

        assert est._samples > 0

        est.reset()

        assert est._samples == 0
        assert est._rate == 0.0
        assert est._first_ts == 0.0
        assert est._last_ts == 0.0
        assert est._last_completed == 0


# ---------------------------------------------------------------------------
# fmt_eta
# ---------------------------------------------------------------------------


class TestFmtEta:
    def test_none_returns_warmup(self) -> None:
        assert fmt_eta(None) == "WARMUP"

    def test_zero_returns_tilde_zero(self) -> None:
        assert fmt_eta(0) == "~0s"

    def test_negative_returns_tilde_zero(self) -> None:
        assert fmt_eta(-5) == "~0s"

    def test_positive_formats_with_tilde(self) -> None:
        assert fmt_eta(90) == "~1m30s"

    def test_seconds_only(self) -> None:
        assert fmt_eta(45) == "~45s"

    def test_hours(self) -> None:
        assert fmt_eta(3661) == "~1h01m"


# ---------------------------------------------------------------------------
# fmt_rows
# ---------------------------------------------------------------------------


class TestFmtRows:
    def test_small_number(self) -> None:
        assert fmt_rows(42) == "42"

    def test_zero(self) -> None:
        assert fmt_rows(0) == "0"

    def test_thousands(self) -> None:
        assert fmt_rows(1500) == "2K"

    def test_exact_thousand(self) -> None:
        assert fmt_rows(1000) == "1K"

    def test_millions(self) -> None:
        assert fmt_rows(14_234_567) == "14.2M"

    def test_exact_million(self) -> None:
        assert fmt_rows(1_000_000) == "1.0M"

    def test_just_below_thousand(self) -> None:
        assert fmt_rows(999) == "999"


# ---------------------------------------------------------------------------
# PatternState.rows_extracted
# ---------------------------------------------------------------------------


class TestPatternState:
    def test_rows_extracted_default_zero(self) -> None:
        state = PatternState(label="test", total=100)
        assert state.rows_extracted == 0

    def test_rows_extracted_accumulates(self) -> None:
        state = PatternState(label="test", total=100)
        state.rows_extracted += 500
        state.rows_extracted += 300
        assert state.rows_extracted == 800

    def test_default_values(self) -> None:
        state = PatternState(label="season", total=50)
        assert state.completed == 0
        assert state.succeeded == 0
        assert state.failed == 0
        assert state.skipped == 0
        assert state.rows_extracted == 0
        assert state.status.value == "pending"


# ---------------------------------------------------------------------------
# CIProgress
# ---------------------------------------------------------------------------


class TestCIProgress:
    def test_context_manager(self) -> None:
        ci = CIProgress("test")
        with ci:
            pass  # should not raise

    def test_start_and_complete_phase(self, capsys: pytest.CaptureFixture[str]) -> None:
        ci = CIProgress("test")
        with ci:
            ci.start_phase("Discovery")
            ci.complete_phase()
        captured = capsys.readouterr()
        assert "Discovery" in captured.err

    def test_advance_pattern_periodic_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        ci = CIProgress("test")
        with ci:
            ci.start_pattern("season", 100)
            for _ in range(100):
                ci.advance_pattern(success=True, rows=10)
        captured = capsys.readouterr()
        assert "season" in captured.err

    def test_log_resume_context(self, capsys: pytest.CaptureFixture[str]) -> None:
        ci = CIProgress("test")
        with ci:
            ci.log_resume_context(1000, 50, 500000)
        captured = capsys.readouterr()
        assert "1,000" in captured.err

    def test_export_summary(self) -> None:
        ci = CIProgress("test")
        with ci:
            ci.start_pattern("season", 10)
            for _ in range(10):
                ci.advance_pattern(success=True, rows=100)
        summary = ci.export_summary()
        assert summary.mode == "test"
        assert len(summary.patterns) == 1
        assert summary.totals["succeeded"] == 10
        assert summary.totals["rows_extracted"] == 1000

    def test_gh_actions_group(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        ci = CIProgress("test")
        with ci:
            ci.start_phase("Discovery")
            ci.complete_phase()
        captured = capsys.readouterr()
        assert "::group::" in captured.err
        assert "::endgroup::" in captured.err

    def test_noop_methods(self) -> None:
        """Methods that exist for protocol compatibility should not raise."""
        ci = CIProgress("test")
        with ci:
            ci.update_rate_info(5.0, 10.0)
            ci.update_circuit_breakers([])
            ci.log_discovery("games", 100)

    def test_rate_degradation_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Rate dropping below 50% of base should trigger a warning."""
        ci = CIProgress("test")
        with ci:
            ci.update_rate_info(2.0, 10.0)
        captured = capsys.readouterr()
        assert "Rate degraded" in captured.err

    def test_circuit_breaker_warning(self, capsys: pytest.CaptureFixture[str]) -> None:
        ci = CIProgress("test")
        with ci:
            ci.update_circuit_breakers(["endpoint1", "endpoint2"])
        captured = capsys.readouterr()
        assert "Circuit breakers tripped" in captured.err
        assert "endpoint1" in captured.err

    def test_record_skip(self) -> None:
        ci = CIProgress("test")
        with ci:
            ci.start_pattern("season", 20)
            ci.record_skip(5)
        summary = ci.export_summary()
        assert summary.patterns[0]["skipped"] == 5

    def test_advance_pattern_with_failures(self) -> None:
        ci = CIProgress("test")
        with ci:
            ci.start_pattern("season", 10)
            for _ in range(7):
                ci.advance_pattern(success=True, rows=50)
            for _ in range(3):
                ci.advance_pattern(success=False, rows=0)
        summary = ci.export_summary()
        assert summary.totals["succeeded"] == 7
        assert summary.totals["failed"] == 3
        assert summary.totals["rows_extracted"] == 350


# ---------------------------------------------------------------------------
# PipelineProgress throttling
# ---------------------------------------------------------------------------


class TestPipelineProgressThrottle:
    @staticmethod
    def _start_pattern_no_refresh(progress: PipelineProgress, label: str, total: int) -> None:
        """Helper: start a pattern without calling _refresh (no Live context)."""
        from nbadb.cli._progress_common import PatternStatus

        state = PatternState(
            label=label,
            total=total,
            status=PatternStatus.RUNNING,
            start_time=time.monotonic(),
        )
        progress._patterns.append(state)
        progress._current_pattern = state

    def test_advance_pattern_throttled(self) -> None:
        """_refresh should not be called for every advance — only at 1% boundaries."""
        progress = PipelineProgress(mode="test")
        progress._start_time = time.monotonic()

        refresh_count = 0

        def counting_refresh() -> None:
            nonlocal refresh_count
            refresh_count += 1

        progress._refresh = counting_refresh  # type: ignore[assignment]

        self._start_pattern_no_refresh(progress, "season", 1000)
        for _ in range(1000):
            progress.advance_pattern(success=True, rows=10)

        # With total=1000, 1% step = 10, so ~100 boundary hits + 1 for completion
        # Plus a few for failures. Should be far less than 1000.
        assert refresh_count < 200
        assert refresh_count >= 10  # At least the 10% boundaries

    def test_record_skip_throttled(self) -> None:
        """record_skip should also throttle refreshes."""
        progress = PipelineProgress(mode="test")
        progress._start_time = time.monotonic()

        refresh_count = 0

        def counting_refresh() -> None:
            nonlocal refresh_count
            refresh_count += 1

        progress._refresh = counting_refresh  # type: ignore[assignment]

        self._start_pattern_no_refresh(progress, "season", 1000)
        for _ in range(1000):
            progress.record_skip(1)

        assert refresh_count < 200
        assert refresh_count >= 10


# ---------------------------------------------------------------------------
# NoopProgress
# ---------------------------------------------------------------------------


class TestNoopProgress:
    def test_context_manager(self) -> None:
        noop = NoopProgress()
        with noop:
            pass

    def test_new_methods_no_op(self) -> None:
        noop = NoopProgress()
        noop.log_resume_context(100, 5, 50000)
        noop.update_rate_info(5.0, 10.0)
        noop.update_circuit_breakers(["endpoint1"])
        summary = noop.export_summary()
        assert summary is not None
        assert isinstance(summary, RunSummary)

    def test_export_summary_empty(self) -> None:
        noop = NoopProgress()
        summary = noop.export_summary()
        assert summary.mode == ""
        assert summary.patterns == []
        assert summary.totals == {}

    def test_all_protocol_methods(self) -> None:
        """All protocol methods should silently accept calls."""
        noop = NoopProgress()
        noop.start_phase("phase", total=10)
        noop.update_phase_info("info")
        noop.complete_phase()
        noop.log_discovery("games", 100)
        noop.start_pattern("pattern", 50)
        noop.advance_pattern(success=True, rows=10)
        noop.record_skip(5)
        noop.log_resume_context(10, 2, 5000)
        noop.update_rate_info(1.0, 2.0)
        noop.update_circuit_breakers(["ep1"])


# ---------------------------------------------------------------------------
# RunSummary
# ---------------------------------------------------------------------------


class TestRunSummary:
    def test_default_values(self) -> None:
        s = RunSummary()
        assert s.mode == ""
        assert s.patterns == []
        assert s.totals == {}
        assert s.errors == []
        assert s.discoveries == {}
        assert s.duration_seconds == 0.0
        assert s.started_at == ""

    def test_custom_values(self) -> None:
        s = RunSummary(
            mode="full",
            patterns=[{"label": "season", "total": 10}],
            totals={"succeeded": 10},
        )
        assert s.mode == "full"
        assert len(s.patterns) == 1
        assert s.totals["succeeded"] == 10

    def test_independent_defaults(self) -> None:
        """Mutable default fields should be independent across instances."""
        s1 = RunSummary()
        s2 = RunSummary()
        s1.patterns.append({"label": "a"})
        assert len(s2.patterns) == 0


# ---------------------------------------------------------------------------
# Journal resume_summary / error_breakdown
# ---------------------------------------------------------------------------


def _create_journal_tables(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the _extraction_journal and _pipeline_metrics tables."""
    conn.execute("""
        CREATE TABLE _extraction_journal (
            endpoint VARCHAR NOT NULL,
            params VARCHAR,
            status VARCHAR NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            rows_extracted BIGINT,
            error_message VARCHAR,
            retry_count INTEGER DEFAULT 0,
            PRIMARY KEY (endpoint, params)
        )
    """)
    conn.execute("""
        CREATE TABLE _pipeline_metrics (
            endpoint VARCHAR NOT NULL,
            run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_seconds FLOAT,
            rows_extracted BIGINT,
            error_count INT DEFAULT 0,
            PRIMARY KEY (endpoint, run_timestamp)
        )
    """)


class TestJournalResumeSummary:
    def test_resume_summary_empty(self) -> None:
        """Empty journal should return all zeros."""
        conn = duckdb.connect(":memory:")
        _create_journal_tables(conn)
        journal = PipelineJournal(conn)

        summary = journal.resume_summary()
        assert summary["done"] == 0
        assert summary["failed"] == 0
        assert summary["running"] == 0
        assert summary["abandoned"] == 0
        assert summary["total_rows"] == 0
        conn.close()

    def test_resume_summary_with_data(self) -> None:
        """Insert done/failed entries, verify counts and row sums."""
        conn = duckdb.connect(":memory:")
        _create_journal_tables(conn)

        # Insert done entries
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, rows_extracted) "
            "VALUES ('ep1', 'p1', 'done', 100)"
        )
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, rows_extracted) "
            "VALUES ('ep2', 'p2', 'done', 250)"
        )
        # Insert failed entry
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, error_message) "
            "VALUES ('ep3', 'p3', 'failed', 'timeout')"
        )
        # Insert running entry
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status) "
            "VALUES ('ep4', 'p4', 'running')"
        )
        # Insert abandoned entry
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep5', 'p5', 'abandoned', 5)"
        )

        journal = PipelineJournal(conn)
        summary = journal.resume_summary()

        assert summary["done"] == 2
        assert summary["failed"] == 1
        assert summary["running"] == 1
        assert summary["abandoned"] == 1
        assert summary["total_rows"] == 350
        conn.close()

    def test_error_breakdown(self) -> None:
        """Insert failures with different error messages, verify grouping and ordering."""
        conn = duckdb.connect(":memory:")
        _create_journal_tables(conn)

        # Insert failures with different errors
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, error_message) "
            "VALUES ('ep1', 'p1', 'failed', 'timeout')"
        )
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, error_message) "
            "VALUES ('ep2', 'p2', 'failed', 'timeout')"
        )
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, error_message) "
            "VALUES ('ep3', 'p3', 'failed', 'timeout')"
        )
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, error_message) "
            "VALUES ('ep4', 'p4', 'failed', '429 rate limit')"
        )
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, error_message) "
            "VALUES ('ep5', 'p5', 'failed', '429 rate limit')"
        )
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, error_message) "
            "VALUES ('ep6', 'p6', 'failed', 'connection reset')"
        )
        # Also add a done entry — should not appear in error breakdown
        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, rows_extracted) "
            "VALUES ('ep7', 'p7', 'done', 100)"
        )

        journal = PipelineJournal(conn)
        breakdown = journal.error_breakdown()

        # Ordered by count descending
        assert len(breakdown) == 3
        assert breakdown[0] == ("timeout", 3)
        assert breakdown[1] == ("429 rate limit", 2)
        assert breakdown[2] == ("connection reset", 1)
        conn.close()

    def test_error_breakdown_empty(self) -> None:
        """No failures should return empty list."""
        conn = duckdb.connect(":memory:")
        _create_journal_tables(conn)
        journal = PipelineJournal(conn)

        breakdown = journal.error_breakdown()
        assert breakdown == []
        conn.close()

    def test_error_breakdown_null_message(self) -> None:
        """NULL error_message should be reported as 'Unknown'."""
        conn = duckdb.connect(":memory:")
        _create_journal_tables(conn)

        conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, error_message) "
            "VALUES ('ep1', 'p1', 'failed', NULL)"
        )

        journal = PipelineJournal(conn)
        breakdown = journal.error_breakdown()

        assert len(breakdown) == 1
        assert breakdown[0] == ("Unknown", 1)
        conn.close()

    def test_error_breakdown_limit(self) -> None:
        """Should respect the limit parameter."""
        conn = duckdb.connect(":memory:")
        _create_journal_tables(conn)

        for i in range(15):
            conn.execute(
                "INSERT INTO _extraction_journal (endpoint, params, status, error_message) "
                f"VALUES ('ep{i}', 'p{i}', 'failed', 'error_{i}')"
            )

        journal = PipelineJournal(conn)

        # Default limit is 10
        breakdown = journal.error_breakdown()
        assert len(breakdown) == 10

        # Custom limit
        breakdown = journal.error_breakdown(limit=3)
        assert len(breakdown) == 3
        conn.close()
