from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawScheduleLeagueV2Schema(BaseSchema):
    game_date: str = pa.Field(
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_DATE"
            ),
            "description": "Date of the game",
        },
    )
    game_id: str = pa.Field(
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    game_code: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_CODE"
            ),
            "description": "Game code string",
        },
    )
    game_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_STATUS"
            ),
            "description": "Game status code",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_STATUS_TEXT"
            ),
            "description": "Game status display text",
        },
    )
    game_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_SEQUENCE"
            ),
            "description": "Game sequence number for the day",
        },
    )
    game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_DATE_EST"
            ),
            "description": "Game date in Eastern time",
        },
    )
    game_time_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_TIME_EST"
            ),
            "description": "Game time in Eastern time",
        },
    )
    game_date_time_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2"
                ".GAME_DATE_TIME_EST"
            ),
            "description": (
                "Game date and time in Eastern time"
            ),
        },
    )
    game_date_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_DATE_UTC"
            ),
            "description": "Game date in UTC",
        },
    )
    game_time_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_TIME_UTC"
            ),
            "description": "Game time in UTC",
        },
    )
    game_date_time_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2"
                ".GAME_DATE_TIME_UTC"
            ),
            "description": "Game date and time in UTC",
        },
    )
    away_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.AWAY_TEAM_ID"
            ),
            "description": "Away team identifier",
        },
    )
    away_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.AWAY_TEAM_NAME"
            ),
            "description": "Away team name",
        },
    )
    away_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.AWAY_TEAM_CITY"
            ),
            "description": "Away team city",
        },
    )
    away_team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2"
                ".AWAY_TEAM_TRICODE"
            ),
            "description": "Away team three-letter code",
        },
    )
    away_team_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.AWAY_TEAM_SLUG"
            ),
            "description": "Away team URL slug",
        },
    )
    away_team_wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.AWAY_TEAM_WINS"
            ),
            "description": "Away team win count",
        },
    )
    away_team_losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2"
                ".AWAY_TEAM_LOSSES"
            ),
            "description": "Away team loss count",
        },
    )
    away_team_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.AWAY_TEAM_SCORE"
            ),
            "description": "Away team score",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.HOME_TEAM_ID"
            ),
            "description": "Home team identifier",
        },
    )
    home_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.HOME_TEAM_NAME"
            ),
            "description": "Home team name",
        },
    )
    home_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.HOME_TEAM_CITY"
            ),
            "description": "Home team city",
        },
    )
    home_team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2"
                ".HOME_TEAM_TRICODE"
            ),
            "description": "Home team three-letter code",
        },
    )
    home_team_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.HOME_TEAM_SLUG"
            ),
            "description": "Home team URL slug",
        },
    )
    home_team_wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.HOME_TEAM_WINS"
            ),
            "description": "Home team win count",
        },
    )
    home_team_losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2"
                ".HOME_TEAM_LOSSES"
            ),
            "description": "Home team loss count",
        },
    )
    home_team_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.HOME_TEAM_SCORE"
            ),
            "description": "Home team score",
        },
    )
    arena_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.ARENA_NAME"
            ),
            "description": "Arena name",
        },
    )
    arena_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.ARENA_CITY"
            ),
            "description": "Arena city",
        },
    )
    arena_state: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.ARENA_STATE"
            ),
            "description": "Arena state",
        },
    )
    postponed_status: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.POSTPONED_STATUS"
            ),
            "description": "Postponement status",
        },
    )
    branch_link: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.BRANCH_LINK"
            ),
            "description": "Branch deep link URL",
        },
    )
    game_subtype: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.GAME_SUBTYPE"
            ),
            "description": "Game subtype classification",
        },
    )
    series_conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2"
                ".SERIES_CONFERENCE"
            ),
            "description": "Playoff series conference",
        },
    )
    series_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.SERIES_TEXT"
            ),
            "description": "Playoff series status text",
        },
    )
    if_necessary: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2.IF_NECESSARY"
            ),
            "description": "If-necessary game indicator",
        },
    )
    series_game_number: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScheduleLeagueV2"
                ".ScheduleLeagueV2"
                ".SERIES_GAME_NUMBER"
            ),
            "description": "Game number in playoff series",
        },
    )


class RawScoreboardV2Schema(BaseSchema):
    game_date_est: str = pa.Field(
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".GAME_DATE_EST"
            ),
            "description": (
                "Game date in Eastern time"
            ),
        },
    )
    game_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".GAME_SEQUENCE"
            ),
            "description": (
                "Game sequence number for the day"
            ),
        },
    )
    game_id: str = pa.Field(
        metadata={
            "source": (
                "ScoreboardV2.GameHeader.GAME_ID"
            ),
            "description": "Unique game identifier",
        },
    )
    game_status_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".GAME_STATUS_ID"
            ),
            "description": "Game status identifier",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".GAME_STATUS_TEXT"
            ),
            "description": "Game status display text",
        },
    )
    gamecode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader.GAMECODE"
            ),
            "description": "Game code string",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".HOME_TEAM_ID"
            ),
            "description": "Home team identifier",
        },
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".VISITOR_TEAM_ID"
            ),
            "description": "Visitor team identifier",
        },
    )
    season: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader.SEASON"
            ),
            "description": "Season year string",
        },
    )
    live_period: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".LIVE_PERIOD"
            ),
            "description": "Current live period",
        },
    )
    live_pc_time: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".LIVE_PC_TIME"
            ),
            "description": "Live game clock time",
        },
    )
    natl_tv_broadcaster_abbreviation: (
        str | None
    ) = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".NATL_TV_BROADCASTER_ABBREVIATION"
            ),
            "description": (
                "National TV broadcaster abbreviation"
            ),
        },
    )
    home_tv_broadcaster_abbreviation: (
        str | None
    ) = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".HOME_TV_BROADCASTER_ABBREVIATION"
            ),
            "description": (
                "Home TV broadcaster abbreviation"
            ),
        },
    )
    away_tv_broadcaster_abbreviation: (
        str | None
    ) = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".AWAY_TV_BROADCASTER_ABBREVIATION"
            ),
            "description": (
                "Away TV broadcaster abbreviation"
            ),
        },
    )
    live_period_time_bcast: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader"
                ".LIVE_PERIOD_TIME_BCAST"
            ),
            "description": (
                "Live period time broadcast string"
            ),
        },
    )
    arena_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader.ARENA_NAME"
            ),
            "description": "Arena name",
        },
    )
    wh_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "ScoreboardV2.GameHeader.WH_STATUS"
            ),
            "description": "Wagering hub status flag",
        },
    )
