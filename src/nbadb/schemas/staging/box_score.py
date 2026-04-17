from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingBoxScoreTraditionalPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TEAM_ABBREVIATION"),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TEAM_CITY"),
            "description": "Team city name",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.NICKNAME"),
            "description": "Player nickname",
        },
    )
    start_position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.START_POSITION"),
            "description": ("Starting position (F/C/G)"),
        },
    )
    comment: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.COMMENT"),
            "description": "Player status comment",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FGM"),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FGA"),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG_PCT"),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG3M"),
            "description": ("Three-point field goals made"),
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG3A"),
            "description": ("Three-point field goals attempted"),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FG3_PCT"),
            "description": ("Three-point field goal percentage"),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FTM"),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FTA"),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.FT_PCT"),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.OREB"),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.DREB"),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.REB"),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.AST"),
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.STL"),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.BLK"),
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.TOV"),
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PF"),
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PTS"),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.PlayerStats.PLUS_MINUS"),
            "description": ("Plus-minus differential"),
        },
    )


class StagingBoxScoreTraditionalTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TEAM_NAME"),
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TEAM_ABBREVIATION"),
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TEAM_CITY"),
            "description": "Team city name",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.MIN"),
            "description": ("Total team minutes played"),
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FGM"),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FGA"),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FG_PCT"),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FG3M"),
            "description": ("Three-point field goals made"),
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FG3A"),
            "description": ("Three-point field goals attempted"),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FG3_PCT"),
            "description": ("Three-point field goal percentage"),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FTM"),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FTA"),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.FT_PCT"),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.OREB"),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.DREB"),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.REB"),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.AST"),
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.STL"),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.BLK"),
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.TOV"),
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.PF"),
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.PTS"),
            "description": "Points scored",
        },
    )
    plus_minus: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreTraditionalV3.TeamStats.PLUS_MINUS"),
            "description": ("Plus-minus differential"),
        },
    )


class StagingBoxScoreAdvancedPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    e_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_OFF_RATING"),
            "description": ("Estimated offensive rating"),
        },
    )
    off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.OFF_RATING"),
            "description": "Offensive rating",
        },
    )
    e_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_DEF_RATING"),
            "description": ("Estimated defensive rating"),
        },
    )
    def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.DEF_RATING"),
            "description": "Defensive rating",
        },
    )
    e_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_NET_RATING"),
            "description": ("Estimated net rating"),
        },
    )
    net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.NET_RATING"),
            "description": "Net rating",
        },
    )
    ast_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.AST_PCT"),
            "description": "Assist percentage",
        },
    )
    ast_tov: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.AST_TOV"),
            "description": ("Assist to turnover ratio"),
        },
    )
    ast_ratio: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.AST_RATIO"),
            "description": "Assist ratio",
        },
    )
    oreb_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.OREB_PCT"),
            "description": ("Offensive rebound percentage"),
        },
    )
    dreb_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.DREB_PCT"),
            "description": ("Defensive rebound percentage"),
        },
    )
    reb_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.REB_PCT"),
            "description": ("Total rebound percentage"),
        },
    )
    tov_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.TOV_PCT"),
            "description": "Turnover percentage",
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.EFG_PCT"),
            "description": ("Effective field goal percentage"),
        },
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.TS_PCT"),
            "description": "True shooting percentage",
        },
    )
    usg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.USG_PCT"),
            "description": "Usage percentage",
        },
    )
    e_usg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_USG_PCT"),
            "description": ("Estimated usage percentage"),
        },
    )
    e_pace: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.E_PACE"),
            "description": "Estimated pace",
        },
    )
    pace: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PACE"),
            "description": "Pace factor",
        },
    )
    pace_per40: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PACE_PER40"),
            "description": "Pace per 40 minutes",
        },
    )
    poss: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.POSS"),
            "description": "Possessions",
        },
    )
    pie: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreAdvancedV3.PlayerStats.PIE"),
            "description": ("Player impact estimate"),
        },
    )


class StagingBoxScoreHustlePlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    contested_shots: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.CONTESTED_SHOTS"),
            "description": "Contested shots",
        },
    )
    contested_shots_2pt: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.CONTESTED_SHOTS_2PT"),
            "description": ("Contested two-point shots"),
        },
    )
    contested_shots_3pt: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.CONTESTED_SHOTS_3PT"),
            "description": ("Contested three-point shots"),
        },
    )
    deflections: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.DEFLECTIONS"),
            "description": "Deflections",
        },
    )
    charges_drawn: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.CHARGES_DRAWN"),
            "description": "Charges drawn",
        },
    )
    screen_assists: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.SCREEN_ASSISTS"),
            "description": "Screen assists",
        },
    )
    screen_ast_pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.SCREEN_AST_PTS"),
            "description": ("Points from screen assists"),
        },
    )
    loose_balls_recovered: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.LOOSE_BALLS_RECOVERED"),
            "description": "Loose balls recovered",
        },
    )
    box_outs: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreHustleV2.PlayerStats.BOX_OUTS"),
            "description": "Box outs",
        },
    )


class StagingBoxScorePlayerTrackSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    spd: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.SPD"),
            "description": "Average speed in mph",
        },
    )
    dist: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DIST"),
            "description": ("Distance covered in miles"),
        },
    )
    orbc: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.ORBC"),
            "description": ("Offensive rebound chances"),
        },
    )
    drbc: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DRBC"),
            "description": ("Defensive rebound chances"),
        },
    )
    rbc: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.RBC"),
            "description": ("Total rebound chances"),
        },
    )
    tchs: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.TCHS"),
            "description": "Touches",
        },
    )
    sast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.SAST"),
            "description": "Secondary assists",
        },
    )
    ftast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.FTAST"),
            "description": ("Free throw assists"),
        },
    )
    pass_: float | None = pa.Field(
        nullable=True,
        ge=0,
        alias="pass",
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.PASS"),
            "description": "Passes made",
        },
    )
    cfgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.CFGM"),
            "description": ("Contested field goals made"),
        },
    )
    cfga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.CFGA"),
            "description": ("Contested field goals attempted"),
        },
    )
    cfg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.CFG_PCT"),
            "description": ("Contested field goal percentage"),
        },
    )
    ufgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.UFGM"),
            "description": ("Uncontested field goals made"),
        },
    )
    ufga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.UFGA"),
            "description": ("Uncontested field goals attempted"),
        },
    )
    ufg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.UFG_PCT"),
            "description": ("Uncontested field goal percentage"),
        },
    )
    dfgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DFGM"),
            "description": ("Defended field goals made"),
        },
    )
    dfga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DFGA"),
            "description": ("Defended field goals attempted"),
        },
    )
    dfg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScorePlayerTrackV3.PlayerStats.DFG_PCT"),
            "description": ("Defended field goal percentage"),
        },
    )


class StagingBoxScoreDefensivePlayerSchema(
    BaseSchema,
):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.GAME_ID"),
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.PLAYER_ID"),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.PLAYER_NAME"),
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.MIN"),
            "description": ("Minutes played as string"),
        },
    )
    matchup_min: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.MATCHUP_MIN"),
            "description": ("Minutes in matchup defense"),
        },
    )
    partial_poss: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.PARTIAL_POSS"),
            "description": ("Partial possessions defended"),
        },
    )
    switches_on: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.SWITCHES_ON"),
            "description": ("Number of defensive switches"),
        },
    )
    player_pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.PLAYER_PTS"),
            "description": ("Points allowed on defense"),
        },
    )
    def_fgm: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.DEF_FGM"),
            "description": ("Defended field goals made"),
        },
    )
    def_fga: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.DEF_FGA"),
            "description": ("Defended field goals attempted"),
        },
    )
    def_fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": ("BoxScoreDefensiveV2.PlayerStats.DEF_FG_PCT"),
            "description": ("Defended field goal percentage"),
        },
    )


class StagingBoxScoreFourFactorsPlayerSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.PLAYER_ID",
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.PLAYER_NAME",
            "description": "Player full name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.MIN",
            "description": "Minutes played as string",
        },
    )
    effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.EFG_PCT",
            "description": "Effective field goal percentage",
        },
    )
    free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.FTA_RATE",
            "description": "Free throw attempt rate",
        },
    )
    team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.TM_TOV_PCT",
            "description": "Team turnover percentage",
        },
    )
    offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OREB_PCT",
            "description": "Offensive rebound percentage",
        },
    )
    opp_effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OPP_EFG_PCT",
            "description": "Opponent effective field goal percentage",
        },
    )
    opp_free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OPP_FTA_RATE",
            "description": "Opponent free throw attempt rate",
        },
    )
    opp_team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OPP_TOV_PCT",
            "description": "Opponent team turnover percentage",
        },
    )
    opp_offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.PlayerStats.OPP_OREB_PCT",
            "description": "Opponent offensive rebound percentage",
        },
    )


class StagingBoxScoreFourFactorsTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.TEAM_NAME",
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.EFG_PCT",
            "description": "Effective field goal percentage",
        },
    )
    free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.FTA_RATE",
            "description": "Free throw attempt rate",
        },
    )
    team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.TM_TOV_PCT",
            "description": "Team turnover percentage",
        },
    )
    offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OREB_PCT",
            "description": "Offensive rebound percentage",
        },
    )
    opp_effective_field_goal_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OPP_EFG_PCT",
            "description": "Opponent effective field goal percentage",
        },
    )
    opp_free_throw_attempt_rate: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OPP_FTA_RATE",
            "description": "Opponent free throw attempt rate",
        },
    )
    opp_team_turnover_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OPP_TOV_PCT",
            "description": "Opponent team turnover percentage",
        },
    )
    opp_offensive_rebound_percentage: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "BoxScoreFourFactorsV3.TeamStats.OPP_OREB_PCT",
            "description": "Opponent offensive rebound percentage",
        },
    )


class StagingBoxScoreTraditionalStarterBenchSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.TEAM_NAME",
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.TEAM_CITY",
            "description": "Team city name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.MIN",
            "description": "Minutes played as string",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.FGM",
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.FGA",
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.FG_PCT",
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.FG3M",
            "description": "Three-point field goals made",
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.FG3A",
            "description": "Three-point field goals attempted",
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.FG3_PCT",
            "description": "Three-point field goal percentage",
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.FTM",
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.FTA",
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.FT_PCT",
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.OREB",
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.DREB",
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.REB",
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.AST",
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.STL",
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.BLK",
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.TOV",
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.PF",
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.PTS",
            "description": "Points scored",
        },
    )
    starters_bench: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreTraditionalV3.TeamStarterBenchStats.STARTERS_BENCH",
            "description": "Starter or bench split label",
        },
    )


class StagingBoxScoreAdvancedTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreAdvancedV3.TeamStats.TEAM_NAME", "description": "Team name"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.TEAM_CITY",
            "description": "Team city name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.MIN",
            "description": "Minutes played as string",
        },
    )
    e_off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.E_OFF_RATING",
            "description": "Estimated offensive rating",
        },
    )
    off_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.OFF_RATING",
            "description": "Offensive rating",
        },
    )
    e_def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.E_DEF_RATING",
            "description": "Estimated defensive rating",
        },
    )
    def_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.DEF_RATING",
            "description": "Defensive rating",
        },
    )
    e_net_rating: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.E_NET_RATING",
            "description": "Estimated net rating",
        },
    )
    net_rating: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreAdvancedV3.TeamStats.NET_RATING", "description": "Net rating"},
    )
    ast_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.AST_PCT",
            "description": "Assist percentage",
        },
    )
    ast_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.AST_TOV",
            "description": "Assist-to-turnover ratio",
        },
    )
    ast_ratio: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.AST_RATIO",
            "description": "Assist ratio",
        },
    )
    oreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.OREB_PCT",
            "description": "Offensive rebound percentage",
        },
    )
    dreb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.DREB_PCT",
            "description": "Defensive rebound percentage",
        },
    )
    reb_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.REB_PCT",
            "description": "Total rebound percentage",
        },
    )
    tm_tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.TM_TOV_PCT",
            "description": "Estimated team turnover percentage",
        },
    )
    tov_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.TOV_PCT",
            "description": "Turnover ratio",
        },
    )
    efg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.EFG_PCT",
            "description": "Effective field goal percentage",
        },
    )
    ts_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.TS_PCT",
            "description": "True shooting percentage",
        },
    )
    usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.USG_PCT",
            "description": "Usage percentage",
        },
    )
    e_usg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.E_USG_PCT",
            "description": "Estimated usage percentage",
        },
    )
    e_pace: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreAdvancedV3.TeamStats.E_PACE", "description": "Estimated pace"},
    )
    pace: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreAdvancedV3.TeamStats.PACE", "description": "Pace"},
    )
    pace_per40: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.PACE_PER40",
            "description": "Pace per 40 minutes",
        },
    )
    poss: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreAdvancedV3.TeamStats.POSS", "description": "Possessions"},
    )
    pie: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreAdvancedV3.TeamStats.PIE",
            "description": "Player impact estimate",
        },
    )


class StagingBoxScoreMiscTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreMiscV3.TeamStats.TEAM_NAME", "description": "Team name"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreMiscV3.TeamStats.TEAM_CITY", "description": "Team city name"},
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.MIN",
            "description": "Minutes played as string",
        },
    )
    pts_off_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.PTS_OFF_TOV",
            "description": "Points off turnovers",
        },
    )
    second_chance_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.SECOND_CHANCE_PTS",
            "description": "Second chance points",
        },
    )
    fbps: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreMiscV3.TeamStats.FBPS", "description": "Fast break points"},
    )
    pitp: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreMiscV3.TeamStats.PITP", "description": "Points in the paint"},
    )
    opp_pts_off_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.OPP_PTS_OFF_TOV",
            "description": "Opponent points off turnovers",
        },
    )
    opp_second_chance_pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.OPP_SECOND_CHANCE_PTS",
            "description": "Opponent second chance points",
        },
    )
    opp_fbps: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.OPP_FBPS",
            "description": "Opponent fast break points",
        },
    )
    opp_pitp: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.OPP_PITP",
            "description": "Opponent points in the paint",
        },
    )
    blk: float | None = pa.Field(
        nullable=True, metadata={"source": "BoxScoreMiscV3.TeamStats.BLK", "description": "Blocks"}
    )
    blka: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreMiscV3.TeamStats.BLKA",
            "description": "Blocked shot attempts",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreMiscV3.TeamStats.PF", "description": "Personal fouls"},
    )
    pfd: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreMiscV3.TeamStats.PFD", "description": "Personal fouls drawn"},
    )


class StagingBoxScoreScoringTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreScoringV3.TeamStats.TEAM_NAME", "description": "Team name"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.TEAM_CITY",
            "description": "Team city name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.MIN",
            "description": "Minutes played as string",
        },
    )
    pct_fga_2pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_FGA_2PT",
            "description": "Percent of FGA that are 2-pointers",
        },
    )
    pct_fga_3pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_FGA_3PT",
            "description": "Percent of FGA that are 3-pointers",
        },
    )
    pct_pts_2pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_PTS_2PT",
            "description": "Percent of points from 2-pointers",
        },
    )
    pct_pts_2pt_mr: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_PTS_2PT_MR",
            "description": "Percent of points from mid-range 2-pointers",
        },
    )
    pct_pts_3pt: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_PTS_3PT",
            "description": "Percent of points from 3-pointers",
        },
    )
    pct_pts_fb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_PTS_FB",
            "description": "Percent of points from fast breaks",
        },
    )
    pct_pts_ft: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_PTS_FT",
            "description": "Percent of points from free throws",
        },
    )
    pct_pts_off_tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_PTS_OFF_TOV",
            "description": "Percent of points off turnovers",
        },
    )
    pct_pts_pitp: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_PTS_PITP",
            "description": "Percent of points in the paint",
        },
    )
    pct_ast_2pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_AST_2PM",
            "description": "Percent of assisted 2-point makes",
        },
    )
    pct_uast_2pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_UAST_2PM",
            "description": "Percent of unassisted 2-point makes",
        },
    )
    pct_ast_3pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_AST_3PM",
            "description": "Percent of assisted 3-point makes",
        },
    )
    pct_uast_3pm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_UAST_3PM",
            "description": "Percent of unassisted 3-point makes",
        },
    )
    pct_ast_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_AST_FGM",
            "description": "Percent of assisted field goal makes",
        },
    )
    pct_uast_fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreScoringV3.TeamStats.PCT_UAST_FGM",
            "description": "Percent of unassisted field goal makes",
        },
    )


class StagingBoxScorePlayerTrackTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.TEAM_NAME",
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.TEAM_CITY",
            "description": "Team city name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.MIN",
            "description": "Minutes played as string",
        },
    )
    dist: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.DIST",
            "description": "Distance covered",
        },
    )
    orbc: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.ORBC",
            "description": "Offensive rebound chances",
        },
    )
    drbc: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.DRBC",
            "description": "Defensive rebound chances",
        },
    )
    rbc: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.RBC",
            "description": "Total rebound chances",
        },
    )
    tchs: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScorePlayerTrackV3.TeamStats.TCHS", "description": "Touches"},
    )
    sast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.SAST",
            "description": "Secondary assists",
        },
    )
    ftast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.FTAST",
            "description": "Free throw assists",
        },
    )
    passes: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScorePlayerTrackV3.TeamStats.PASSES", "description": "Passes made"},
    )
    ast: float | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScorePlayerTrackV3.TeamStats.AST", "description": "Assists"},
    )
    cfgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.CFGM",
            "description": "Contested field goals made",
        },
    )
    cfga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.CFGA",
            "description": "Contested field goals attempted",
        },
    )
    cfg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.CFG_PCT",
            "description": "Contested field goal percentage",
        },
    )
    ufgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.UFGM",
            "description": "Uncontested field goals made",
        },
    )
    ufga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.UFGA",
            "description": "Uncontested field goals attempted",
        },
    )
    ufg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.UFG_PCT",
            "description": "Uncontested field goal percentage",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.FG_PCT",
            "description": "Field goal percentage",
        },
    )
    dfgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.DFGM",
            "description": "Defended-at-rim field goals made",
        },
    )
    dfga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.DFGA",
            "description": "Defended-at-rim field goals attempted",
        },
    )
    dfg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScorePlayerTrackV3.TeamStats.DFG_PCT",
            "description": "Defended-at-rim field goal percentage",
        },
    )


class StagingBoxScoreDefensiveTeamSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreDefensiveV2.TeamStats.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreDefensiveV2.TeamStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreDefensiveV2.TeamStats.TEAM_NAME", "description": "Team name"},
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreDefensiveV2.TeamStats.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreDefensiveV2.TeamStats.TEAM_CITY",
            "description": "Team city name",
        },
    )
    min: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreDefensiveV2.TeamStats.MIN",
            "description": "Minutes played as string",
        },
    )


class StagingGameSummaryAvailableVideoSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV2.AvailableVideo.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    video_available_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.AvailableVideo.VIDEO_AVAILABLE_FLAG",
            "description": "Video availability flag",
        },
    )
    pt_available: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.AvailableVideo.PT_AVAILABLE",
            "description": "Player tracking availability flag",
        },
    )
    pt_xyz_available: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.AvailableVideo.PT_XYZ_AVAILABLE",
            "description": "Player tracking XYZ availability flag",
        },
    )
    wh_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.AvailableVideo.WH_STATUS",
            "description": "Wagering hub status flag",
        },
    )
    hustle_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.AvailableVideo.HUSTLE_STATUS",
            "description": "Hustle availability flag",
        },
    )
    historical_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.AvailableVideo.HISTORICAL_STATUS",
            "description": "Historical data availability flag",
        },
    )


class StagingGameInfoSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={"source": "derived.game_id", "description": "Unique game identifier"},
    )
    game_date: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV2.GameInfo.GAME_DATE", "description": "Game date"},
    )
    attendance: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameInfo.ATTENDANCE",
            "description": "Reported attendance",
        },
    )
    game_time: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameInfo.GAME_TIME",
            "description": "Game duration or elapsed time",
        },
    )


class StagingGameSummarySchema(BaseSchema):
    game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.GAME_DATE_EST",
            "description": "Game date in Eastern time",
        },
    )
    game_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.GAME_SEQUENCE",
            "description": "Game sequence number for the day",
        },
    )
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    game_status_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.GAME_STATUS_ID",
            "description": "Game status identifier",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.GAME_STATUS_TEXT",
            "description": "Game status display text",
        },
    )
    gamecode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.GAMECODE",
            "description": "Game code string",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.HOME_TEAM_ID",
            "description": "Home team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.VISITOR_TEAM_ID",
            "description": "Visitor team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    season: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.SEASON",
            "description": "Season identifier",
        },
    )
    live_period: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.LIVE_PERIOD",
            "description": "Current live period",
        },
    )
    live_pc_time: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.LIVE_PC_TIME",
            "description": "Live game clock",
        },
    )
    natl_tv_broadcaster_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.NATL_TV_BROADCASTER_ABBREVIATION",
            "description": "National TV broadcaster abbreviation",
        },
    )
    live_period_time_bcast: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.LIVE_PERIOD_TIME_BCAST",
            "description": "Broadcast clock string",
        },
    )
    wh_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.GameSummary.WH_STATUS",
            "description": "Wagering hub status flag",
        },
    )


class StagingInactivePlayersSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={"source": "derived.game_id", "description": "Unique game identifier"},
    )
    player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.InactivePlayers.PLAYER_ID",
            "description": "Player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.InactivePlayers.FIRST_NAME",
            "description": "First name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.InactivePlayers.LAST_NAME",
            "description": "Last name",
        },
    )
    jersey_num: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.InactivePlayers.JERSEY_NUM",
            "description": "Jersey number",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.InactivePlayers.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.InactivePlayers.TEAM_CITY",
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.InactivePlayers.TEAM_NAME",
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.InactivePlayers.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )


class StagingLastMeetingSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    last_game_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_ID",
            "description": "Previous meeting game identifier",
        },
    )
    last_game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_DATE_EST",
            "description": "Previous meeting date",
        },
    )
    last_game_home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_HOME_TEAM_ID",
            "description": "Previous home team identifier",
        },
    )
    last_game_home_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_HOME_TEAM_CITY",
            "description": "Previous home team city",
        },
    )
    last_game_home_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_HOME_TEAM_NAME",
            "description": "Previous home team name",
        },
    )
    last_game_home_team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_HOME_TEAM_ABBREVIATION",
            "description": "Previous home team abbreviation",
        },
    )
    last_game_home_team_points: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_HOME_TEAM_POINTS",
            "description": "Previous home team points",
        },
    )
    last_game_visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_VISITOR_TEAM_ID",
            "description": "Previous visitor team identifier",
        },
    )
    last_game_visitor_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_VISITOR_TEAM_CITY",
            "description": "Previous visitor team city",
        },
    )
    last_game_visitor_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_VISITOR_TEAM_NAME",
            "description": "Previous visitor team name",
        },
    )
    last_game_visitor_team_city1: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_VISITOR_TEAM_CITY1",
            "description": "Alternate previous visitor city label",
        },
    )
    last_game_visitor_team_points: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LastMeeting.LAST_GAME_VISITOR_TEAM_POINTS",
            "description": "Previous visitor team points",
        },
    )


class StagingLineScoreSchema(BaseSchema):
    game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.GAME_DATE_EST",
            "description": "Game date in Eastern time",
        },
    )
    game_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.GAME_SEQUENCE",
            "description": "Game sequence number for the day",
        },
    )
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_city_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.TEAM_CITY_NAME",
            "description": "Team city name",
        },
    )
    team_nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.TEAM_NICKNAME",
            "description": "Team nickname",
        },
    )
    team_wins_losses: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.TEAM_WINS_LOSSES",
            "description": "Team record entering the game",
        },
    )
    pts_qtr1: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_QTR1",
            "description": "Points in first quarter",
        },
    )
    pts_qtr2: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_QTR2",
            "description": "Points in second quarter",
        },
    )
    pts_qtr3: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_QTR3",
            "description": "Points in third quarter",
        },
    )
    pts_qtr4: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_QTR4",
            "description": "Points in fourth quarter",
        },
    )
    pts_ot1: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT1",
            "description": "Points in first overtime",
        },
    )
    pts_ot2: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT2",
            "description": "Points in second overtime",
        },
    )
    pts_ot3: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT3",
            "description": "Points in third overtime",
        },
    )
    pts_ot4: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT4",
            "description": "Points in fourth overtime",
        },
    )
    pts_ot5: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT5",
            "description": "Points in fifth overtime",
        },
    )
    pts_ot6: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT6",
            "description": "Points in sixth overtime",
        },
    )
    pts_ot7: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT7",
            "description": "Points in seventh overtime",
        },
    )
    pts_ot8: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT8",
            "description": "Points in eighth overtime",
        },
    )
    pts_ot9: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT9",
            "description": "Points in ninth overtime",
        },
    )
    pts_ot10: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.LineScore.PTS_OT10",
            "description": "Points in tenth overtime",
        },
    )
    pts: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV2.LineScore.PTS", "description": "Total points"},
    )


class StagingOfficialsSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={"source": "derived.game_id", "description": "Unique game identifier"},
    )
    official_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.Officials.OFFICIAL_ID",
            "description": "Official identifier",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.Officials.FIRST_NAME",
            "description": "Official first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.Officials.LAST_NAME",
            "description": "Official last name",
        },
    )
    jersey_number: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.Officials.JERSEY_NUM",
            "description": "Official jersey number",
        },
    )


class StagingOtherStatsSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={"source": "derived.game_id", "description": "Unique game identifier"},
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.LEAGUE_ID",
            "description": "League identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.TEAM_ABBREVIATION",
            "description": "Team abbreviation code",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.TEAM_CITY",
            "description": "Team city name",
        },
    )
    pts_paint: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.PTS_PAINT",
            "description": "Points in the paint",
        },
    )
    pts_2nd_chance: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.PTS_2ND_CHANCE",
            "description": "Second chance points",
        },
    )
    pts_fb: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.PTS_FB",
            "description": "Fast break points",
        },
    )
    largest_lead: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.LARGEST_LEAD",
            "description": "Largest lead",
        },
    )
    lead_changes: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.LEAD_CHANGES",
            "description": "Lead changes",
        },
    )
    times_tied: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV2.OtherStats.TIMES_TIED", "description": "Times tied"},
    )
    team_turnovers: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.TEAM_TURNOVERS",
            "description": "Team turnovers",
        },
    )
    total_turnovers: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.TOTAL_TURNOVERS",
            "description": "Total turnovers",
        },
    )
    team_rebounds: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.TEAM_REBOUNDS",
            "description": "Team rebounds",
        },
    )
    pts_off_to: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.OtherStats.PTS_OFF_TO",
            "description": "Points off turnovers",
        },
    )


class StagingSeasonSeriesSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV2.SeasonSeries.GAME_ID",
            "description": "Unique game identifier",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.SeasonSeries.HOME_TEAM_ID",
            "description": "Home team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    visitor_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.SeasonSeries.VISITOR_TEAM_ID",
            "description": "Visitor team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    game_date_est: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.SeasonSeries.GAME_DATE_EST",
            "description": "Game date in Eastern time",
        },
    )
    home_team_wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.SeasonSeries.HOME_TEAM_WINS",
            "description": "Home team wins in the season series",
        },
    )
    home_team_losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.SeasonSeries.HOME_TEAM_LOSSES",
            "description": "Home team losses in the season series",
        },
    )
    series_leader: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV2.SeasonSeries.SERIES_LEADER",
            "description": "Season series leader label",
        },
    )


class StagingSummaryV3GameSummarySchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.gameId",
            "description": "Unique game identifier",
        },
    )
    game_code: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.gameCode",
            "description": "Game code string",
        },
    )
    game_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.gameStatus",
            "description": "Game status identifier",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.gameStatusText",
            "description": "Game status display text",
        },
    )
    period: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.period",
            "description": "Current game period",
        },
    )
    game_clock: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.GameSummary.gameClock", "description": "Game clock"},
    )
    game_time_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.gameTimeUTC",
            "description": "Game time in UTC",
        },
    )
    game_et: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.gameEt",
            "description": "Game time in Eastern time",
        },
    )
    away_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.awayTeamId",
            "description": "Away team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.homeTeamId",
            "description": "Home team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    duration: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.duration",
            "description": "Game duration",
        },
    )
    attendance: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameSummary.attendance",
            "description": "Reported attendance",
        },
    )
    sellout: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.GameSummary.sellout", "description": "Sellout flag"},
    )


class StagingSummaryV3GameInfoSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV3.GameInfo.gameId",
            "description": "Unique game identifier",
        },
    )
    game_date: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.GameInfo.gameDate", "description": "Game date"},
    )
    attendance: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameInfo.attendance",
            "description": "Reported attendance",
        },
    )
    game_duration: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.GameInfo.gameDuration",
            "description": "Game duration",
        },
    )


class StagingSummaryV3OfficialsSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV3.Officials.gameId",
            "description": "Unique game identifier",
        },
    )
    person_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.Officials.personId",
            "description": "Official identifier",
        },
    )
    name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.Officials.name",
            "description": "Official display name",
        },
    )
    name_i: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.Officials.nameI",
            "description": "Abbreviated official name",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.Officials.firstName",
            "description": "Official first name",
        },
    )
    family_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.Officials.familyName",
            "description": "Official last name",
        },
    )
    jersey_num: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.Officials.jerseyNum",
            "description": "Official jersey number",
        },
    )


class StagingSummaryV3LineScoreSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.gameId",
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.teamId",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.teamCity",
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.LineScore.teamName", "description": "Team name"},
    )
    team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.teamTricode",
            "description": "Team tricode",
        },
    )
    team_slug: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.LineScore.teamSlug", "description": "Team slug"},
    )
    team_wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.teamWins",
            "description": "Team wins entering the game",
        },
    )
    team_losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.teamLosses",
            "description": "Team losses entering the game",
        },
    )
    period1_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.period1Score",
            "description": "First period score",
        },
    )
    period2_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.period2Score",
            "description": "Second period score",
        },
    )
    period3_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.period3Score",
            "description": "Third period score",
        },
    )
    period4_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LineScore.period4Score",
            "description": "Fourth period score",
        },
    )
    score: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.LineScore.score", "description": "Total points"},
    )


class StagingSummaryV3InactivePlayersSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV3.InactivePlayers.gameId",
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.InactivePlayers.teamId",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    person_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.InactivePlayers.personId",
            "description": "Player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.InactivePlayers.firstName",
            "description": "First name",
        },
    )
    family_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.InactivePlayers.familyName",
            "description": "Last name",
        },
    )
    jersey_num: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.InactivePlayers.jerseyNum",
            "description": "Jersey number",
        },
    )


class StagingSummaryV3LastFiveMeetingsSchema(BaseSchema):
    recency_order: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.recencyOrder",
            "description": "Recency ordering value",
        },
    )
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.gameId",
            "description": "Historical game identifier",
        },
    )
    game_time_utc: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.gameTimeUTC",
            "description": "Historical game time in UTC",
        },
    )
    game_et: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.gameEt",
            "description": "Historical game time in Eastern time",
        },
    )
    game_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.gameStatus",
            "description": "Historical game status identifier",
        },
    )
    game_status_text: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.gameStatusText",
            "description": "Historical game status text",
        },
    )
    away_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.awayTeamId",
            "description": "Away team identifier",
        },
    )
    away_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.awayTeamCity",
            "description": "Away team city",
        },
    )
    away_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.awayTeamName",
            "description": "Away team name",
        },
    )
    away_team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.awayTeamTricode",
            "description": "Away team tricode",
        },
    )
    away_team_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.awayTeamScore",
            "description": "Away team score",
        },
    )
    away_team_wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.awayTeamWins",
            "description": "Away team wins entering the game",
        },
    )
    away_team_losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.awayTeamLosses",
            "description": "Away team losses entering the game",
        },
    )
    home_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.homeTeamId",
            "description": "Home team identifier",
        },
    )
    home_team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.homeTeamCity",
            "description": "Home team city",
        },
    )
    home_team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.homeTeamName",
            "description": "Home team name",
        },
    )
    home_team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.homeTeamTricode",
            "description": "Home team tricode",
        },
    )
    home_team_score: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.homeTeamScore",
            "description": "Home team score",
        },
    )
    home_team_wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.homeTeamWins",
            "description": "Home team wins entering the game",
        },
    )
    home_team_losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.LastFiveMeetings.homeTeamLosses",
            "description": "Home team losses entering the game",
        },
    )


class StagingSummaryV3OtherStatsSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.gameId",
            "description": "Unique game identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.teamId",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.teamCity",
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.OtherStats.teamName", "description": "Team name"},
    )
    team_tricode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.teamTricode",
            "description": "Team tricode",
        },
    )
    points: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.OtherStats.points", "description": "Total points"},
    )
    rebounds_total: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.reboundsTotal",
            "description": "Total rebounds",
        },
    )
    assists: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.OtherStats.assists", "description": "Assists"},
    )
    steals: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.OtherStats.steals", "description": "Steals"},
    )
    blocks: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.OtherStats.blocks", "description": "Blocks"},
    )
    turnovers: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.OtherStats.turnovers", "description": "Turnovers"},
    )
    field_goals_percentage: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.fieldGoalsPercentage",
            "description": "Field goal percentage",
        },
    )
    three_pointers_percentage: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.threePointersPercentage",
            "description": "Three-point percentage",
        },
    )
    free_throws_percentage: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.freeThrowsPercentage",
            "description": "Free throw percentage",
        },
    )
    points_in_the_paint: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.pointsInThePaint",
            "description": "Points in the paint",
        },
    )
    points_second_chance: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.pointsSecondChance",
            "description": "Second chance points",
        },
    )
    points_fast_break: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.pointsFastBreak",
            "description": "Fast break points",
        },
    )
    biggest_lead: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.biggestLead",
            "description": "Biggest lead",
        },
    )
    lead_changes: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.leadChanges",
            "description": "Lead changes",
        },
    )
    times_tied: int | None = pa.Field(
        nullable=True,
        metadata={"source": "BoxScoreSummaryV3.OtherStats.timesTied", "description": "Times tied"},
    )
    biggest_scoring_run: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.biggestScoringRun",
            "description": "Biggest scoring run",
        },
    )
    turnovers_team: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.turnoversTeam",
            "description": "Team turnovers",
        },
    )
    turnovers_total: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.turnoversTotal",
            "description": "Total turnovers",
        },
    )
    rebounds_team: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.reboundsTeam",
            "description": "Team rebounds",
        },
    )
    points_from_turnovers: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.pointsFromTurnovers",
            "description": "Points from turnovers",
        },
    )
    bench_points: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.OtherStats.benchPoints",
            "description": "Bench points",
        },
    )


class StagingSummaryV3AvailableVideoSchema(BaseSchema):
    game_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": "BoxScoreSummaryV3.AvailableVideo.gameId",
            "description": "Unique game identifier",
        },
    )
    video_available_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.AvailableVideo.videoAvailableFlag",
            "description": "Video availability flag",
        },
    )
    pt_available: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.AvailableVideo.ptAvailable",
            "description": "Player tracking availability flag",
        },
    )
    pt_xyz_available: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.AvailableVideo.ptXYZAvailable",
            "description": "Player tracking XYZ availability flag",
        },
    )
    wh_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.AvailableVideo.whStatus",
            "description": "Wagering hub status flag",
        },
    )
    hustle_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.AvailableVideo.hustleStatus",
            "description": "Hustle availability flag",
        },
    )
    historical_status: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "BoxScoreSummaryV3.AvailableVideo.historicalStatus",
            "description": "Historical data availability flag",
        },
    )
