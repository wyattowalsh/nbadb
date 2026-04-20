"""Pandera star-schema contract for dim_schedule_int."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class DimScheduleIntSchema(BaseSchema):
    """International schedule dimension — one row per game from ScheduleLeagueV2Int."""

    game_id: str = pa.Field(
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameId",
            "description": "Unique game identifier",
        },
    )
    game_code: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameCode",
            "description": "Game code (e.g. 20250115/BOSLAL)",
        },
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.leagueId",
            "description": "League identifier",
        },
    )
    season_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.seasonYear",
            "description": "Season year string",
        },
    )
    game_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameDate",
            "description": "Game date",
        },
    )
    game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameDateEst",
            "description": "Game date in US Eastern time",
        },
    )
    game_date_time_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameDateTimeEst",
            "description": "Game date-time in US Eastern time",
        },
    )
    game_date_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameDateUTC",
            "description": "Game date in UTC",
        },
    )
    game_time_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameTimeUTC",
            "description": "Game time in UTC",
        },
    )
    game_date_time_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameDateTimeUTC",
            "description": "Game date-time in UTC",
        },
    )
    game_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameStatus",
            "description": "Game status code (1=scheduled, 2=in-progress, 3=final)",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameStatusText",
            "description": "Human-readable game status",
        },
    )
    game_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameSequence",
            "description": "Game sequence number within the day",
        },
    )
    week_number: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.weekNumber",
            "description": "Week number within the season",
        },
    )
    week_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.weekName",
            "description": "Week name label",
        },
    )
    day_of_week: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.day",
            "description": "Day of the week",
        },
    )
    arena_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.arenaName",
            "description": "Arena name",
        },
    )
    arena_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.arenaCity",
            "description": "Arena city",
        },
    )
    arena_state: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.arenaState",
            "description": "Arena state",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.homeTeam_teamId",
            "description": "Home team identifier",
        },
    )
    home_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.homeTeam_teamName",
            "description": "Home team name",
        },
    )
    home_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.homeTeam_teamCity",
            "description": "Home team city",
        },
    )
    home_team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.homeTeam_teamTricode",
            "description": "Home team three-letter code",
        },
    )
    home_team_wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.homeTeam_wins",
            "description": "Home team wins at time of game",
        },
    )
    home_team_losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.homeTeam_losses",
            "description": "Home team losses at time of game",
        },
    )
    home_team_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.homeTeam_score",
            "description": "Home team final score",
        },
    )
    away_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.awayTeam_teamId",
            "description": "Away team identifier",
        },
    )
    away_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.awayTeam_teamName",
            "description": "Away team name",
        },
    )
    away_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.awayTeam_teamCity",
            "description": "Away team city",
        },
    )
    away_team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.awayTeam_teamTricode",
            "description": "Away team three-letter code",
        },
    )
    away_team_wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.awayTeam_wins",
            "description": "Away team wins at time of game",
        },
    )
    away_team_losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.awayTeam_losses",
            "description": "Away team losses at time of game",
        },
    )
    away_team_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.awayTeam_score",
            "description": "Away team final score",
        },
    )
    if_necessary: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.ifNecessary",
            "description": "Whether the game is if-necessary (playoffs)",
        },
    )
    series_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.seriesText",
            "description": "Playoff series status text",
        },
    )
    game_subtype: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.gameSubtype",
            "description": "Game subtype classification",
        },
    )
    is_neutral: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.isNeutral",
            "description": "Whether the game is at a neutral site",
        },
    )
    postponed_status: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.SeasonGames.postponedStatus",
            "description": "Postponement status",
        },
    )
    week_start_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.Weeks.startDate",
            "description": "Start date of the week this game falls in",
        },
    )
    week_end_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2Int.Weeks.endDate",
            "description": "End date of the week this game falls in",
        },
    )
