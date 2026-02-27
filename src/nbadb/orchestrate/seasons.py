from __future__ import annotations

from datetime import datetime


def season_string(year: int) -> str:
    """Convert start year to NBA season format: 2024 -> '2024-25'."""
    return f"{year}-{str(year + 1)[-2:]}"


def current_season() -> str:
    """Current NBA season. Season starts in October."""
    now = datetime.now()
    year = now.year if now.month >= 10 else now.year - 1
    return season_string(year)


def season_range(start: int = 1946, end: int | None = None) -> list[str]:
    """All season strings from start year to end (default: current)."""
    if end is None:
        now = datetime.now()
        end = now.year if now.month >= 10 else now.year - 1
    return [season_string(y) for y in range(start, end + 1)]


def recent_seasons(n: int = 3) -> list[str]:
    """Last N seasons including current."""
    now = datetime.now()
    current_year = now.year if now.month >= 10 else now.year - 1
    start = current_year - n + 1
    return [season_string(y) for y in range(start, current_year + 1)]
