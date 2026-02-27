from __future__ import annotations

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
CURRENT_SEASON: SeasonYear = "2024-25"
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
