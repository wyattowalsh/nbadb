"""Shared constants, types, and utilities for progress display modules."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

# ── shared constants ──────────────────────────────────────

BAR_CHARS = " ▏▎▍▌▋▊▉█"
DONE_CHAR = "█"
EMPTY_CHAR = "░"
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ENTITY_ICONS = {"games": "🎮", "players": "👤", "teams": "🏟️", "dates": "📅"}


# ── types ─────────────────────────────────────────────────


class PatternStatus(StrEnum):
    """Status of an extraction pattern."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"


@dataclass
class PatternState:
    """Mutable state for a single extraction pattern."""

    label: str
    total: int
    completed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    rows_extracted: int = 0
    status: PatternStatus = PatternStatus.PENDING
    start_time: float = 0.0
    end_time: float = 0.0
    eta: ETAEstimator = field(default_factory=lambda: ETAEstimator())


# ── ETA estimation ───────────────────────────────────────


class ETAEstimator:
    """EWMA-based time-remaining estimator.

    Uses an exponentially-weighted moving average of items/sec to project
    remaining time.  Returns ``None`` during warmup (first *min_warmup_s*
    seconds or fewer than *min_samples* updates).
    """

    __slots__ = (
        "_alpha",
        "_min_samples",
        "_min_warmup_s",
        "_rate",
        "_samples",
        "_first_ts",
        "_last_ts",
        "_last_completed",
    )

    def __init__(
        self,
        alpha: float = 0.1,
        min_samples: int = 5,
        min_warmup_s: float = 10.0,
    ) -> None:
        self._alpha = alpha
        self._min_samples = min_samples
        self._min_warmup_s = min_warmup_s
        self._rate: float = 0.0  # items/sec EWMA
        self._samples: int = 0
        self._first_ts: float = 0.0
        self._last_ts: float = 0.0
        self._last_completed: int = 0

    def update(self, completed: int, total: int) -> float | None:
        """Feed a new (completed, total) sample.

        Returns estimated seconds remaining, or ``None`` if still warming up.
        """
        now = time.monotonic()
        if self._samples == 0:
            self._first_ts = now
            self._last_ts = now
            self._last_completed = completed
            self._samples = 1
            return None

        dt = now - self._last_ts
        if dt <= 0:
            return self._estimate(completed, total, now)

        delta = completed - self._last_completed
        if delta < 0:
            # Reset on backwards movement (new pattern started)
            self._rate = 0.0
            self._samples = 1
            self._first_ts = now
            self._last_ts = now
            self._last_completed = completed
            return None

        instant_rate = delta / dt
        if self._samples == 1:
            self._rate = instant_rate
        else:
            self._rate = self._alpha * instant_rate + (1 - self._alpha) * self._rate

        self._last_ts = now
        self._last_completed = completed
        self._samples += 1

        return self._estimate(completed, total, now)

    def _estimate(self, completed: int, total: int, now: float) -> float | None:
        """Compute the estimate if we have enough data."""
        if self._samples < self._min_samples:
            return None
        if now - self._first_ts < self._min_warmup_s:
            return None
        if self._rate <= 0:
            return None
        remaining = total - completed
        if remaining <= 0:
            return 0.0
        return remaining / self._rate

    def reset(self) -> None:
        """Reset state for a new estimation window."""
        self._rate = 0.0
        self._samples = 0
        self._first_ts = 0.0
        self._last_ts = 0.0
        self._last_completed = 0


def fmt_eta(seconds: float | None) -> str:
    """Format ETA seconds into a display string."""
    if seconds is None:
        return "WARMUP"
    if seconds <= 0:
        return "~0s"
    return f"~{fmt_time(seconds)}"


def fmt_rows(n: int) -> str:
    """Format a row count with K/M suffix for compact display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


@dataclass
class RunSummary:
    """Structured summary of a pipeline run for JSON export and GH Step Summary."""

    mode: str = ""
    started_at: str = ""
    duration_seconds: float = 0.0
    discoveries: dict[str, int] = field(default_factory=dict)
    patterns: list[dict[str, object]] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ── utility functions ─────────────────────────────────────


def gradient_bar(pct: float, width: int = 18) -> str:
    """Smooth gradient progress bar using Unicode block characters."""
    if pct >= 1.0:
        return DONE_CHAR * width
    filled = pct * width
    full = int(filled)
    rem = filled - full
    pidx = int(rem * (len(BAR_CHARS) - 1))
    partial = BAR_CHARS[pidx] if full < width else ""
    empty = width - full - (1 if partial else 0)
    return DONE_CHAR * full + partial + EMPTY_CHAR * empty


def fmt_time(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def proportional_bar(
    ok: int,
    fail: int,
    skip: int,
    width: int = 28,
) -> tuple[int, int, int]:
    """Compute proportional bar segment widths, clamped to *width*."""
    total = ok + fail + skip
    if not total:
        return (0, 0, 0)
    fail_w = max(1, int(fail / total * width)) if fail else 0
    skip_w = max(1, int(skip / total * width)) if skip else 0
    ok_w = max(0, width - fail_w - skip_w)
    return (ok_w, fail_w, skip_w)
