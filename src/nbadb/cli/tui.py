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
from dataclasses import dataclass

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import (
    DataTable,
    Footer,
    ProgressBar,
    RichLog,
    Sparkline,
    Static,
)

# ── constants ──────────────────────────────────────────────
_BAR_CHARS = " ▏▎▍▌▋▊▉█"
_DONE = "█"
_EMPTY = "░"
_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_ICONS = {"games": "🎮", "players": "👤", "teams": "🏟️ ", "dates": "📅"}

# NBA official colors
_NBA_RED = "#C8102E"
_NBA_BLUE = "#1D428A"
_NBA_GOLD = "#FDB927"

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


def _gradient_bar(pct: float, width: int = 18) -> str:
    if pct >= 1.0:
        return _DONE * width
    filled = pct * width
    full = int(filled)
    rem = filled - full
    pidx = int(rem * (len(_BAR_CHARS) - 1))
    partial = _BAR_CHARS[pidx] if full < width else ""
    empty = width - full - (1 if partial else 0)
    return _DONE * full + partial + _EMPTY * empty


def _fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


@dataclass
class PatternState:
    label: str
    total: int
    completed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    status: str = "pending"
    start_time: float = 0.0
    end_time: float = 0.0


# ── custom widgets ─────────────────────────────────────────


class Scoreboard(Static):
    """NBA scoreboard header."""

    def __init__(self, mode: str = "INIT", **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._mode = mode
        self._elapsed = 0.0
        self._ok = 0
        self._fail = 0
        self._phase = ""

    def set_stats(self, elapsed: float, ok: int, fail: int, phase: str) -> None:
        self._elapsed = elapsed
        self._ok = ok
        self._fail = fail
        self._phase = phase
        self.refresh()

    def render(self) -> Text:
        t = Text()
        t.append(" 🏀 ", style="")
        t.append(" NBADB ", style=f"bold bright_white on {_NBA_RED}")
        t.append(f" {self._mode} ", style=f"bold bright_white on {_NBA_BLUE}")
        t.append(f"  ⏱ {_fmt_time(self._elapsed)} ", style="bold")
        total = self._ok + self._fail
        if self._elapsed > 1 and total > 0:
            rate = total / self._elapsed
            t.append(f" ⚡{rate:.1f}/s ", style=f"bold {_NBA_GOLD}")
        if self._phase:
            t.append(f" │ {self._phase} ", style="italic dim")
        return t


class StatCard(Static):
    """Single stat with big number + label."""

    def __init__(self, label: str, icon: str = "📊", **kwargs: object) -> None:
        super().__init__(**kwargs)
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

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
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
        bar_w = 28
        ok_w = max(1, int(self._ok / total * bar_w)) if self._ok else 0
        fail_w = max(1, int(self._fail / total * bar_w)) if self._fail else 0
        skip_w = max(1, int(self._skip / total * bar_w)) if self._skip else 0
        used = ok_w + fail_w + skip_w
        if used < bar_w:
            ok_w += bar_w - used
        elif used > bar_w and ok_w > 1:
            ok_w -= used - bar_w

        t = Text(" ")
        if ok_w:
            t.append(_DONE * ok_w, style="green")
        if fail_w:
            t.append(_DONE * fail_w, style=_NBA_RED)
        if skip_w:
            t.append(_DONE * skip_w, style=_NBA_GOLD)
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

    def __init__(self, mode: str = "INIT") -> None:
        super().__init__()
        self._mode = mode.upper()
        self._start_time = 0.0
        self._phase = ""
        self._phase_detail = ""
        self._discoveries: dict[str, int] = {}
        self._patterns: list[PatternState] = []
        self._current_pattern: PatternState | None = None
        self._tick = 0
        self._row_keys: dict[str, object] = {}
        self._pipeline_result: object = None
        self._pipeline_error: Exception | None = None
        self._run_fn: object = None
        self._settings: object = None
        self._orchestrator_cls: type | None = None
        self._rate_history: list[float] = [0.0] * 60
        self._last_total = 0
        self._stat_cards: dict[str, StatCard] = {}

    def compose(self) -> ComposeResult:
        yield Scoreboard(mode=self._mode, id="scoreboard")

        with Horizontal(id="stats-row"):
            games_card = StatCard("games", "🎮", id="stat-games", classes="stat-card")
            players_card = StatCard("players", "👤", id="stat-players", classes="stat-card")
            teams_card = StatCard("teams", "🏟️", id="stat-teams", classes="stat-card")
            dates_card = StatCard("dates", "📅", id="stat-dates", classes="stat-card")
            self._stat_cards = {
                "games": games_card,
                "players": players_card,
                "teams": teams_card,
                "dates": dates_card,
            }
            yield games_card
            yield players_card
            yield teams_card
            yield dates_card
            yield Sparkline(self._rate_history, summary_function=max, id="throughput-spark")

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

        # Set up progress table
        table = self.query_one("#game-clock", DataTable)
        table.border_title = "🏀 GAME CLOCK"
        table.cursor_type = "none"
        table.add_columns("", "PLAY", "PROGRESS", "%", "SCORE", "FG", "TO", "DNP", "TIME")

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

    @work(exclusive=True)
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
            raise
        else:
            self.write_log("", "")
            self.write_log("🏆 PERFECT GAME — Pipeline complete!", "bold green")
        finally:
            self.set_timer(3.0, self.exit)

    def _tick_clock(self) -> None:
        self._tick += 1
        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        ok = sum(p.succeeded for p in self._patterns)
        fail = sum(p.failed for p in self._patterns)

        # Update scoreboard
        scoreboard = self.query_one("#scoreboard", Scoreboard)
        scoreboard.set_stats(elapsed, ok, fail, self._phase_detail or self._phase)

        # Update throughput sparkline
        current_total = ok + fail
        delta = current_total - self._last_total
        self._last_total = current_total
        rate = delta / 0.5  # ticks every 0.5s
        self._rate_history.append(rate)
        if len(self._rate_history) > 60:
            self._rate_history = self._rate_history[-60:]
        try:
            spark = self.query_one("#throughput-spark", Sparkline)
            spark.data = list(self._rate_history)
        except Exception:
            pass

        # Animate running pattern
        if self._current_pattern and self._current_pattern.status == "running":
            self._update_pattern_row(self._current_pattern)

        # Overall progress
        total_done = sum(p.completed for p in self._patterns)
        total_all = sum(p.total for p in self._patterns)
        try:
            pbar = self.query_one("#overall-bar", ProgressBar)
            if total_all > 0:
                pbar.update(total=total_all, progress=total_done)
        except Exception:
            pass

        # Totals strip
        try:
            strip = self.query_one("#totals-strip", TotalsStrip)
            strip.set_totals(ok, fail, sum(p.skipped for p in self._patterns))
        except Exception:
            pass

    def _update_pattern_row(self, p: PatternState) -> None:
        table = self.query_one("#game-clock", DataTable)
        key = self._row_keys.get(p.label)
        if key is None:
            return

        pct = p.completed / p.total if p.total else 0

        if p.status == "done":
            icon = "✓" if p.failed == 0 else "!"
            color = "green" if p.failed == 0 else _NBA_GOLD
        elif p.status == "running":
            icon = _SPINNER[self._tick % len(_SPINNER)]
            color = _NBA_GOLD
        else:
            icon = "○"
            color = "dim"

        bar = _gradient_bar(pct, width=16)

        elapsed_str = ""
        if p.status == "done" and p.end_time:
            elapsed_str = _fmt_time(p.end_time - p.start_time)
        elif p.status == "running" and p.start_time:
            elapsed_str = _fmt_time(time.monotonic() - p.start_time)

        try:
            table.update_cell(key, "", Text(icon, style=color))
            table.update_cell(
                key,
                "PLAY",
                Text(p.label, style="bold" if p.status == "running" else ""),
            )
            table.update_cell(key, "PROGRESS", Text(bar, style=color))
            table.update_cell(key, "%", Text(f"{pct:>3.0%}", style=color))
            table.update_cell(key, "SCORE", Text(f"{p.completed:,}/{p.total:,}"))
            table.update_cell(key, "FG", Text(f"{p.succeeded:,}", style="green"))
            table.update_cell(
                key,
                "TO",
                Text(f"{p.failed:,}", style=_NBA_RED) if p.failed else Text("0", style="dim"),
            )
            table.update_cell(
                key,
                "DNP",
                Text(f"{p.skipped:,}", style=_NBA_GOLD) if p.skipped else Text("-", style="dim"),
            )
            table.update_cell(key, "TIME", Text(elapsed_str, style="dim"))
        except Exception:
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
            if style:
                log.write(Text(message, style=style))
            else:
                log.write(message)
        except Exception:
            pass

    def start_phase(self, name: str, total: int = 0) -> None:
        self._phase = name
        self._phase_detail = ""
        self.write_log(f"▶ {name}", f"bold {_NBA_BLUE}")

    def advance_phase(self, n: int = 1) -> None:
        pass

    def update_phase_total(self, total: int) -> None:
        pass

    def update_phase_info(self, info: str) -> None:
        self._phase_detail = info
        self.write_log(f"  {info}", "dim")

    def complete_phase(self) -> None:
        if self._current_pattern and self._current_pattern.status == "running":
            self._current_pattern.status = "done"
            self._current_pattern.end_time = time.monotonic()
            self._update_pattern_row(self._current_pattern)
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
        if self._current_pattern and self._current_pattern.status == "running":
            self._current_pattern.status = "done"
            self._current_pattern.end_time = time.monotonic()
            self._update_pattern_row(self._current_pattern)

        state = PatternState(
            label=pattern,
            total=total,
            status="running",
            start_time=time.monotonic(),
        )
        self._patterns.append(state)
        self._current_pattern = state

        table = self.query_one("#game-clock", DataTable)
        row_key = table.add_row(
            Text(_SPINNER[0], style=_NBA_GOLD),
            Text(pattern, style="bold"),
            Text(_gradient_bar(0, width=16), style=_NBA_GOLD),
            Text("0%", style=_NBA_GOLD),
            Text(f"0/{total:,}"),
            Text("0", style="green"),
            Text("0", style="dim"),
            Text("-", style="dim"),
            Text("0s", style="dim"),
        )
        self._row_keys[pattern] = row_key
        self.write_log(f"🏀 {pattern}: {total:,} tasks", "bold")

    def advance_pattern(self, *, success: bool = True) -> None:
        if self._current_pattern is None:
            return
        self._current_pattern.completed += 1
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
        self._update_pattern_row(self._current_pattern)


# ── loguru sink ────────────────────────────────────────────


class TuiLogSink:
    """Loguru sink that writes to the TUI's RichLog panel."""

    def __init__(self, app: NbaDbDashboard) -> None:
        self._app = app

    def write(self, message: str) -> None:
        msg = message.rstrip("\n")
        if not msg:
            return
        style = "dim"
        if "ERROR" in msg or "FAIL" in msg:
            style = _NBA_RED
        elif "WARNING" in msg or "WARN" in msg:
            style = _NBA_GOLD
        elif "INFO" in msg:
            style = ""
        elif "SUCCESS" in msg:
            style = "green"
        with contextlib.suppress(Exception):
            self._app.write_log(msg, style)


# ── public entry point ─────────────────────────────────────


def run_with_tui(
    mode: str,
    run_fn: object,
    settings: object,
    orchestrator_cls: type | None = None,
) -> tuple[object, Exception | None]:
    """Run pipeline inside the Textual TUI.

    Returns (result, error). The TUI app owns the event loop —
    the pipeline runs as an async worker inside it.
    """
    from loguru import logger

    app = NbaDbDashboard(mode=mode)
    app._run_fn = run_fn
    app._settings = settings
    app._orchestrator_cls = orchestrator_cls

    # Wire loguru into the TUI log panel
    logger.remove()
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

    return app.pipeline_result, app.pipeline_error
