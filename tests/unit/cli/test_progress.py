"""Tests for nbadb.cli.progress — TUI dashboard components."""

from __future__ import annotations

import pytest
from rich.console import Console, Group

from nbadb.cli._progress_common import PatternState, fmt_time, gradient_bar
from nbadb.cli.progress import (
    NoopProgress,
    PipelineProgress,
)

# ── _gradient_bar ──────────────────────────────────────────


class TestGradientBar:
    def test_pct_zero_returns_all_empty(self) -> None:
        bar = gradient_bar(0.0, width=10)
        assert len(bar) == 10
        # First char is the partial block (space from _BAR_CHARS[0]),
        # remaining chars are empty blocks ░
        assert bar[1:] == "\u2591" * 9

    def test_pct_one_returns_all_full(self) -> None:
        bar = gradient_bar(1.0, width=10)
        assert len(bar) == 10
        assert all(c == "\u2588" for c in bar)  # █

    def test_pct_one_width_30(self) -> None:
        bar = gradient_bar(1.0, width=30)
        assert len(bar) == 30
        assert bar == "\u2588" * 30

    def test_half_returns_correct_length(self) -> None:
        bar = gradient_bar(0.5, width=30)
        assert len(bar) == 30

    def test_half_has_filled_and_empty(self) -> None:
        bar = gradient_bar(0.5, width=10)
        # First half should be filled blocks, second half empty
        assert "\u2588" in bar
        assert "\u2591" in bar

    def test_near_one_returns_correct_length(self) -> None:
        bar = gradient_bar(0.999, width=30)
        assert len(bar) == 30

    def test_small_width(self) -> None:
        bar = gradient_bar(0.5, width=4)
        assert len(bar) == 4

    def test_default_width_is_18(self) -> None:
        bar = gradient_bar(0.5)
        assert len(bar) == 18

    def test_above_one_treated_as_full(self) -> None:
        bar = gradient_bar(1.5, width=10)
        assert bar == "\u2588" * 10


# ── _PatternState ──────────────────────────────────────────


class TestPatternState:
    def test_defaults(self) -> None:
        ps = PatternState(label="test", total=100)
        assert ps.completed == 0
        assert ps.succeeded == 0
        assert ps.failed == 0
        assert ps.skipped == 0
        assert ps.status == "pending"  # PatternStatus.PENDING
        assert ps.start_time == 0.0
        assert ps.end_time == 0.0

    def test_custom_values(self) -> None:
        ps = PatternState(
            label="boxscore",
            total=50,
            completed=10,
            succeeded=8,
            failed=2,
            skipped=0,
            status="running",
            start_time=1.0,
        )
        assert ps.label == "boxscore"
        assert ps.total == 50
        assert ps.completed == 10


# ── PipelineProgress ───────────────────────────────────────


class TestPipelineProgress:
    @pytest.fixture()
    def console(self) -> Console:
        return Console(force_terminal=False, no_color=True, width=120)

    @pytest.fixture()
    def progress(self, console: Console) -> PipelineProgress:
        return PipelineProgress(mode="test", console=console)

    def test_constructor_defaults(self, progress: PipelineProgress) -> None:
        assert progress._mode == "test"
        assert progress._phase == ""
        assert progress._discoveries == {}
        assert progress._patterns == []
        assert progress._current_pattern is None

    def test_context_manager(self, console: Console) -> None:
        pp = PipelineProgress(mode="test", console=console)
        with pp as ctx:
            assert ctx is pp
            assert pp._live is not None
            assert pp._start_time > 0
        # After exit, live should have been stopped
        assert pp._live is not None  # object still exists but stopped

    def test_start_phase(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0  # avoid zero-time render issues
        progress.start_phase("discovery", total=5)
        assert progress._phase == "discovery"
        assert progress._phase_detail == ""

    def test_update_phase_info(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.start_phase("loading")
        progress.update_phase_info("processing teams...")
        assert progress._phase_detail == "processing teams..."

    def test_complete_phase(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.start_phase("loading")
        progress.complete_phase()
        assert progress._phase == ""
        assert progress._phase_detail == ""

    def test_complete_phase_ends_running_pattern(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.start_pattern("boxscore", total=10)
        assert progress._current_pattern is not None
        assert progress._current_pattern.status == "running"
        progress.complete_phase()
        assert progress._current_pattern.status == "done"
        assert progress._current_pattern.end_time > 0

    def test_log_discovery(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.log_discovery("games", 42)
        assert progress._discoveries == {"games": 42}
        progress.log_discovery("teams", 30)
        assert progress._discoveries == {"games": 42, "teams": 30}

    def test_start_pattern(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.start_pattern("boxscore", total=100)
        assert len(progress._patterns) == 1
        assert progress._current_pattern is not None
        assert progress._current_pattern.label == "boxscore"
        assert progress._current_pattern.total == 100
        assert progress._current_pattern.status == "running"

    def test_start_pattern_ends_previous(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.start_pattern("first", total=10)
        progress.start_pattern("second", total=20)
        assert len(progress._patterns) == 2
        assert progress._patterns[0].status == "done"
        assert progress._patterns[0].end_time > 0
        assert progress._current_pattern is not None
        assert progress._current_pattern.label == "second"

    def test_advance_pattern_success(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.start_pattern("test", total=5)
        progress.advance_pattern(success=True)
        assert progress._current_pattern is not None
        assert progress._current_pattern.completed == 1
        assert progress._current_pattern.succeeded == 1
        assert progress._current_pattern.failed == 0

    def test_advance_pattern_failure(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.start_pattern("test", total=5)
        progress.advance_pattern(success=False)
        assert progress._current_pattern is not None
        assert progress._current_pattern.completed == 1
        assert progress._current_pattern.succeeded == 0
        assert progress._current_pattern.failed == 1

    def test_advance_pattern_no_current(self, progress: PipelineProgress) -> None:
        # Should not raise when no current pattern
        progress.advance_pattern(success=True)

    def test_record_skip(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.start_pattern("test", total=10)
        progress.record_skip(3)
        assert progress._current_pattern is not None
        assert progress._current_pattern.completed == 3
        assert progress._current_pattern.skipped == 3

    def test_record_skip_no_current(self, progress: PipelineProgress) -> None:
        # Should not raise when no current pattern
        progress.record_skip(1)

    def test_record_skip_default_one(self, progress: PipelineProgress) -> None:
        progress._start_time = 1.0
        progress.start_pattern("test", total=10)
        progress.record_skip()
        assert progress._current_pattern is not None
        assert progress._current_pattern.skipped == 1


class TestFmtTime:
    def test_under_60_seconds(self) -> None:
        assert fmt_time(30) == "30s"
        assert fmt_time(0) == "0s"
        assert fmt_time(59.9) == "60s"

    def test_minutes(self) -> None:
        assert fmt_time(60) == "1m00s"
        assert fmt_time(125) == "2m05s"
        assert fmt_time(3599) == "59m59s"

    def test_hours(self) -> None:
        assert fmt_time(3600) == "1h00m"
        assert fmt_time(7265) == "2h01m"


class TestRenderMethods:
    @pytest.fixture()
    def console(self) -> Console:
        return Console(force_terminal=False, no_color=True, width=120)

    @pytest.fixture()
    def progress(self, console: Console) -> PipelineProgress:
        pp = PipelineProgress(mode="test", console=console)
        pp._start_time = 1.0
        return pp

    def test_render_returns_group(self, progress: PipelineProgress) -> None:
        result = progress._render()
        assert isinstance(result, Group)

    def test_render_final_returns_group(self, progress: PipelineProgress) -> None:
        result = progress._render(final=True)
        assert isinstance(result, Group)

    def test_render_discovery_after_log(self, progress: PipelineProgress) -> None:
        progress.log_discovery("games", 82)
        progress.log_discovery("teams", 30)
        panel = progress._render_discovery()
        assert panel is not None

    def test_render_extraction_with_patterns(self, progress: PipelineProgress) -> None:
        progress.start_pattern("boxscore", total=50)
        progress.advance_pattern(success=True)
        panel = progress._render_extraction()
        assert panel is not None

    def test_render_extraction_final(self, progress: PipelineProgress) -> None:
        progress.start_pattern("boxscore", total=50)
        panel = progress._render_extraction(final=True)
        assert panel is not None

    def test_render_totals_empty(self, progress: PipelineProgress) -> None:
        # No patterns → empty text
        from rich.text import Text

        result = progress._render_totals()
        assert isinstance(result, Text)

    def test_render_totals_with_data(self, progress: PipelineProgress) -> None:
        progress.start_pattern("p1", total=10)
        for _ in range(7):
            progress.advance_pattern(success=True)
        for _ in range(2):
            progress.advance_pattern(success=False)
        progress.record_skip(1)
        result = progress._render_totals()
        assert result is not None

    def test_render_totals_final_with_failures(self, progress: PipelineProgress) -> None:
        progress.start_pattern("p1", total=3)
        progress.advance_pattern(success=True)
        progress.advance_pattern(success=False)
        progress.record_skip(1)
        result = progress._render_totals(final=True)
        assert result is not None

    def test_render_totals_final_perfect(self, progress: PipelineProgress) -> None:
        progress.start_pattern("p1", total=2)
        progress.advance_pattern(success=True)
        progress.advance_pattern(success=True)
        result = progress._render_totals(final=True)
        assert result is not None


# ── NoopProgress ───────────────────────────────────────────


class TestNoopProgress:
    def test_context_manager(self) -> None:
        noop = NoopProgress()
        with noop as ctx:
            assert ctx is noop

    def test_all_methods_callable(self) -> None:
        noop = NoopProgress()
        # None of these should raise
        noop.start_phase("phase", total=10)
        noop.update_phase_info("info")
        noop.complete_phase()
        noop.log_discovery("games", 100)
        noop.start_pattern("pattern", 50)
        noop.advance_pattern(success=True)
        noop.advance_pattern(success=False)
        noop.record_skip(3)

    def test_methods_return_none(self) -> None:
        noop = NoopProgress()
        assert noop.start_phase("x") is None
        assert noop.update_phase_info("x") is None
        assert noop.complete_phase() is None
        assert noop.log_discovery("x", 1) is None
        assert noop.start_pattern("x", 1) is None
        assert noop.advance_pattern(success=True) is None
        assert noop.record_skip() is None
