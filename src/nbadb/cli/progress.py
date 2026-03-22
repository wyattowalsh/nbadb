"""Rich TUI dashboard for nbadb pipeline runs — basketball themed."""

from __future__ import annotations

import time

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from nbadb.cli._progress_common import (
    DONE_CHAR,
    ENTITY_ICONS,
    SPINNER_FRAMES,
    PatternState,
    PatternStatus,
    fmt_time,
    gradient_bar,
    proportional_bar,
)


class PipelineProgress:
    """Live basketball-themed TUI dashboard for nbadb extraction pipelines."""

    def __init__(self, mode: str = "init", console: Console | None = None) -> None:
        self._console = console or Console()
        self._mode = mode
        self._live: Live | None = None
        self._phase = ""
        self._phase_detail = ""
        self._discoveries: dict[str, int] = {}
        self._patterns: list[PatternState] = []
        self._current_pattern: PatternState | None = None
        self._start_time = 0.0
        self._tick = 0

    def __enter__(self) -> PipelineProgress:
        self._start_time = time.monotonic()
        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=4,
            transient=False,
        )
        self._live.start()
        return self

    def __exit__(self, *args: object) -> None:
        if self._live:
            self._live.update(self._render(final=True))
            self._live.stop()

    def _refresh(self) -> None:
        self._tick += 1
        if self._live:
            self._live.update(self._render())

    # ── main render ────────────────────────────────────────

    def _render(self, *, final: bool = False) -> Group:
        parts: list[object] = []
        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        ok = sum(p.succeeded for p in self._patterns)
        fail = sum(p.failed for p in self._patterns)

        # ── scoreboard header ──
        ball = "🏀" if (self._tick // 3) % 2 == 0 or final else "  "
        rate = ""
        if elapsed > 1 and (ok + fail) > 0:
            rate = f"  {(ok + fail) / elapsed:.1f} req/s"

        header = Text()
        header.append(f" {ball} ", style="")
        header.append(" NBADB ", style="bold bright_white on dark_orange3")
        header.append(f" {self._mode.upper()} ", style="bold white on orange4")
        header.append(f"  {fmt_time(elapsed)}", style="bold")
        header.append(rate, style="cyan bold")
        parts.append(header)
        parts.append(Text(""))

        # ── discovery scoreboard ──
        if self._discoveries:
            parts.append(self._render_discovery())
            parts.append(Text(""))

        # ── phase spinner (pre-extraction) ──
        if self._phase and not self._patterns:
            s = SPINNER_FRAMES[self._tick % len(SPINNER_FRAMES)]
            parts.append(
                Text.assemble(
                    ("  ", ""),
                    (f"{s} ", "dark_orange3"),
                    (self._phase_detail or self._phase, "italic"),
                )
            )
            parts.append(Text(""))

        # ── extraction court ──
        if self._patterns:
            parts.append(self._render_extraction(final))
            parts.append(Text(""))

        # ── totals strip ──
        if self._patterns:
            parts.append(self._render_totals(final))

        return Group(*parts)

    def _render_discovery(self) -> Panel:
        """Scoreboard-style entity discovery display."""
        table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
        for _ in self._discoveries:
            table.add_column(justify="center")

        values = []
        labels = []
        for entity, count in self._discoveries.items():
            icon = ENTITY_ICONS.get(entity, "📊")
            values.append(f"[bold bright_white]{count:,}[/]")
            labels.append(f"[dim]{icon} {entity}[/]")
        table.add_row(*values)
        table.add_row(*labels)

        return Panel(
            table,
            title="[bold dark_orange3]SCOUTING REPORT[/]",
            border_style="dark_orange3",
            padding=(0, 1),
        )

    def _render_extraction(self, final: bool = False) -> Panel:
        """Court-style extraction progress table."""
        table = Table(
            show_header=True,
            header_style="bold dark_orange3",
            box=None,
            padding=(0, 1),
            expand=True,
        )
        table.add_column("", width=2)
        table.add_column("PLAY", min_width=14)
        table.add_column("PROGRESS", ratio=1, min_width=30)
        table.add_column("%", justify="right", width=5)
        table.add_column("SCORE", justify="right", width=13)
        table.add_column("FG", justify="right", width=7, style="green")
        table.add_column("TO", justify="right", width=7)
        table.add_column("DNP", justify="right", width=7)
        table.add_column("MIN", justify="right", width=7)

        for p in self._patterns:
            pct = p.completed / p.total if p.total else 0

            # Status icon with animation
            if p.status == PatternStatus.DONE:
                icon = "[green]✓[/]" if p.failed == 0 else "[yellow]![/]"
                bar_color = "green" if p.failed == 0 else "yellow"
            elif p.status == PatternStatus.RUNNING:
                icon = f"[dark_orange3]{SPINNER_FRAMES[self._tick % len(SPINNER_FRAMES)]}[/]"
                bar_color = "dark_orange3"
            else:
                icon = "[dim]○[/]"
                bar_color = "dim"

            bar = gradient_bar(pct, width=26)
            pct_s = f"[{bar_color}]{pct:>3.0%}[/]" if p.total else "[dim]  -[/]"

            elapsed = ""
            if p.status == PatternStatus.DONE and p.end_time:
                elapsed = fmt_time(p.end_time - p.start_time)
            elif p.status == PatternStatus.RUNNING and p.start_time:
                elapsed = fmt_time(time.monotonic() - p.start_time)

            fail_s = f"[bold red]{p.failed:,}[/]" if p.failed else "[dim]0[/]"
            skip_s = f"[yellow]{p.skipped:,}[/]" if p.skipped else "[dim]-[/]"

            name = f"[bold]{p.label}[/]" if p.status == PatternStatus.RUNNING else p.label
            score = (
                f"[bold]{p.completed:,}[/]/{p.total:,}"
                if p.status == PatternStatus.RUNNING
                else f"{p.completed:,}/{p.total:,}"
            )

            table.add_row(
                icon,
                name,
                f"[{bar_color}]{bar}[/]",
                pct_s,
                score,
                f"{p.succeeded:,}",
                fail_s,
                skip_s,
                f"[dim]{elapsed}[/]",
            )

        # Overall extraction pct
        total_done = sum(p.completed for p in self._patterns)
        total_all = sum(p.total for p in self._patterns)
        overall_pct = total_done / total_all if total_all else 0
        subtitle = f"[dim]{total_done:,}/{total_all:,}  {overall_pct:.0%}[/]"

        title_text = "[bold green]FINAL SCORE[/]" if final else "[bold dark_orange3]GAME CLOCK[/]"

        return Panel(
            table,
            title=title_text,
            subtitle=subtitle,
            border_style="green" if final else "dark_orange3",
            padding=(0, 1),
        )

    def _render_totals(self, final: bool = False) -> Text:
        """Proportional color bar + stats."""
        ok = sum(p.succeeded for p in self._patterns)
        fail = sum(p.failed for p in self._patterns)
        skip = sum(p.skipped for p in self._patterns)
        total = ok + fail + skip
        if not total:
            return Text("")

        ok_w, fail_w, skip_w = proportional_bar(ok, fail, skip, width=50)

        t = Text()
        t.append("  ")
        if ok_w:
            t.append(DONE_CHAR * ok_w, style="green")
        if fail_w:
            t.append(DONE_CHAR * fail_w, style="red")
        if skip_w:
            t.append(DONE_CHAR * skip_w, style="yellow")
        t.append("  ")
        t.append(f"{ok:,}", style="bold green")
        t.append(" FGM", style="dim")
        if fail:
            t.append(f"  {fail:,}", style="bold red")
            t.append(" TO", style="dim")
        if skip:
            t.append(f"  {skip:,}", style="yellow")
            t.append(" DNP", style="dim")

        if final:
            if fail:
                t.append("  🏀 run ", style="")
                t.append("nbadb full", style="bold")
                t.append(" to retry", style="dim")
            else:
                t.append("  🏆 PERFECT GAME", style="bold green")

        return t

    # ── phase management ───────────────────────────────────

    def start_phase(self, name: str, total: int = 0) -> None:
        self._phase = name
        self._phase_detail = ""
        self._refresh()

    def update_phase_info(self, info: str) -> None:
        self._phase_detail = info
        self._refresh()

    def complete_phase(self) -> None:
        if self._current_pattern and self._current_pattern.status == "running":
            self._current_pattern.status = PatternStatus.DONE
            self._current_pattern.end_time = time.monotonic()
        self._phase = ""
        self._phase_detail = ""
        self._refresh()

    # ── discovery ──────────────────────────────────────────

    def log_discovery(self, entity: str, count: int) -> None:
        self._discoveries[entity] = count
        self._refresh()

    # ── extraction pattern ─────────────────────────────────

    def start_pattern(self, pattern: str, total: int) -> None:
        if self._current_pattern and self._current_pattern.status == "running":
            self._current_pattern.status = PatternStatus.DONE
            self._current_pattern.end_time = time.monotonic()

        state = PatternState(
            label=pattern,
            total=total,
            status=PatternStatus.RUNNING,
            start_time=time.monotonic(),
        )
        self._patterns.append(state)
        self._current_pattern = state
        self._refresh()

    def advance_pattern(self, *, success: bool = True) -> None:
        if self._current_pattern is None:
            return
        self._current_pattern.completed += 1
        if success:
            self._current_pattern.succeeded += 1
        else:
            self._current_pattern.failed += 1
        self._refresh()

    def record_skip(self, n: int = 1) -> None:
        if self._current_pattern is None:
            return
        self._current_pattern.completed += n
        self._current_pattern.skipped += n
        self._refresh()


class NoopProgress:
    """Silent progress tracker (for tests and non-TTY)."""

    def __enter__(self) -> NoopProgress:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def start_phase(self, name: str, total: int = 0) -> None:
        pass

    def update_phase_info(self, info: str) -> None:
        pass

    def complete_phase(self) -> None:
        pass

    def log_discovery(self, entity: str, count: int) -> None:
        pass

    def start_pattern(self, pattern: str, total: int) -> None:
        pass

    def advance_pattern(self, *, success: bool = True) -> None:
        pass

    def record_skip(self, n: int = 1) -> None:
        pass
