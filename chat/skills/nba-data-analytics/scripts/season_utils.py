"""NBA season utilities for date and identifier handling.

Aligns calendar logic with ``nbadb.orchestrate.seasons`` when available.
Offline skill scripts may still import this module standalone.
"""

from __future__ import annotations

import re
from datetime import date

_SEASON_YEAR_PATTERN = r"(19|20)([0-9]{2})-([0-9]{2})"
_SEASON_ID_PATTERN = r"2(19|20)([0-9]{2})"


def current_season(today: date | None = None) -> str:
    """Return the current NBA season in 'YYYY-YY' format.

    NBA seasons span October-June. Before October, returns previous season.
    """
    if today is None:
        try:
            from nbadb.orchestrate.seasons import current_season as _current

            return _current()
        except ImportError:
            today = date.today()
    year = today.year if today.month >= 10 else today.year - 1
    return f"{year}-{str(year + 1)[-2:]}"


def season_year_to_id(season_year: str) -> str:
    """Convert 'YYYY-YY' to nba_api season_id format ('2YYYY')."""
    match = re.fullmatch(_SEASON_YEAR_PATTERN, season_year)
    if match is None:
        raise ValueError("season_year must use exact YYYY-YY format")
    start_year = int(f"{match.group(1)}{match.group(2)}")
    if int(match.group(3)) != (start_year + 1) % 100:
        raise ValueError("season_year must name consecutive calendar years")
    return f"2{start_year}"


def season_id_to_year(season_id: str) -> str:
    """Convert nba_api season_id ('2YYYY') to 'YYYY-YY' format."""
    match = re.fullmatch(_SEASON_ID_PATTERN, season_id)
    if match is None:
        raise ValueError("season_id must use exact 2YYYY format")
    start_year = int(f"{match.group(1)}{match.group(2)}")
    return f"{start_year}-{str(start_year + 1)[-2:]}"
