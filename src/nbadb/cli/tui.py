"""Interactive Textual TUI dashboard for nbadb pipeline runs — NBA themed.

Features:
  - Split-pane layout: progress table + live scrolling log
  - NBA color theme (red/blue/gold)
  - Sparkline showing live req/s throughput
  - Digits widget for big stat counters
  - Animated progress bars per extraction pattern
  - Keyboard shortcuts: L=log, S=stats, Q=quit
  - Loguru integration — all logs stream into the log panel
"""

from __future__ import annotations

import contextlib
import time
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from textual.visual import VisualType
    from textual.widgets.data_table import RowKey

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.theme import Theme
from textual.widgets import (
    DataTable,
    Footer,
    ProgressBar,
    RichLog,
    Sparkline,
    Static,
)

from nbadb.cli._progress_common import (
    DONE_CHAR,
    SPINNER_FRAMES,
    ETAEstimator,
    PatternState,
    PatternStatus,
    RunSummary,
    fmt_eta,
    fmt_rows,
    fmt_time,
    gradient_bar,
    proportional_bar,
)

# ── constants ──────────────────────────────────────────────

# NBA official colors
_NBA_RED = "#C8102E"
_NBA_BLUE = "#1D428A"
_NBA_GOLD = "#FDB927"

_COLUMNS = ("", "PLAY", "PROGRESS", "%", "SCORE", "FG", "TO", "DNP", "TIME")

NBA_THEME = Theme(
    name="nba-dark",
    primary=_NBA_BLUE,
    secondary=_NBA_RED,
    accent=_NBA_GOLD,
    foreground="#E8E8E8",
    background="#0E1117",
    success="#00C853",
    warning=_NBA_GOLD,
    error=_NBA_RED,
    surface="#1A1D23",
    panel="#252830",
    dark=True,
    variables={
        "block-cursor-text-style": "bold",
        "footer-key-foreground": _NBA_GOLD,
    },
)

# ── log level style map ───────────────────────────────────
# Loguru format: {time:HH:mm:ss} | {level:<7} | {message}
# Level field occupies chars 11..18 (0-indexed).
_LEVEL_STYLES: dict[str, str] = {
    "ERROR": _NBA_RED,
    "CRITICA": _NBA_RED,  # CRITICAL truncated to 7 chars
    "WARNING": _NBA_GOLD,
    "SUCCESS": "green",
    "INFO": "",
    "DEBUG": "dim",
    "TRACE": "dim",
}


# ── custom widgets ─────────────────────────────────────────


class Scoreboard(Static):
    """NBA scoreboard header."""

    def __init__(
        self,
        mode: str = "INIT",
        content: VisualType = "",
        *,
        expand: bool = False,
        shrink: bool = False,
        markup: bool = True,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            content,
            expand=expand,
            shrink=shrink,
            markup=markup,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self._mode = mode
        self._elapsed = 0.0
        self._ok = 0
        self._fail = 0
        self._phase = ""
        self._eta_str = ""
        self._resuming = False
        self._current_rate = 0.0
        self._base_rate = 0.0
        self._tripped_count = 0

    def set_stats(self, elapsed: float, ok: int, fail: int, phase: str) -> None:
        self._elapsed = elapsed
        self._ok = ok
        self._fail = fail
        self._phase = phase
        self.refresh()

    def set_eta(self, s: str) -> None:
        self._eta_str = s

    def set_resuming(self, v: bool) -> None:
        self._resuming = v

    def set_rate(self, current: float, base: float) -> None:
        self._current_rate = current
        self._base_rate = base

    def set_breakers(self, tripped: list[str]) -> None:
        self._tripped_count = len(tripped)

    def render(self) -> Text:
        t = Text()
        t.append(" 🏀 ", style="")
        t.append(" NBADB ", style=f"bold bright_white on {_NBA_RED}")
        t.append(f" {self._mode} ", style=f"bold bright_white on {_NBA_BLUE}")
        if self._resuming:
            t.append(" RESUME ", style="bold bright_white on green")
        t.append(f"  ⏱ {fmt_time(self._elapsed)} ", style="bold")
        total = self._ok + self._fail
        if self._elapsed > 1 and total > 0:
            rate = total / self._elapsed
            t.append(f" ⚡{rate:.1f}/s ", style=f"bold {_NBA_GOLD}")
        if self._eta_str:
            t.append(f" │ {self._eta_str}", style="dim")
        if self._base_rate > 0 and self._current_rate < self._base_rate * 0.7:
            rate_str = f" ⚡{self._current_rate:.1f}/{self._base_rate:.0f}"
            t.append(rate_str, style=f"bold {_NBA_GOLD}")
        if self._tripped_count > 0:
            t.append(f" CB:{self._tripped_count}", style=f"bold {_NBA_RED}")
        if self._phase:
            t.append(f" │ {self._phase} ", style="italic dim")
        return t


class StatCard(Static):
    """Single stat with big number + label."""

    def __init__(
        self,
        label: str,
        icon: str = "📊",
        content: VisualType = "",
        *,
        expand: bool = False,
        shrink: bool = False,
        markup: bool = True,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            content,
            expand=expand,
            shrink=shrink,
            markup=markup,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self._label = label
        self._icon = icon
        self._value = 0

    def set_value(self, v: int) -> None:
        self._value = v
        self.refresh()

    def render(self) -> Text:
        t = Text()
        t.append(f" {self._icon} ", style="")
        t.append(f"{self._value:,}", style="bold bright_white")
        t.append(f" {self._label}", style="dim")
        return t


class TotalsStrip(Static):
    """Color-proportional bar + stats."""

    def __init__(
        self,
        content: VisualType = "",
        *,
        expand: bool = False,
        shrink: bool = False,
        markup: bool = True,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            content,
            expand=expand,
            shrink=shrink,
            markup=markup,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        self._ok = 0
        self._fail = 0
        self._skip = 0

    def set_totals(self, ok: int, fail: int, skip: int) -> None:
        self._ok = ok
        self._fail = fail
        self._skip = skip
        self.refresh()

    def render(self) -> Text:
        total = self._ok + self._fail + self._skip
        if not total:
            return Text(" Waiting for first pitch...", style="dim italic")

        ok_w, fail_w, skip_w = proportional_bar(
            self._ok,
            self._fail,
            self._skip,
            width=28,
        )

        t = Text(" ")
        if ok_w:
            t.append(DONE_CHAR * ok_w, style="green")
        if fail_w:
            t.append(DONE_CHAR * fail_w, style=_NBA_RED)
        if skip_w:
            t.append(DONE_CHAR * skip_w, style=_NBA_GOLD)
        t.append("  ")
        t.append(f"{self._ok:,}", style="bold green")
        t.append(" FGM", style="dim")
        if self._fail:
            t.append(f"  {self._fail:,}", style=f"bold {_NBA_RED}")
            t.append(" TO", style="dim")
        if self._skip:
            t.append(f"  {self._skip:,}", style=_NBA_GOLD)
            t.append(" DNP", style="dim")
        pct = self._ok / total * 100
        t.append(f"  │ FG% {pct:.1f}", style="bold")
        return t


# ── main app ───────────────────────────────────────────────

APP_CSS = """
Screen {
    layout: vertical;
}

#scoreboard {
    height: 1;
    dock: top;
    background: $surface;
}

#stats-row {
    height: 3;
    layout: horizontal;
    background: $panel;
    padding: 0 0;
}

.stat-card {
    width: 1fr;
    height: 3;
    content-align: center middle;
    border: round $primary;
}

#throughput-spark {
    width: 2fr;
    height: 3;
    border: round $accent;
    min-width: 20;
}

#throughput-spark > .sparkline--max-color {
    color: $accent;
}

#throughput-spark > .sparkline--min-color {
    color: $primary;
}

#main-split {
    height: 1fr;
}

#left-pane {
    width: 3fr;
    min-width: 50;
}

#right-pane {
    width: 2fr;
    min-width: 25;
}

#game-clock {
    height: 1fr;
    border: round $primary;
    border-title-color: $accent;
    border-title-style: bold;
}

DataTable > .datatable--header {
    background: $primary;
    color: $accent;
    text-style: bold;
}

DataTable > .datatable--even-row {
    background: $surface;
}

DataTable > .datatable--odd-row {
    background: $panel;
}

#overall-bar {
    height: 1;
    margin: 0 1;
}

#overall-bar Bar {
    color: $accent;
}

#overall-bar PercentageStatus {
    color: $accent;
    text-style: bold;
}

#totals-strip {
    height: 1;
    background: $surface;
}

#log-header {
    height: 1;
    background: $primary;
    color: $accent;
    text-style: bold;
    padding: 0 1;
}

#log-panel {
    height: 1fr;
    border: round $primary;
    border-title-color: $accent;
    scrollbar-size: 1 1;
    scrollbar-color: $primary;
    scrollbar-color-hover: $accent;
    scrollbar-color-active: $secondary;
}

Footer {
    background: $primary;
}

Footer > .footer--key {
    background: $secondary;
    color: white;
}

Footer > .footer--description {
    color: $accent;
}
"""


class NbaDbDashboard(App):
    """Interactive NBA-themed extraction dashboard."""

    CSS = APP_CSS
    TITLE = "NBADB"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("l", "toggle_log", "Log"),
        Binding("s", "toggle_stats", "Stats"),
    ]

    def __init__(
        self,
        mode: str = "INIT",
        *,
        run_fn: Callable[..., Awaitable[Any]] | None = None,
        settings: Any = None,
        orchestrator_cls: type | None = None,
    ) -> None:
        super().__init__()
        self._mode = mode.upper()
        self._run_fn = run_fn
        self._settings = settings
        self._orchestrator_cls = orchestrator_cls
        self._start_time = 0.0
        self._phase = ""
        self._phase_detail = ""
        self._discoveries: dict[str, int] = {}
        self._patterns: list[PatternState] = []
        self._current_pattern: PatternState | None = None
        self._tick = 0
        self._row_keys: dict[str, RowKey] = {}
        self._pipeline_result: object = None
        self._pipeline_error: Exception | None = None
        self._rate_history: deque[float] = deque([0.0] * 60, maxlen=60)
        self._last_total = 0
        self._stat_cards: dict[str, StatCard] = {}
        self._eta = ETAEstimator()
        self._resuming = False
        self._current_rate = 0.0
        self._base_rate = 0.0
        self._tripped: list[str] = []
        # Cached widget references — set in on_mount
        self._scoreboard: Scoreboard | None = None
        self._spark: Sparkline | None = None
        self._pbar: ProgressBar | None = None
        self._strip: TotalsStrip | None = None
        self._table: DataTable | None = None

    def compose(self) -> ComposeResult:
        yield Scoreboard(mode=self._mode, id="scoreboard")

        with Horizontal(id="stats-row"):
            games_card = StatCard("games", "🎮", id="stat-games", classes="stat-card")
            players_card = StatCard("players", "👤", id="stat-players", classes="stat-card")
            teams_card = StatCard("teams", "🏟️", id="stat-teams", classes="stat-card")
            dates_card = StatCard("dates", "📅", id="stat-dates", classes="stat-card")
            rows_card = StatCard("rows", "📊", id="stat-rows", classes="stat-card")
            self._stat_cards = {
                "games": games_card,
                "players": players_card,
                "teams": teams_card,
                "dates": dates_card,
                "rows": rows_card,
            }
            yield games_card
            yield players_card
            yield teams_card
            yield dates_card
            yield rows_card
            yield Sparkline(list(self._rate_history), summary_function=max, id="throughput-spark")

        with Horizontal(id="main-split"):
            with Vertical(id="left-pane"):
                yield DataTable(id="game-clock", zebra_stripes=True)
                yield ProgressBar(id="overall-bar", total=100, show_eta=False)
                yield TotalsStrip(id="totals-strip")
            with Vertical(id="right-pane"):
                yield Static(" 📋 PLAY-BY-PLAY LOG", id="log-header")
                yield RichLog(
                    id="log-panel",
                    highlight=True,
                    markup=True,
                    max_lines=5000,
                )
        yield Footer()

    def on_mount(self) -> None:
        # Register and apply NBA theme
        self.register_theme(NBA_THEME)
        self.theme = "nba-dark"

        self._start_time = time.monotonic()

        # Cache widget references
        self._scoreboard = self.query_one("#scoreboard", Scoreboard)
        self._spark = self.query_one("#throughput-spark", Sparkline)
        self._pbar = self.query_one("#overall-bar", ProgressBar)
        self._strip = self.query_one("#totals-strip", TotalsStrip)
        self._table = self.query_one("#game-clock", DataTable)

        # Set up progress table
        self._table.border_title = "🏀 GAME CLOCK"
        self._table.cursor_type = "none"
        self._table.add_columns(*_COLUMNS)

        # Start the clock ticker
        self.set_interval(0.5, self._tick_clock)

        # Welcome log
        log = self.query_one("#log-panel", RichLog)
        log.write(
            Text.assemble(
                ("🏀 NBADB ", f"bold {_NBA_RED}"),
                (f"{self._mode} ", f"bold {_NBA_BLUE}"),
                ("— game on!", "dim"),
            )
        )
        log.write("")

        # Start pipeline if configured
        if self._run_fn is not None:
            self._launch_pipeline()

    @property
    def pipeline_result(self) -> object:
        return self._pipeline_result

    @property
    def pipeline_error(self) -> Exception | None:
        return self._pipeline_error

    @work(exclusive=True, exit_on_error=False)
    async def _launch_pipeline(self) -> None:
        """Run the extraction pipeline inside Textual's event loop."""
        orch_cls = self._orchestrator_cls
        if orch_cls is None:
            from nbadb.orchestrate import Orchestrator

            orch_cls = Orchestrator

        orch = orch_cls(settings=self._settings, progress=self)
        try:
            self._pipeline_result = await self._run_fn(orch)  # type: ignore[misc]
        except Exception as exc:
            self._pipeline_error = exc
            self.write_log(f"❌ Pipeline failed: {type(exc).__name__}", f"bold {_NBA_RED}")
        else:
            self.write_log("", "")
            self.write_log("🏆 PERFECT GAME — Pipeline complete!", "bold green")
        finally:
            self.set_timer(3.0, self.exit)

    def _tick_clock(self) -> None:
        self._tick += 1
        elapsed = time.monotonic() - self._start_time if self._start_time else 0

        # Single-pass aggregation
        ok = fail = done = total = skipped = 0
        for p in self._patterns:
            ok += p.succeeded
            fail += p.failed
            done += p.completed
            total += p.total
            skipped += p.skipped

        # ETA estimation
        eta_secs = self._eta.update(done, total) if total > 0 else None

        # Total rows
        total_rows = sum(p.rows_extracted for p in self._patterns)

        # Update scoreboard
        if self._scoreboard is not None:
            self._scoreboard.set_stats(elapsed, ok, fail, self._phase_detail or self._phase)
            self._scoreboard.set_eta(fmt_eta(eta_secs))
            self._scoreboard.set_rate(self._current_rate, self._base_rate)
            self._scoreboard.set_breakers(self._tripped)

        # Update rows stat card
        rows_card = self._stat_cards.get("rows")
        if rows_card is not None:
            rows_card.set_value(total_rows)

        # Update throughput sparkline
        current_total = ok + fail
        delta = current_total - self._last_total
        self._last_total = current_total
        rate = delta / 0.5  # ticks every 0.5s
        self._rate_history.append(rate)
        if self._spark is not None:
            self._spark.data = list(self._rate_history)

        # Animate running pattern
        if self._current_pattern and self._current_pattern.status == PatternStatus.RUNNING:
            self._update_pattern_row(self._current_pattern)

        # Overall progress
        if self._pbar is not None and total > 0:
            self._pbar.update(total=total, progress=done)

        # Totals strip
        if self._strip is not None:
            self._strip.set_totals(ok, fail, skipped)

    def _update_pattern_row(self, p: PatternState) -> None:
        table = self._table
        if table is None:
            return
        key = self._row_keys.get(p.label)
        if key is None:
            return

        pct = p.completed / p.total if p.total else 0

        if p.status == PatternStatus.DONE:
            icon = "✓" if p.failed == 0 else "!"
            color = "green" if p.failed == 0 else _NBA_GOLD
        elif p.status == PatternStatus.RUNNING:
            icon = SPINNER_FRAMES[self._tick % len(SPINNER_FRAMES)]
            color = _NBA_GOLD
        else:
            icon = "○"
            color = "dim"

        bar = gradient_bar(pct, width=16)

        elapsed_str = ""
        if p.status == PatternStatus.DONE and p.end_time:
            elapsed_str = fmt_time(p.end_time - p.start_time)
        elif p.status == PatternStatus.RUNNING and p.start_time:
            eta_secs = p.eta.update(p.completed, p.total)
            elapsed_str = fmt_time(time.monotonic() - p.start_time)
            if eta_secs is not None:
                elapsed_str += f" {fmt_eta(eta_secs)}"

        cells = (
            Text(icon, style=color),
            Text(p.label, style="bold" if p.status == PatternStatus.RUNNING else ""),
            Text(bar, style=color),
            Text(f"{pct:>3.0%}", style=color),
            Text(f"{p.completed:,}/{p.total:,}"),
            Text(f"{p.succeeded:,}", style="green"),
            Text(f"{p.failed:,}", style=_NBA_RED) if p.failed else Text("0", style="dim"),
            Text(f"{p.skipped:,}", style=_NBA_GOLD) if p.skipped else Text("-", style="dim"),
            Text(elapsed_str, style="dim"),
        )

        try:
            with self.batch_update():
                for col, val in zip(_COLUMNS, cells, strict=True):
                    table.update_cell(key, col, val)
        except NoMatches:
            pass

    # ── actions ────────────────────────────────────────────

    def action_toggle_log(self) -> None:
        pane = self.query_one("#right-pane")
        pane.display = not pane.display

    def action_toggle_stats(self) -> None:
        row = self.query_one("#stats-row")
        row.display = not row.display

    # ── progress interface ─────────────────────────────────

    def write_log(self, message: str, style: str = "") -> None:
        try:
            log = self.query_one("#log-panel", RichLog)
        except (NoMatches, Exception):
            return
        if style:
            log.write(Text(message, style=style))
        else:
            log.write(message)

    def start_phase(self, name: str, total: int = 0) -> None:
        self._phase = name
        self._phase_detail = ""
        self.write_log("━" * 40, f"dim {_NBA_BLUE}")
        self.write_log(f"🏀 {name.upper()}", f"bold {_NBA_BLUE}")
        self.write_log("━" * 40, f"dim {_NBA_BLUE}")

    def update_phase_info(self, info: str) -> None:
        self._phase_detail = info
        self.write_log(f"  {info}", "dim")

    def _celebrate_pattern(self, p: PatternState) -> None:
        """Log a celebration message when a pattern finishes."""
        label = p.label
        if p.failed == 0:
            self.write_log(f"✓ {label} PERFECT", "bold green")
        elif p.total > 0 and p.failed / p.total > 0.05:
            pct = p.failed / p.total * 100
            self.write_log(f"⚠ {label} {pct:.1f}% turnover rate", _NBA_GOLD)
        else:
            self.write_log(f"✓ {label} complete ({p.failed} TO)", "green")

    def complete_phase(self) -> None:
        if self._current_pattern and self._current_pattern.status == PatternStatus.RUNNING:
            self._current_pattern.status = PatternStatus.DONE
            self._current_pattern.end_time = time.monotonic()
            self._update_pattern_row(self._current_pattern)
            self._celebrate_pattern(self._current_pattern)
        phase = self._phase or "Phase"
        self._phase = ""
        self._phase_detail = ""
        self.write_log(f"✓ {phase} complete", "green")

    def log_discovery(self, entity: str, count: int) -> None:
        self._discoveries[entity] = count
        card = self._stat_cards.get(entity)
        if card:
            card.set_value(count)
        self.write_log(f"  🔍 {entity}: {count:,}")

    def start_pattern(self, pattern: str, total: int) -> None:
        if self._current_pattern and self._current_pattern.status == PatternStatus.RUNNING:
            self._current_pattern.status = PatternStatus.DONE
            self._current_pattern.end_time = time.monotonic()
            self._update_pattern_row(self._current_pattern)
            self._celebrate_pattern(self._current_pattern)

        state = PatternState(
            label=pattern,
            total=total,
            status=PatternStatus.RUNNING,
            start_time=time.monotonic(),
        )
        self._patterns.append(state)
        self._current_pattern = state

        table = self._table
        if table is not None:
            row_key = table.add_row(
                Text(SPINNER_FRAMES[0], style=_NBA_GOLD),
                Text(pattern, style="bold"),
                Text(gradient_bar(0, width=16), style=_NBA_GOLD),
                Text("0%", style=_NBA_GOLD),
                Text(f"0/{total:,}"),
                Text("0", style="green"),
                Text("0", style="dim"),
                Text("-", style="dim"),
                Text("0s", style="dim"),
            )
            self._row_keys[pattern] = row_key
        self.write_log(f"🏀 {pattern}: {total:,} tasks", "bold")

    def advance_pattern(self, *, success: bool = True, rows: int = 0) -> None:
        if self._current_pattern is None:
            return
        self._current_pattern.completed += 1
        self._current_pattern.rows_extracted += rows
        if success:
            self._current_pattern.succeeded += 1
        else:
            self._current_pattern.failed += 1
            self.write_log(
                f"  ✗ {self._current_pattern.label} fail #{self._current_pattern.failed}",
                _NBA_RED,
            )
        # Throttle UI updates — every 1% or on failure
        c = self._current_pattern.completed
        t = self._current_pattern.total
        if c % max(1, t // 100) == 0 or c == t or not success:
            self._update_pattern_row(self._current_pattern)

    def record_skip(self, n: int = 1) -> None:
        if self._current_pattern is None:
            return
        self._current_pattern.completed += n
        self._current_pattern.skipped += n
        # Throttle like advance_pattern
        c = self._current_pattern.completed
        t = self._current_pattern.total
        if c % max(1, t // 100) == 0 or c == t:
            self._update_pattern_row(self._current_pattern)

    def log_resume_context(self, done: int, failed: int, rows: int) -> None:
        self._resuming = True
        if self._scoreboard is not None:
            self._scoreboard.set_resuming(True)
        self.write_log(
            f"🔄 RESUMING: {done:,} done, {failed:,} failed, "
            f"{fmt_rows(rows)} rows already extracted",
            "bold green",
        )

    def update_rate_info(self, current_rate: float, base_rate: float) -> None:
        self._current_rate = current_rate
        self._base_rate = base_rate

    def update_circuit_breakers(self, tripped: list[str]) -> None:
        if tripped and tripped != self._tripped:
            self.write_log(f"⚡ Circuit breakers open: {', '.join(tripped)}", _NBA_RED)
        self._tripped = tripped

    def export_summary(self) -> RunSummary:
        patterns = []
        for p in self._patterns:
            dur = (
                (p.end_time - p.start_time)
                if p.end_time
                else (time.monotonic() - p.start_time if p.start_time else 0)
            )
            patterns.append({
                "label": p.label, "total": p.total, "succeeded": p.succeeded,
                "failed": p.failed, "skipped": p.skipped, "rows": p.rows_extracted,
                "duration": dur,
            })
        ok = sum(p.succeeded for p in self._patterns)
        fail = sum(p.failed for p in self._patterns)
        skip = sum(p.skipped for p in self._patterns)
        rows = sum(p.rows_extracted for p in self._patterns)
        return RunSummary(
            mode=self._mode, started_at="", duration_seconds=time.monotonic() - self._start_time,
            discoveries=dict(self._discoveries), patterns=patterns,
            totals={"ok": ok, "fail": fail, "skip": skip, "rows": rows},
            errors=[],
        )


# ── loguru sink ────────────────────────────────────────────


class TuiLogSink:
    """Loguru sink that writes to the TUI's RichLog panel."""

    def __init__(self, app: NbaDbDashboard) -> None:
        self._app = app

    def write(self, message: str) -> None:
        msg = message.rstrip("\n")
        if not msg:
            return
        # Parse level from known fixed position in loguru format:
        #   {time:HH:mm:ss} | {level:<7} | {message}
        #   0         1
        #   0123456789012345678
        level = msg[11:18].strip().upper() if len(msg) > 18 else ""
        style = _LEVEL_STYLES.get(level, "dim")
        with contextlib.suppress(Exception):
            self._app.write_log(msg, style)


# ── public entry point ─────────────────────────────────────


def run_with_tui(
    mode: str,
    run_fn: Callable[..., Awaitable[Any]],
    settings: Any,
    orchestrator_cls: type | None = None,
) -> tuple[object, Exception | None, object]:
    """Run pipeline inside the Textual TUI.

    Returns (result, error, summary). The TUI app owns the event loop —
    the pipeline runs as an async worker inside it.
    """
    from loguru import logger

    app = NbaDbDashboard(
        mode=mode,
        run_fn=run_fn,
        settings=settings,
        orchestrator_cls=orchestrator_cls,
    )

    # Wire loguru into the TUI log panel — don't nuke existing sinks
    sink = TuiLogSink(app)
    sink_id = logger.add(
        sink.write,
        level="DEBUG",
        format="{time:HH:mm:ss} | {level:<7} | {message}",
    )

    try:
        app.run()
    finally:
        logger.remove(sink_id)

    summary = None
    with contextlib.suppress(Exception):
        summary = app.export_summary()

    return app.pipeline_result, app.pipeline_error, summary
