from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingLeagueStandingsV3Schema(BaseSchema):
    league_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LeagueID"),
            "description": "League identifier",
        },
    )
    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.SeasonID"),
            "description": "Season identifier",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TeamID"),
            "description": "Unique team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TeamCity"),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TeamName"),
            "description": "Team name",
        },
    )
    team_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TeamSlug"),
            "description": "URL-friendly team slug",
        },
    )
    conference: str | None = pa.Field(
        nullable=True,
        isin=["East", "West"],
        metadata={
            "source": ("LeagueStandingsV3.Standings.Conference"),
            "description": "Conference name",
        },
    )
    conference_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ConferenceRecord"),
            "description": ("Win-loss record in conference"),
        },
    )
    playoff_rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.PlayoffRank"),
            "description": "Playoff seeding rank",
        },
    )
    clinch_indicator: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ClinchIndicator"),
            "description": "Clinch status indicator",
        },
    )
    division: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.Division"),
            "description": "Division name",
        },
    )
    division_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DivisionRecord"),
            "description": ("Win-loss record in division"),
        },
    )
    division_rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DivisionRank"),
            "description": "Rank within division",
        },
    )
    wins: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.WINS"),
            "description": "Total wins",
        },
    )
    losses: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LOSSES"),
            "description": "Total losses",
        },
    )
    win_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.WinPCT"),
            "description": "Winning percentage",
        },
    )
    league_rank: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LeagueRank"),
            "description": "Overall league rank",
        },
    )
    record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.Record"),
            "description": "Overall win-loss record",
        },
    )
    home: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.HOME"),
            "description": "Home win-loss record",
        },
    )
    road: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ROAD"),
            "description": "Road win-loss record",
        },
    )
    l10: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.L10"),
            "description": "Record in last 10 games",
        },
    )
    long_win_streak: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LongWinStreak"),
            "description": "Longest winning streak",
        },
    )
    long_loss_streak: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.LongLossStreak"),
            "description": "Longest losing streak",
        },
    )
    current_streak: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.CurrentStreak"),
            "description": ("Current win or loss streak"),
        },
    )
    ot_record: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.OT_Record"),
            "description": ("Overtime win-loss record"),
        },
    )
    three_pts_or_less: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ThreePTSOrLess"),
            "description": ("Record in games decided by 3 points or less"),
        },
    )
    ten_pts_or_more: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.TenPTSOrMore"),
            "description": ("Record in games decided by 10 points or more"),
        },
    )
    conference_games_back: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.ConferenceGamesBack"),
            "description": ("Games behind conference leader"),
        },
    )
    division_games_back: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DivisionGamesBack"),
            "description": ("Games behind division leader"),
        },
    )
    clinched_conference_title: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("LeagueStandingsV3.Standings.ClinchedConferenceTitle"),
            "description": ("Whether team clinched conference"),
        },
    )
    clinched_division_title: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("LeagueStandingsV3.Standings.ClinchedDivisionTitle"),
            "description": ("Whether team clinched division"),
        },
    )
    clinched_playoff_birth: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("LeagueStandingsV3.Standings.ClinchedPlayoffBirth"),
            "description": ("Whether team clinched playoff berth"),
        },
    )
    eliminated_conference: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("LeagueStandingsV3.Standings.EliminatedConference"),
            "description": ("Whether team eliminated from conference playoff contention"),
        },
    )
    pts_pg: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.PointsPG"),
            "description": "Points per game",
        },
    )
    opp_pts_pg: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("LeagueStandingsV3.Standings.OppPointsPG"),
            "description": ("Opponent points per game"),
        },
    )
    diff_pts_pg: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("LeagueStandingsV3.Standings.DiffPointsPG"),
            "description": ("Point differential per game"),
        },
    )


class StagingShotChartDetailSchema(BaseSchema):
    grid_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.GRID_TYPE"),
            "description": "Shot chart grid type",
        },
    )
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    game_event_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.GAME_EVENT_ID"),
            "description": ("Event identifier within game"),
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.TEAM_NAME"),
            "description": "Team name",
        },
    )
    period: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.PERIOD"),
            "description": "Game period number",
        },
    )
    minutes_remaining: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.MINUTES_REMAINING"),
            "description": ("Minutes remaining in period"),
        },
    )
    seconds_remaining: int | None = pa.Field(
        nullable=True,
        ge=0,
        le=59,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SECONDS_REMAINING"),
            "description": ("Seconds remaining in period"),
        },
    )
    event_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.EVENT_TYPE"),
            "description": ("Shot event type (Made/Missed)"),
        },
    )
    action_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.ACTION_TYPE"),
            "description": ("Specific shot action type"),
        },
    )
    shot_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_TYPE"),
            "description": ("Shot type (2PT/3PT Field Goal)"),
        },
    )
    shot_zone_basic: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_ZONE_BASIC"),
            "description": ("Basic shot zone category"),
        },
    )
    shot_zone_area: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_ZONE_AREA"),
            "description": "Shot zone area on court",
        },
    )
    shot_zone_range: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_ZONE_RANGE"),
            "description": ("Shot distance range bucket"),
        },
    )
    shot_distance: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_DISTANCE"),
            "description": "Shot distance in feet",
        },
    )
    loc_x: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.LOC_X"),
            "description": ("Shot X coordinate on court"),
        },
    )
    loc_y: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.LOC_Y"),
            "description": ("Shot Y coordinate on court"),
        },
    )
    shot_attempted_flag: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_ATTEMPTED_FLAG"),
            "description": ("Flag indicating shot was attempted"),
        },
    )
    shot_made_flag: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.SHOT_MADE_FLAG"),
            "description": ("Flag indicating shot was made"),
        },
    )
    game_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.GAME_DATE"),
            "description": "Date of the game",
        },
    )
    htm: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.HTM"),
            "description": "Home team abbreviation",
        },
    )
    vtm: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("ShotChartDetail.Shot_Chart_Detail.VTM"),
            "description": ("Visitor team abbreviation"),
        },
    )


class StagingWinProbabilitySchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    event_num: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.EVENT_NUM"),
            "description": "Event sequence number",
        },
    )
    home_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.HOME_PCT"),
            "description": ("Home team win probability"),
        },
    )
    visitor_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.VISITOR_PCT"),
            "description": ("Visitor team win probability"),
        },
    )
    home_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.HOME_PTS"),
            "description": "Home team points",
        },
    )
    visitor_pts: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.VISITOR_PTS"),
            "description": "Visitor team points",
        },
    )
    home_score_margin: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.HOME_SCORE_MARGIN"),
            "description": ("Home team score margin"),
        },
    )
    period: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.PERIOD"),
            "description": "Game period number",
        },
    )
    seconds_remaining: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.SECONDS_REMAINING"),
            "description": ("Seconds remaining in period"),
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.HOME_TEAM_ID"),
            "description": "Home team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    home_team_abb: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.HOME_TEAM_ABB"),
            "description": ("Home team abbreviation code"),
        },
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.VISITOR_TEAM_ID"),
            "description": ("Visitor team identifier"),
            "fk_ref": "staging_team.team_id",
        },
    )
    visitor_team_abb: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.VISITOR_TEAM_ABB"),
            "description": ("Visitor team abbreviation code"),
        },
    )
    description: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.DESCRIPTION"),
            "description": ("Text description of the play"),
        },
    )
    location: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.LOCATION"),
            "description": ("Home or away location indicator"),
        },
    )
    pctimestring: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.PCTIMESTRING"),
            "description": ("Period clock time string"),
        },
    )
    is_score_change: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": ("WinProbabilityPBP.WinProbPBP.IS_SCORE_CHANGE"),
            "description": ("Flag indicating if score changed"),
        },
    )


class StagingGameRotationSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("GameRotation.HomeTeam.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.TEAM_CITY"),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.TEAM_NAME"),
            "description": "Team name",
        },
    )
    person_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.PERSON_ID"),
            "description": "Player person identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_first: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.PLAYER_FIRST"),
            "description": "Player first name",
        },
    )
    player_last: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.PLAYER_LAST"),
            "description": "Player last name",
        },
    )
    in_time_real: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("GameRotation.HomeTeam.IN_TIME_REAL"),
            "description": ("Real time player entered game"),
        },
    )
    out_time_real: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("GameRotation.HomeTeam.OUT_TIME_REAL"),
            "description": ("Real time player exited game"),
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("GameRotation.HomeTeam.PLAYER_PTS"),
            "description": ("Points scored during stint"),
        },
    )
    pt_diff: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("GameRotation.HomeTeam.PT_DIFF"),
            "description": ("Point differential during stint"),
        },
    )
    usg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("GameRotation.HomeTeam.USG_PCT"),
            "description": ("Usage percentage during stint"),
        },
    )


class StagingSynergyPlayTypesSchema(BaseSchema):
    season_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.SEASON_ID"),
            "description": "NBA season identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TEAM_ABBREVIATION"),
            "description": ("Team abbreviation code"),
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TEAM_NAME"),
            "description": "Team name",
        },
    )
    player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PLAYER_ID"),
            "description": ("Unique player identifier"),
            "fk_ref": ("staging_player.person_id"),
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    play_type: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PLAY_TYPE"),
            "description": ("Synergy play type classification"),
        },
    )
    type_grouping: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TYPE_GROUPING"),
            "description": ("Offensive or defensive grouping"),
        },
    )
    percentile: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PERCENTILE"),
            "description": ("Percentile rank for play type"),
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.GP"),
            "description": "Games played",
        },
    )
    poss_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.POSS_PCT"),
            "description": ("Percentage of possessions"),
        },
    )
    ppp: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PPP"),
            "description": ("Points per possession"),
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FG_PCT"),
            "description": ("Field goal percentage"),
        },
    )
    ft_pct_adjust: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FT_PCT_ADJUST"),
            "description": ("Free throw percentage adjusted"),
        },
    )
    to_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.TO_PCT"),
            "description": "Turnover percentage",
        },
    )
    sf_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.SF_PCT"),
            "description": ("Shooting foul percentage"),
        },
    )
    plusone_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PLUSONE_PCT"),
            "description": ("And-one conversion percentage"),
        },
    )
    score_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.SCORE_PCT"),
            "description": "Scoring percentage",
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.EFG_PCT"),
            "description": ("Effective field goal percentage"),
        },
    )
    poss: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.POSS"),
            "description": "Total possessions",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.PTS"),
            "description": "Total points scored",
        },
    )
    fgm: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FGM"),
            "description": "Field goals made",
        },
    )
    fga: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FGA"),
            "description": ("Field goals attempted"),
        },
    )
    fgmx: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("SynergyPlayTypes.SynergyPlayType.FGMX"),
            "description": "Field goals missed",
        },
    )


class StagingBoxScoreMatchupsSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.GAME_ID"),
            "description": ("Unique game identifier"),
            "fk_ref": ("staging_game_log.game_id"),
        },
    )
    off_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.OFF_TEAM_ID"),
            "description": ("Offensive team identifier"),
            "fk_ref": "staging_team.team_id",
        },
    )
    off_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.OFF_TEAM_ABBREVIATION"),
            "description": ("Offensive team abbreviation"),
        },
    )
    def_team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.DEF_TEAM_ID"),
            "description": ("Defensive team identifier"),
            "fk_ref": "staging_team.team_id",
        },
    )
    def_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.DEF_TEAM_ABBREVIATION"),
            "description": ("Defensive team abbreviation"),
        },
    )
    off_player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.OFF_PLAYER_ID"),
            "description": ("Offensive player identifier"),
            "fk_ref": ("staging_player.person_id"),
        },
    )
    off_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.OFF_PLAYER_NAME"),
            "description": ("Offensive player name"),
        },
    )
    def_player_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.DEF_PLAYER_ID"),
            "description": ("Defensive player identifier"),
            "fk_ref": ("staging_player.person_id"),
        },
    )
    def_player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.DEF_PLAYER_NAME"),
            "description": ("Defensive player name"),
        },
    )
    matchup_min: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_MIN"),
            "description": ("Minutes in matchup"),
        },
    )
    partial_poss: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.PARTIAL_POSS"),
            "description": ("Partial possessions in matchup"),
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.PLAYER_PTS"),
            "description": ("Player points in matchup"),
        },
    )
    team_pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.TEAM_PTS"),
            "description": ("Team points in matchup"),
        },
    )
    matchup_ast: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_AST"),
            "description": ("Assists in matchup"),
        },
    )
    matchup_tov: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_TOV"),
            "description": ("Turnovers in matchup"),
        },
    )
    matchup_blk: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_BLK"),
            "description": "Blocks in matchup",
        },
    )
    matchup_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_FGM"),
            "description": ("Field goals made in matchup"),
        },
    )
    matchup_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_FGA"),
            "description": ("Field goals attempted"),
        },
    )
    matchup_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_FG_PCT"),
            "description": ("Field goal pct in matchup"),
        },
    )
    matchup_fg3m: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_FG3M"),
            "description": ("Three-pointers made"),
        },
    )
    matchup_fg3a: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_FG3A"),
            "description": ("Three-pointers attempted"),
        },
    )
    matchup_fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_FG3_PCT"),
            "description": ("Three-point pct in matchup"),
        },
    )
    help_blk: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.HELP_BLK"),
            "description": ("Help blocks in matchup"),
        },
    )
    help_fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.HELP_FGM"),
            "description": ("Help field goals made"),
        },
    )
    help_fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.HELP_FGA"),
            "description": ("Help field goals attempted"),
        },
    )
    help_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.HELP_FG_PCT"),
            "description": ("Help field goal percentage"),
        },
    )
    matchup_ftm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_FTM"),
            "description": ("Free throws made in matchup"),
        },
    )
    matchup_fta: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.MATCHUP_FTA"),
            "description": ("Free throws attempted"),
        },
    )
    switches_on: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("BoxScoreMatchupsV3.PlayerStats.SWITCHES_ON"),
            "description": ("Switches onto player"),
        },
    )


class StagingArenaInfoSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreSummaryV3.ArenaInfo.gameId"),
            "description": "Unique game identifier",
        },
    )
    arena_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreSummaryV3.ArenaInfo.arenaId"),
            "description": "Arena identifier",
        },
    )
    arena_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreSummaryV3.ArenaInfo.arenaName"),
            "description": "Arena name",
        },
    )
    arena_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreSummaryV3.ArenaInfo.arenaCity"),
            "description": "Arena city",
        },
    )
    arena_state: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreSummaryV3.ArenaInfo.arenaState"),
            "description": "Arena state or province",
        },
    )
    arena_country: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreSummaryV3.ArenaInfo.arenaCountry"),
            "description": "Arena country",
        },
    )
    arena_timezone: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreSummaryV3.ArenaInfo.arenaTimezone"),
            "description": "Arena timezone",
        },
    )
