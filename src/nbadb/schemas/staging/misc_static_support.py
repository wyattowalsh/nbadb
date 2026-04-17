from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingLeagueGameFinderSchema(BaseSchema):
    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.SEASON_ID",
            "description": "Season identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.TEAM_ABBREVIATION",
            "description": "Team abbreviation",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.TEAM_NAME",
            "description": "Team name",
        },
    )
    game_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.GAME_ID",
            "description": "Game identifier",
        },
    )
    game_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.GAME_DATE",
            "description": "Game date",
        },
    )
    matchup: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.MATCHUP",
            "description": "Matchup label",
        },
    )
    wl: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.WL",
            "description": "Win or loss result",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.MIN",
            "description": "Minutes played",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.PTS",
            "description": "Points scored",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.FGM",
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.FGA",
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.FG_PCT",
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.FG3M",
            "description": "Three-pointers made",
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.FG3A",
            "description": "Three-pointers attempted",
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.FG3_PCT",
            "description": "Three-point percentage",
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.FTM",
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.FTA",
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.FT_PCT",
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.OREB",
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.DREB",
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.REB",
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.AST",
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.STL",
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.BLK",
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.TOV",
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.PF",
            "description": "Personal fouls",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueGameFinder.LeagueGameFinderResults.PLUS_MINUS",
            "description": "Plus-minus",
        },
    )


class StagingSeasonMatchupsSchema(BaseSchema):
    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.SEASON_ID",
            "description": "Season identifier",
        },
    )
    off_player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.OFF_PLAYER_ID",
            "description": "Offensive player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    off_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.OFF_PLAYER_NAME",
            "description": "Offensive player name",
        },
    )
    def_player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.DEF_PLAYER_ID",
            "description": "Defensive player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    def_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.DEF_PLAYER_NAME",
            "description": "Defensive player name",
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.GP",
            "description": "Games played",
        },
    )
    matchup_min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_MIN",
            "description": "Minutes in matchup",
        },
    )
    partial_poss: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.PARTIAL_POSS",
            "description": "Partial possessions",
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.PLAYER_PTS",
            "description": "Player points in matchup",
        },
    )
    team_pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.TEAM_PTS",
            "description": "Team points in matchup",
        },
    )
    matchup_ast: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_AST",
            "description": "Assists in matchup",
        },
    )
    matchup_tov: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_TOV",
            "description": "Turnovers in matchup",
        },
    )
    matchup_blk: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_BLK",
            "description": "Blocks in matchup",
        },
    )
    matchup_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_FGM",
            "description": "Field goals made in matchup",
        },
    )
    matchup_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_FGA",
            "description": "Field goals attempted in matchup",
        },
    )
    matchup_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_FG_PCT",
            "description": "Field goal percentage in matchup",
        },
    )
    matchup_fg3m: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_FG3M",
            "description": "Three-pointers made in matchup",
        },
    )
    matchup_fg3a: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_FG3A",
            "description": "Three-pointers attempted in matchup",
        },
    )
    matchup_fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_FG3_PCT",
            "description": "Three-point percentage in matchup",
        },
    )
    help_blk: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.HELP_BLK",
            "description": "Help blocks",
        },
    )
    help_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.HELP_FGM",
            "description": "Help field goals made",
        },
    )
    help_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.HELP_FGA",
            "description": "Help field goals attempted",
        },
    )
    help_fg_perc: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.HELP_FG_PERC",
            "description": "Help field goal percentage",
        },
    )
    matchup_ftm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_FTM",
            "description": "Free throws made in matchup",
        },
    )
    matchup_fta: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.MATCHUP_FTA",
            "description": "Free throws attempted in matchup",
        },
    )
    sfl: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "LeagueSeasonMatchups.SeasonMatchups.SFL",
            "description": "Shooting fouls drawn",
        },
    )


class StagingMatchupsRollupSchema(BaseSchema):
    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.SEASON_ID",
            "description": "Season identifier",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.POSITION",
            "description": "Defensive position bucket",
        },
    )
    percent_of_time: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.PERCENT_OF_TIME",
            "description": "Percent of time guarding this position",
        },
    )
    def_player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.DEF_PLAYER_ID",
            "description": "Defensive player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    def_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.DEF_PLAYER_NAME",
            "description": "Defensive player name",
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"source": "MatchupsRollup.MatchupsRollup.GP", "description": "Games played"},
    )
    matchup_min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_MIN",
            "description": "Minutes in matchup",
        },
    )
    partial_poss: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.PARTIAL_POSS",
            "description": "Partial possessions",
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.PLAYER_PTS",
            "description": "Player points in matchup",
        },
    )
    team_pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.TEAM_PTS",
            "description": "Team points in matchup",
        },
    )
    matchup_ast: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_AST",
            "description": "Assists in matchup",
        },
    )
    matchup_tov: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_TOV",
            "description": "Turnovers in matchup",
        },
    )
    matchup_blk: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_BLK",
            "description": "Blocks in matchup",
        },
    )
    matchup_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_FGM",
            "description": "Field goals made in matchup",
        },
    )
    matchup_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_FGA",
            "description": "Field goals attempted in matchup",
        },
    )
    matchup_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_FG_PCT",
            "description": "Field goal percentage in matchup",
        },
    )
    matchup_fg3m: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_FG3M",
            "description": "Three-pointers made in matchup",
        },
    )
    matchup_fg3a: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_FG3A",
            "description": "Three-pointers attempted in matchup",
        },
    )
    matchup_fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_FG3_PCT",
            "description": "Three-point percentage in matchup",
        },
    )
    matchup_ftm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_FTM",
            "description": "Free throws made in matchup",
        },
    )
    matchup_fta: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.MATCHUP_FTA",
            "description": "Free throws attempted in matchup",
        },
    )
    sfl: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "MatchupsRollup.MatchupsRollup.SFL",
            "description": "Shooting fouls drawn",
        },
    )


class StagingPlayByPlayVideoAvailableSchema(BaseSchema):
    video_available: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": "PlayByPlayV3.AvailableVideo.videoAvailable",
            "description": "Flag indicating whether video is available for the play",
        },
    )


class StagingScheduleWeeksSchema(BaseSchema):
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2.SeasonWeeks.leagueId",
            "description": "League identifier",
        },
    )
    season_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2.SeasonWeeks.seasonYear",
            "description": "Season year",
        },
    )
    week_number: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "ScheduleLeagueV2.SeasonWeeks.weekNumber",
            "description": "Week number within the season",
        },
    )
    week_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2.SeasonWeeks.weekName",
            "description": "Display label for the week",
        },
    )
    start_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ScheduleLeagueV2.SeasonWeeks.startDate",
            "description": "Week start date",
        },
    )
    end_date: str | None = pa.Field(
        nullable=True,
        metadata={"source": "ScheduleLeagueV2.SeasonWeeks.endDate", "description": "Week end date"},
    )


class StagingTeamStreakFinderSchema(BaseSchema):
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.TEAM_NAME",
            "description": "Team name",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    gamestreak: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.GAMESTREAK",
            "description": "Game streak summary",
        },
    )
    startdate: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.STARTDATE",
            "description": "Start date of the streak window",
        },
    )
    enddate: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.ENDDATE",
            "description": "End date of the streak window",
        },
    )
    activestreak: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.ACTIVESTREAK",
            "description": "Whether the streak is still active",
        },
    )
    numseasons: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.NUMSEASONS",
            "description": "Number of seasons represented by the streak",
        },
    )
    lastseason: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.LASTSEASON",
            "description": "Last season represented by the streak",
        },
    )
    firstseason: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.FIRSTSEASON",
            "description": "First season represented by the streak",
        },
    )
    abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamGameStreakFinder.TeamGameStreakFinderParametersResults.ABBREVIATION",
            "description": "Team abbreviation",
        },
    )


class StagingStaticPlayersSchema(BaseSchema):
    id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": "nba_api.stats.static.players.get_players.id",
            "description": "Static player identifier",
        },
    )
    full_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.players.get_players.full_name",
            "description": "Player full name",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.players.get_players.first_name",
            "description": "Player first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.players.get_players.last_name",
            "description": "Player last name",
        },
    )
    is_active: bool | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.players.get_players.is_active",
            "description": "Whether the player is currently active",
        },
    )


class StagingStaticTeamsSchema(BaseSchema):
    id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.id",
            "description": "Static team identifier",
        },
    )
    full_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.full_name",
            "description": "Team full name",
        },
    )
    abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.abbreviation",
            "description": "Team abbreviation",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.nickname",
            "description": "Team nickname",
        },
    )
    city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.city",
            "description": "Team city",
        },
    )
    state: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.state",
            "description": "Team state or province",
        },
    )
    year_founded: int | None = pa.Field(
        nullable=True,
        ge=1900,
        metadata={
            "source": "nba_api.stats.static.teams.get_teams.year_founded",
            "description": "Franchise founding year",
        },
    )
