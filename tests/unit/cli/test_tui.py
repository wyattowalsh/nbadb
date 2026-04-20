"""Tests for nbadb.cli.tui — Textual TUI dashboard components."""

from __future__ import annotations

import pytest

from nbadb.cli._progress_common import (
    DONE_CHAR,
    EMPTY_CHAR,
    PatternState,
    PatternStatus,
    fmt_time,
    gradient_bar,
    proportional_bar,
)
from nbadb.cli.tui import (
    _NBA_GOLD,
    _NBA_RED,
    NbaDbDashboard,
    Scoreboard,
    StatCard,
    TotalsStrip,
    TuiLogSink,
)

# ── shared _progress_common ────────────────────────────────


class TestPatternStatus:
    def test_values(self) -> None:
        assert PatternStatus.PENDING == "pending"
        assert PatternStatus.RUNNING == "running"
        assert PatternStatus.DONE == "done"

    def test_is_strenum(self) -> None:
        assert isinstance(PatternStatus.PENDING, str)


class TestPatternStateDefaults:
    def test_defaults(self) -> None:
        ps = PatternState(label="test", total=100)
        assert ps.completed == 0
        assert ps.succeeded == 0
        assert ps.failed == 0
        assert ps.skipped == 0
        assert ps.status == PatternStatus.PENDING
        assert ps.start_time == 0.0
        assert ps.end_time == 0.0


class TestGradientBar:
    def test_pct_zero(self) -> None:
        bar = gradient_bar(0.0, width=10)
        assert len(bar) == 10

    def test_pct_one(self) -> None:
        bar = gradient_bar(1.0, width=10)
        assert bar == DONE_CHAR * 10

    def test_above_one(self) -> None:
        bar = gradient_bar(1.5, width=10)
        assert bar == DONE_CHAR * 10

    def test_half_has_both(self) -> None:
        bar = gradient_bar(0.5, width=10)
        assert DONE_CHAR in bar
        assert EMPTY_CHAR in bar

    def test_default_width(self) -> None:
        bar = gradient_bar(0.5)
        assert len(bar) == 18

    def test_correct_length(self) -> None:
        for w in (4, 10, 16, 30):
            for pct in (0.0, 0.25, 0.5, 0.75, 1.0):
                assert len(gradient_bar(pct, width=w)) == w


class TestFmtTime:
    def test_seconds(self) -> None:
        assert fmt_time(0) == "0s"
        assert fmt_time(30) == "30s"
        assert fmt_time(59.9) == "60s"

    def test_minutes(self) -> None:
        assert fmt_time(60) == "1m00s"
        assert fmt_time(125) == "2m05s"
        assert fmt_time(3599) == "59m59s"

    def test_hours(self) -> None:
        assert fmt_time(3600) == "1h00m"
        assert fmt_time(7265) == "2h01m"


class TestProportionalBar:
    def test_all_zero(self) -> None:
        assert proportional_bar(0, 0, 0) == (0, 0, 0)

    def test_all_ok(self) -> None:
        ok_w, fail_w, skip_w = proportional_bar(100, 0, 0, width=28)
        assert ok_w == 28
        assert fail_w == 0
        assert skip_w == 0

    def test_all_fail(self) -> None:
        ok_w, fail_w, skip_w = proportional_bar(0, 100, 0, width=28)
        assert ok_w == 0
        assert fail_w + skip_w <= 28

    def test_mixed_sums_to_width(self) -> None:
        ok_w, fail_w, skip_w = proportional_bar(70, 20, 10, width=28)
        assert ok_w + fail_w + skip_w == 28

    def test_no_overflow(self) -> None:
        """Regression: bar width must never exceed requested width."""
        ok_w, fail_w, skip_w = proportional_bar(1, 50, 50, width=28)
        assert ok_w + fail_w + skip_w == 28
        assert ok_w >= 0


# ── Widget rendering ──────────────────────────────────────


class TestScoreboard:
    def test_render_basic(self) -> None:
        widget = Scoreboard(mode="TEST")
        text = widget.render()
        assert "NBADB" in text.plain
        assert "TEST" in text.plain

    def test_render_with_stats(self) -> None:
        widget = Scoreboard(mode="FULL")
        widget.set_stats(elapsed=120.0, ok=50, fail=3, phase="extracting")
        text = widget.render()
        assert "2m00s" in text.plain
        assert "extracting" in text.plain


class TestStatCard:
    def test_render_default(self) -> None:
        card = StatCard("games", "🎮")
        text = card.render()
        assert "0" in text.plain
        assert "games" in text.plain

    def test_render_with_value(self) -> None:
        card = StatCard("players", "👤")
        card.set_value(1_234)
        text = card.render()
        assert "1,234" in text.plain


class TestTotalsStrip:
    def test_render_empty(self) -> None:
        strip = TotalsStrip()
        text = strip.render()
        assert "Waiting" in text.plain

    def test_render_with_data(self) -> None:
        strip = TotalsStrip()
        strip.set_totals(ok=80, fail=15, skip=5)
        text = strip.render()
        assert "FGM" in text.plain
        assert "TO" in text.plain
        assert "DNP" in text.plain

    def test_render_no_failures(self) -> None:
        strip = TotalsStrip()
        strip.set_totals(ok=100, fail=0, skip=0)
        text = strip.render()
        assert "FGM" in text.plain
        assert "TO" not in text.plain


# ── TuiLogSink ────────────────────────────────────────────


class TestTuiLogSink:
    class FakeApp:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        def write_log(self, message: str, style: str = "") -> None:
            self.messages.append((message, style))

    def test_empty_message_skipped(self) -> None:
        app = self.FakeApp()
        sink = TuiLogSink(app)  # type: ignore[arg-type]
        sink.write("\n")
        assert app.messages == []

    def test_error_styled(self) -> None:
        app = self.FakeApp()
        sink = TuiLogSink(app)  # type: ignore[arg-type]
        sink.write("12:34:56 | ERROR   | something failed\n")
        assert len(app.messages) == 1
        assert app.messages[0][1] == _NBA_RED

    def test_warning_styled(self) -> None:
        app = self.FakeApp()
        sink = TuiLogSink(app)  # type: ignore[arg-type]
        sink.write("12:34:56 | WARNING | heads up\n")
        assert len(app.messages) == 1
        assert app.messages[0][1] == _NBA_GOLD

    def test_info_styled(self) -> None:
        app = self.FakeApp()
        sink = TuiLogSink(app)  # type: ignore[arg-type]
        sink.write("12:34:56 | INFO    | all good\n")
        assert len(app.messages) == 1
        assert app.messages[0][1] == ""

    def test_success_styled(self) -> None:
        app = self.FakeApp()
        sink = TuiLogSink(app)  # type: ignore[arg-type]
        sink.write("12:34:56 | SUCCESS | done\n")
        assert len(app.messages) == 1
        assert app.messages[0][1] == "green"

    def test_short_message_fallback(self) -> None:
        app = self.FakeApp()
        sink = TuiLogSink(app)  # type: ignore[arg-type]
        sink.write("short msg\n")
        assert len(app.messages) == 1
        assert app.messages[0][1] == "dim"


# ── NbaDbDashboard (headless) ─────────────────────────────


class TestDashboardInit:
    def test_constructor_defaults(self) -> None:
        app = NbaDbDashboard()
        assert app._mode == "INIT"
        assert app._run_fn is None
        assert app._settings is None
        assert app._orchestrator_cls is None
        assert app._patterns == []
        assert app._current_pattern is None

    def test_constructor_with_params(self) -> None:
        async def fake_fn(orch: object) -> None:
            pass

        app = NbaDbDashboard(
            mode="full",
            run_fn=fake_fn,
            settings={"key": "value"},
            orchestrator_cls=type,
        )
        assert app._mode == "FULL"
        assert app._run_fn is fake_fn
        assert app._settings == {"key": "value"}


class TestDashboardProgressProtocol:
    """Test progress protocol methods on the dashboard (without running the app)."""

    @pytest.fixture()
    def app(self) -> NbaDbDashboard:
        return NbaDbDashboard(mode="TEST")

    def test_start_pattern_creates_state(self, app: NbaDbDashboard) -> None:
        # Can't use widget methods without mounting, but state mutation works
        app._table = None  # ensure no widget access
        app.start_pattern("boxscore", total=100)
        assert len(app._patterns) == 1
        assert app._current_pattern is not None
        assert app._current_pattern.label == "boxscore"
        assert app._current_pattern.total == 100
        assert app._current_pattern.status == PatternStatus.RUNNING

    def test_start_pattern_ends_previous(self, app: NbaDbDashboard) -> None:
        app._table = None
        app.start_pattern("first", total=10)
        app.start_pattern("second", total=20)
        assert len(app._patterns) == 2
        assert app._patterns[0].status == PatternStatus.DONE
        assert app._patterns[0].end_time > 0
        assert app._current_pattern is not None
        assert app._current_pattern.label == "second"

    def test_advance_pattern_success(self, app: NbaDbDashboard) -> None:
        app._table = None
        app.start_pattern("test", total=100)
        app.advance_pattern(success=True)
        assert app._current_pattern is not None
        assert app._current_pattern.completed == 1
        assert app._current_pattern.succeeded == 1
        assert app._current_pattern.failed == 0

    def test_advance_pattern_failure(self, app: NbaDbDashboard) -> None:
        app._table = None
        app.start_pattern("test", total=100)
        app.advance_pattern(success=False)
        assert app._current_pattern is not None
        assert app._current_pattern.completed == 1
        assert app._current_pattern.failed == 1

    def test_advance_pattern_no_current(self, app: NbaDbDashboard) -> None:
        app.advance_pattern(success=True)  # should not raise

    def test_record_skip(self, app: NbaDbDashboard) -> None:
        app._table = None
        app.start_pattern("test", total=100)
        app.record_skip(5)
        assert app._current_pattern is not None
        assert app._current_pattern.completed == 5
        assert app._current_pattern.skipped == 5

    def test_record_skip_no_current(self, app: NbaDbDashboard) -> None:
        app.record_skip(1)  # should not raise

    def test_complete_phase_ends_pattern(self, app: NbaDbDashboard) -> None:
        app._table = None
        app.start_pattern("test", total=10)
        app.complete_phase()
        assert app._current_pattern is not None
        assert app._current_pattern.status == PatternStatus.DONE
        assert app._current_pattern.end_time > 0
        assert app._phase == ""

    def test_log_discovery(self, app: NbaDbDashboard) -> None:
        app.log_discovery("games", 42)
        assert app._discoveries == {"games": 42}
        app.log_discovery("teams", 30)
        assert app._discoveries == {"games": 42, "teams": 30}

    def test_start_phase(self, app: NbaDbDashboard) -> None:
        app.start_phase("discovery")
        assert app._phase == "discovery"
        assert app._phase_detail == ""

    def test_update_phase_info(self, app: NbaDbDashboard) -> None:
        app.start_phase("loading")
        app.update_phase_info("processing teams...")
        assert app._phase_detail == "processing teams..."


# ── run_with_tui ──────────────────────────────────────────


class TestRunWithTui:
    def test_import_succeeds(self) -> None:
        from nbadb.cli.tui import run_with_tui

        assert callable(run_with_tui)
