"""NBA season utilities for date and identifier handling.

Usage in run_python:
    from season_utils import current_season, season_year_to_id
"""

from __future__ import annotations

from datetime import date


def current_season(today: date | None = None) -> str:
    """Return the current NBA season in 'YYYY-YY' format.

    NBA seasons span October-June. Before October, returns previous season.
    """
    today = today or date.today()
    year = today.year if today.month >= 10 else today.year - 1
    return f"{year}-{str(year + 1)[-2:]}"


def season_year_to_id(season_year: str) -> str:
    """Convert 'YYYY-YY' to nba_api season_id format ('2YYYY')."""
    start_year = season_year.split("-")[0]
    return f"2{start_year}"


def season_id_to_year(season_id: str) -> str:
    """Convert nba_api season_id ('2YYYY') to 'YYYY-YY' format."""
    start_year = int(season_id[1:])
    return f"{start_year}-{str(start_year + 1)[-2:]}"
