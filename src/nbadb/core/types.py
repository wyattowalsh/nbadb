from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from nbadb.orchestrate.seasons import current_season


class SeasonType(StrEnum):
    REGULAR = "Regular Season"
    PLAYOFFS = "Playoffs"
    PRE_SEASON = "Pre Season"
    PLAY_IN = "PlayIn"
    ALL_STAR = "All Star"


type SeasonTypeAvailability = Literal["supported", "upstream_unavailable"]

# nba_api 1.11.4 accepts SeasonType=PlayIn at runtime. NBA history classifies the
# 2019-20 restart as the first Play-In edition, so earlier NBA seasons have no
# upstream rows for that season type.
PLAY_IN_FIRST_SEASON_START_YEAR = 2019
PLAY_IN_UPSTREAM_UNAVAILABLE_REASON = "competition_not_held_before_2019_20"
ALL_STAR_FIRST_SEASON_START_YEAR = 1950
ALL_STAR_CANCELLED_SEASON_START_YEAR = 1998
ALL_STAR_PRE_HISTORY_UPSTREAM_UNAVAILABLE_REASON = "competition_not_held_before_1950_51"
ALL_STAR_CANCELLED_UPSTREAM_UNAVAILABLE_REASON = "competition_not_held_in_1998_99"


def season_type_upstream_unavailable_reason(
    season_start_year: int,
    season_type: str,
) -> str | None:
    """Return the deterministic reason a season/type scope cannot exist upstream."""

    resolved = SeasonType(season_type)
    if resolved is SeasonType.PLAY_IN and season_start_year < PLAY_IN_FIRST_SEASON_START_YEAR:
        return PLAY_IN_UPSTREAM_UNAVAILABLE_REASON
    if resolved is SeasonType.ALL_STAR:
        if season_start_year < ALL_STAR_FIRST_SEASON_START_YEAR:
            return ALL_STAR_PRE_HISTORY_UPSTREAM_UNAVAILABLE_REASON
        if season_start_year == ALL_STAR_CANCELLED_SEASON_START_YEAR:
            return ALL_STAR_CANCELLED_UPSTREAM_UNAVAILABLE_REASON
    return None


def classify_season_type_availability(
    season_start_year: int,
    season_type: str,
) -> SeasonTypeAvailability:
    """Classify whether an NBA season can contain the requested season type."""

    if season_type_upstream_unavailable_reason(season_start_year, season_type) is not None:
        return "upstream_unavailable"
    return "supported"


class VideoContextMeasure(StrEnum):
    """VideoDetails ContextMeasure union for pinned nba_api 1.11.4.

    The generated endpoint docs declare 78 values. The runtime
    ``ContextMeasureDetailed`` helper exposes 72 of them; the six documented-only
    values are retained because both video endpoint regex contracts accept them.
    """

    PTS = "PTS"
    FGM = "FGM"
    FGA = "FGA"
    FG_PCT = "FG_PCT"
    FG3M = "FG3M"
    FG3A = "FG3A"
    FG3_PCT = "FG3_PCT"
    PTS_FB = "PTS_FB"
    PTS_OFF_TOV = "PTS_OFF_TOV"
    PTS_2ND_CHANCE = "PTS_2ND_CHANCE"
    FTM = "FTM"
    FTA = "FTA"
    OREB = "OREB"
    DREB = "DREB"
    AST = "AST"
    FGM_AST = "FGM_AST"
    FG3_AST = "FG3_AST"
    STL = "STL"
    BLK = "BLK"
    BLKA = "BLKA"
    TOV = "TOV"
    PF = "PF"
    PFD = "PFD"
    POSS_END_FT = "POSS_END_FT"
    PTS_PAINT = "PTS_PAINT"
    REB = "REB"
    TM_FGM = "TM_FGM"
    TM_FGA = "TM_FGA"
    TM_FG3M = "TM_FG3M"
    TM_FG3A = "TM_FG3A"
    TM_FTM = "TM_FTM"
    TM_FTA = "TM_FTA"
    TM_OREB = "TM_OREB"
    TM_DREB = "TM_DREB"
    TM_REB = "TM_REB"
    TM_TEAM_REB = "TM_TEAM_REB"
    TM_AST = "TM_AST"
    TM_STL = "TM_STL"
    TM_BLK = "TM_BLK"
    TM_BLKA = "TM_BLKA"
    TM_TOV = "TM_TOV"
    TM_TEAM_TOV = "TM_TEAM_TOV"
    TM_PF = "TM_PF"
    TM_PFD = "TM_PFD"
    TM_PTS = "TM_PTS"
    TM_PTS_PAINT = "TM_PTS_PAINT"
    TM_PTS_FB = "TM_PTS_FB"
    TM_PTS_OFF_TOV = "TM_PTS_OFF_TOV"
    TM_PTS_2ND_CHANCE = "TM_PTS_2ND_CHANCE"
    TM_FGM_AST = "TM_FGM_AST"
    TM_FG3_AST = "TM_FG3_AST"
    TM_POSS_END_FT = "TM_POSS_END_FT"
    OPP_FGM = "OPP_FGM"
    OPP_FGA = "OPP_FGA"
    OPP_FG3M = "OPP_FG3M"
    OPP_FG3A = "OPP_FG3A"
    OPP_FTM = "OPP_FTM"
    OPP_FTA = "OPP_FTA"
    OPP_OREB = "OPP_OREB"
    OPP_DREB = "OPP_DREB"
    OPP_REB = "OPP_REB"
    OPP_TEAM_REB = "OPP_TEAM_REB"
    OPP_AST = "OPP_AST"
    OPP_STL = "OPP_STL"
    OPP_BLK = "OPP_BLK"
    OPP_BLKA = "OPP_BLKA"
    OPP_TOV = "OPP_TOV"
    OPP_TEAM_TOV = "OPP_TEAM_TOV"
    OPP_PF = "OPP_PF"
    OPP_PFD = "OPP_PFD"
    OPP_PTS = "OPP_PTS"
    OPP_PTS_PAINT = "OPP_PTS_PAINT"
    OPP_PTS_FB = "OPP_PTS_FB"
    OPP_PTS_OFF_TOV = "OPP_PTS_OFF_TOV"
    OPP_PTS_2ND_CHANCE = "OPP_PTS_2ND_CHANCE"
    OPP_FGM_AST = "OPP_FGM_AST"
    OPP_FG3_AST = "OPP_FG3_AST"
    OPP_POSS_END_FT = "OPP_POSS_END_FT"


NBA_API_VIDEO_CONTEXT_MEASURE_VERSION = "1.11.4"
NBA_API_VIDEO_CONTEXT_MEASURE_DOCS_SOURCE = (
    "nba_api==1.11.4 docs/nba_api/stats/endpoints/"
    "{videodetails,videodetailsasset}.md parameter_patterns.ContextMeasure"
)
NBA_API_VIDEO_CONTEXT_MEASURE_RUNTIME_SOURCE = (
    "nba_api==1.11.4 nba_api.stats.library.parameters.ContextMeasureDetailed"
)
VIDEO_CONTEXT_MEASURES = tuple(measure.value for measure in VideoContextMeasure)
VIDEO_CONTEXT_MEASURE_DOCS_ONLY = frozenset(
    {
        VideoContextMeasure.PF,
        VideoContextMeasure.PFD,
        VideoContextMeasure.OPP_FGM,
        VideoContextMeasure.OPP_FGA,
        VideoContextMeasure.OPP_FG3M,
        VideoContextMeasure.OPP_FG3A,
    }
)
type VideoContextMeasureProvenance = tuple[Literal["docs", "runtime"], ...]
VIDEO_CONTEXT_MEASURE_PROVENANCE: dict[
    VideoContextMeasure,
    VideoContextMeasureProvenance,
] = {
    measure: ("docs",) if measure in VIDEO_CONTEXT_MEASURE_DOCS_ONLY else ("docs", "runtime")
    for measure in VideoContextMeasure
}

VIDEO_SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)
type VideoSeasonTypeProvenance = tuple[Literal["docs", "runtime"], ...]
VIDEO_SEASON_TYPE_PROVENANCE: dict[SeasonType, VideoSeasonTypeProvenance] = {
    season_type: ("runtime",) if season_type is SeasonType.PLAY_IN else ("docs", "runtime")
    for season_type in SeasonType
}


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

_IDENTIFIER_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_sql_identifier(name: str) -> str:
    """Validate a string is a safe SQL identifier (table/column name)."""
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name
