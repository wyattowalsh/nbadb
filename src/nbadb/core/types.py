from __future__ import annotations

import re
from datetime import date as _date
from enum import StrEnum


class SeasonType(StrEnum):
    REGULAR = "Regular Season"
    PLAYOFFS = "Playoffs"
    PRE_SEASON = "Pre Season"
    ALL_STAR = "All Star"


class LeagueID(StrEnum):
    NBA = "00"
    ABA = "01"
    WNBA = "10"
    G_LEAGUE = "20"


class Format(StrEnum):
    SQLITE = "sqlite"
    DUCKDB = "duckdb"
    CSV = "csv"
    PARQUET = "parquet"


class SeasonPhase(StrEnum):
    PRESEASON = "Preseason"
    REGULAR = "Regular"
    PLAY_IN = "Play-In"
    PLAYOFFS_R1 = "Playoffs R1"
    PLAYOFFS_R2 = "Playoffs R2"
    PLAYOFFS_CF = "Conference Finals"
    FINALS = "Finals"
    ALL_STAR = "All-Star"


type GameId = str
type PlayerId = int
type TeamId = int
type SeasonYear = str
type GameDate = str

NBA_FIRST_SEASON: SeasonYear = "1946-47"


def current_season() -> SeasonYear:
    """Compute the current NBA season string (e.g. '2025-26')."""
    today = _date.today()
    year = today.year if today.month >= 10 else today.year - 1
    return f"{year}-{str(year + 1)[-2:]}"


CURRENT_SEASON: SeasonYear = current_season()
NBA_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        " AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nba.com/",
    "Accept": "application/json, text/plain, */*",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}

_IDENTIFIER_RE: re.Pattern[str] = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def validate_sql_identifier(name: str) -> str:
    """Validate a string is a safe SQL identifier (table/column name)."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name
