"""Shared constants, types, and utilities for progress display modules."""

from __future__ import annotations

from dataclasses import dataclass
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
    status: PatternStatus = PatternStatus.PENDING
    start_time: float = 0.0
    end_time: float = 0.0


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
