from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingScheduleLeagueV2Schema(BaseSchema):
    game_date: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_DATE"),
            "description": "Date of the game",
        },
    )
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    game_code: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_CODE"),
            "description": "Game code string",
        },
    )
    game_status: int | None = pa.Field(
        nullable=True,
        isin=[1, 2, 3],
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_STATUS"),
            "description": "Game status code",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_STATUS_TEXT"),
            "description": "Game status display text",
        },
    )
    game_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_SEQUENCE"),
            "description": ("Game sequence number for the day"),
        },
    )
    game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_DATE_EST"),
            "description": "Game date in Eastern time",
        },
    )
    game_time_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_TIME_EST"),
            "description": "Game time in Eastern time",
        },
    )
    game_date_time_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_DATE_TIME_EST"),
            "description": ("Game date and time in Eastern time"),
        },
    )
    game_date_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_DATE_UTC"),
            "description": "Game date in UTC",
        },
    )
    game_time_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_TIME_UTC"),
            "description": "Game time in UTC",
        },
    )
    game_date_time_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_DATE_TIME_UTC"),
            "description": "Game date and time in UTC",
        },
    )
    away_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.AWAY_TEAM_ID"),
            "description": "Away team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    away_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.AWAY_TEAM_NAME"),
            "description": "Away team name",
        },
    )
    away_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.AWAY_TEAM_CITY"),
            "description": "Away team city",
        },
    )
    away_team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.AWAY_TEAM_TRICODE"),
            "description": "Away team three-letter code",
        },
    )
    away_team_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.AWAY_TEAM_SLUG"),
            "description": "Away team URL slug",
        },
    )
    away_team_wins: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.AWAY_TEAM_WINS"),
            "description": "Away team win count",
        },
    )
    away_team_losses: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.AWAY_TEAM_LOSSES"),
            "description": "Away team loss count",
        },
    )
    away_team_score: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.AWAY_TEAM_SCORE"),
            "description": "Away team score",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.HOME_TEAM_ID"),
            "description": "Home team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    home_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.HOME_TEAM_NAME"),
            "description": "Home team name",
        },
    )
    home_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.HOME_TEAM_CITY"),
            "description": "Home team city",
        },
    )
    home_team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.HOME_TEAM_TRICODE"),
            "description": "Home team three-letter code",
        },
    )
    home_team_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.HOME_TEAM_SLUG"),
            "description": "Home team URL slug",
        },
    )
    home_team_wins: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.HOME_TEAM_WINS"),
            "description": "Home team win count",
        },
    )
    home_team_losses: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.HOME_TEAM_LOSSES"),
            "description": "Home team loss count",
        },
    )
    home_team_score: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.HOME_TEAM_SCORE"),
            "description": "Home team score",
        },
    )
    arena_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.ARENA_NAME"),
            "description": "Arena name",
        },
    )
    arena_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.ARENA_CITY"),
            "description": "Arena city",
        },
    )
    arena_state: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.ARENA_STATE"),
            "description": "Arena state",
        },
    )
    postponed_status: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.POSTPONED_STATUS"),
            "description": "Postponement status",
        },
    )
    branch_link: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.BRANCH_LINK"),
            "description": "Branch deep link URL",
        },
    )
    game_subtype: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.GAME_SUBTYPE"),
            "description": "Game subtype classification",
        },
    )
    series_conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.SERIES_CONFERENCE"),
            "description": "Playoff series conference",
        },
    )
    series_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.SERIES_TEXT"),
            "description": "Playoff series status text",
        },
    )
    if_necessary: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.IF_NECESSARY"),
            "description": "If-necessary game indicator",
        },
    )
    series_game_number: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScheduleLeagueV2.ScheduleLeagueV2.SERIES_GAME_NUMBER"),
            "description": ("Game number in playoff series"),
        },
    )
    league_id: str | None = pa.Field(nullable=True)
    season_year: str | None = pa.Field(nullable=True)
    away_team_time: str | None = pa.Field(nullable=True)
    home_team_time: str | None = pa.Field(nullable=True)
    day: str | None = pa.Field(nullable=True)
    month_num: int | None = pa.Field(nullable=True)
    week_number: int | None = pa.Field(nullable=True)
    week_name: str | None = pa.Field(nullable=True)
    game_label: str | None = pa.Field(nullable=True)
    game_sub_label: str | None = pa.Field(nullable=True)
    is_neutral: bool | int | None = pa.Field(nullable=True)
    home_team_team_id: int | None = pa.Field(nullable=True)
    home_team_team_name: str | None = pa.Field(nullable=True)
    home_team_team_city: str | None = pa.Field(nullable=True)
    home_team_team_tricode: str | None = pa.Field(nullable=True)
    home_team_team_slug: str | None = pa.Field(nullable=True)
    home_team_seed: int | None = pa.Field(nullable=True)
    away_team_team_id: int | None = pa.Field(nullable=True)
    away_team_team_name: str | None = pa.Field(nullable=True)
    away_team_team_city: str | None = pa.Field(nullable=True)
    away_team_team_tricode: str | None = pa.Field(nullable=True)
    away_team_team_slug: str | None = pa.Field(nullable=True)
    away_team_seed: int | None = pa.Field(nullable=True)
    points_leaders_person_id: int | None = pa.Field(nullable=True)
    points_leaders_first_name: str | None = pa.Field(nullable=True)
    points_leaders_last_name: str | None = pa.Field(nullable=True)
    points_leaders_team_id: int | None = pa.Field(nullable=True)
    points_leaders_team_city: str | None = pa.Field(nullable=True)
    points_leaders_team_name: str | None = pa.Field(nullable=True)
    points_leaders_team_tricode: str | None = pa.Field(nullable=True)
    points_leaders_points: int | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    national_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)


class StagingScoreboardV2Schema(BaseSchema):
    game_date_est: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("ScoreboardV2.GameHeader.GAME_DATE_EST"),
            "description": "Game date in Eastern time",
        },
    )
    game_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.GAME_SEQUENCE"),
            "description": ("Game sequence number for the day"),
        },
    )
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("ScoreboardV2.GameHeader.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    game_status_id: int | None = pa.Field(
        nullable=True,
        isin=[1, 2, 3],
        metadata={
            "source": ("ScoreboardV2.GameHeader.GAME_STATUS_ID"),
            "description": "Game status identifier",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.GAME_STATUS_TEXT"),
            "description": "Game status display text",
        },
    )
    gamecode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.GAMECODE"),
            "description": "Game code string",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.HOME_TEAM_ID"),
            "description": "Home team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.VISITOR_TEAM_ID"),
            "description": "Visitor team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    season: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.SEASON"),
            "description": "Season year string",
        },
    )
    live_period: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.LIVE_PERIOD"),
            "description": "Current live period",
        },
    )
    live_pc_time: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.LIVE_PC_TIME"),
            "description": "Live game clock time",
        },
    )
    natl_tv_broadcaster_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.NATL_TV_BROADCASTER_ABBREVIATION"),
            "description": ("National TV broadcaster abbreviation"),
        },
    )
    home_tv_broadcaster_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.HOME_TV_BROADCASTER_ABBREVIATION"),
            "description": ("Home TV broadcaster abbreviation"),
        },
    )
    away_tv_broadcaster_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.AWAY_TV_BROADCASTER_ABBREVIATION"),
            "description": ("Away TV broadcaster abbreviation"),
        },
    )
    live_period_time_bcast: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.LIVE_PERIOD_TIME_BCAST"),
            "description": ("Live period time broadcast string"),
        },
    )
    arena_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.ARENA_NAME"),
            "description": "Arena name",
        },
    )
    wh_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ScoreboardV2.GameHeader.WH_STATUS"),
            "description": "Wagering hub status flag",
        },
    )


class StagingScoreboardAvailableSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV2.Available.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    pt_available: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.Available.PT_AVAILABLE",
            "description": "Player-tracking availability flag",
        },
    )


class StagingScoreboardEastConfSchema(BaseSchema):
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.LEAGUE_ID",
            "description": "League identifier",
        },
    )
    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.SEASON_ID",
            "description": "Season identifier",
        },
    )
    standings_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.STANDINGSDATE",
            "description": "Standings date",
        },
    )
    conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.CONFERENCE",
            "description": "Conference name",
        },
    )
    team: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.TEAM",
            "description": "Team display name",
        },
    )
    g: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.EastConfStandingsByDay.G", "description": "Games played"},
    )
    w: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.EastConfStandingsByDay.W", "description": "Wins"},
    )
    losses: int | None = pa.Field(
        nullable=True,
        alias="l",
        metadata={"source": "ScoreboardV2.EastConfStandingsByDay.L", "description": "Losses"},
    )
    w_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.W_PCT",
            "description": "Winning percentage",
        },
    )
    home_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.HOME_RECORD",
            "description": "Home record",
        },
    )
    road_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.ROAD_RECORD",
            "description": "Road record",
        },
    )
    return_to_play: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.EastConfStandingsByDay.RETURNTOPLAY",
            "description": "Return-to-play marker",
        },
    )


class StagingScoreboardLastMeetingSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV2.LastMeeting.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    last_game_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_ID",
            "description": "Previous meeting game identifier",
        },
    )
    last_game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_DATE_EST",
            "description": "Previous meeting date",
        },
    )
    last_game_home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_HOME_TEAM_ID",
            "description": "Previous home team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    last_game_home_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_HOME_TEAM_CITY",
            "description": "Previous home team city",
        },
    )
    last_game_home_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_HOME_TEAM_NAME",
            "description": "Previous home team name",
        },
    )
    last_game_home_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_HOME_TEAM_ABBREVIATION",
            "description": "Previous home team abbreviation",
        },
    )
    last_game_home_team_points: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_HOME_TEAM_POINTS",
            "description": "Previous home team points",
        },
    )
    last_game_visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_VISITOR_TEAM_ID",
            "description": "Previous visitor team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    last_game_visitor_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_VISITOR_TEAM_CITY",
            "description": "Previous visitor team city",
        },
    )
    last_game_visitor_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_VISITOR_TEAM_NAME",
            "description": "Previous visitor team name",
        },
    )
    last_game_visitor_team_city1: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_VISITOR_TEAM_CITY1",
            "description": "Alternate previous visitor city label",
        },
    )
    last_game_visitor_team_points: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LastMeeting.LAST_GAME_VISITOR_TEAM_POINTS",
            "description": "Previous visitor team points",
        },
    )


class StagingScoreboardLineScoreSchema(BaseSchema):
    game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.GAME_DATE_EST",
            "description": "Game date in Eastern time",
        },
    )
    game_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.GAME_SEQUENCE",
            "description": "Game sequence number for the day",
        },
    )
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV2.LineScore.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_city_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.TEAM_CITY_NAME",
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.LineScore.TEAM_NAME", "description": "Team name"},
    )
    team_wins_losses: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.TEAM_WINS_LOSSES",
            "description": "Team record entering the game",
        },
    )
    pts_qtr1: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_QTR1",
            "description": "Points in first quarter",
        },
    )
    pts_qtr2: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_QTR2",
            "description": "Points in second quarter",
        },
    )
    pts_qtr3: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_QTR3",
            "description": "Points in third quarter",
        },
    )
    pts_qtr4: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_QTR4",
            "description": "Points in fourth quarter",
        },
    )
    pts_ot1: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT1",
            "description": "Points in first overtime",
        },
    )
    pts_ot2: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT2",
            "description": "Points in second overtime",
        },
    )
    pts_ot3: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT3",
            "description": "Points in third overtime",
        },
    )
    pts_ot4: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT4",
            "description": "Points in fourth overtime",
        },
    )
    pts_ot5: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT5",
            "description": "Points in fifth overtime",
        },
    )
    pts_ot6: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT6",
            "description": "Points in sixth overtime",
        },
    )
    pts_ot7: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT7",
            "description": "Points in seventh overtime",
        },
    )
    pts_ot8: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT8",
            "description": "Points in eighth overtime",
        },
    )
    pts_ot9: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT9",
            "description": "Points in ninth overtime",
        },
    )
    pts_ot10: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.PTS_OT10",
            "description": "Points in tenth overtime",
        },
    )
    pts: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.LineScore.PTS", "description": "Total points"},
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.FG_PCT",
            "description": "Field goal percentage",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.FT_PCT",
            "description": "Free throw percentage",
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.LineScore.FG3_PCT",
            "description": "Three-point percentage",
        },
    )
    ast: int | None = pa.Field(
        nullable=True, metadata={"source": "ScoreboardV2.LineScore.AST", "description": "Assists"}
    )
    reb: int | None = pa.Field(
        nullable=True, metadata={"source": "ScoreboardV2.LineScore.REB", "description": "Rebounds"}
    )
    tov: int | None = pa.Field(
        nullable=True, metadata={"source": "ScoreboardV2.LineScore.TOV", "description": "Turnovers"}
    )


class StagingScoreboardSeriesStandingsSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV2.SeriesStandings.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.SeriesStandings.HOME_TEAM_ID",
            "description": "Home team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.SeriesStandings.VISITOR_TEAM_ID",
            "description": "Visitor team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.SeriesStandings.GAME_DATE_EST",
            "description": "Game date in Eastern time",
        },
    )
    home_team_wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.SeriesStandings.HOME_TEAM_WINS",
            "description": "Home team wins in the series",
        },
    )
    home_team_losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.SeriesStandings.HOME_TEAM_LOSSES",
            "description": "Home team losses in the series",
        },
    )
    series_leader: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.SeriesStandings.SERIES_LEADER",
            "description": "Series leader label",
        },
    )


class StagingScoreboardTeamLeadersSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.TeamLeaders.TEAM_CITY", "description": "Team city name"},
    )
    team_nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.TEAM_NICKNAME",
            "description": "Team nickname",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    pts_player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.PTS_PLAYER_ID",
            "description": "Points leader player identifier",
        },
    )
    pts_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.PTS_PLAYER_NAME",
            "description": "Points leader player name",
        },
    )
    pts: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.TeamLeaders.PTS", "description": "Points leader total"},
    )
    reb_player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.REB_PLAYER_ID",
            "description": "Rebounds leader player identifier",
        },
    )
    reb_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.REB_PLAYER_NAME",
            "description": "Rebounds leader player name",
        },
    )
    reb: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.TeamLeaders.REB", "description": "Rebounds leader total"},
    )
    ast_player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.AST_PLAYER_ID",
            "description": "Assists leader player identifier",
        },
    )
    ast_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TeamLeaders.AST_PLAYER_NAME",
            "description": "Assists leader player name",
        },
    )
    ast: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.TeamLeaders.AST", "description": "Assists leader total"},
    )


class StagingScoreboardTicketLinksSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV2.TicketLinks.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    leag_tix: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.TicketLinks.LEAG_TIX",
            "description": "League ticket URL",
        },
    )


class StagingScoreboardV2SeriesStandingsSchema(StagingScoreboardSeriesStandingsSchema):
    pass


class StagingScoreboardWestConfSchema(BaseSchema):
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV2.WestConfStandingsByDay.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WestConfStandingsByDay.LEAGUE_ID",
            "description": "League identifier",
        },
    )
    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WestConfStandingsByDay.SEASON_ID",
            "description": "Season identifier",
        },
    )
    standings_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WestConfStandingsByDay.STANDINGSDATE",
            "description": "Standings date",
        },
    )
    conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WestConfStandingsByDay.CONFERENCE",
            "description": "Conference name",
        },
    )
    team: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WestConfStandingsByDay.TEAM",
            "description": "Team display name",
        },
    )
    g: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.WestConfStandingsByDay.G", "description": "Games played"},
    )
    w: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV2.WestConfStandingsByDay.W", "description": "Wins"},
    )
    losses: int | None = pa.Field(
        nullable=True,
        alias="l",
        metadata={"source": "ScoreboardV2.WestConfStandingsByDay.L", "description": "Losses"},
    )
    w_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WestConfStandingsByDay.W_PCT",
            "description": "Winning percentage",
        },
    )
    home_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WestConfStandingsByDay.HOME_RECORD",
            "description": "Home record",
        },
    )
    road_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WestConfStandingsByDay.ROAD_RECORD",
            "description": "Road record",
        },
    )


class StagingScoreboardWinProbabilitySchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={"source": "derived.game_id", "description": "Unique game identifier"},
    )
    home_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WinProbability.HOME_PCT",
            "description": "Home team win probability",
        },
    )
    visitor_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV2.WinProbability.VISITOR_PCT",
            "description": "Visitor team win probability",
        },
    )


class StagingScoreboardV3MetadataSchema(BaseSchema):
    game_date: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.ScoreboardInfo.gameDate", "description": "Game date"},
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.ScoreboardInfo.leagueId",
            "description": "League identifier",
        },
    )
    league_name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.ScoreboardInfo.leagueName", "description": "League name"},
    )


class StagingScoreboardV3SummarySchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV3.GameHeader.gameId",
            "description": "Unique game identifier",
        },
    )
    game_code: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.GameHeader.gameCode", "description": "Game code string"},
    )
    game_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.gameStatus",
            "description": "Game status identifier",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.gameStatusText",
            "description": "Game status display text",
        },
    )
    period: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.GameHeader.period", "description": "Current period"},
    )
    game_clock: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.GameHeader.gameClock", "description": "Game clock"},
    )
    game_time_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.gameTimeUTC",
            "description": "Game time in UTC",
        },
    )
    game_et: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.gameEt",
            "description": "Game time in Eastern time",
        },
    )
    regulation_periods: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.regulationPeriods",
            "description": "Regulation periods",
        },
    )
    series_game_number: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.seriesGameNumber",
            "description": "Series game number",
        },
    )
    game_label: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.GameHeader.gameLabel", "description": "Game label"},
    )
    game_sub_label: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.gameSubLabel",
            "description": "Game sub-label",
        },
    )
    series_text: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.GameHeader.seriesText", "description": "Series text"},
    )
    if_necessary: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.ifNecessary",
            "description": "If-necessary indicator",
        },
    )
    series_conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.seriesConference",
            "description": "Series conference",
        },
    )
    po_round_desc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.poRoundDesc",
            "description": "Playoff round description",
        },
    )
    game_subtype: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.GameHeader.gameSubtype", "description": "Game subtype"},
    )
    is_neutral: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.GameHeader.isNeutral",
            "description": "Neutral site flag",
        },
    )


class StagingScoreboardV3LineScoreSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV3.LineScore.gameId",
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.LineScore.teamId",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.LineScore.teamCity", "description": "Team city name"},
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.LineScore.teamName", "description": "Team name"},
    )
    team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.LineScore.teamTricode", "description": "Team tricode"},
    )
    team_slug: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.LineScore.teamSlug", "description": "Team slug"},
    )
    wins: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.LineScore.wins", "description": "Wins entering the game"},
    )
    losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.LineScore.losses",
            "description": "Losses entering the game",
        },
    )
    score: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.LineScore.score", "description": "Current score"},
    )
    seed: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.LineScore.seed", "description": "Playoff seed"},
    )
    in_bonus: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.LineScore.inBonus", "description": "In-bonus flag"},
    )
    timeouts_remaining: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.LineScore.timeoutsRemaining",
            "description": "Timeouts remaining",
        },
    )


class StagingScoreboardV3TeamStatsSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV3.TeamLeaders.gameId",
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.TeamLeaders.teamId",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    leader_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.TeamLeaders.leaderType",
            "description": "Leader statistic type",
        },
    )
    person_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.TeamLeaders.personId",
            "description": "Leader player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.TeamLeaders.name", "description": "Leader player name"},
    )
    player_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.TeamLeaders.playerSlug",
            "description": "Leader player slug",
        },
    )
    jersey_num: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.TeamLeaders.jerseyNum",
            "description": "Leader player jersey number",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.TeamLeaders.position",
            "description": "Leader player position",
        },
    )
    team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.TeamLeaders.teamTricode", "description": "Team tricode"},
    )
    points: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.TeamLeaders.points", "description": "Leader points"},
    )
    rebounds: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.TeamLeaders.rebounds", "description": "Leader rebounds"},
    )
    assists: int | None = pa.Field(
        nullable=True,
        metadata={"source": "ScoreboardV3.TeamLeaders.assists", "description": "Leader assists"},
    )
    season_leaders_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.TeamLeaders.seasonLeadersFlag",
            "description": "Season leaders flag",
        },
    )


class StagingScoreboardV3BroadcasterSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "ScoreboardV3.Broadcasters.gameId",
            "description": "Unique game identifier",
        },
    )
    broadcaster_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.Broadcasters.broadcasterType",
            "description": "Broadcaster type",
        },
    )
    broadcaster_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.Broadcasters.broadcasterId",
            "description": "Broadcaster identifier",
        },
    )
    broadcast_display: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.Broadcasters.broadcastDisplay",
            "description": "Broadcast display string",
        },
    )
    broadcaster_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.Broadcasters.broadcasterTeamId",
            "description": "Broadcaster team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    broadcaster_description: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScoreboardV3.Broadcasters.broadcasterDescription",
            "description": "Broadcaster description",
        },
    )


class StagingScheduleIntSchema(BaseSchema):
    league_id: str | None = pa.Field(nullable=True)
    season_year: str | None = pa.Field(nullable=True)
    game_date: str | None = pa.Field(nullable=True)
    game_id: str = pa.Field(nullable=False)
    game_code: str | None = pa.Field(nullable=True)
    game_status: int | None = pa.Field(nullable=True)
    game_status_text: str | None = pa.Field(nullable=True)
    game_sequence: int | None = pa.Field(nullable=True)
    game_date_est: str | None = pa.Field(nullable=True)
    game_date_time_est: str | None = pa.Field(nullable=True)
    game_date_utc: str | None = pa.Field(nullable=True)
    game_time_utc: str | None = pa.Field(nullable=True)
    game_date_time_utc: str | None = pa.Field(nullable=True)
    day: str | None = pa.Field(nullable=True)
    week_number: int | None = pa.Field(nullable=True)
    week_name: str | None = pa.Field(nullable=True)
    if_necessary: str | None = pa.Field(nullable=True)
    series_text: str | None = pa.Field(nullable=True)
    arena_name: str | None = pa.Field(nullable=True)
    arena_state: str | None = pa.Field(nullable=True)
    arena_city: str | None = pa.Field(nullable=True)
    postponed_status: str | None = pa.Field(nullable=True)
    game_subtype: str | None = pa.Field(nullable=True)
    is_neutral: bool | int | None = pa.Field(nullable=True)
    home_team_team_id: int | None = pa.Field(nullable=True, gt=0)
    home_team_team_name: str | None = pa.Field(nullable=True)
    home_team_team_city: str | None = pa.Field(nullable=True)
    home_team_team_tricode: str | None = pa.Field(nullable=True)
    home_team_wins: int | None = pa.Field(nullable=True, ge=0)
    home_team_losses: int | None = pa.Field(nullable=True, ge=0)
    home_team_score: int | None = pa.Field(nullable=True, ge=0)
    away_team_team_id: int | None = pa.Field(nullable=True, gt=0)
    away_team_team_name: str | None = pa.Field(nullable=True)
    away_team_team_city: str | None = pa.Field(nullable=True)
    away_team_team_tricode: str | None = pa.Field(nullable=True)
    away_team_wins: int | None = pa.Field(nullable=True, ge=0)
    away_team_losses: int | None = pa.Field(nullable=True, ge=0)
    away_team_score: int | None = pa.Field(nullable=True, ge=0)
    game_time_est: str | None = pa.Field(nullable=True)
    branch_link: str | None = pa.Field(nullable=True)
    month_num: int | None = pa.Field(nullable=True)
    series_game_number: str | None = pa.Field(nullable=True)
    game_label: str | None = pa.Field(nullable=True)
    game_sub_label: str | None = pa.Field(nullable=True)
    home_team_time: str | None = pa.Field(nullable=True)
    home_team_team_slug: str | None = pa.Field(nullable=True)
    home_team_seed: int | None = pa.Field(nullable=True)
    away_team_time: str | None = pa.Field(nullable=True)
    away_team_team_slug: str | None = pa.Field(nullable=True)
    away_team_seed: int | None = pa.Field(nullable=True)
    points_leaders_person_id: int | None = pa.Field(nullable=True)
    points_leaders_first_name: str | None = pa.Field(nullable=True)
    points_leaders_last_name: str | None = pa.Field(nullable=True)
    points_leaders_team_id: int | None = pa.Field(nullable=True)
    points_leaders_team_city: str | None = pa.Field(nullable=True)
    points_leaders_team_name: str | None = pa.Field(nullable=True)
    points_leaders_team_tricode: str | None = pa.Field(nullable=True)
    points_leaders_points: int | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    national_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    national_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    national_radio_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    national_ott_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    home_tv_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    home_radio_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    home_ott_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    away_tv_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    away_radio_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_scope: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_media: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_id: int | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_display: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_tape_delay_comments: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_video_link: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_description: str | None = pa.Field(nullable=True)
    away_ott_broadcasters_broadcaster_team_id: int | None = pa.Field(nullable=True)


class StagingScheduleIntWeeksSchema(BaseSchema):
    league_id: str | None = pa.Field(nullable=True)
    season_year: str | None = pa.Field(nullable=True)
    week_number: int | None = pa.Field(nullable=True)
    week_name: str | None = pa.Field(nullable=True)
    start_date: str | None = pa.Field(nullable=True)
    end_date: str | None = pa.Field(nullable=True)


class StagingScheduleIntBroadcasterSchema(BaseSchema):
    league_id: str | None = pa.Field(nullable=True)
    season_year: str | None = pa.Field(nullable=True)
    broadcaster_abbreviation: str | None = pa.Field(nullable=True)
    broadcaster_display: str | None = pa.Field(nullable=True)
    broadcaster_id: int | None = pa.Field(nullable=True)
    region_id: int | None = pa.Field(nullable=True)
